# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-8 Filters stage tests (Story C.f).

Covers the stage's pre-split / post-split dispatch and the image plugin's
filter operations (`filter_by_label`, `random_sample`) end-to-end through
`plugin.operation_factory("Filters", op_name)`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from datarefinery.core.errors import MaterializeError, PluginError
from datarefinery.pipeline.stages.filters import (
    FilterResult,
    apply_post_split_filters,
    apply_pre_split_filters,
)
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import FilterOp


def _records(n: int = 10, classes: int = 2) -> list[Mapping[str, Any]]:
    return [{"id": i, "label": f"c{i % classes}", "value": i / n} for i in range(n)]


# ---------------------------------------------------------------------------
# Pre-split predicate filtering (filter_by_label)
# ---------------------------------------------------------------------------


def test_filter_by_label_include_keeps_only_named_classes() -> None:
    op = FilterOp(
        name="keep_c0",
        predicate={
            "op": "filter_by_label",
            "labels": ["c0"],
            "action": "include",
        },
    )
    result = apply_pre_split_filters(
        _records(10, classes=2),
        [op],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert all(r["label"] == "c0" for r in result.records)
    assert len(result.records) == 5
    assert result.removed == 5


def test_filter_by_label_exclude_drops_named_classes() -> None:
    op = FilterOp(
        name="drop_c1",
        predicate={
            "op": "filter_by_label",
            "labels": ["c1"],
            "action": "exclude",
        },
    )
    result = apply_pre_split_filters(
        _records(10, classes=2),
        [op],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert all(r["label"] != "c1" for r in result.records)


def test_filter_by_label_default_action_is_include() -> None:
    op = FilterOp(
        name="keep",
        predicate={"op": "filter_by_label", "labels": ["c0"]},
    )
    result = apply_pre_split_filters(
        _records(6, classes=2), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    assert all(r["label"] == "c0" for r in result.records)


def test_filter_by_label_unknown_action_raises_plugin_error() -> None:
    op = FilterOp(
        name="bad",
        predicate={
            "op": "filter_by_label",
            "labels": ["c0"],
            "action": "invert",
        },
    )
    with pytest.raises(PluginError, match="action"):
        apply_pre_split_filters(
            _records(4),
            [op],
            plugin=IMAGE_PLUGIN,
            label_field="label",
        )


def test_filter_by_label_without_label_field_raises_plugin_error() -> None:
    op = FilterOp(
        name="x",
        predicate={"op": "filter_by_label", "labels": ["c0"]},
    )
    with pytest.raises(PluginError, match=r"Labels\.field"):
        apply_pre_split_filters(_records(4), [op], plugin=IMAGE_PLUGIN)


# ---------------------------------------------------------------------------
# Pre-split sampling (random_sample) - reproducibility
# ---------------------------------------------------------------------------


def test_random_sample_with_fixed_seed_is_reproducible() -> None:
    op = FilterOp(
        name="subsample",
        predicate={"op": "random_sample", "fraction": 0.5, "seed": 42},
        seed=42,
    )
    a = apply_pre_split_filters(_records(20), [op], plugin=IMAGE_PLUGIN, label_field="label")
    b = apply_pre_split_filters(_records(20), [op], plugin=IMAGE_PLUGIN, label_field="label")
    assert [r["id"] for r in a.records] == [r["id"] for r in b.records]


def test_random_sample_different_seeds_produce_different_subsets() -> None:
    op_a = FilterOp(
        name="s",
        predicate={"op": "random_sample", "fraction": 0.5, "seed": 1},
        seed=1,
    )
    op_b = FilterOp(
        name="s",
        predicate={"op": "random_sample", "fraction": 0.5, "seed": 2},
        seed=2,
    )
    a = apply_pre_split_filters(_records(20), [op_a], plugin=IMAGE_PLUGIN, label_field="label")
    b = apply_pre_split_filters(_records(20), [op_b], plugin=IMAGE_PLUGIN, label_field="label")
    assert [r["id"] for r in a.records] != [r["id"] for r in b.records]


def test_random_sample_preserves_original_order_of_chosen_records() -> None:
    op = FilterOp(
        name="s",
        predicate={"op": "random_sample", "n": 5, "seed": 7},
        seed=7,
    )
    result = apply_pre_split_filters(_records(20), [op], plugin=IMAGE_PLUGIN, label_field="label")
    ids = [r["id"] for r in result.records]
    assert ids == sorted(ids)


def test_random_sample_n_supersedes_total_count() -> None:
    op = FilterOp(
        name="s",
        predicate={"op": "random_sample", "n": 100, "seed": 0},
        seed=0,
    )
    result = apply_pre_split_filters(_records(10), [op], plugin=IMAGE_PLUGIN, label_field="label")
    assert len(result.records) == 10


def test_random_sample_requires_fraction_or_n_not_both() -> None:
    op = FilterOp(
        name="s",
        predicate={
            "op": "random_sample",
            "fraction": 0.5,
            "n": 5,
            "seed": 1,
        },
        seed=1,
    )
    with pytest.raises(PluginError, match="exactly one of"):
        apply_pre_split_filters(_records(10), [op], plugin=IMAGE_PLUGIN, label_field="label")


def test_random_sample_requires_seed() -> None:
    op = FilterOp(
        name="s",
        predicate={"op": "random_sample", "fraction": 0.5},
    )
    with pytest.raises(PluginError, match="seed"):
        apply_pre_split_filters(_records(10), [op], plugin=IMAGE_PLUGIN, label_field="label")


def test_random_sample_fraction_out_of_range_raises() -> None:
    op = FilterOp(
        name="s",
        predicate={"op": "random_sample", "fraction": 1.5, "seed": 1},
        seed=1,
    )
    with pytest.raises(PluginError, match="in \\[0, 1\\]"):
        apply_pre_split_filters(_records(10), [op], plugin=IMAGE_PLUGIN, label_field="label")


# ---------------------------------------------------------------------------
# Stage filtering: applies_at (pre_split / post_split) dispatch
# ---------------------------------------------------------------------------


def test_pre_split_skips_post_only_filters() -> None:
    post_only = FilterOp(
        name="post",
        predicate={"op": "filter_by_label", "labels": ["c0"]},
        stages=["post_split"],
        splits=["train"],
    )
    result = apply_pre_split_filters(
        _records(6),
        [post_only],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert len(result.records) == 6  # untouched
    assert result.removed == 0


def test_post_split_applies_only_to_named_splits() -> None:
    op = FilterOp(
        name="train_only",
        predicate={"op": "filter_by_label", "labels": ["c0"]},
        stages=["post_split"],
        splits=["train"],
    )
    splits = {
        "train": _records(6, classes=2),
        "val": _records(4, classes=2),
    }
    out = apply_post_split_filters(splits, [op], plugin=IMAGE_PLUGIN, label_field="label")
    assert all(r["label"] == "c0" for r in out["train"].records)
    assert len(out["val"].records) == 4  # untouched
    assert out["val"].removed == 0


def test_post_split_filter_with_no_splits_listed_does_nothing() -> None:
    op = FilterOp(
        name="orphan",
        predicate={"op": "filter_by_label", "labels": ["c0"]},
        stages=["post_split"],
        splits=[],  # no splits named -> no application
    )
    splits = {"train": _records(6, classes=2)}
    out = apply_post_split_filters(splits, [op], plugin=IMAGE_PLUGIN, label_field="label")
    assert len(out["train"].records) == 6


def test_filter_with_both_stages_runs_in_both() -> None:
    op = FilterOp(
        name="both",
        predicate={"op": "filter_by_label", "labels": ["c0"]},
        stages=["pre_split", "post_split"],
        splits=["train"],
    )
    pre = apply_pre_split_filters(
        _records(8),
        [op],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert all(r["label"] == "c0" for r in pre.records)


# ---------------------------------------------------------------------------
# Empty-class warning
# ---------------------------------------------------------------------------


def test_empty_class_warning_when_filter_drops_a_class() -> None:
    op = FilterOp(
        name="drop_c1",
        predicate={
            "op": "filter_by_label",
            "labels": ["c1"],
            "action": "exclude",
        },
    )
    result = apply_pre_split_filters(
        _records(6, classes=2),
        [op],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert any("c1" in w and "emptied" in w for w in result.warnings)


def test_no_empty_class_warning_when_classes_remain_populated() -> None:
    op = FilterOp(
        name="halve",
        predicate={"op": "random_sample", "fraction": 0.5, "seed": 42},
        seed=42,
    )
    result = apply_pre_split_filters(
        _records(20, classes=2),
        [op],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert result.warnings == ()


def test_no_empty_class_warning_without_label_field() -> None:
    op = FilterOp(
        name="halve",
        predicate={"op": "random_sample", "fraction": 0.5, "seed": 42},
        seed=42,
    )
    result = apply_pre_split_filters(_records(20, classes=2), [op], plugin=IMAGE_PLUGIN)
    assert result.warnings == ()


def test_post_split_empty_class_warning_includes_split_name() -> None:
    op = FilterOp(
        name="drop_c1",
        predicate={
            "op": "filter_by_label",
            "labels": ["c1"],
            "action": "exclude",
        },
        stages=["post_split"],
        splits=["train"],
    )
    splits = {"train": _records(6, classes=2)}
    out = apply_post_split_filters(splits, [op], plugin=IMAGE_PLUGIN, label_field="label")
    assert any("'train'" in w for w in out["train"].warnings)


# ---------------------------------------------------------------------------
# Misc / dispatch errors
# ---------------------------------------------------------------------------


def test_predicate_missing_op_key_raises_materialize_error() -> None:
    op = FilterOp(name="bad", predicate={"labels": ["c0"]})
    with pytest.raises(MaterializeError, match="missing 'op'"):
        apply_pre_split_filters(_records(2), [op], plugin=IMAGE_PLUGIN, label_field="label")


def test_filters_run_in_declared_order() -> None:
    """Earlier filters' output feeds later filters."""
    keep_c0 = FilterOp(
        name="keep_c0",
        predicate={"op": "filter_by_label", "labels": ["c0"]},
    )
    halve = FilterOp(
        name="halve",
        predicate={"op": "random_sample", "fraction": 0.5, "seed": 13},
        seed=13,
    )
    result = apply_pre_split_filters(
        _records(20, classes=2),
        [keep_c0, halve],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert all(r["label"] == "c0" for r in result.records)
    # 20 / 2 classes = 10 c0; halve to 5
    assert len(result.records) == 5


def test_filter_result_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    fr = FilterResult(records=[], warnings=(), removed=0)
    with pytest.raises(FrozenInstanceError):
        fr.removed = 1  # type: ignore[misc]


def test_empty_filter_list_is_passthrough() -> None:
    records = _records(5)
    result = apply_pre_split_filters(records, [], plugin=IMAGE_PLUGIN, label_field="label")
    assert [r["id"] for r in result.records] == [r["id"] for r in records]
    assert result.removed == 0
    assert result.warnings == ()
