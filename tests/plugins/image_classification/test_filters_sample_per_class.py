# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-FILTER-1 / Story H.j tests for `sample_per_class`.

Exercises balanced subsampling, label tagging, the disjoint-pool pattern,
and downstream byte-identical behavior under ProcessPoolExecutor at
workers=1/2/4 (the determinism contract in ``pipeline.workers``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from datarefinery.core.errors import PluginError
from datarefinery.pipeline.stages.filters import apply_pre_split_filters
from datarefinery.pipeline.workers import run_parallel
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.image_classification.filters_sample_per_class import (
    TAG_FIELD,
)
from datarefinery.recipe.models import FilterOp, SamplePerClassParams

Record = Mapping[str, Any]


def _records(per_class: int = 20, classes: int = 4) -> list[Record]:
    out: list[Record] = []
    for ci in range(classes):
        for j in range(per_class):
            rid = ci * per_class + j
            out.append({"record_id": rid, "label": f"c{ci}", "value": rid / 100})
    return out


def _filter_op(
    name: str,
    *,
    n_per_class: int,
    seed: int,
    label: str | None = None,
    exclude_already_labeled: list[str] | None = None,
) -> FilterOp:
    params: dict[str, Any] = {"n_per_class": n_per_class}
    if label is not None:
        params["label"] = label
    if exclude_already_labeled is not None:
        params["exclude_already_labeled"] = exclude_already_labeled
    return FilterOp(name=name, op="sample_per_class", params=params, seed=seed)


# ---------------------------------------------------------------------------
# Balanced subsample without tagging
# ---------------------------------------------------------------------------


def test_balanced_subsample_yields_n_per_class_records_per_label() -> None:
    op = _filter_op("balanced", n_per_class=5, seed=42)
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    counts: dict[str, int] = {}
    for r in result.records:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    assert counts == {"c0": 5, "c1": 5, "c2": 5, "c3": 5}
    assert len(result.records) == 20


def test_n_per_class_capped_by_available_records() -> None:
    op = _filter_op("oversample", n_per_class=100, seed=1)
    result = apply_pre_split_filters(
        _records(per_class=10, classes=2), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    counts: dict[str, int] = {}
    for r in result.records:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    assert counts == {"c0": 10, "c1": 10}


def test_fixed_seed_is_reproducible_across_calls() -> None:
    op = _filter_op("balanced", n_per_class=5, seed=42)
    records = _records(per_class=20, classes=4)
    a = apply_pre_split_filters(list(records), [op], plugin=IMAGE_PLUGIN, label_field="label")
    b = apply_pre_split_filters(list(records), [op], plugin=IMAGE_PLUGIN, label_field="label")
    assert [r["record_id"] for r in a.records] == [r["record_id"] for r in b.records]


def test_different_seeds_pick_different_records() -> None:
    records = _records(per_class=20, classes=4)
    a = apply_pre_split_filters(
        list(records),
        [_filter_op("s", n_per_class=5, seed=1)],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    b = apply_pre_split_filters(
        list(records),
        [_filter_op("s", n_per_class=5, seed=999)],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    assert {r["record_id"] for r in a.records} != {r["record_id"] for r in b.records}


def test_selection_invariant_to_input_order() -> None:
    records = _records(per_class=20, classes=4)
    forward = apply_pre_split_filters(
        list(records),
        [_filter_op("s", n_per_class=5, seed=42)],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    reversed_in = apply_pre_split_filters(
        list(reversed(records)),
        [_filter_op("s", n_per_class=5, seed=42)],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    forward_ids = {r["record_id"] for r in forward.records}
    reversed_ids = {r["record_id"] for r in reversed_in.records}
    assert forward_ids == reversed_ids


def test_output_preserves_input_order() -> None:
    records = _records(per_class=20, classes=4)
    result = apply_pre_split_filters(
        records, [_filter_op("s", n_per_class=5, seed=42)], plugin=IMAGE_PLUGIN, label_field="label"
    )
    ids = [r["record_id"] for r in result.records]
    assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Label tagging on surviving records
# ---------------------------------------------------------------------------


def test_label_tag_emitted_non_destructive_marks_only_chosen() -> None:
    op = _filter_op("train_pool", n_per_class=5, seed=42, label="train_pool")
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    # Non-destructive: all 80 records pass through.
    assert len(result.records) == 80
    tagged = [r for r in result.records if "train_pool" in r.get(TAG_FIELD, ())]
    untagged = [r for r in result.records if TAG_FIELD not in r]
    assert len(tagged) == 20  # 5 per class * 4 classes
    assert len(untagged) == 60


def test_no_label_no_tag_field_added() -> None:
    op = _filter_op("balanced", n_per_class=5, seed=42)
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    for r in result.records:
        assert TAG_FIELD not in r


# ---------------------------------------------------------------------------
# Disjoint-pool selection via chained ops
# ---------------------------------------------------------------------------


def test_disjoint_pool_via_exclude_already_labeled() -> None:
    train_op = _filter_op("train", n_per_class=5, seed=42, label="train_pool")
    test_op = _filter_op(
        "test",
        n_per_class=5,
        seed=42,
        label="test_pool",
        exclude_already_labeled=["train_pool"],
    )
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4),
        [train_op, test_op],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    # Non-destructive chain: all 80 records pass through; train and test
    # pools are tagged disjointly.
    assert len(result.records) == 80
    train_ids: set[int] = set()
    test_ids: set[int] = set()
    for r in result.records:
        tags = r.get(TAG_FIELD, ())
        if "train_pool" in tags:
            train_ids.add(r["record_id"])
        if "test_pool" in tags:
            test_ids.add(r["record_id"])
    assert len(train_ids) == 20
    assert len(test_ids) == 20
    assert train_ids.isdisjoint(test_ids)


def test_exclude_without_existing_tag_keeps_all_candidates() -> None:
    op = _filter_op(
        "s",
        n_per_class=5,
        seed=42,
        label="kept",
        exclude_already_labeled=["never_tagged"],
    )
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    # Non-destructive marking: full pass-through, 20 tagged.
    assert len(result.records) == 80
    tagged = [r for r in result.records if "kept" in r.get(TAG_FIELD, ())]
    assert len(tagged) == 20


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_n_per_class_must_be_positive() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SamplePerClassParams(n_per_class=0)


def test_missing_seed_raises_plugin_error() -> None:
    op = FilterOp(name="s", op="sample_per_class", params={"n_per_class": 5})
    with pytest.raises(PluginError, match="seed"):
        apply_pre_split_filters(
            _records(per_class=10, classes=2), [op], plugin=IMAGE_PLUGIN, label_field="label"
        )


def test_missing_label_field_raises_plugin_error() -> None:
    op = _filter_op("s", n_per_class=5, seed=1)
    with pytest.raises(PluginError, match=r"Labels\.field"):
        apply_pre_split_filters(_records(), [op], plugin=IMAGE_PLUGIN, label_field=None)


# ---------------------------------------------------------------------------
# Determinism across workers=1/2/4 (downstream byte-identical contract)
# ---------------------------------------------------------------------------


def _identity_worker(record: Record, prs: int) -> Record:
    del prs  # not used by identity op
    return dict(record)


@pytest.mark.slow
def test_workers_byte_identical_after_sample_per_class() -> None:
    """sample_per_class output, threaded through ``run_parallel`` at three
    worker counts, must produce identical record sequences. This honors
    the determinism contract in ``pipeline.workers`` for any pipeline
    that begins with a balanced subsample.
    """
    op = _filter_op("s", n_per_class=5, seed=42, label="train_pool")
    filtered = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    baseline = list(run_parallel(seed=42, fn=_identity_worker, items=filtered.records, workers=1))
    for workers in (2, 4):
        out = list(
            run_parallel(seed=42, fn=_identity_worker, items=filtered.records, workers=workers)
        )
        assert out == baseline
