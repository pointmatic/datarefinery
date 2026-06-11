# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-J-1 SampleData runtime stage tests (Story J.a).

Covers the P-postpipeline + M-sidecar runtime: ``apply_sample_data``
subsets per-split records after the pipeline, returning a SampleResult
whose ``samples`` map feeds ``sample/<split>.jsonl`` persistence.

Determinism contract: per-record seed ranking via
``pipeline.workers.per_record_seed(seed, record)`` mirrors the
``stratified_seeded_sample`` helper used by ``sample_per_class`` -
selection is invariant to input ordering, worker count, and scheduling.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.stages.sample_data import (
    SampleResult,
    apply_sample_data,
    resolve_sample_seed,
)
from datarefinery.recipe.models import (
    SampleDataSection,
    SampleSelector,
    SeedDerivationSpec,
)


def _records(n: int, *, classes: int = 2, prefix: str = "r") -> list[Mapping[str, Any]]:
    return [{"record_id": f"{prefix}{i:03d}", "label": f"c{i % classes}"} for i in range(n)]


# ---------------------------------------------------------------------------
# kind: uniform
# ---------------------------------------------------------------------------


def test_uniform_n_takes_n_records_per_split() -> None:
    section = SampleDataSection(selector=SampleSelector(n=10, kind="uniform"))
    split_map = {"train": _records(100), "val": _records(40, prefix="v")}
    result = apply_sample_data(split_map, section, seed=42, label_field="label")
    assert isinstance(result, SampleResult)
    assert set(result.samples.keys()) == {"train", "val"}
    assert len(result.samples["train"]) == 10
    assert len(result.samples["val"]) == 10
    # Every sampled record is from the source split.
    train_ids = {r["record_id"] for r in split_map["train"]}
    assert {r["record_id"] for r in result.samples["train"]} <= train_ids


def test_uniform_fraction_takes_floor_fraction_records_per_split() -> None:
    section = SampleDataSection(selector=SampleSelector(fraction=0.25, kind="uniform"))
    split_map = {"train": _records(100), "val": _records(40, prefix="v")}
    result = apply_sample_data(split_map, section, seed=42, label_field="label")
    assert len(result.samples["train"]) == 25
    assert len(result.samples["val"]) == 10


def test_uniform_n_clamps_to_split_size_when_too_large() -> None:
    section = SampleDataSection(selector=SampleSelector(n=500, kind="uniform"))
    split_map = {"train": _records(100)}
    result = apply_sample_data(split_map, section, seed=42, label_field="label")
    assert len(result.samples["train"]) == 100


def test_uniform_sampling_is_deterministic_for_fixed_seed() -> None:
    section = SampleDataSection(selector=SampleSelector(n=10, kind="uniform"))
    split_map = {"train": _records(50)}
    a = apply_sample_data(split_map, section, seed=7, label_field="label")
    b = apply_sample_data(split_map, section, seed=7, label_field="label")
    assert [r["record_id"] for r in a.samples["train"]] == [
        r["record_id"] for r in b.samples["train"]
    ]


def test_uniform_sampling_changes_with_different_seed() -> None:
    section = SampleDataSection(selector=SampleSelector(n=10, kind="uniform"))
    split_map = {"train": _records(50)}
    a = apply_sample_data(split_map, section, seed=7, label_field="label")
    b = apply_sample_data(split_map, section, seed=8, label_field="label")
    assert {r["record_id"] for r in a.samples["train"]} != {
        r["record_id"] for r in b.samples["train"]
    }


def test_uniform_sampling_is_invariant_to_input_order() -> None:
    """Per-record-seed ranking → ordering-independent selection."""
    section = SampleDataSection(selector=SampleSelector(n=10, kind="uniform"))
    records = _records(50)
    a = apply_sample_data({"train": records}, section, seed=7, label_field="label")
    b = apply_sample_data({"train": list(reversed(records))}, section, seed=7, label_field="label")
    assert {r["record_id"] for r in a.samples["train"]} == {
        r["record_id"] for r in b.samples["train"]
    }


# ---------------------------------------------------------------------------
# kind: per_class
# ---------------------------------------------------------------------------


def test_per_class_n_takes_n_records_per_class() -> None:
    section = SampleDataSection(selector=SampleSelector(n=3, kind="per_class"))
    split_map = {"train": _records(60, classes=3)}  # 20 per class
    result = apply_sample_data(split_map, section, seed=42, label_field="label")
    counts: dict[str, int] = {}
    for r in result.samples["train"]:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    assert counts == {"c0": 3, "c1": 3, "c2": 3}


def test_per_class_n_clamps_per_class_when_too_large() -> None:
    section = SampleDataSection(selector=SampleSelector(n=50, kind="per_class"))
    split_map = {"train": _records(30, classes=3)}  # 10 per class
    result = apply_sample_data(split_map, section, seed=42, label_field="label")
    counts: dict[str, int] = {}
    for r in result.samples["train"]:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    assert counts == {"c0": 10, "c1": 10, "c2": 10}


def test_per_class_fraction_takes_floor_per_class() -> None:
    section = SampleDataSection(selector=SampleSelector(fraction=0.2, kind="per_class"))
    split_map = {"train": _records(60, classes=3)}  # 20 per class
    result = apply_sample_data(split_map, section, seed=42, label_field="label")
    counts: dict[str, int] = {}
    for r in result.samples["train"]:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    assert counts == {"c0": 4, "c1": 4, "c2": 4}


def test_per_class_refuses_split_with_records_missing_label_field() -> None:
    section = SampleDataSection(selector=SampleSelector(n=2, kind="per_class"))
    bad: list[Mapping[str, Any]] = [
        {"record_id": "r0"},
        {"record_id": "r1"},
    ]  # no `label`
    with pytest.raises(MaterializeError, match="per_class"):
        apply_sample_data({"train": bad}, section, seed=42, label_field="label")


# ---------------------------------------------------------------------------
# splits honoring
# ---------------------------------------------------------------------------


def test_splits_default_to_all_when_unset() -> None:
    section = SampleDataSection(selector=SampleSelector(n=5, kind="uniform"))
    split_map = {
        "train": _records(20),
        "val": _records(20, prefix="v"),
        "test": _records(20, prefix="t"),
    }
    result = apply_sample_data(split_map, section, seed=1, label_field="label")
    assert set(result.samples.keys()) == {"train", "val", "test"}


def test_splits_filter_subsets_only_listed_splits() -> None:
    section = SampleDataSection(
        selector=SampleSelector(n=5, kind="uniform", splits=["train", "val"])
    )
    split_map = {
        "train": _records(20),
        "val": _records(20, prefix="v"),
        "test": _records(20, prefix="t"),
    }
    result = apply_sample_data(split_map, section, seed=1, label_field="label")
    assert set(result.samples.keys()) == {"train", "val"}
    assert "test" not in result.samples


# ---------------------------------------------------------------------------
# resolve_sample_seed
# ---------------------------------------------------------------------------


def test_resolve_sample_seed_none_falls_back_to_master() -> None:
    section = SampleDataSection(selector=SampleSelector(n=1, kind="uniform", seed=None))
    assert resolve_sample_seed(section, fallback=12345) == 12345


def test_resolve_sample_seed_literal_int_wins() -> None:
    section = SampleDataSection(selector=SampleSelector(n=1, kind="uniform", seed=99))
    assert resolve_sample_seed(section, fallback=12345) == 99


def test_resolve_sample_seed_derives_from_master_via_op_name() -> None:
    from datarefinery.recipe.seeds import derive_seed

    section = SampleDataSection(
        selector=SampleSelector(n=1, kind="uniform", seed=SeedDerivationSpec(from_="master"))
    )
    assert resolve_sample_seed(section, fallback=12345) == derive_seed(12345, "SampleData")


# ---------------------------------------------------------------------------
# selector_echo (drives manifest.sample.selector)
# ---------------------------------------------------------------------------


def test_selector_echo_round_trips_selector_fields() -> None:
    selector = SampleSelector(n=10, kind="per_class", splits=["train"])
    section = SampleDataSection(selector=selector)
    result = apply_sample_data(
        {"train": _records(30, classes=3)},
        section,
        seed=42,
        label_field="label",
    )
    assert result.selector_echo["kind"] == "per_class"
    assert result.selector_echo["n"] == 10
    assert result.selector_echo["fraction"] is None
    assert result.selector_echo["splits"] == ["train"]


# ---------------------------------------------------------------------------
# Manifest round-trip — SampleManifestEntry survives write/read
# ---------------------------------------------------------------------------


def test_manifest_sample_entry_round_trips(tmp_path: Any) -> None:
    """``Manifest.sample`` survives ``write_manifest`` -> ``read_manifest``
    with selector echo and per-split record counts intact."""
    from datetime import UTC, datetime

    from datarefinery.pipeline.manifest import (
        Manifest,
        SampleManifestEntry,
        read_manifest,
        write_manifest,
    )

    sample_entry = SampleManifestEntry(
        selector={"kind": "per_class", "n": 3, "fraction": None, "splits": ["train"], "seed": None},
        record_counts={"train": 9},
    )
    manifest = Manifest(
        datarefinery_version="0.20.0",
        plugin="image_classification",
        plugin_version="1",
        recipe_hash="0" * 64,
        input_hash="1" * 64,
        seed=42,
        created_at=datetime.now(UTC),
        elapsed_seconds=0.0,
        record_counts={"train": 60},
        sample=sample_entry,
    )
    target = tmp_path / "manifest.json"
    write_manifest(target, manifest)
    loaded = read_manifest(target)
    assert loaded.sample is not None
    assert loaded.sample.selector == sample_entry.selector
    assert loaded.sample.record_counts == {"train": 9}


def test_manifest_sample_defaults_to_none_when_unset(tmp_path: Any) -> None:
    """Recipes without ``SampleData:`` produce a manifest whose ``sample``
    field is ``None`` (additive default - existing manifests stay valid)."""
    from datetime import UTC, datetime

    from datarefinery.pipeline.manifest import Manifest, read_manifest, write_manifest

    manifest = Manifest(
        datarefinery_version="0.20.0",
        plugin="image_classification",
        plugin_version="1",
        recipe_hash="0" * 64,
        input_hash="1" * 64,
        seed=42,
        created_at=datetime.now(UTC),
        elapsed_seconds=0.0,
    )
    target = tmp_path / "manifest.json"
    write_manifest(target, manifest)
    loaded = read_manifest(target)
    assert loaded.sample is None


def test_result_echoes_resolved_seed_passed_by_caller() -> None:
    """``apply_sample_data`` takes the already-resolved seed; precedence
    lives in :func:`resolve_sample_seed`. ``SampleResult.seed`` echoes
    whatever the caller passed so the runner can record it in the manifest
    without re-resolving."""
    section = SampleDataSection(selector=SampleSelector(n=5, kind="uniform"))
    result = apply_sample_data({"train": _records(20)}, section, seed=42, label_field="label")
    assert result.seed == 42
