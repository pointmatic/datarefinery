# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-VIZ-2: ``augmented_sample_grid`` visualization.

For each ``AugmentationOp`` declared in ``recipe.Augmentations``, emit a
``n_base x n_variants`` grid showing how the op transforms a small
deterministic sample of train records. One PNG per augmentation op,
persisted as ``<viz.name>_<aug.name>.png`` via the H.t multi-PNG
protocol.

Mode-aware:

* **Aggressive** (``materialization == "aggressive"``): variants are
  already in the materialized train split, tagged with
  ``source_record_id`` + ``variant_index``. The viz groups by
  ``source_record_id``, takes the first ``n_base`` groups in id order,
  and the first ``n_variants`` per group.
* **Lazy** (``materialization == "lazy"``): variants are not in the
  split. The viz picks the first ``n_base`` records (record-order is
  the FR-3 determinism-contract iteration order) and realizes
  ``n_variants`` variants inline via the plugin's realizer registry,
  seeded by :func:`per_record_variant_seed` with
  ``global_seed = recipe.seed ^ (viz.seed or 0)``.

Train-only by FR-11; the viz pulls exclusively from ``splits["train"]``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from matplotlib.figure import Figure
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from datarefinery.pipeline.workers import per_record_variant_seed
from datarefinery.plugins.image_classification.augmentations._realizer import Realizer
from datarefinery.plugins.image_classification.visualizations._render import (
    encode_png,
    new_figure,
)
from datarefinery.recipe.models import AugmentationOp, Recipe

Record = Mapping[str, Any]


class AugmentedSampleGridParams(BaseModel):
    """Params for ``augmented_sample_grid``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_base: int = Field(gt=0)
    n_variants: int = Field(gt=0)
    seed: int | None = None


# ---------------------------------------------------------------------------
# Aggressive-mode grid selection
# ---------------------------------------------------------------------------


def select_aggressive_grid(
    records: Sequence[Record],
    *,
    n_base: int,
    n_variants: int,
) -> list[list[Record]]:
    """Group aggressive-mode records into the n_base x n_variants grid.

    Group by ``source_record_id``; sort groups by id; pick the first
    ``n_base`` groups; within each group sort by ``variant_index`` and
    pick the first ``n_variants``.
    """
    by_src: dict[Any, list[Record]] = {}
    for r in records:
        src = r["source_record_id"]
        by_src.setdefault(src, []).append(r)
    sorted_keys = sorted(by_src.keys(), key=lambda x: (type(x).__name__, repr(x)))
    if len(sorted_keys) < n_base:
        raise ValueError(
            f"select_aggressive_grid: have {len(sorted_keys)} source groups, "
            f"fewer than n_base={n_base}"
        )
    grid: list[list[Record]] = []
    for key in sorted_keys[:n_base]:
        variants = sorted(by_src[key], key=lambda r: int(r["variant_index"]))
        if len(variants) < n_variants:
            raise ValueError(
                f"select_aggressive_grid: source {key!r} has {len(variants)} "
                f"variants, fewer than n_variants={n_variants}"
            )
        grid.append(variants[:n_variants])
    return grid


# ---------------------------------------------------------------------------
# Lazy-mode inline realization
# ---------------------------------------------------------------------------


def realize_lazy_grid(
    records: Sequence[Record],
    *,
    aug: AugmentationOp,
    realizer: Realizer,
    n_base: int,
    n_variants: int,
    global_seed: int,
) -> list[list[Record]]:
    """Realize n_base x n_variants variants inline via the realizer.

    Picks the first ``n_base`` records in iteration order (the FR-3
    determinism-contract order); for each, calls ``realizer`` with a
    per-variant seed derived via :func:`per_record_variant_seed`.
    """
    if len(records) < n_base:
        raise ValueError(
            f"realize_lazy_grid: have {len(records)} records, fewer than n_base={n_base}"
        )
    grid: list[list[Record]] = []
    for record in records[:n_base]:
        row: list[Record] = []
        for vi in range(n_variants):
            seed = per_record_variant_seed(global_seed, record, vi, op_id=aug.name)
            realized = realizer(record, seed, vi, aug.params)
            row.append(realized)
        grid.append(row)
    return grid


# ---------------------------------------------------------------------------
# Figure construction
# ---------------------------------------------------------------------------


def _tile(record: Record, *, thumb: int) -> np.ndarray:
    arr = np.asarray(record["image"])
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    elif arr.ndim == 3 and arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return np.asarray(
        Image.fromarray(arr).resize((thumb, thumb), resample=Image.Resampling.BILINEAR)
    )


def build_augmented_sample_grid_figure(
    grid: Sequence[Sequence[Record]],
    *,
    title: str,
    thumb_px: int = 48,
) -> Figure:
    """Build an n_base x n_variants subplot figure displaying the grid."""
    n_base = len(grid)
    n_variants = len(grid[0]) if n_base else 0
    # Aspect: width ≈ n_variants tiles; height ≈ n_base tiles. 1 inch per tile keeps it readable.
    fig = new_figure(width_in=max(2.0, n_variants * 1.2), height_in=max(2.0, n_base * 1.2 + 0.5))
    fig.suptitle(title)
    for r_idx in range(n_base):
        for c_idx in range(n_variants):
            ax = fig.add_subplot(n_base, n_variants, r_idx * n_variants + c_idx + 1)
            tile = _tile(grid[r_idx][c_idx], thumb=thumb_px)
            ax.imshow(tile)
            ax.set_xticks([])
            ax.set_yticks([])
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Op handle
# ---------------------------------------------------------------------------


class AugmentedSampleGridOp:
    """Visualization handle for ``augmented_sample_grid``.

    Returns a ``Mapping[str, bytes]`` keyed by each declared
    ``AugmentationOp.name``; the pipeline stage writes each entry as
    ``<viz.name>_<aug.name>.png``. Returns an empty mapping when no
    augmentations are declared.

    The handle is constructed with a reference to the plugin's
    realizer registry so lazy-mode rendering can dispatch without
    importing the plugin module (avoiding a circular import). The
    plugin owns the dict instance — the handle reads through it, so
    realizer registrations added after construction are still visible.
    """

    def __init__(self, realizers: Mapping[str, Realizer] | None = None) -> None:
        self._realizers: Mapping[str, Realizer] = realizers if realizers is not None else {}

    def render(
        self,
        splits: Mapping[str, list[Record]],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
        recipe: Recipe | None = None,
    ) -> Mapping[str, bytes]:
        del label_field
        if recipe is None:
            raise ValueError(
                "augmented_sample_grid requires the recipe context to read "
                "Augmentations and seed; the stage runner must pass recipe=..."
            )
        p = AugmentedSampleGridParams(**dict(params))
        train_records = list(splits.get("train", []))
        global_seed = int(recipe.seed) ^ int(p.seed or 0)

        out: dict[str, bytes] = {}
        for aug in recipe.Augmentations:
            if aug.materialization == "aggressive":
                grid = select_aggressive_grid(
                    train_records, n_base=p.n_base, n_variants=p.n_variants
                )
            else:
                realizer = self._realizers.get(aug.op)
                if realizer is None:
                    raise ValueError(
                        f"augmented_sample_grid: no realizer registered for "
                        f"lazy op {aug.op!r} (name={aug.name!r})"
                    )
                grid = realize_lazy_grid(
                    train_records,
                    aug=aug,
                    realizer=realizer,
                    n_base=p.n_base,
                    n_variants=p.n_variants,
                    global_seed=global_seed,
                )
            fig = build_augmented_sample_grid_figure(grid, title=aug.name)
            out[aug.name] = encode_png(fig)
        return out
