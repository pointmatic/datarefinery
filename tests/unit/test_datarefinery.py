# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the public ``DataRefinery`` class and ``Instance`` loader.

Story D.a verifies that:

- ``DataRefinery.from_recipe(...)`` runs validation exactly once and
  memoizes the report behind :meth:`DataRefinery.validate`.
- ``Instance.load(path)`` parses the on-disk manifest, restores the
  canonicalized recipe, and exposes ``fitted_statistics`` lazily
  (no I/O at construction).
- The full library round-trip — load recipe, materialize against
  synthetic in-memory records, reload via ``Instance.load`` — succeeds
  and produces a self-consistent instance directory.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

import datarefinery as dr
from datarefinery import DataRefinery, Instance
from datarefinery.cache.cleaner import CleanReport, CleanSelector
from datarefinery.cache.layout import (
    fitted_stats_dir,
    manifest_path,
    recipe_path,
    report_dir,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import MaterializeError
from datarefinery.recipe import validator as validator_module
from datarefinery.recipe.segments import recipe_identity_hash


def _records(n: int = 12, classes: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": np.full((4, 4, 3), 20 + i * 5, dtype=np.uint8),
            "label": f"c{i % classes}",
            "path": f"/data/c{i % classes}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[dict[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _recipe_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 7,
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]},
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                "label": {"dtype": "str"},
            }
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {
            "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
            "seed": 11,
        },
    }


def _write_recipe(tmp_path: Path, payload: dict[str, Any] | None = None) -> Path:
    payload = payload if payload is not None else _recipe_dict()
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(cache_root=tmp_path / "cache")


# ---------------------------------------------------------------------------
# Public package surface
# ---------------------------------------------------------------------------


def test_public_re_exports() -> None:
    assert dr.DataRefinery is DataRefinery
    assert dr.Instance is Instance
    assert isinstance(dr.__version__, str)
    assert callable(dr.materialize)


# ---------------------------------------------------------------------------
# from_recipe + validation memoization
# ---------------------------------------------------------------------------


def test_from_recipe_loads_and_validates(tmp_path: Path) -> None:
    path = _write_recipe(tmp_path)
    obj = DataRefinery.from_recipe(path, config=_config(tmp_path))
    assert obj.recipe.plugin == "image_classification"
    assert obj.plugin.name == "image_classification"
    assert obj.seed == 7  # from recipe.seed default
    report = obj.validate()
    assert report.passed


def test_from_recipe_runs_validation_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Construction validates; subsequent .validate() calls reuse the report."""
    path = _write_recipe(tmp_path)
    calls: list[int] = []
    real_validate = validator_module.validate

    def counting_validate(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real_validate(*args, **kwargs)

    monkeypatch.setattr("datarefinery.core.datarefinery.validate_recipe", counting_validate)

    obj = DataRefinery.from_recipe(path, config=_config(tmp_path))
    assert len(calls) == 1
    first = obj.validate()
    second = obj.validate()
    assert first is second  # memoized identity
    assert len(calls) == 1  # no extra validator runs


def test_from_recipe_seed_override(tmp_path: Path) -> None:
    obj = DataRefinery.from_recipe(_write_recipe(tmp_path), config=_config(tmp_path), seed=99)
    assert obj.seed == 99


def test_from_recipe_unknown_plugin_raises(tmp_path: Path) -> None:
    payload = _recipe_dict()
    payload["plugin"] = "nope_not_a_plugin"
    from datarefinery.core.errors import PluginError

    with pytest.raises(PluginError, match="nope_not_a_plugin"):
        DataRefinery.from_recipe(_write_recipe(tmp_path, payload), config=_config(tmp_path))


# ---------------------------------------------------------------------------
# cache_key
# ---------------------------------------------------------------------------


def test_cache_key_uses_recipe_inputs_and_seed(tmp_path: Path) -> None:
    path = _write_recipe(tmp_path)
    obj = DataRefinery.from_recipe(path, config=_config(tmp_path), seed=42)
    records = _records()
    key = obj.cache_key(_input_hashes(records))

    expected_recipe = recipe_identity_hash(obj.recipe)
    assert key.recipe_hash == expected_recipe
    assert key.seed == 42


# ---------------------------------------------------------------------------
# materialize round-trip + Instance.load
# ---------------------------------------------------------------------------


def test_materialize_round_trip_via_instance_load(tmp_path: Path) -> None:
    path = _write_recipe(tmp_path)
    obj = DataRefinery.from_recipe(path, config=_config(tmp_path), seed=7)
    records = _records(12)

    instance = obj.materialize(raw_records=records, raw_input_hashes=_input_hashes(records))
    assert isinstance(instance, Instance)
    assert manifest_path(instance.path).exists()
    assert recipe_path(instance.path).exists()
    assert instance.is_partial is False

    # Reload the same instance from disk independently and confirm it round-trips.
    reloaded = Instance.load(instance.path)
    assert reloaded.path == instance.path
    assert reloaded.manifest.recipe_hash == instance.manifest.recipe_hash
    # The reloaded recipe canonicalizes to the same hash recorded in the manifest.
    expected_hash = recipe_identity_hash(reloaded.recipe)
    assert expected_hash == reloaded.manifest.recipe_hash


def test_instance_fitted_statistics_is_lazy(tmp_path: Path) -> None:
    """Construction reads no fitted-statistics bytes."""
    path = _write_recipe(tmp_path)
    obj = DataRefinery.from_recipe(path, config=_config(tmp_path), seed=7)
    records = _records(12)
    instance = obj.materialize(raw_records=records, raw_input_hashes=_input_hashes(records))

    stats = instance.fitted_statistics
    # The accessor object is rooted at the instance dir; no I/O has happened.
    assert stats.root == fitted_stats_dir(instance.path)


def test_instance_load_rejects_directory_without_manifest(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(MaterializeError, match=r"no manifest\.json"):
        Instance.load(empty)


def test_instance_load_rejects_directory_without_recipe(tmp_path: Path) -> None:
    """If only manifest.json is present (an instance from before recipe
    persistence), Instance.load raises rather than silently dropping the
    field."""
    path = _write_recipe(tmp_path)
    obj = DataRefinery.from_recipe(path, config=_config(tmp_path), seed=7)
    records = _records(8)
    instance = obj.materialize(raw_records=records, raw_input_hashes=_input_hashes(records))
    # Simulate a pre-D.a instance by removing recipe.json.
    recipe_path(instance.path).unlink()
    with pytest.raises(MaterializeError, match=r"no recipe\.json"):
        Instance.load(instance.path)


def test_instance_load_detects_recipe_hash_mismatch(tmp_path: Path) -> None:
    """If recipe.json was tampered with, Instance.load refuses."""
    path = _write_recipe(tmp_path)
    obj = DataRefinery.from_recipe(path, config=_config(tmp_path), seed=7)
    records = _records(8)
    instance = obj.materialize(raw_records=records, raw_input_hashes=_input_hashes(records))

    # Mutate recipe.json: change the seed (which is part of canonical bytes).
    rp = recipe_path(instance.path)
    text = rp.read_text(encoding="utf-8")
    # Switch the seed=7 we know is in the recipe to seed=999.
    rp.write_text(text.replace('"seed": 7', '"seed": 999'), encoding="utf-8")
    with pytest.raises(MaterializeError, match="inconsistent"):
        Instance.load(instance.path)


def test_dr_report_re_renders_in_place(tmp_path: Path) -> None:
    path = _write_recipe(tmp_path)
    obj = DataRefinery.from_recipe(path, config=_config(tmp_path), seed=7)
    records = _records(8)
    instance = obj.materialize(raw_records=records, raw_input_hashes=_input_hashes(records))
    rp = report_dir(instance.path) / "report.md"
    original = rp.read_text(encoding="utf-8")
    rp.write_text("clobbered", encoding="utf-8")

    obj.report(instance.path)
    assert rp.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# clean delegates to cache.cleaner with the configured cache root
# ---------------------------------------------------------------------------


def test_clean_routes_through_configured_cache_root(tmp_path: Path) -> None:
    path = _write_recipe(tmp_path)
    obj = DataRefinery.from_recipe(path, config=_config(tmp_path), seed=7)
    records = _records(8)
    obj.materialize(raw_records=records, raw_input_hashes=_input_hashes(records))

    report = obj.clean(CleanSelector(all=True), force=True)
    assert isinstance(report, CleanReport)
    assert len(report.removed) >= 1


# ---------------------------------------------------------------------------
# Verbs deferred to later stories
# ---------------------------------------------------------------------------
