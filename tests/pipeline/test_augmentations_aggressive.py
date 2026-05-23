# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.p — FR-11 aggressive-mode framework tests (stub realizer).

These tests exercise the framework only — H.q lands the first concrete
ops (``random_crop``, ``horizontal_flip``). The stub realizer here just
records the seed and variant_index so we can check the determinism
contract and the metadata-tagging shape without depending on Pillow.

Worker functions used by the parallel-determinism test are at module
scope so they pickle cleanly for :class:`ProcessPoolExecutor`. The
realizer-registry is built per test from these module-level stubs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.stages.augmentations import (
    realize_aggressive_split,
)
from datarefinery.recipe.models import AugmentationOp


def _records(n: int) -> list[dict[str, Any]]:
    return [{"record_id": f"img_{i:03d}", "label": i % 3} for i in range(n)]


# ---------------------------------------------------------------------------
# Module-level stub realizers (picklable for ProcessPoolExecutor)
# ---------------------------------------------------------------------------


def _stub_realizer(record: Mapping[str, Any], seed: int, variant_index: int) -> dict[str, Any]:
    """Deterministic stub: copies record + records the seed and index it saw."""
    out = dict(record)
    out["_observed_seed"] = seed
    out["_observed_variant_index"] = variant_index
    return out


def _identity_realizer(record: Mapping[str, Any], seed: int, variant_index: int) -> dict[str, Any]:
    """Realizer that ignores seed/variant; identical output for every variant."""
    del seed, variant_index
    return dict(record)


REGISTRY = {
    "horizontal_flip": _stub_realizer,
    "random_crop": _stub_realizer,
    "identity": _identity_realizer,
}


# ---------------------------------------------------------------------------
# Lazy-mode pass-through: aggressive dispatcher must not touch lazy ops
# ---------------------------------------------------------------------------


def test_only_lazy_ops_yields_input_records_unchanged() -> None:
    records = _records(5)
    ops = [
        AugmentationOp(
            name="lazy_flip",
            op="horizontal_flip",
            params={"p": 0.5},
            splits=["train"],
            seed=1,
        ),
    ]
    out = realize_aggressive_split(records, ops, global_seed=42, realizer_registry=REGISTRY)
    assert out == records


def test_no_ops_yields_input_records_unchanged() -> None:
    records = _records(3)
    out = realize_aggressive_split(records, [], global_seed=42, realizer_registry=REGISTRY)
    assert out == records


# ---------------------------------------------------------------------------
# Aggressive mode: N x expansion record multiplication + metadata
# ---------------------------------------------------------------------------


def _aggressive_op(expansion: int) -> AugmentationOp:
    return AugmentationOp(
        name="aug",
        op="horizontal_flip",
        params={"p": 0.5},
        splits=["train"],
        seed=1,
        materialization="aggressive",
        expansion=expansion,
    )


def test_aggressive_produces_N_times_expansion_records() -> None:
    records = _records(10)
    out = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=4)],
        global_seed=42,
        realizer_registry=REGISTRY,
    )
    assert len(out) == 10 * 4


def test_aggressive_records_carry_source_record_id_and_variant_index() -> None:
    records = _records(3)
    out = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=2)],
        global_seed=42,
        realizer_registry=REGISTRY,
    )
    grouped: dict[str, list[int]] = {}
    for r in out:
        assert "source_record_id" in r
        assert "variant_index" in r
        assert isinstance(r["variant_index"], int)
        grouped.setdefault(str(r["source_record_id"]), []).append(r["variant_index"])
    assert grouped == {
        "img_000": [0, 1],
        "img_001": [0, 1],
        "img_002": [0, 1],
    }


def test_aggressive_record_ids_are_unique_and_sorted() -> None:
    records = _records(4)
    out = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=3)],
        global_seed=42,
        realizer_registry=REGISTRY,
    )
    record_ids = [r["record_id"] for r in out]
    assert len(set(record_ids)) == len(record_ids)
    assert record_ids == sorted(record_ids)


def test_aggressive_seed_depends_only_on_global_op_record_variant() -> None:
    """The per-variant seed each realizer sees must be a pure function of
    ``(global_seed, op_id, source_record_id, variant_index)``."""
    records = _records(3)
    out = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=2)],
        global_seed=42,
        realizer_registry=REGISTRY,
    )
    # Two records with the same (op_id, source_record_id, variant_index) but
    # different global seeds must produce different seeds.
    other = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=2)],
        global_seed=43,
        realizer_registry=REGISTRY,
    )
    seeds_42 = [(r["source_record_id"], r["variant_index"], r["_observed_seed"]) for r in out]
    seeds_43 = [(r["source_record_id"], r["variant_index"], r["_observed_seed"]) for r in other]
    # Same shape, different seed values per slot.
    assert {(s, v) for s, v, _ in seeds_42} == {(s, v) for s, v, _ in seeds_43}
    assert {seed for _, _, seed in seeds_42} != {seed for _, _, seed in seeds_43}


# ---------------------------------------------------------------------------
# Worker-count determinism: workers=1, 2, 4 produce byte-identical output
# ---------------------------------------------------------------------------


def _dump_for_compare(records: list[dict[str, Any]]) -> str:
    """JSON-stable rendering for byte-comparison across worker counts."""
    import json

    return json.dumps(
        [{k: r[k] for k in sorted(r)} for r in records],
        sort_keys=True,
        separators=(",", ":"),
    )


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_workers_1_2_4_produce_byte_identical_aggressive_output(
    workers: int,
) -> None:
    records = _records(10)
    out_1 = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=4)],
        global_seed=42,
        realizer_registry=REGISTRY,
        workers=1,
    )
    out_w = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=4)],
        global_seed=42,
        realizer_registry=REGISTRY,
        workers=workers,
    )
    assert _dump_for_compare(out_1) == _dump_for_compare(out_w)


# ---------------------------------------------------------------------------
# Op composition: two aggressive ops in sequence compose as documented
# ---------------------------------------------------------------------------


def test_two_aggressive_ops_compose_multiplicatively() -> None:
    """``expansion=2`` then ``expansion=3`` -> N * 2 * 3 = 6N records."""
    records = _records(2)
    ops = [
        AugmentationOp(
            name="first",
            op="horizontal_flip",
            params={},
            splits=["train"],
            seed=1,
            materialization="aggressive",
            expansion=2,
        ),
        AugmentationOp(
            name="second",
            op="random_crop",
            params={},
            splits=["train"],
            seed=2,
            materialization="aggressive",
            expansion=3,
        ),
    ]
    out = realize_aggressive_split(records, ops, global_seed=42, realizer_registry=REGISTRY)
    assert len(out) == 2 * 2 * 3


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_aggressive_op_missing_from_registry_raises() -> None:
    records = _records(2)
    op = AugmentationOp(
        name="aug",
        op="not_a_real_op",
        params={},
        splits=["train"],
        seed=1,
        materialization="aggressive",
        expansion=2,
    )
    with pytest.raises(MaterializeError, match="no realizer registered"):
        realize_aggressive_split(records, [op], global_seed=42, realizer_registry=REGISTRY)


def test_non_train_split_raises_in_aggressive_dispatch() -> None:
    records = _records(2)
    # Bypass validator check 5 to exercise the defensive re-check.
    op = AugmentationOp(
        name="bad",
        op="horizontal_flip",
        params={},
        splits=["train", "val"],
        seed=1,
        materialization="aggressive",
        expansion=2,
    )
    with pytest.raises(MaterializeError, match="non-train"):
        realize_aggressive_split(records, [op], global_seed=42, realizer_registry=REGISTRY)


def test_explicit_non_train_split_argument_raises() -> None:
    records = _records(2)
    with pytest.raises(MaterializeError, match="not train"):
        realize_aggressive_split(
            records,
            [_aggressive_op(expansion=2)],
            global_seed=42,
            realizer_registry=REGISTRY,
            split="val",
        )
