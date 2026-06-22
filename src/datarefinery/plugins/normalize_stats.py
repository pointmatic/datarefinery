# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Shared per-axis mean/std normalization helpers (Story J.t).

Extracted from the image-classification ``NormalizeOp`` so the audio
``audio_normalize`` op can reuse the *identical* fit / parquet-wrap /
zero-variance-guard discipline while keeping a **different statistics axis** —
per-channel for images (last axis), per-mel-bin for audio log-mel features
(mel axis). The two callers differ only in:

- the record field they normalize (``image`` vs. ``feature``), and
- which array axis the statistics are computed per (passed as ``reduce_axes_for``
  for the fit phase and ``axis`` for the apply phase).

Keeping one implementation of the fit math, the ``pa.Table`` wrap/unwrap, and the
``std == 0 → 1.0`` apply-time guard means the cross-modality contract pinned in
``modelfoundry/vendor-dependency-spec.md`` (persisted ``std.parquet`` carries the
*unmodified* fit value; the guard fires only at apply) holds for both modalities
by construction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
import pyarrow as pa

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.stages.transformations import FittedValues

Record = Mapping[str, Any]

#: A function mapping the *stacked* array's ndim to the axes to reduce over when
#: fitting (``None`` ⇒ reduce everything to a scalar, NumPy's ``axis=None``).
ReduceAxesFor = Callable[[int], tuple[int, ...] | None]


def fit_mean_std(
    records: list[Record],
    *,
    field: str,
    reduce_axes_for: ReduceAxesFor,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute mean/std vectors over a stack of per-record arrays.

    The per-record arrays at ``field`` are stacked along a new leading axis; the
    statistic is reduced over ``reduce_axes_for(stack.ndim)`` and the surviving
    axis (or axes) becomes the length of the returned vectors. Always returns at
    least 1-D arrays (``np.atleast_1d``).
    """
    if not records:
        raise MaterializeError(
            "fit phase received an empty records list; cannot compute normalization statistics"
        )
    stack = np.stack([np.asarray(r[field], dtype=np.float64) for r in records])
    axes = reduce_axes_for(stack.ndim)
    mean = np.atleast_1d(stack.mean(axis=axes)).astype(np.float64)
    std = np.atleast_1d(stack.std(axis=axes)).astype(np.float64)
    return mean, std


def wrap_mean_std(mean: np.ndarray, std: np.ndarray | None) -> FittedValues:
    """Wrap mean (and optional std) vectors as a persistable ``FittedValues``."""
    vectors = {"mean": pa.table({"value": mean.tolist()})}
    if std is not None:
        vectors["std"] = pa.table({"value": std.tolist()})
    return FittedValues(scalars={}, vectors=vectors)


def unwrap_mean_std(fitted: FittedValues) -> tuple[np.ndarray, np.ndarray]:
    """Read back mean/std vectors; a missing ``std`` defaults to all-ones."""
    if "mean" not in fitted.vectors:
        raise MaterializeError("transformation apply received fitted values without 'mean'")
    mean = np.asarray(fitted.vectors["mean"]["value"].to_pylist(), dtype=np.float64)
    std_table = fitted.vectors.get("std")
    if std_table is None:
        std = np.ones_like(mean)
    else:
        std = np.asarray(std_table["value"].to_pylist(), dtype=np.float64)
    return mean, std


def zscore(arr: Any, mean: np.ndarray, std: np.ndarray, *, axis: int) -> np.ndarray:
    """Z-score ``arr`` with ``mean``/``std`` broadcast along ``axis``.

    The zero-variance guard substitutes ``std == 0 → 1.0`` at apply time only
    (the persisted ``std`` keeps the unmodified fit value). ``mean``/``std`` are
    reshaped to broadcast along ``axis`` of ``arr`` — ``axis=-1`` reproduces the
    image per-channel behavior (NumPy's natural trailing-axis broadcast); other
    axes (e.g. ``axis=0`` for per-mel-bin audio features) reshape explicitly.
    """
    a = np.asarray(arr, dtype=np.float64)
    std_safe = np.where(std == 0, 1.0, std)
    shape = [1] * a.ndim
    shape[axis] = mean.shape[0]
    result: np.ndarray = (a - mean.reshape(shape)) / std_safe.reshape(shape)
    return result
