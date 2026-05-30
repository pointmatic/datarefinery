# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-FILTER-2 / Story H.k tests for `sample_per_class_fractional`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from datarefinery.core.errors import PluginError
from datarefinery.pipeline.stages.filters import apply_pre_split_filters
from datarefinery.pipeline.workers import run_parallel
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.image_classification.filters_stratified_sampling import (
    TAG_FIELD,
)
from datarefinery.recipe.models import FilterOp, SamplePerClassFractionalParams

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
    n_per_class_base: int,
    fractions: dict[str, float] | None = None,
    seed: int,
    label: str | None = None,
    exclude_already_labeled: list[str] | None = None,
) -> FilterOp:
    params: dict[str, Any] = {"n_per_class_base": n_per_class_base}
    if fractions is not None:
        params["fractions"] = fractions
    if label is not None:
        params["label"] = label
    if exclude_already_labeled is not None:
        params["exclude_already_labeled"] = exclude_already_labeled
    return FilterOp(name=name, op="sample_per_class_fractional", params=params, seed=seed)


def _counts(records: list[Record]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Per-class floor formula
# ---------------------------------------------------------------------------


def test_floor_formula_yields_per_class_targets() -> None:
    op = _filter_op(
        "imbalance",
        n_per_class_base=10,
        fractions={"c0": 1.0, "c1": 0.5, "c2": 0.25, "c3": 0.1},
        seed=42,
    )
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    assert _counts(result.records) == {"c0": 10, "c1": 5, "c2": 2, "c3": 1}


def test_missing_class_in_fractions_defaults_to_one() -> None:
    op = _filter_op(
        "default_one",
        n_per_class_base=10,
        fractions={"c1": 0.3},  # c0/c2/c3 unspecified -> 1.0 each
        seed=42,
    )
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    assert _counts(result.records) == {"c0": 10, "c1": 3, "c2": 10, "c3": 10}


def test_fractions_zero_drops_class_entirely() -> None:
    op = _filter_op(
        "drop_c1",
        n_per_class_base=10,
        fractions={"c0": 1.0, "c1": 0.0, "c2": 1.0, "c3": 1.0},
        seed=42,
    )
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    counts = _counts(result.records)
    assert "c1" not in counts
    assert counts == {"c0": 10, "c2": 10, "c3": 10}


def test_empty_fractions_dict_keeps_base_count_for_all_classes() -> None:
    op = _filter_op("all_default", n_per_class_base=5, seed=42)
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    assert _counts(result.records) == {"c0": 5, "c1": 5, "c2": 5, "c3": 5}


def test_floor_truncates_non_integer_products() -> None:
    # n_per_class_base=7, fraction=0.5 -> floor(3.5)=3
    op = _filter_op(
        "truncate",
        n_per_class_base=7,
        fractions={"c0": 0.5, "c1": 0.5},
        seed=42,
    )
    result = apply_pre_split_filters(
        _records(per_class=20, classes=2), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    assert _counts(result.records) == {"c0": 3, "c1": 3}


# ---------------------------------------------------------------------------
# Determinism + invariance
# ---------------------------------------------------------------------------


def test_fixed_seed_is_reproducible_across_calls() -> None:
    op = _filter_op(
        "imbalance",
        n_per_class_base=10,
        fractions={"c0": 1.0, "c1": 0.5, "c2": 0.25, "c3": 0.1},
        seed=42,
    )
    records = _records(per_class=20, classes=4)
    a = apply_pre_split_filters(list(records), [op], plugin=IMAGE_PLUGIN, label_field="label")
    b = apply_pre_split_filters(list(records), [op], plugin=IMAGE_PLUGIN, label_field="label")
    assert [r["record_id"] for r in a.records] == [r["record_id"] for r in b.records]


def test_selection_invariant_to_input_order() -> None:
    records = _records(per_class=20, classes=4)
    op = _filter_op(
        "imbalance",
        n_per_class_base=10,
        fractions={"c0": 1.0, "c1": 0.5, "c2": 0.25, "c3": 0.1},
        seed=42,
    )
    forward = apply_pre_split_filters(list(records), [op], plugin=IMAGE_PLUGIN, label_field="label")
    reversed_in = apply_pre_split_filters(
        list(reversed(records)), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    forward_ids = {r["record_id"] for r in forward.records}
    reversed_ids = {r["record_id"] for r in reversed_in.records}
    assert forward_ids == reversed_ids


# ---------------------------------------------------------------------------
# Label tagging consistency with H.j
# ---------------------------------------------------------------------------


def test_label_tag_non_destructive_full_pass_through() -> None:
    op = _filter_op(
        "tag",
        n_per_class_base=10,
        fractions={"c0": 1.0, "c1": 0.5, "c2": 0.25, "c3": 0.1},
        seed=42,
        label="train_pool",
    )
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    assert len(result.records) == 80
    tagged = [r for r in result.records if "train_pool" in r.get(TAG_FIELD, ())]
    assert len(tagged) == 10 + 5 + 2 + 1


# ---------------------------------------------------------------------------
# Disjoint-pool chained with sample_per_class
# ---------------------------------------------------------------------------


def test_disjoint_pool_chained_with_sample_per_class() -> None:
    train_op = FilterOp(
        name="train",
        op="sample_per_class",
        params={"n_per_class": 5, "label": "train_pool"},
        seed=42,
    )
    holdout_op = _filter_op(
        "holdout",
        n_per_class_base=10,
        fractions={"c0": 0.5, "c1": 0.5, "c2": 0.5, "c3": 0.5},
        seed=42,
        label="holdout_pool",
        exclude_already_labeled=["train_pool"],
    )
    result = apply_pre_split_filters(
        _records(per_class=20, classes=4),
        [train_op, holdout_op],
        plugin=IMAGE_PLUGIN,
        label_field="label",
    )
    train_ids: set[int] = set()
    holdout_ids: set[int] = set()
    for r in result.records:
        tags = r.get(TAG_FIELD, ())
        if "train_pool" in tags:
            train_ids.add(r["record_id"])
        if "holdout_pool" in tags:
            holdout_ids.add(r["record_id"])
    assert len(train_ids) == 20  # 5 per class * 4 classes
    assert len(holdout_ids) == 20  # 5 per class (floor(10*0.5)) * 4 classes
    assert train_ids.isdisjoint(holdout_ids)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_n_per_class_base_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        SamplePerClassFractionalParams(n_per_class_base=0, fractions={})


def test_fraction_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        SamplePerClassFractionalParams(n_per_class_base=10, fractions={"c0": 1.5})


def test_negative_fraction_rejected() -> None:
    with pytest.raises(ValidationError):
        SamplePerClassFractionalParams(n_per_class_base=10, fractions={"c0": -0.1})


def test_missing_seed_raises_plugin_error() -> None:
    op = FilterOp(
        name="s",
        op="sample_per_class_fractional",
        params={"n_per_class_base": 5},
    )
    with pytest.raises(PluginError, match="seed"):
        apply_pre_split_filters(
            _records(per_class=10, classes=2), [op], plugin=IMAGE_PLUGIN, label_field="label"
        )


def test_missing_label_field_raises_plugin_error() -> None:
    op = _filter_op("s", n_per_class_base=5, seed=1)
    with pytest.raises(PluginError, match=r"Labels\.field"):
        apply_pre_split_filters(_records(), [op], plugin=IMAGE_PLUGIN, label_field=None)


# ---------------------------------------------------------------------------
# Workers determinism (downstream byte-identical contract)
# ---------------------------------------------------------------------------


def _identity_worker(record: Record, prs: int) -> Record:
    del prs
    return dict(record)


@pytest.mark.slow
def test_workers_byte_identical_after_sample_per_class_fractional() -> None:
    op = _filter_op(
        "tag",
        n_per_class_base=10,
        fractions={"c0": 1.0, "c1": 0.5, "c2": 0.25, "c3": 0.1},
        seed=42,
        label="train_pool",
    )
    filtered = apply_pre_split_filters(
        _records(per_class=20, classes=4), [op], plugin=IMAGE_PLUGIN, label_field="label"
    )
    baseline = list(run_parallel(seed=42, fn=_identity_worker, items=filtered.records, workers=1))
    for workers in (2, 4):
        out = list(
            run_parallel(seed=42, fn=_identity_worker, items=filtered.records, workers=workers)
        )
        assert out == baseline
