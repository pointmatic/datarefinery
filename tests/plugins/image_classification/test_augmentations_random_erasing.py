# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.r — `random_erasing` augmentation op tests (FR-AUG-4).

Aggressive-mode realizer for the Zhong et al. 2020 random-erasing
pattern: per-variant ``rng.random() < p`` coin decides whether to
erase; area fraction sampled from ``scale``, aspect ratio sampled
log-uniformly from ``ratio``; rectangle filled with the image's mean
pixel value. Bounded retry handles cases where the sampled (area,
aspect_ratio) doesn't produce a rectangle that fits inside the image.

Lazy mode is covered by the existing policy-capture suite.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from datarefinery.pipeline.stages.augmentations import realize_aggressive_split
from datarefinery.plugins.image_classification.augmentations.random_erasing import (
    RandomErasingParams,
    realize_random_erasing,
)
from datarefinery.recipe.models import AugmentationOp

# ---------------------------------------------------------------------------
# Param-model surface
# ---------------------------------------------------------------------------


def _re(**over: object) -> dict[str, object]:
    """Complete random_erasing params (others at their pre-J.n.4 defaults)."""
    base: dict[str, object] = {"p": 0.5, "scale": (0.02, 0.33), "ratio": (0.3, 3.3)}
    base.update(over)
    return base


def test_random_erasing_params_require_all_fields() -> None:
    # No-implicit-defaults (J.n.4): p / scale / ratio are all required.
    with pytest.raises(ValidationError):
        RandomErasingParams()  # type: ignore[call-arg]


def test_random_erasing_params_accepts_p_zero() -> None:
    assert RandomErasingParams(**_re(p=0.0)).p == 0.0


def test_random_erasing_params_accepts_p_one() -> None:
    assert RandomErasingParams(**_re(p=1.0)).p == 1.0


def test_random_erasing_params_rejects_p_outside_unit() -> None:
    with pytest.raises(ValidationError):
        RandomErasingParams(**_re(p=-0.1))
    with pytest.raises(ValidationError):
        RandomErasingParams(**_re(p=1.1))


def test_random_erasing_params_rejects_inverted_scale() -> None:
    with pytest.raises(ValidationError):
        RandomErasingParams(**_re(scale=(0.5, 0.1)))


def test_random_erasing_params_rejects_inverted_ratio() -> None:
    with pytest.raises(ValidationError):
        RandomErasingParams(**_re(ratio=(3.3, 0.3)))


def test_random_erasing_params_rejects_non_positive_scale() -> None:
    with pytest.raises(ValidationError):
        RandomErasingParams(**_re(scale=(0.0, 0.1)))


def test_random_erasing_params_rejects_non_positive_ratio() -> None:
    with pytest.raises(ValidationError):
        RandomErasingParams(**_re(ratio=(0.0, 1.0)))


def test_random_erasing_params_rejects_scale_above_one() -> None:
    with pytest.raises(ValidationError):
        RandomErasingParams(**_re(scale=(0.1, 1.1)))


def test_random_erasing_params_is_frozen() -> None:
    p = RandomErasingParams(**_re())
    with pytest.raises(ValidationError):
        p.p = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Realizer correctness
# ---------------------------------------------------------------------------


def _rgb(h: int = 32, w: int = 32, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def _record(rid: str, arr: np.ndarray, label: int = 0) -> dict[str, Any]:
    return {"record_id": rid, "image": arr, "label": label}


def test_realizer_p_zero_is_identity() -> None:
    arr = _rgb()
    out = realize_random_erasing(_record("r", arr), seed=1, variant_index=0, params=_re(p=0.0))
    assert np.array_equal(out["image"], arr)


def test_realizer_p_one_modifies_image() -> None:
    """With ``p=1.0`` and default ``scale``/``ratio``, the realizer
    erases on every call (modulo the bounded-retry no-op fallback —
    rare for 32x32 images)."""
    arr = _rgb()
    # Run several seeds; at least one must produce a modified image.
    modified = 0
    for s in range(10):
        out = realize_random_erasing(_record("r", arr), seed=s, variant_index=0, params=_re(p=1.0))
        if not np.array_equal(out["image"], arr):
            modified += 1
    assert modified >= 8, f"expected most seeds to erase; got {modified}/10"


def test_realizer_erased_region_pixels_are_uniform_mean() -> None:
    """After erasing, find a rectangle in the output where every pixel
    is identical and equal to the input image's mean color. The mean is
    a single uint8 triple, so the erased rectangle's variance across
    its pixels is zero."""
    arr = _rgb(64, 64, seed=3)  # larger for a higher-area-target rectangle
    out = realize_random_erasing(
        _record("r", arr),
        seed=99,
        variant_index=0,
        params={"p": 1.0, "scale": (0.1, 0.3), "ratio": (0.8, 1.2)},
    )
    diff = out["image"].astype(np.int32) - arr.astype(np.int32)
    erased_mask = (diff != 0).any(axis=-1)
    assert erased_mask.any(), "expected the realizer to erase a non-empty rectangle"
    # All erased pixels should share the same uint8 triple (the mean color).
    erased_pixels = out["image"][erased_mask]
    unique = np.unique(erased_pixels.reshape(-1, 3), axis=0)
    assert unique.shape[0] == 1, f"erased pixels not uniform: {unique.shape[0]} distinct colors"


def test_realizer_same_seed_same_output() -> None:
    arr = _rgb()
    a = realize_random_erasing(_record("r", arr), seed=42, variant_index=0, params=_re(p=1.0))
    b = realize_random_erasing(_record("r", arr), seed=42, variant_index=0, params=_re(p=1.0))
    assert np.array_equal(a["image"], b["image"])


def test_realizer_preserves_label_and_other_fields() -> None:
    arr = _rgb()
    record = _record("r", arr, label=4)
    record["extra"] = "keep-me"
    out = realize_random_erasing(record, seed=1, variant_index=0, params=_re(p=1.0))
    assert out["label"] == 4
    assert out["extra"] == "keep-me"


def test_realizer_output_shape_and_dtype_match_input() -> None:
    arr = _rgb()
    out = realize_random_erasing(_record("r", arr), seed=1, variant_index=0, params=_re(p=1.0))
    assert out["image"].shape == arr.shape
    assert out["image"].dtype == np.uint8


# ---------------------------------------------------------------------------
# Aggressive-mode integration through realize_aggressive_split
# ---------------------------------------------------------------------------


def _aggressive_op(p: float = 1.0, expansion: int = 4) -> AugmentationOp:
    return AugmentationOp(
        name="erase",
        op="random_erasing",
        params=_re(p=p),
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
            "image": rng.integers(0, 256, size=(32, 32, 3), dtype=np.uint8),
            "label": i % 3,
        }
        for i in range(n)
    ]


def _registry() -> dict[str, Any]:
    return {"random_erasing": realize_random_erasing}


def test_aggressive_random_erasing_emits_n_times_expansion_records() -> None:
    out = realize_aggressive_split(
        _records(5),
        [_aggressive_op(expansion=3)],
        global_seed=42,
        realizer_registry=_registry(),
    )
    assert len(out) == 5 * 3


def _digest(records: list[dict[str, Any]]) -> bytes:
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
                    "image_sha256": img_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return "\n".join(parts).encode("utf-8")


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_workers_1_2_4_produce_byte_identical_aggressive_output(workers: int) -> None:
    records = _records(4)
    out_1 = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=3)],
        global_seed=42,
        realizer_registry=_registry(),
        workers=1,
    )
    out_w = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=3)],
        global_seed=42,
        realizer_registry=_registry(),
        workers=workers,
    )
    assert _digest(out_1) == _digest(out_w)
