# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-AUG-3 ``color_jitter`` augmentation op (Story H.r).

Aggressive-mode realizer for the appearance-perturbation pattern. Each
enabled dimension draws a uniform offset from
``[-magnitude, +magnitude]`` against the per-variant seed, then applies
the perturbation:

- ``brightness`` -> ``ImageEnhance.Brightness(...).enhance(1.0 + offset)``
- ``contrast``   -> ``ImageEnhance.Contrast(...).enhance(1.0 + offset)``
- ``saturation`` -> ``ImageEnhance.Color(...).enhance(1.0 + offset)``
- ``hue``        -> HSV-space rotation; H channel shifted by
  ``round(offset * 256)`` modulo 256 (PIL's HSV mode stores H in
  ``[0, 255]`` representing the full 360° circle).

Grayscale edge case: ``hue`` is a no-op on images with ``< 3`` channels
— rotating hue in HSV space requires a chroma component to rotate. The
brightness/contrast/saturation paths still apply through Pillow's
single-channel modes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance
from pydantic import BaseModel, ConfigDict, Field


class ColorJitterParams(BaseModel):
    """Pydantic schema for ``color_jitter`` op parameters.

    Each magnitude lives in ``[0.0, 1.0]`` except ``hue`` which lives in
    ``[0.0, 0.5]`` (a magnitude of 0.5 corresponds to a 180° rotation in
    either direction — the full meaningful range for hue).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    brightness: float = Field(default=0.0, ge=0.0, le=1.0)
    contrast: float = Field(default=0.0, ge=0.0, le=1.0)
    saturation: float = Field(default=0.0, ge=0.0, le=1.0)
    hue: float = Field(default=0.0, ge=0.0, le=0.5)


def realize_color_jitter(
    record: Mapping[str, Any],
    seed: int,
    variant_index: int,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """Single-variant realizer for ``color_jitter``.

    The variant_index argument is unused — the per-variant seed already
    incorporates it upstream.
    """
    del variant_index
    parsed = ColorJitterParams.model_validate(dict(params))
    rng = np.random.default_rng(seed)

    img_arr = np.asarray(record["image"])
    out_record = dict(record)

    # Build a Pillow image. Grayscale arrays get "L" mode; multi-channel
    # is assumed to be RGB (the image_classification plugin's contract).
    if img_arr.ndim == 2:
        img_pil = Image.fromarray(img_arr, mode="L")
        has_chroma = False
    else:
        img_pil = Image.fromarray(img_arr)
        has_chroma = img_arr.shape[-1] >= 3

    if parsed.brightness > 0:
        offset = float(rng.uniform(-parsed.brightness, parsed.brightness))
        img_pil = ImageEnhance.Brightness(img_pil).enhance(1.0 + offset)
    if parsed.contrast > 0:
        offset = float(rng.uniform(-parsed.contrast, parsed.contrast))
        img_pil = ImageEnhance.Contrast(img_pil).enhance(1.0 + offset)
    if parsed.saturation > 0:
        offset = float(rng.uniform(-parsed.saturation, parsed.saturation))
        img_pil = ImageEnhance.Color(img_pil).enhance(1.0 + offset)
    if parsed.hue > 0 and has_chroma:
        offset = float(rng.uniform(-parsed.hue, parsed.hue))
        shift = round(offset * 256) % 256
        hsv_arr = np.asarray(img_pil.convert("HSV"))
        new_h = ((hsv_arr[..., 0].astype(np.int32) + shift) % 256).astype(np.uint8)
        rotated = np.stack([new_h, hsv_arr[..., 1], hsv_arr[..., 2]], axis=-1)
        img_pil = Image.fromarray(rotated, mode="HSV").convert("RGB")

    out_record["image"] = np.asarray(img_pil)
    return out_record
