# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-11 augmentations policy-capture tests (Story C.j).

v1 does not pre-materialize augmented examples; this stage converts
each declared ``AugmentationOp`` into a manifest-serializable policy.
"""

from __future__ import annotations

import json

import pytest

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.stages.augmentations import (
    AugmentationPolicy,
    AugmentationsResult,
    collect_augmentation_policies,
    manifest_block,
)
from datarefinery.recipe.models import AugmentationOp


def _flip_op() -> AugmentationOp:
    return AugmentationOp(
        name="flip",
        op="horizontal_flip",
        params={"p": 0.5},
        splits=["train"],
        seed=1,
    )


def _crop_op() -> AugmentationOp:
    return AugmentationOp(
        name="crop",
        op="random_crop",
        params={"size": 28},
        splits=["train"],
        seed=2,
    )


def _jitter_op() -> AugmentationOp:
    return AugmentationOp(
        name="jit",
        op="color_jitter",
        params={"brightness": 0.2, "contrast": 0.1, "saturation": 0.0},
        splits=["train"],
        seed=3,
    )


# ---------------------------------------------------------------------------
# Happy path: policies captured verbatim
# ---------------------------------------------------------------------------


def test_collects_policies_from_declared_ops() -> None:
    result = collect_augmentation_policies([_flip_op(), _crop_op()])
    assert isinstance(result, AugmentationsResult)
    names = [p.name for p in result.policies]
    assert names == ["flip", "crop"]


def test_policy_carries_op_params_splits_seed() -> None:
    result = collect_augmentation_policies([_flip_op()])
    p = result.policies[0]
    assert p.op == "horizontal_flip"
    assert p.params == {"p": 0.5}
    assert p.splits == ("train",)
    assert p.seed == 1


def test_empty_ops_list_yields_empty_result() -> None:
    result = collect_augmentation_policies([])
    assert result.policies == ()
    assert result.to_manifest_list() == []


# ---------------------------------------------------------------------------
# Manifest serialization
# ---------------------------------------------------------------------------


def test_to_manifest_dict_shape() -> None:
    p = AugmentationPolicy(
        name="flip",
        op="horizontal_flip",
        params={"p": 0.5},
        splits=("train",),
        seed=42,
    )
    assert p.to_manifest_dict() == {
        "name": "flip",
        "op": "horizontal_flip",
        "params": {"p": 0.5},
        "splits": ["train"],
        "seed": 42,
        "materialization": "lazy",
        "expansion": 1,
    }


def test_to_manifest_dict_sorts_param_keys() -> None:
    """Two runs producing the same params must serialize identically."""
    p = AugmentationPolicy(
        name="jit",
        op="color_jitter",
        params={"saturation": 0.0, "brightness": 0.2, "contrast": 0.1},
        splits=("train",),
        seed=7,
    )
    keys = list(p.to_manifest_dict()["params"].keys())
    assert keys == ["brightness", "contrast", "saturation"]


def test_manifest_block_is_stable_json() -> None:
    result = collect_augmentation_policies([_flip_op(), _crop_op()])
    raw = manifest_block(result)
    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    # Stable formatting: no whitespace, sorted keys.
    assert " " not in raw
    assert raw == manifest_block(result)


def test_round_trip_through_manifest_preserves_information() -> None:
    """Recipe -> policies -> manifest JSON -> back: no semantic loss for
    fields the spec captures (name, op, params, splits, seed)."""
    ops = [_flip_op(), _crop_op(), _jitter_op()]
    result = collect_augmentation_policies(ops)
    parsed = json.loads(manifest_block(result))
    for op, entry in zip(ops, parsed, strict=True):
        assert entry["name"] == op.name
        assert entry["op"] == op.op
        assert entry["splits"] == list(op.splits)
        assert entry["seed"] == op.seed
        assert entry["params"] == dict(op.params)


def test_seed_none_round_trips_as_null() -> None:
    op = AugmentationOp(name="x", op="horizontal_flip", params={}, splits=["train"], seed=None)
    result = collect_augmentation_policies([op])
    parsed = json.loads(manifest_block(result))
    assert parsed[0]["seed"] is None


# ---------------------------------------------------------------------------
# Defensive train-only re-check
# ---------------------------------------------------------------------------


def test_non_train_split_raises_materialize_error() -> None:
    # Bypass validator: directly build an op with val in splits.
    op = AugmentationOp(
        name="bad",
        op="horizontal_flip",
        params={"p": 0.5},
        splits=["train", "val"],  # validator check 5 would normally reject
        seed=1,
    )
    with pytest.raises(MaterializeError, match="non-train"):
        collect_augmentation_policies([op])


def test_test_split_only_raises() -> None:
    op = AugmentationOp(name="bad", op="horizontal_flip", params={}, splits=["test"], seed=1)
    with pytest.raises(MaterializeError, match="non-train"):
        collect_augmentation_policies([op])


def test_empty_splits_does_not_raise() -> None:
    """An op with empty splits is allowed (no policy applies anywhere);
    validator check 4 would catch it for non-augmentation sections, but
    augmentations default to ["train"] in the model."""
    op = AugmentationOp(name="x", op="horizontal_flip", params={}, splits=[], seed=1)
    result = collect_augmentation_policies([op])
    assert result.policies[0].splits == ()


# ---------------------------------------------------------------------------
# Frozen result types
# ---------------------------------------------------------------------------


def test_augmentation_policy_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    p = AugmentationPolicy(name="x", op="y", params={}, splits=("train",), seed=None)
    with pytest.raises(FrozenInstanceError):
        p.name = "z"  # type: ignore[misc]


def test_augmentations_result_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    r = AugmentationsResult(policies=())
    with pytest.raises(FrozenInstanceError):
        r.policies = ()  # type: ignore[misc]
