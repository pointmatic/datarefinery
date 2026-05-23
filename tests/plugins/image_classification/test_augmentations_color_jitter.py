# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.r — `color_jitter` augmentation op tests (FR-AUG-3).

Aggressive-mode realizer for appearance-perturbation pattern: Pillow
``ImageEnhance.Brightness`` / ``Contrast`` / ``Color`` for the
brightness/contrast/saturation dimensions; HSV-space hue rotation for
the hue dimension. Each enabled dimension's offset is drawn uniformly
in ``[-magnitude, +magnitude]`` from the per-variant seed.

Lazy mode is covered by the existing policy-capture suite in
``tests/unit/test_augmentations_stage.py``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from datarefinery.pipeline.stages.augmentations import realize_aggressive_split
from datarefinery.plugins.image_classification.augmentations.color_jitter import (
    ColorJitterParams,
    realize_color_jitter,
)
from datarefinery.recipe.models import AugmentationOp

# ---------------------------------------------------------------------------
# Param-model surface
# ---------------------------------------------------------------------------


def test_color_jitter_params_defaults_all_zero() -> None:
    p = ColorJitterParams()
    assert p.brightness == 0.0
    assert p.contrast == 0.0
    assert p.saturation == 0.0
    assert p.hue == 0.0


def test_color_jitter_params_accepts_bcs_at_bounds() -> None:
    p = ColorJitterParams(brightness=0.0, contrast=1.0, saturation=0.5, hue=0.5)
    assert p.brightness == 0.0
    assert p.contrast == 1.0
    assert p.saturation == 0.5
    assert p.hue == 0.5


@pytest.mark.parametrize("field", ["brightness", "contrast", "saturation"])
def test_color_jitter_params_rejects_bcs_negative(field: str) -> None:
    with pytest.raises(ValidationError):
        ColorJitterParams(**{field: -0.1})  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["brightness", "contrast", "saturation"])
def test_color_jitter_params_rejects_bcs_above_one(field: str) -> None:
    with pytest.raises(ValidationError):
        ColorJitterParams(**{field: 1.1})  # type: ignore[arg-type]


def test_color_jitter_params_rejects_hue_negative() -> None:
    with pytest.raises(ValidationError):
        ColorJitterParams(hue=-0.01)


def test_color_jitter_params_rejects_hue_above_half() -> None:
    with pytest.raises(ValidationError):
        ColorJitterParams(hue=0.51)


def test_color_jitter_params_is_frozen() -> None:
    p = ColorJitterParams()
    with pytest.raises(ValidationError):
        p.brightness = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Realizer correctness
# ---------------------------------------------------------------------------


def _rgb(h: int = 8, w: int = 8, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def _record(rid: str, arr: np.ndarray, label: int = 0) -> dict[str, Any]:
    return {"record_id": rid, "image": arr, "label": label}


def test_realizer_all_zero_params_is_identity() -> None:
    arr = _rgb()
    out = realize_color_jitter(_record("r", arr), seed=1, variant_index=0, params={})
    assert np.array_equal(out["image"], arr)


def test_realizer_brightness_can_modify_image() -> None:
    arr = _rgb()
    out = realize_color_jitter(
        _record("r", arr),
        seed=1,
        variant_index=0,
        params={"brightness": 1.0},
    )
    # With magnitude=1.0 and a seeded offset, the brightness factor is
    # very unlikely to be exactly 1.0 -> bytes should change.
    assert not np.array_equal(out["image"], arr)
    assert out["image"].dtype == np.uint8
    assert out["image"].shape == arr.shape


def test_realizer_same_seed_same_output() -> None:
    arr = _rgb()
    params = {"brightness": 0.5, "contrast": 0.5, "saturation": 0.5, "hue": 0.25}
    a = realize_color_jitter(_record("r", arr), seed=42, variant_index=0, params=params)
    b = realize_color_jitter(_record("r", arr), seed=42, variant_index=0, params=params)
    assert np.array_equal(a["image"], b["image"])


def test_realizer_different_seed_yields_different_output() -> None:
    arr = _rgb()
    params = {"brightness": 0.5}
    a = realize_color_jitter(_record("r", arr), seed=1, variant_index=0, params=params)
    b = realize_color_jitter(_record("r", arr), seed=2, variant_index=0, params=params)
    assert not np.array_equal(a["image"], b["image"])


def test_realizer_preserves_label_and_other_fields() -> None:
    arr = _rgb()
    record = _record("r", arr, label=4)
    record["extra"] = "keep-me"
    out = realize_color_jitter(record, seed=1, variant_index=0, params={"brightness": 0.5})
    assert out["label"] == 4
    assert out["extra"] == "keep-me"


def test_realizer_hue_is_noop_on_grayscale() -> None:
    """Hue rotation is HSV-space — only meaningful for >=3-channel images.
    On grayscale, the realizer must skip the hue path and leave the image
    untouched (no other dimension is enabled here)."""
    arr = np.random.default_rng(0).integers(0, 256, size=(8, 8), dtype=np.uint8)
    out = realize_color_jitter(_record("r", arr), seed=1, variant_index=0, params={"hue": 0.5})
    assert np.array_equal(out["image"], arr)


# ---------------------------------------------------------------------------
# Aggressive-mode integration through realize_aggressive_split
# ---------------------------------------------------------------------------


def _aggressive_op(expansion: int = 4) -> AugmentationOp:
    return AugmentationOp(
        name="jit",
        op="color_jitter",
        params={"brightness": 0.3, "contrast": 0.2, "saturation": 0.1, "hue": 0.1},
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
    return {"color_jitter": realize_color_jitter}


def test_aggressive_color_jitter_emits_n_times_expansion_records() -> None:
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
    records = _records(6)
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
