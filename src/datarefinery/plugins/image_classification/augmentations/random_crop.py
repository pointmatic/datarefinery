# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-AUG-1 ``random_crop`` augmentation op (Story H.q).

Aggressive-mode realizer: pad the input per ``padding_mode``, then take
a random crop of size ``size`` using
``numpy.random.default_rng(seed_for_variant)`` to choose the top-left
crop coordinates. The padding step uses ``numpy.pad`` with the
following mode mapping:

- ``reflect`` -> numpy ``reflect``
- ``replicate`` -> numpy ``edge``
- ``zero`` / ``constant`` -> numpy ``constant`` (fill value 0)

(``zero`` and ``constant`` collapse to the same fill in v1; ``constant``
is kept in the schema for symmetry with the broader torchvision-style
convention and so that a future ``fill_value`` parameter has a natural
home without a schema break.)

Lazy mode is policy-only and uses no code path in this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

PaddingMode = Literal["reflect", "replicate", "zero", "constant"]


class RandomCropParams(BaseModel):
    """Pydantic schema for ``random_crop`` op parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    size: int | tuple[int, int] = Field(...)
    padding: int = Field(default=0, ge=0)
    padding_mode: PaddingMode = "reflect"

    @model_validator(mode="after")
    def _validate_size(self) -> RandomCropParams:
        if isinstance(self.size, int):
            if self.size <= 0:
                raise ValueError(f"random_crop: size must be positive (got {self.size})")
        else:
            h, w = self.size
            if h <= 0 or w <= 0:
                raise ValueError(f"random_crop: size dimensions must be positive (got {self.size})")
        return self


def _crop_shape(size: int | tuple[int, int]) -> tuple[int, int]:
    if isinstance(size, int):
        return size, size
    return size


def realize_random_crop(
    record: Mapping[str, Any],
    seed: int,
    variant_index: int,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """Single-variant realizer for ``random_crop``.

    The variant_index argument is unused — the per-variant seed already
    incorporates it upstream.
    """
    del variant_index
    parsed = RandomCropParams.model_validate(dict(params))
    crop_h, crop_w = _crop_shape(parsed.size)
    img_arr = np.asarray(record["image"])

    if parsed.padding > 0:
        if img_arr.ndim == 3:
            pad_width: tuple[tuple[int, int], ...] = (
                (parsed.padding, parsed.padding),
                (parsed.padding, parsed.padding),
                (0, 0),
            )
        else:
            pad_width = (
                (parsed.padding, parsed.padding),
                (parsed.padding, parsed.padding),
            )
        # Branch per mode so each np.pad call receives a Literal-typed
        # `mode` argument (numpy stubs reject a runtime-string `mode`).
        if parsed.padding_mode == "reflect":
            padded = np.pad(img_arr, pad_width, mode="reflect")
        elif parsed.padding_mode == "replicate":
            padded = np.pad(img_arr, pad_width, mode="edge")
        else:
            # `zero` and `constant` both fill with 0 in v1.
            padded = np.pad(img_arr, pad_width, mode="constant", constant_values=0)
    else:
        padded = img_arr

    padded_h, padded_w = padded.shape[:2]
    if crop_h > padded_h or crop_w > padded_w:
        raise ValueError(
            f"random_crop: requested size {parsed.size!r} exceeds padded image "
            f"shape {(padded_h, padded_w)!r}"
        )

    rng = np.random.default_rng(seed)
    # rng.integers(low, high) where high is exclusive — high = padded_h - crop_h + 1.
    top = int(rng.integers(0, padded_h - crop_h + 1))
    left = int(rng.integers(0, padded_w - crop_w + 1))
    cropped = padded[top : top + crop_h, left : left + crop_w]

    out = dict(record)
    out["image"] = np.ascontiguousarray(cropped)
    return out
