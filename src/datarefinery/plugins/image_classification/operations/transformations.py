# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: Transformations operations (Story C.h, FR-10).

Each handle exposes ``fit`` and ``apply`` per the Transformations
operation interface in ``datarefinery.pipeline.stages.transformations``.

v1 ships ``resize``, ``normalize``, ``mean_subtract``, and ``cast``
(Story I.k / G2). A real ``to_grayscale`` implementation is deferred to
``stories.md § Future``; the declared-but-unimplemented spec was removed
in Story I.k.

Image records carry an ``"image"`` field whose value is a NumPy array of
shape ``(H, W, C)`` with a numeric dtype. ``normalize`` and
``mean_subtract`` compute per-channel statistics, which means the same
``C`` is required across the train split and at apply time.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from PIL import Image

from datarefinery.core.errors import PluginError
from datarefinery.pipeline.stages.transformations import FittedValues
from datarefinery.plugins.normalize_stats import (
    fit_mean_std,
    unwrap_mean_std,
    wrap_mean_std,
    zscore,
)

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
            raise PluginError(f"resize requires positive integer 'size' (got {size!r})")
        method_name = str(params["method"])
        method = _RESAMPLE_METHODS.get(method_name)
        if method is None:
            raise PluginError(
                f"resize 'method' must be one of "
                f"{sorted(_RESAMPLE_METHODS)!r} (got {method_name!r})"
            )
        return [_replace_image(r, _resize_one(r["image"], size, method)) for r in records]


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
        raise PluginError(f"resize expects 2-D or 3-D image array (got ndim={arr.ndim})")
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
        # Per-channel z-score (last axis); the std==0 guard lives in `zscore`.
        return [_replace_image(r, zscore(r["image"], mean, std, axis=-1)) for r in records]


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
        return [_replace_image(r, np.asarray(r["image"], dtype=np.float64) - mean) for r in records]


# ---------------------------------------------------------------------------
# cast (no fit; Story I.k / G2)
# ---------------------------------------------------------------------------


class CastOp:
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
        dtype_param = params.get("dtype")
        if not isinstance(dtype_param, str):
            raise PluginError(f"cast requires string 'dtype' (got {dtype_param!r})")
        try:
            target_dtype = np.dtype(dtype_param)
        except TypeError as exc:
            raise PluginError(f"cast 'dtype' is not a valid NumPy dtype: {dtype_param!r}") from exc
        scale = float(params["scale"])
        return [_replace_image(r, _cast_one(r["image"], target_dtype, scale)) for r in records]


def _cast_one(image: Any, target_dtype: np.dtype, scale: float) -> np.ndarray:
    arr = np.asarray(image).astype(target_dtype)
    if scale != 1.0:
        arr = (arr * np.array(scale, dtype=target_dtype)).astype(target_dtype)
    return arr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _image_reduce_axes(ndim: int) -> tuple[int, ...] | None:
    # Reduce across N, H, W; keep the channel axis (last) if present. A stack of
    # 1-D per-record arrays (ndim < 3) reduces to a single scalar statistic.
    return tuple(range(ndim - 1)) if ndim >= 3 else None


def _per_channel_mean_std(
    records: list[Record],
) -> tuple[np.ndarray, np.ndarray]:
    # Shared fit machinery (Story J.t); the image op keeps the *last* axis.
    return fit_mean_std(records, field="image", reduce_axes_for=_image_reduce_axes)


# Thin aliases preserved for the image ops (NormalizeOp / MeanSubtractOp); the
# implementations now live in `datarefinery.plugins.normalize_stats`.
_wrap_mean_std = wrap_mean_std
_unwrap_mean_std = unwrap_mean_std


def _replace_image(record: Record, new_image: np.ndarray) -> dict[str, Any]:
    out = dict(record)
    out["image"] = new_image
    return out
