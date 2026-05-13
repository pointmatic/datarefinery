# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-7 Splits stage tests (Story C.e).

Determinism contract: same seed + same record order produces byte-identical
partitions across runs (the worker-count invariance check lives in C.l's
worker tests; this module covers the partitioning algorithm itself).
"""

from __future__ import annotations

from typing import Any

import pytest

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.stages.splits import (
    SplitResult,
    apply_splits,
    resolve_seed,
)
from datarefinery.recipe.models import KeyAssignment, SplitsSection


def _records(n: int, *, classes: int = 2) -> list[dict[str, Any]]:
    return [{"id": i, "label": f"c{i % classes}", "key": f"k{i}"} for i in range(n)]


# ---------------------------------------------------------------------------
# Ratio-based splits
# ---------------------------------------------------------------------------


def test_ratio_split_partitions_records_into_named_splits() -> None:
    section = SplitsSection(ratios={"train": 0.6, "val": 0.2, "test": 0.2})
    result = apply_splits(_records(100), section, seed=42)
    assert isinstance(result, SplitResult)
    assert set(result.splits.keys()) == {"train", "val", "test"}
    counts = {k: len(v) for k, v in result.splits.items()}
    assert counts == {"train": 60, "val": 20, "test": 20}
    assert result.unassigned == []


def test_ratio_split_is_deterministic_for_fixed_seed() -> None:
    section = SplitsSection(ratios={"train": 0.7, "val": 0.15, "test": 0.15})
    records = _records(50)
    a = apply_splits(records, section, seed=7)
    b = apply_splits(records, section, seed=7)
    for name in a.splits:
        assert [r["id"] for r in a.splits[name]] == [r["id"] for r in b.splits[name]]


def test_ratio_split_changes_with_different_seed() -> None:
    section = SplitsSection(ratios={"train": 0.7, "val": 0.15, "test": 0.15})
    records = _records(50)
    a = apply_splits(records, section, seed=7)
    b = apply_splits(records, section, seed=8)
    assert [r["id"] for r in a.splits["train"]] != [r["id"] for r in b.splits["train"]]


def test_ratios_summing_below_one_record_remainder_in_unassigned() -> None:
    section = SplitsSection(ratios={"train": 0.5, "val": 0.25})
    result = apply_splits(_records(100), section, seed=42)
    assert len(result.splits["train"]) == 50
    assert len(result.splits["val"]) == 25
    assert len(result.unassigned) == 25
    # Total preserved (no record lost or duplicated).
    seen_ids = (
        [r["id"] for r in result.splits["train"]]
        + [r["id"] for r in result.splits["val"]]
        + [r["id"] for r in result.unassigned]
    )
    assert sorted(seen_ids) == list(range(100))


def test_partition_is_a_partition_no_dupes_no_loss() -> None:
    section = SplitsSection(ratios={"train": 0.7, "val": 0.15, "test": 0.15})
    records = _records(73)  # awkward count to expose off-by-one
    result = apply_splits(records, section, seed=11)
    seen = sorted(r["id"] for split in result.splits.values() for r in split) + sorted(
        r["id"] for r in result.unassigned
    )
    assert sorted(seen) == list(range(73))


# ---------------------------------------------------------------------------
# Stratification
# ---------------------------------------------------------------------------


def test_stratification_preserves_class_distribution() -> None:
    section = SplitsSection(
        ratios={"train": 0.5, "val": 0.5},
        stratify_by="label",
    )
    records = _records(40, classes=4)  # 10 per class
    result = apply_splits(records, section, seed=3)
    for split_name in ("train", "val"):
        per_class: dict[str, int] = {}
        for r in result.splits[split_name]:
            label = str(r["label"])
            per_class[label] = per_class.get(label, 0) + 1
        assert per_class == {"c0": 5, "c1": 5, "c2": 5, "c3": 5}, (
            split_name,
            per_class,
        )


def test_stratification_warns_on_sparse_class() -> None:
    # 3 classes; class c2 has only 1 record but 3 positive-ratio splits.
    records = (
        [{"id": i, "label": "c0"} for i in range(8)]
        + [{"id": i + 8, "label": "c1"} for i in range(8)]
        + [{"id": 16, "label": "c2"}]
    )
    section = SplitsSection(
        ratios={"train": 0.6, "val": 0.2, "test": 0.2},
        stratify_by="label",
    )
    result = apply_splits(records, section, seed=1)
    assert any("c2" in w and "sparse" in w for w in result.warnings)


def test_stratification_no_warning_when_classes_dense() -> None:
    section = SplitsSection(
        ratios={"train": 0.6, "val": 0.2, "test": 0.2},
        stratify_by="label",
    )
    result = apply_splits(_records(60, classes=2), section, seed=1)
    assert result.warnings == ()


def test_stratification_is_deterministic_for_fixed_seed() -> None:
    section = SplitsSection(
        ratios={"train": 0.7, "val": 0.3},
        stratify_by="label",
    )
    records = _records(40, classes=4)
    a = apply_splits(records, section, seed=99)
    b = apply_splits(records, section, seed=99)
    for name in a.splits:
        assert [r["id"] for r in a.splits[name]] == [r["id"] for r in b.splits[name]]


# ---------------------------------------------------------------------------
# Key-based splits
# ---------------------------------------------------------------------------


def test_key_assignment_partitions_by_explicit_mapping() -> None:
    records = [
        {"id": 1, "key": "k1"},
        {"id": 2, "key": "k2"},
        {"id": 3, "key": "k1"},
        {"id": 4, "key": "k3"},
    ]
    section = SplitsSection(
        key_assignment=KeyAssignment(
            field="key",
            mapping={"k1": "train", "k2": "val", "k3": "test"},
        )
    )
    result = apply_splits(records, section, seed=0)

    def ids(name: str) -> list[int]:
        return sorted(int(r["id"]) for r in result.splits[name])

    assert ids("train") == [1, 3]
    assert ids("val") == [2]
    assert ids("test") == [4]
    assert result.unassigned == []


def test_key_assignment_unmapped_record_raises_materialize_error() -> None:
    records = [
        {"id": 1, "key": "k1"},
        {"id": 2, "key": "kX"},  # not in mapping
    ]
    section = SplitsSection(
        key_assignment=KeyAssignment(
            field="key",
            mapping={"k1": "train", "k2": "val"},
        )
    )
    with pytest.raises(MaterializeError, match="not in mapping"):
        apply_splits(records, section, seed=0)


def test_key_assignment_missing_field_raises_materialize_error() -> None:
    records = [{"id": 1}]  # no `key` field
    section = SplitsSection(key_assignment=KeyAssignment(field="key", mapping={"k1": "train"}))
    with pytest.raises(MaterializeError):
        apply_splits(records, section, seed=0)


def test_key_assignment_creates_empty_split_for_target_with_no_records() -> None:
    records = [{"id": 1, "key": "k1"}]
    section = SplitsSection(
        key_assignment=KeyAssignment(
            field="key",
            mapping={"k1": "train", "k2": "val"},
        )
    )
    result = apply_splits(records, section, seed=0)
    assert "val" in result.splits
    assert result.splits["val"] == []


# ---------------------------------------------------------------------------
# class_balance pass-through
# ---------------------------------------------------------------------------


def test_class_balance_tag_is_passed_through_unchanged() -> None:
    section = SplitsSection(
        ratios={"train": 0.5, "val": 0.5},
        class_balance="weighted",
    )
    result = apply_splits(_records(20), section, seed=0)
    assert result.class_balance == "weighted"


def test_class_balance_does_not_resample() -> None:
    """Resampling is ModelFoundry-side; this stage just tags the result."""
    section = SplitsSection(
        ratios={"train": 0.5, "val": 0.5},
        class_balance="oversample",
    )
    records = _records(20, classes=2)
    result = apply_splits(records, section, seed=0)
    total = sum(len(s) for s in result.splits.values()) + len(result.unassigned)
    assert total == 20  # no resampling applied at the splits stage


# ---------------------------------------------------------------------------
# Seed precedence helper
# ---------------------------------------------------------------------------


def test_resolve_seed_prefers_section_seed_when_set() -> None:
    section = SplitsSection(ratios={"train": 1.0}, seed=99)
    assert resolve_seed(section, fallback=7) == 99


def test_resolve_seed_uses_fallback_when_section_seed_is_none() -> None:
    section = SplitsSection(ratios={"train": 1.0})
    assert resolve_seed(section, fallback=7) == 7


# ---------------------------------------------------------------------------
# Misc / defensive
# ---------------------------------------------------------------------------


def test_empty_record_stream_yields_empty_splits() -> None:
    section = SplitsSection(ratios={"train": 0.7, "val": 0.3})
    result = apply_splits([], section, seed=0)
    assert result.splits == {"train": [], "val": []}
    assert result.unassigned == []


# ---------------------------------------------------------------------------
# Partition-honoring splits (Story H.b)
# ---------------------------------------------------------------------------


def _r(rid: str, partition: str, label: str = "x") -> dict[str, Any]:
    return {"record_id": rid, "partition": partition, "label": label}


def test_partitioned_form_a_honors_source_partitions_verbatim() -> None:
    """Form A: records carry `partition` and Splits is effectively empty."""
    records = [_r("a", "train"), _r("b", "train"), _r("c", "test")]
    section = SplitsSection()  # no ratios, no applies_to
    result = apply_splits(records, section, seed=0)
    assert set(result.splits.keys()) == {"train", "test"}
    assert [r["record_id"] for r in result.splits["train"]] == ["a", "b"]
    assert [r["record_id"] for r in result.splits["test"]] == ["c"]


def test_partitioned_form_b_sub_partitions_named_partition() -> None:
    """Form B: applies_to: train carves train/val; test is preserved verbatim."""
    train = [_r(f"t{i}", "train") for i in range(10)]
    test = [_r(f"e{i}", "test") for i in range(3)]
    section = SplitsSection(
        ratios={"train": 0.8, "val": 0.2},
        applies_to="train",
        seed=11,
    )
    result = apply_splits(train + test, section, seed=11)
    assert set(result.splits.keys()) == {"train", "val", "test"}
    assert [r["record_id"] for r in result.splits["test"]] == ["e0", "e1", "e2"]
    sub_total = len(result.splits["train"]) + len(result.splits["val"])
    assert sub_total == 10


def test_partitioned_test_split_is_byte_equal_across_forms() -> None:
    """Form A and Form B should yield the same test split when applies_to=train."""
    train = [_r(f"t{i}", "train") for i in range(10)]
    test = [_r(f"e{i}", "test") for i in range(3)]
    form_a = apply_splits(train + test, SplitsSection(), seed=11)
    form_b = apply_splits(
        train + test,
        SplitsSection(ratios={"train": 0.8, "val": 0.2}, applies_to="train", seed=11),
        seed=11,
    )
    assert form_a.splits["test"] == form_b.splits["test"]


def test_applies_to_without_partitioned_records_errors() -> None:
    records: list[dict[str, Any]] = [{"record_id": "a", "label": "x"}]  # no partition
    section = SplitsSection(ratios={"train": 1.0}, applies_to="train")
    with pytest.raises(MaterializeError, match=r"applies_to.*no record carries"):
        apply_splits(records, section, seed=0)


def test_partitioned_records_with_ratios_no_applies_to_errors() -> None:
    """Source partitions + non-empty ratios without applies_to is contradictory."""
    records = [_r("a", "train"), _r("b", "test")]
    section = SplitsSection(ratios={"train": 0.5, "val": 0.5})
    with pytest.raises(MaterializeError, match="applies_to"):
        apply_splits(records, section, seed=0)


def test_applies_to_targeting_unknown_partition_errors() -> None:
    records = [_r("a", "train"), _r("b", "test")]
    section = SplitsSection(ratios={"train": 0.5, "val": 0.5}, applies_to="ghost")
    with pytest.raises(MaterializeError, match="ghost"):
        apply_splits(records, section, seed=0)


def test_applies_to_sub_partition_name_colliding_with_sibling_errors() -> None:
    """ratios cannot produce a split named the same as an existing sibling partition."""
    records = [_r("a", "train"), _r("b", "test")]
    section = SplitsSection(
        ratios={"train": 0.5, "test": 0.5},  # 'test' collides
        applies_to="train",
    )
    with pytest.raises(MaterializeError, match="collides"):
        apply_splits(records, section, seed=0)


def test_mixed_partitioned_and_unpartitioned_records_errors() -> None:
    records: list[dict[str, Any]] = [
        _r("a", "train"),
        {"record_id": "b", "label": "x"},
    ]
    section = SplitsSection()
    with pytest.raises(MaterializeError, match="missing 'partition'"):
        apply_splits(records, section, seed=0)
