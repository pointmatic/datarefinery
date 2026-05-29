# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Tag-driven `Splits.applies_to` across the filters → splits boundary (Story I.t / G1).

Exercises the disjoint-pool pattern end-to-end at the stage level (no disk I/O):
two `sample_per_class` filters tag a `train_pool` and a disjoint `test` pool,
then a tag-driven `Splits.applies_to: train_pool` sub-partitions the train pool
and passes the test-tagged records through verbatim as the `test` split.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datarefinery.pipeline.stages.filters import apply_pre_split_filters
from datarefinery.pipeline.stages.splits import apply_splits
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import FilterOp, SplitsSection


def _records() -> list[dict[str, Any]]:
    # 2 classes x 4 records each.
    return [{"record_id": f"{c}_{i}", "label": c} for c in ("a", "b") for i in range(4)]


def _filters() -> list[FilterOp]:
    return [
        FilterOp(
            name="train_pool_filter",
            predicate={
                "op": "sample_per_class",
                "n_per_class": 2,
                "label": "train_pool",
                "seed": 1,
            },
            stages=["pre_split"],
        ),
        FilterOp(
            name="test_pool_filter",
            predicate={
                "op": "sample_per_class",
                "n_per_class": 1,
                "label": "test",
                "exclude_already_labeled": ["train_pool"],
                "seed": 1,
            },
            stages=["pre_split"],
        ),
    ]


def test_tag_driven_splits_disjoint_pool_flow() -> None:
    tagged = apply_pre_split_filters(
        _records(), _filters(), plugin=IMAGE_PLUGIN, label_field="label"
    ).records
    section = SplitsSection(
        ratios={"train": 0.5, "val": 0.5},
        applies_to="train_pool",
        seed=11,
    )
    result = apply_splits(tagged, section, seed=11)

    assert set(result.splits.keys()) == {"train", "val", "test"}
    # train_pool: 2 per class x 2 classes = 4, ratio-split 0.5/0.5 → 2 + 2.
    assert len(result.splits["train"]) + len(result.splits["val"]) == 4
    # test: 1 per class x 2 classes = 2, passed through verbatim.
    assert len(result.splits["test"]) == 2
    # The remaining untagged records (8 - 4 - 2 = 2) land in unassigned.
    assert len(result.unassigned) == 2
    # No record appears twice across splits + unassigned.
    seen = [
        r["record_id"] for bucket in (*result.splits.values(), result.unassigned) for r in bucket
    ]
    assert len(seen) == len(set(seen)) == 8


def test_tag_driven_test_split_membership_is_filter_determined() -> None:
    """The test split is the filter-tagged set, independent of the Splits seed."""
    tagged = apply_pre_split_filters(
        _records(), _filters(), plugin=IMAGE_PLUGIN, label_field="label"
    ).records
    a = apply_splits(
        tagged,
        SplitsSection(ratios={"train": 0.5, "val": 0.5}, applies_to="train_pool", seed=11),
        seed=11,
    )
    b = apply_splits(
        tagged,
        SplitsSection(ratios={"train": 0.5, "val": 0.5}, applies_to="train_pool", seed=999),
        seed=999,
    )

    def _ids(split: list[Mapping[str, Any]]) -> list[str]:
        return sorted(r["record_id"] for r in split)

    assert _ids(a.splits["test"]) == _ids(b.splits["test"])
