# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: Transformations operations (Story C.h, FR-10).

Each handle exposes ``fit`` and ``apply`` per the Transformations
operation interface in ``datarefinery.pipeline.stages.transformations``.

v1 ships ``resize``, ``normalize``, and ``mean_subtract``. The remaining
declared ops (``to_grayscale``, ``cast_dtype``) raise
``NotImplementedError`` from the plugin's ``operation_factory`` until
follow-up stories land them.

Image records carry an ``"image"`` field whose value is a NumPy array of
shape ``(H, W, C)`` with a numeric dtype. ``normalize`` and
``mean_subtract`` compute per-channel statistics, which means the same
``C`` is required across the train split and at apply time.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pyarrow as pa
from PIL import Image

from datarefinery.core.errors import MaterializeError, PluginError
from datarefinery.pipeline.stages.transformations import FittedValues

Record = Mapping[str, Any]


# ---------------------------------------------------------------------------
# resize (no fit phase)
# ---------------------------------------------------------------------------


class ResizeOp:
    fit_on_train: bool = False

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
    ) -> FittedValues:
        del records, params, label_field
        return FittedValues()

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        label_field: str | None,
    ) -> list[Record]:
        del fitted, label_field
        size = params.get("size")
        if not isinstance(size, int) or size <= 0:
            raise PluginError(
                f"resize requires positive integer 'size' (got {size!r})"
            )
        method_name = str(params.get("method", "bilinear"))
        method = _RESAMPLE_METHODS.get(method_name)
        if method is None:
            raise PluginError(
                f"resize 'method' must be one of "
                f"{sorted(_RESAMPLE_METHODS)!r} (got {method_name!r})"
            )
        return [
            _replace_image(r, _resize_one(r["image"], size, method))
            for r in records
        ]


_RESAMPLE_METHODS: dict[str, Image.Resampling] = {
    "nearest": Image.Resampling.NEAREST,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS,
}


def _resize_one(image: Any, size: int, method: Image.Resampling) -> np.ndarray:
    arr = _as_uint8_image(image)
    pil = Image.fromarray(arr)
    pil = pil.resize((size, size), resample=method)
    return np.asarray(pil)


def _as_uint8_image(image: Any) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim not in (2, 3):
        raise PluginError(
            f"resize expects 2-D or 3-D image array (got ndim={arr.ndim})"
        )
    if arr.dtype != np.uint8:
        # Pillow needs uint8 for arbitrary mode; clip and cast.
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return arr


# ---------------------------------------------------------------------------
# normalize (fit-on-train)
# ---------------------------------------------------------------------------


class NormalizeOp:
    fit_on_train: bool = True

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
    ) -> FittedValues:
        del label_field
        # If the recipe pinned mean/std, honor it as the fit output so
        # apply uses the recipe values rather than computing.
        mean_param = params.get("mean")
        std_param = params.get("std")
        if mean_param is not None and std_param is not None:
            mean = np.asarray(mean_param, dtype=np.float64)
            std = np.asarray(std_param, dtype=np.float64)
        else:
            mean, std = _per_channel_mean_std(records)
        return _wrap_mean_std(mean, std)

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        label_field: str | None,
    ) -> list[Record]:
        del params, label_field
        mean, std = _unwrap_mean_std(fitted)
        # Guard against zero variance channels.
        std_safe = np.where(std == 0, 1.0, std)
        return [
            _replace_image(
                r, ((np.asarray(r["image"], dtype=np.float64) - mean) / std_safe)
            )
            for r in records
        ]


# ---------------------------------------------------------------------------
# mean_subtract (fit-on-train, mean only)
# ---------------------------------------------------------------------------


class MeanSubtractOp:
    fit_on_train: bool = True

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
    ) -> FittedValues:
        del params, label_field
        mean, _ = _per_channel_mean_std(records)
        return _wrap_mean_std(mean, None)

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        label_field: str | None,
    ) -> list[Record]:
        del params, label_field
        mean, _ = _unwrap_mean_std(fitted)
        return [
            _replace_image(
                r, np.asarray(r["image"], dtype=np.float64) - mean
            )
            for r in records
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _per_channel_mean_std(
    records: list[Record],
) -> tuple[np.ndarray, np.ndarray]:
    if not records:
        raise MaterializeError(
            "fit phase received an empty records list; cannot compute "
            "per-channel statistics"
        )
    stack = np.stack(
        [np.asarray(r["image"], dtype=np.float64) for r in records]
    )
    # Reduce across N, H, W; keep channel axis if present.
    axes_to_reduce = tuple(range(stack.ndim - 1)) if stack.ndim >= 3 else None
    mean = stack.mean(axis=axes_to_reduce)
    std = stack.std(axis=axes_to_reduce)
    mean = np.atleast_1d(mean).astype(np.float64)
    std = np.atleast_1d(std).astype(np.float64)
    return mean, std


def _wrap_mean_std(
    mean: np.ndarray, std: np.ndarray | None
) -> FittedValues:
    vectors = {"mean": pa.table({"value": mean.tolist()})}
    if std is not None:
        vectors["std"] = pa.table({"value": std.tolist()})
    return FittedValues(scalars={}, vectors=vectors)


def _unwrap_mean_std(
    fitted: FittedValues,
) -> tuple[np.ndarray, np.ndarray]:
    if "mean" not in fitted.vectors:
        raise MaterializeError(
            "transformation apply received fitted values without 'mean'"
        )
    mean = np.asarray(fitted.vectors["mean"]["value"].to_pylist(), dtype=np.float64)
    std_table = fitted.vectors.get("std")
    if std_table is None:
        std = np.ones_like(mean)
    else:
        std = np.asarray(std_table["value"].to_pylist(), dtype=np.float64)
    return mean, std


def _replace_image(record: Record, new_image: np.ndarray) -> dict[str, Any]:
    out = dict(record)
    out["image"] = new_image
    return out
