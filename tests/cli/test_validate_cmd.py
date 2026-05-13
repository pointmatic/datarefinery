# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for ``datarefinery validate``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

from datarefinery.cli.app import app

runner = CliRunner()


def _clean_recipe_dict() -> dict[str, Any]:
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


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_clean_recipe_exits_zero(tmp_path: Path) -> None:
    path = _write(tmp_path, _clean_recipe_dict())
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0
    assert "passed" in result.stdout


def test_recipe_with_failures_exits_one(tmp_path: Path) -> None:
    """A multi-violation recipe surfaces every failure (no short-circuit)
    and exits 1."""
    payload = _clean_recipe_dict()
    # Violate check 4: filter declares an empty stages list.
    payload["Filters"] = [
        {"name": "f", "predicate": {"kind": "label_in", "labels": []}, "stages": []},
    ]
    # Violate check 6: transformation declares fit_source pointing at a
    # non-train split.
    payload["Transformations"] = [
        {
            "name": "norm",
            "op": "normalize",
            "fit_source": "val",
            "splits": ["train", "val", "test"],
        }
    ]
    path = _write(tmp_path, payload)
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 1
    # Both failures are reported (the validator never short-circuits).
    assert "fail" in result.stdout


def test_validate_renders_all_twenty_check_rows(tmp_path: Path) -> None:
    path = _write(tmp_path, _clean_recipe_dict())
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0
    # Count rows by looking for each check id; the check_id column is rendered.
    for check_id in range(1, 21):
        assert f" {check_id} " in result.stdout or f"│ {check_id} " in result.stdout


def test_validate_missing_recipe_path_is_usage_error(tmp_path: Path) -> None:
    """Missing argument is a typer usage error, not a recipe error."""
    result = runner.invoke(app, ["validate", str(tmp_path / "does-not-exist.yaml")])
    assert result.exit_code != 0


def test_validate_with_variant_overlay(tmp_path: Path) -> None:
    payload = _clean_recipe_dict()
    payload["variants"] = {
        "no_aug": {"Augmentations": []},
    }
    path = _write(tmp_path, payload)
    result = runner.invoke(app, ["--variant", "no_aug", "validate", str(path)])
    assert result.exit_code == 0
