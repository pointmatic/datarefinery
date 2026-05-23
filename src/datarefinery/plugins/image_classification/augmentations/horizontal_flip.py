# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-AUG-2 ``horizontal_flip`` augmentation op (Story H.q).

Aggressive-mode realizer: per-variant ``rng.random() < p`` coin flip
against the per-variant seed; ``Image.transpose(Image.FLIP_LEFT_RIGHT)``
when the coin lands heads. Pillow's transpose is RNG-free (validated
by the H.o spike), so the only stochastic choice is the coin flip we
control.

Lazy mode is policy-only and uses no code path in this module — the
existing ``stages/augmentations.py`` policy-capture loop handles it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field


class HorizontalFlipParams(BaseModel):
    """Pydantic schema for ``horizontal_flip`` op parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    p: float = Field(default=0.5, ge=0.0, le=1.0)


def realize_horizontal_flip(
    record: Mapping[str, Any],
    seed: int,
    variant_index: int,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """Single-variant realizer for ``horizontal_flip``.

    The variant_index argument is unused — the coin-flip seed already
    incorporates it via :func:`per_record_variant_seed` upstream.
    """
    del variant_index
    parsed = HorizontalFlipParams.model_validate(dict(params))
    rng = np.random.default_rng(seed)
    do_flip = bool(rng.random() < parsed.p)

    out = dict(record)
    if do_flip:
        img_arr = np.asarray(record["image"])
        flipped = np.asarray(Image.fromarray(img_arr).transpose(Image.Transpose.FLIP_LEFT_RIGHT))
        out["image"] = flipped
    return out
