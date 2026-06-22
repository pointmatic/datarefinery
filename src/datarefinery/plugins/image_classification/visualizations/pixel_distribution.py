# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-VIZ-1: per-channel pixel-value histogram visualization.

Emits one PNG per requested split, each showing three subplots (R, G, B)
of pixel-value distributions. Reporting-mode only — the in-memory mode
collapses gracefully via the ``extras`` mapping returned by
``RenderedVisualization`` (see ``reporting/visualizations.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from matplotlib.figure import Figure
from pydantic import BaseModel, Field, field_validator

from datarefinery.plugins.image_classification.visualizations._render import (
    encode_png,
    new_figure,
)

Record = Mapping[str, Any]

_CHANNELS: tuple[tuple[str, str], ...] = (
    ("R", "#cc3333"),
    ("G", "#33aa55"),
    ("B", "#3366cc"),
)


class PixelDistributionParams(BaseModel):
    """Params for ``pixel_distribution``.

    ``splits`` selects which split's records to render; one PNG per
    entry. ``bins`` controls the histogram bin count for each channel.
    """

    model_config = {"extra": "forbid"}

    bins: int = Field(gt=0)
    splits: list[str]

    @field_validator("splits")
    @classmethod
    def _splits_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("splits must be a non-empty list")
        return value


def build_pixel_distribution_figure(
    records: Sequence[Record],
    *,
    bins: int,
) -> Figure:
    """Build a 1x3 figure of R/G/B pixel-value histograms.

    Each subplot title is the channel letter so callers (and tests) can
    identify the subplot ordering without inspecting bar geometry. An
    empty record list yields an empty axis per channel (no bars).
    """
    fig = new_figure(width_in=9.0, height_in=3.0)
    pixels_per_channel: list[np.ndarray] = [np.empty(0, dtype=np.float64) for _ in _CHANNELS]
    if records:
        stacked = np.concatenate(
            [np.asarray(r["image"]).reshape(-1, 3) for r in records],
            axis=0,
        )
        for idx in range(3):
            pixels_per_channel[idx] = stacked[:, idx].astype(np.float64, copy=False)

    for idx, (label, color) in enumerate(_CHANNELS):
        ax = fig.add_subplot(1, 3, idx + 1)
        ax.hist(
            pixels_per_channel[idx],
            bins=bins,
            range=(0.0, 255.0),
            color=color,
        )
        ax.set_title(label)
        ax.set_xlim(0, 255)
        ax.set_xlabel("pixel value")
        ax.set_ylabel("count")
    fig.tight_layout()
    return fig


class PixelDistributionOp:
    """Visualization handle for ``pixel_distribution``.

    Returns ``Mapping[str, bytes]`` keyed by split name. The pipeline
    stage writes each entry as ``<op.name>_<split>.png``.
    """

    def render(
        self,
        splits: Mapping[str, list[Record]],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
        recipe: Any = None,
    ) -> Mapping[str, bytes]:
        del label_field, recipe
        p = PixelDistributionParams(**dict(params))
        out: dict[str, bytes] = {}
        for split in p.splits:
            if split not in splits:
                raise KeyError(
                    f"pixel_distribution: split {split!r} absent from materialized splits "
                    f"(have: {sorted(splits.keys())!r})"
                )
            records = splits[split]
            fig = build_pixel_distribution_figure(records, bins=p.bins)
            out[split] = encode_png(fig)
        return out
