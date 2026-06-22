# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-AUG-4 ``random_erasing`` augmentation op (Story H.r).

Aggressive-mode realizer for the Zhong et al. 2020 random-erasing
augmentation. Per-variant ``rng.random() < p`` decides whether to
erase. When erasing:

1. Draw a target area fraction uniformly from ``scale[0]..scale[1]``.
2. Draw an aspect ratio log-uniformly from ``ratio[0]..ratio[1]``
   (matches the torchvision convention; ``ratio=(0.3, 3.3)`` is
   symmetric in log space around 1.0).
3. Compute rectangle dimensions ``(rect_h, rect_w)`` from area + aspect.
4. If the rectangle fits inside the image, pick a top-left coordinate
   uniformly and fill that rectangle with the input image's mean pixel
   value. Otherwise retry up to ``_RETRY_BUDGET`` times. If still no
   valid rectangle, the image is left unchanged (matches torchvision).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

_RETRY_BUDGET = 10


class RandomErasingParams(BaseModel):
    """Pydantic schema for ``random_erasing`` op parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    p: float = Field(ge=0.0, le=1.0)
    scale: tuple[float, float]
    ratio: tuple[float, float]

    @model_validator(mode="after")
    def _validate_ranges(self) -> RandomErasingParams:
        s_lo, s_hi = self.scale
        if not (0.0 < s_lo <= s_hi <= 1.0):
            raise ValueError(
                f"random_erasing.scale must satisfy 0 < lo <= hi <= 1 (got {self.scale})"
            )
        r_lo, r_hi = self.ratio
        if not (0.0 < r_lo <= r_hi):
            raise ValueError(f"random_erasing.ratio must satisfy 0 < lo <= hi (got {self.ratio})")
        return self


def _mean_color(img_arr: np.ndarray) -> Any:
    """Mean pixel value across spatial axes, cast back to ``uint8``.

    For a 3D ``(H, W, C)`` image the result is a length-``C`` ``uint8``
    vector; for a 2D ``(H, W)`` grayscale image it's a scalar ``uint8``.
    The return type is widened to ``Any`` because numpy broadcast-assigns
    both shapes into an array slice (``arr[t:t+h, l:l+w] = mean_color``).
    """
    if img_arr.ndim == 3:
        mean_vec = img_arr.reshape(-1, img_arr.shape[-1]).mean(axis=0)
        return np.round(mean_vec).astype(np.uint8)
    return np.uint8(round(float(img_arr.mean())))


def realize_random_erasing(
    record: Mapping[str, Any],
    seed: int,
    variant_index: int,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """Single-variant realizer for ``random_erasing``.

    The variant_index argument is unused — the per-variant seed already
    incorporates it upstream.
    """
    del variant_index
    parsed = RandomErasingParams.model_validate(dict(params))
    rng = np.random.default_rng(seed)

    out_record = dict(record)
    if rng.random() >= parsed.p:
        return out_record

    img_arr = np.asarray(record["image"])
    h, w = img_arr.shape[:2]
    scale_lo, scale_hi = parsed.scale
    log_lo, log_hi = math.log(parsed.ratio[0]), math.log(parsed.ratio[1])
    area = float(h * w)

    for _ in range(_RETRY_BUDGET):
        target_area = float(rng.uniform(scale_lo, scale_hi)) * area
        aspect = math.exp(float(rng.uniform(log_lo, log_hi)))
        rect_h = round(math.sqrt(target_area * aspect))
        rect_w = round(math.sqrt(target_area / aspect))
        if 0 < rect_h < h and 0 < rect_w < w:
            top = int(rng.integers(0, h - rect_h + 1))
            left = int(rng.integers(0, w - rect_w + 1))
            erased = img_arr.copy()
            erased[top : top + rect_h, left : left + rect_w] = _mean_color(img_arr)
            out_record["image"] = erased
            return out_record

    # No valid rectangle found within the retry budget — leave the image
    # unchanged. This matches torchvision's behavior and keeps output
    # deterministic (the rng draws are still consumed in a fixed order).
    return out_record
