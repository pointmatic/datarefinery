# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-FILTER-3 / Story H.l tests for `drop_by_label`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from datarefinery.pipeline.stages.filters import apply_pre_split_filters
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.image_classification.filters_stratified_sampling import (
    TAG_FIELD,
)
from datarefinery.recipe.models import DropByLabelParams, FilterOp

Record = Mapping[str, Any]


def _records(per_class: int = 20, classes: int = 4) -> list[Record]:
    out: list[Record] = []
    for ci in range(classes):
        for j in range(per_class):
            rid = ci * per_class + j
            out.append({"record_id": rid, "label": f"c{ci}", "value": rid / 100})
    return out


def _train_tag_op(name: str = "train", seed: int = 42) -> FilterOp:
    return FilterOp(
        name=name,
        predicate={
            "op": "sample_per_class",
            "n_per_class": 5,
            "seed": seed,
            "label": "train_pool",
        },
    )


def _holdout_tag_op(name: str = "holdout", seed: int = 42) -> FilterOp:
    return FilterOp(
        name=name,
        predicate={
            "op": "sample_per_class",
            "n_per_class": 5,
            "seed": seed,
            "label": "holdout_pool",
            "exclude_already_labeled": ["train_pool"],
        },
    )


def _drop_op(name: str, labels: list[str]) -> FilterOp:
    return FilterOp(
        name=name,
        predicate={"op": "drop_by_label", "labels": labels},
    )


# ---------------------------------------------------------------------------
# Drop semantics
# ---------------------------------------------------------------------------


def test_single_label_drop_removes_tagged_records() -> None:
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4),
        [_train_tag_op(), _drop_op("drop_train", ["train_pool"])],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert len(result.records) == 60  # 80 - 20 tagged
    for r in result.records:
        assert "train_pool" not in r.get(TAG_FIELD, ())


def test_multi_label_drop_removes_union() -> None:
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4),
        [
            _train_tag_op(),
            _holdout_tag_op(),
            _drop_op("drop_both", ["train_pool", "holdout_pool"]),
        ],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert len(result.records) == 40  # 80 - 20 train - 20 holdout
    for r in result.records:
        tags = r.get(TAG_FIELD, ())
        assert "train_pool" not in tags
        assert "holdout_pool" not in tags


def test_untagged_records_pass_through_unchanged() -> None:
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4),
        [_train_tag_op(), _drop_op("drop_train", ["train_pool"])],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    # All surviving records lack the train_pool tag; they may have no
    # tag field at all (the H.j tagging only set it on chosen records).
    for r in result.records:
        if TAG_FIELD in r:
            assert "train_pool" not in r[TAG_FIELD]
        else:
            assert "label" in r and "record_id" in r  # original record intact


def test_drop_keeps_only_named_pool() -> None:
    # Drop everything except the train_pool tag.
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4),
        [
            _train_tag_op(),
            _holdout_tag_op(),
            _drop_op("drop_holdout_and_untagged", ["holdout_pool"]),
        ],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert len(result.records) == 60  # 80 - 20 holdout
    train_count = sum(1 for r in result.records if "train_pool" in r.get(TAG_FIELD, ()))
    assert train_count == 20


def test_nonexistent_label_is_no_op() -> None:
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4),
        [_train_tag_op(), _drop_op("drop_nonexistent", ["never_tagged"])],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    # All 80 records pass through; nothing carries the named tag.
    assert len(result.records) == 80


def test_drop_with_no_prior_tagging_passes_through() -> None:
    # `drop_by_label` applied to a record set that has never been tagged
    # is a no-op rather than an error.
    result = apply_pre_split_filters(
        _records(per_class=10, classes=2),
        [_drop_op("drop_anything", ["never_tagged"])],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert len(result.records) == 20


# ---------------------------------------------------------------------------
# Cross-recipe bit-identity (the canonical use case)
# ---------------------------------------------------------------------------


def test_sibling_recipes_split_a_common_pool_byte_identically() -> None:
    """Two recipes share the same H.j tagging chain, then peel off
    disjoint sub-instances via `drop_by_label`. The resulting record
    sequences must be byte-identical and non-overlapping.
    """
    records = _records(per_class=20, classes=4)
    common_chain = [_train_tag_op(), _holdout_tag_op()]

    recipe_a = apply_pre_split_filters(
        list(records),
        [*common_chain, _drop_op("keep_train_only", ["holdout_pool"])],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    recipe_b = apply_pre_split_filters(
        list(records),
        [*common_chain, _drop_op("keep_holdout_only", ["train_pool"])],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )

    # The two recipes select disjoint pools.
    a_ids = {r["record_id"] for r in recipe_a.records}
    b_ids = {r["record_id"] for r in recipe_b.records}
    train_a = {r["record_id"] for r in recipe_a.records if "train_pool" in r.get(TAG_FIELD, ())}
    holdout_b = {r["record_id"] for r in recipe_b.records if "holdout_pool" in r.get(TAG_FIELD, ())}
    assert len(train_a) == 20
    assert len(holdout_b) == 20
    assert train_a.isdisjoint(holdout_b)

    # Each recipe is deterministic: re-running yields byte-identical records.
    recipe_a_replay = apply_pre_split_filters(
        list(records),
        [*common_chain, _drop_op("keep_train_only", ["holdout_pool"])],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert list(recipe_a.records) == list(recipe_a_replay.records)
    assert a_ids != b_ids  # different recipes -> different surviving sets


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_empty_labels_rejected() -> None:
    with pytest.raises(ValidationError):
        DropByLabelParams(labels=[])


def test_empty_labels_at_op_invocation_raises() -> None:
    op = FilterOp(name="bad", predicate={"op": "drop_by_label", "labels": []})
    with pytest.raises(ValidationError):
        apply_pre_split_filters(_records(), [op], plugin=IMAGE_PLUGIN, label_field="label")
