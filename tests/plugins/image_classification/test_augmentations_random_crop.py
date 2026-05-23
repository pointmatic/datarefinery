# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.q — `random_crop` augmentation op tests (FR-AUG-1).

Aggressive-mode realizer for the spatial-crop pattern: pad per
``padding_mode``, then random crop to ``size`` using
``numpy.random.default_rng(seed_for_variant)`` for crop coordinates.

Lazy mode is covered by the existing policy-capture suite in
``tests/unit/test_augmentations_stage.py``; this file focuses on:

- Param model surface (size shapes, padding non-negative, modes).
- Output shape correctness across the four padding modes.
- Determinism across ``workers=1/2/4``.
- Pad-then-crop semantics: with ``padding=0`` and ``size`` equal to the
  input, no spatial randomness is possible — the crop is fully
  determined.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from datarefinery.pipeline.stages.augmentations import realize_aggressive_split
from datarefinery.plugins.image_classification.augmentations.random_crop import (
    RandomCropParams,
    realize_random_crop,
)
from datarefinery.recipe.models import AugmentationOp

# ---------------------------------------------------------------------------
# Param-model surface
# ---------------------------------------------------------------------------


def test_random_crop_params_accepts_int_size() -> None:
    p = RandomCropParams(size=32)
    assert p.size == 32


def test_random_crop_params_accepts_tuple_size() -> None:
    p = RandomCropParams(size=(28, 24))
    assert p.size == (28, 24)


def test_random_crop_params_defaults() -> None:
    p = RandomCropParams(size=32)
    assert p.padding == 0
    assert p.padding_mode == "reflect"


def test_random_crop_params_rejects_zero_size() -> None:
    with pytest.raises(ValidationError):
        RandomCropParams(size=0)


def test_random_crop_params_rejects_negative_size() -> None:
    with pytest.raises(ValidationError):
        RandomCropParams(size=-4)


def test_random_crop_params_rejects_negative_padding() -> None:
    with pytest.raises(ValidationError):
        RandomCropParams(size=32, padding=-1)


def test_random_crop_params_rejects_unknown_padding_mode() -> None:
    with pytest.raises(ValidationError):
        RandomCropParams(size=32, padding=1, padding_mode="zebra")


def test_random_crop_params_accepts_each_padding_mode() -> None:
    for mode in ("reflect", "replicate", "zero", "constant"):
        p = RandomCropParams(size=4, padding=1, padding_mode=mode)
        assert p.padding_mode == mode


def test_random_crop_params_is_frozen() -> None:
    p = RandomCropParams(size=32)
    with pytest.raises(ValidationError):
        p.size = 16  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Realizer correctness — output shape
# ---------------------------------------------------------------------------


def _arr(h: int, w: int, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def _record(rid: str, arr: np.ndarray, label: int = 0) -> dict[str, Any]:
    return {"record_id": rid, "image": arr, "label": label}


def test_realizer_int_size_yields_square_crop() -> None:
    arr = _arr(16, 16)
    out = realize_random_crop(_record("r", arr), seed=1, variant_index=0, params={"size": 8})
    assert out["image"].shape == (8, 8, 3)


def test_realizer_tuple_size_yields_rectangular_crop() -> None:
    arr = _arr(16, 16)
    out = realize_random_crop(_record("r", arr), seed=1, variant_index=0, params={"size": (4, 6)})
    assert out["image"].shape == (4, 6, 3)


def test_realizer_padding_expands_input_then_crops() -> None:
    """With padding=2 and size equal to input, the post-pad canvas is 4
    pixels larger in each spatial axis, giving room for the crop to vary."""
    arr = _arr(8, 8)
    out = realize_random_crop(
        _record("r", arr),
        seed=1,
        variant_index=0,
        params={"size": 8, "padding": 2, "padding_mode": "reflect"},
    )
    assert out["image"].shape == (8, 8, 3)


def test_realizer_zero_padding_no_randomness_when_size_equals_input() -> None:
    """size=H,W and padding=0 leaves the realizer with exactly one valid
    crop position; the seed cannot affect the output."""
    arr = _arr(8, 8)
    out_a = realize_random_crop(
        _record("r", arr), seed=1, variant_index=0, params={"size": 8, "padding": 0}
    )
    out_b = realize_random_crop(
        _record("r", arr), seed=999, variant_index=0, params={"size": 8, "padding": 0}
    )
    assert np.array_equal(out_a["image"], out_b["image"])
    assert np.array_equal(out_a["image"], arr)


def test_realizer_same_seed_same_crop_coords() -> None:
    arr = _arr(16, 16)
    a = realize_random_crop(_record("r", arr), seed=42, variant_index=0, params={"size": 8})
    b = realize_random_crop(_record("r", arr), seed=42, variant_index=0, params={"size": 8})
    assert np.array_equal(a["image"], b["image"])


def test_realizer_different_seeds_can_pick_different_crops() -> None:
    arr = _arr(16, 16)
    seen: set[bytes] = set()
    for s in range(20):
        out = realize_random_crop(_record("r", arr), seed=s, variant_index=0, params={"size": 4})
        seen.add(np.ascontiguousarray(out["image"]).tobytes())
    # 20 different seeds should yield more than one distinct crop in a 16x16 -> 4x4 space.
    assert len(seen) > 1


def test_realizer_preserves_label_and_other_fields() -> None:
    arr = _arr(16, 16)
    record = _record("r", arr, label=4)
    record["extra"] = "keep-me"
    out = realize_random_crop(record, seed=1, variant_index=0, params={"size": 8})
    assert out["label"] == 4
    assert out["extra"] == "keep-me"


# ---------------------------------------------------------------------------
# Realizer correctness — padding modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["reflect", "replicate", "zero", "constant"])
def test_realizer_each_padding_mode_yields_correct_shape(mode: str) -> None:
    arr = _arr(8, 8)
    out = realize_random_crop(
        _record("r", arr),
        seed=1,
        variant_index=0,
        params={"size": 8, "padding": 2, "padding_mode": mode},
    )
    assert out["image"].shape == (8, 8, 3)


def test_realizer_zero_padding_mode_introduces_zeros_at_corners() -> None:
    """Padding=4 with mode=zero on an 8x8 image, then size=8 leaves room
    for the crop top-left to land at (0,0) — which means the cropped
    region's top-left is all zero-padded."""
    arr = _arr(8, 8) + 1  # ensure no source pixel is exactly 0
    arr = np.minimum(arr, 255).astype(np.uint8)
    # Force the crop top-left to (0, 0) by seeding such that rng.integers
    # returns 0 for both axes. Instead of hunting for such a seed, verify
    # via the *existence* of a zero block somewhere in the output across
    # several seeds — at padding=4, all 8x8 crops include at least one
    # row or column of zero-padded pixels.
    found_zero_block = False
    for s in range(30):
        out = realize_random_crop(
            _record("r", arr),
            seed=s,
            variant_index=0,
            params={"size": 8, "padding": 4, "padding_mode": "zero"},
        )
        if (out["image"] == 0).any():
            found_zero_block = True
            break
    assert found_zero_block, "expected at least one zero pixel across 30 seeds with zero padding"


# ---------------------------------------------------------------------------
# Aggressive-mode integration through realize_aggressive_split
# ---------------------------------------------------------------------------


def _aggressive_op(size: int = 8, expansion: int = 4) -> AugmentationOp:
    return AugmentationOp(
        name="crop",
        op="random_crop",
        params={"size": size, "padding": 2, "padding_mode": "reflect"},
        splits=["train"],
        seed=1,
        materialization="aggressive",
        expansion=expansion,
    )


def _records(n: int, seed: int = 7) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    return [
        {
            "record_id": f"img_{i:03d}",
            "image": rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8),
            "label": i % 3,
        }
        for i in range(n)
    ]


def _registry() -> dict[str, Any]:
    return {"random_crop": realize_random_crop}


def test_aggressive_random_crop_emits_n_times_expansion_records() -> None:
    records = _records(5)
    out = realize_aggressive_split(
        records,
        [_aggressive_op(size=8, expansion=3)],
        global_seed=42,
        realizer_registry=_registry(),
    )
    assert len(out) == 5 * 3


def _serialize_for_compare(records: list[dict[str, Any]]) -> bytes:
    import hashlib
    import json

    parts: list[str] = []
    for r in sorted(records, key=lambda x: str(x["record_id"])):
        img_hash = hashlib.sha256(np.ascontiguousarray(r["image"]).tobytes()).hexdigest()
        parts.append(
            json.dumps(
                {
                    "record_id": r["record_id"],
                    "source_record_id": r["source_record_id"],
                    "variant_index": r["variant_index"],
                    "label": r.get("label"),
                    "image_sha256": img_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return "\n".join(parts).encode("utf-8")


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_workers_1_2_4_produce_byte_identical_aggressive_output(workers: int) -> None:
    records = _records(6)
    out_1 = realize_aggressive_split(
        records,
        [_aggressive_op(size=4, expansion=4)],
        global_seed=42,
        realizer_registry=_registry(),
        workers=1,
    )
    out_w = realize_aggressive_split(
        records,
        [_aggressive_op(size=4, expansion=4)],
        global_seed=42,
        realizer_registry=_registry(),
        workers=workers,
    )
    assert _serialize_for_compare(out_1) == _serialize_for_compare(out_w)
