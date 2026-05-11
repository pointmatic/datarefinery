# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: Visualizations operations (Story C.k).

All three handles return PNG bytes via Pillow alone (no matplotlib in
the v1 dependency set, per `pyproject.toml`). The renders are
deterministic given fixed input record order: class iteration uses a
stable ``(type, repr)`` ordering, sample selection takes the first N
records (no RNG), and Pillow's PNG encoder is byte-deterministic for
identical pixel inputs.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from datarefinery.core.errors import PluginError

Record = Mapping[str, Any]


# ---------------------------------------------------------------------------
# class_distribution_histogram
# ---------------------------------------------------------------------------


class ClassDistributionHistogramOp:
    """Bar chart of per-class record counts across all splits."""

    def render(
        self,
        splits: Mapping[str, list[Record]],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
    ) -> bytes:
        del params
        if label_field is None:
            raise PluginError("class_distribution_histogram requires Labels.field")
        counts: dict[Any, int] = {}
        for recs in splits.values():
            for r in recs:
                lbl = r.get(label_field)
                counts[lbl] = counts.get(lbl, 0) + 1

        canvas_w, canvas_h = 400, 300
        margin = 30
        plot_w = canvas_w - 2 * margin
        plot_h = canvas_h - 2 * margin

        img = Image.new("RGB", (canvas_w, canvas_h), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        if counts:
            classes = sorted(counts.keys(), key=lambda x: (type(x).__name__, repr(x)))
            max_count = max(counts.values())
            n = len(classes)
            bar_w = plot_w / max(n, 1)
            for i, cls in enumerate(classes):
                h = (counts[cls] / max_count) * (plot_h - 20)
                x0 = margin + i * bar_w + 2
                x1 = margin + (i + 1) * bar_w - 2
                y0 = canvas_h - margin - int(h)
                y1 = canvas_h - margin
                draw.rectangle([(x0, y0), (x1, y1)], fill=(70, 130, 180))
                draw.text(
                    (x0, canvas_h - margin + 2),
                    str(cls),
                    fill=(0, 0, 0),
                )
        # Axes (just two lines).
        draw.line(
            [(margin, margin), (margin, canvas_h - margin)],
            fill=(0, 0, 0),
            width=1,
        )
        draw.line(
            [
                (margin, canvas_h - margin),
                (canvas_w - margin, canvas_h - margin),
            ],
            fill=(0, 0, 0),
            width=1,
        )
        return _encode_png(img)


# ---------------------------------------------------------------------------
# sample_grid
# ---------------------------------------------------------------------------


class SampleGridOp:
    """Tile the first N records' images into a square-ish grid.

    Deterministic by record order. With ``per_class=True``, takes the
    first N from each class instead.
    """

    def render(
        self,
        splits: Mapping[str, list[Record]],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
    ) -> bytes:
        n = int(params.get("n", 16))
        per_class = bool(params.get("per_class", False))
        all_records = [r for recs in splits.values() for r in recs]
        if not all_records:
            return _encode_png(_blank(64, 64))

        if per_class:
            if label_field is None:
                raise PluginError("sample_grid per_class=True requires Labels.field")
            by_class: dict[Any, list[Record]] = {}
            for r in all_records:
                by_class.setdefault(r.get(label_field), []).append(r)
            chosen: list[Record] = []
            for cls in sorted(by_class.keys(), key=lambda x: (type(x).__name__, repr(x))):
                chosen.extend(by_class[cls][:n])
        else:
            chosen = all_records[:n]

        # Resize each image to a uniform thumbnail.
        thumb = 32
        tiles = [_to_uint8_rgb(_to_array(r["image"]), thumb) for r in chosen]
        if not tiles:
            return _encode_png(_blank(thumb, thumb))

        cols = max(1, int(np.ceil(np.sqrt(len(tiles)))))
        rows = (len(tiles) + cols - 1) // cols
        canvas = Image.new("RGB", (cols * thumb, rows * thumb), color=(255, 255, 255))
        for idx, tile_arr in enumerate(tiles):
            r_idx, c_idx = divmod(idx, cols)
            tile_img = Image.fromarray(tile_arr)
            canvas.paste(tile_img, (c_idx * thumb, r_idx * thumb))
        return _encode_png(canvas)


# ---------------------------------------------------------------------------
# mean_image_per_class
# ---------------------------------------------------------------------------


class MeanImagePerClassOp:
    """Per-class mean image, tiled in a row."""

    def render(
        self,
        splits: Mapping[str, list[Record]],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
    ) -> bytes:
        del params
        if label_field is None:
            raise PluginError("mean_image_per_class requires Labels.field")
        all_records = [r for recs in splits.values() for r in recs]
        if not all_records:
            return _encode_png(_blank(64, 64))

        by_class: dict[Any, list[np.ndarray]] = {}
        for r in all_records:
            by_class.setdefault(r.get(label_field), []).append(_to_array(r["image"]))
        if not by_class:
            return _encode_png(_blank(64, 64))

        thumb = 32
        means: list[np.ndarray] = []
        for cls in sorted(by_class.keys(), key=lambda x: (type(x).__name__, repr(x))):
            arrs = by_class[cls]
            stack = np.stack([_resize_array(a, thumb) for a in arrs], dtype=np.float64)
            mean = stack.mean(axis=0)
            means.append(np.clip(mean, 0, 255).astype(np.uint8))

        rgb_tiles = [_to_rgb(m) for m in means]
        canvas = Image.new("RGB", (len(rgb_tiles) * thumb, thumb), color=(255, 255, 255))
        for idx, tile in enumerate(rgb_tiles):
            canvas.paste(Image.fromarray(tile), (idx * thumb, 0))
        return _encode_png(canvas)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _blank(w: int, h: int) -> Image.Image:
    return Image.new("RGB", (w, h), color=(255, 255, 255))


def _to_array(image: Any) -> np.ndarray:
    arr = np.asarray(image)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return arr


def _to_rgb(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        return np.stack([arr, arr, arr], axis=-1)
    if arr.ndim == 3 and arr.shape[-1] == 1:
        return np.repeat(arr, 3, axis=-1)
    if arr.ndim == 3 and arr.shape[-1] == 3:
        return arr
    raise PluginError(f"image array shape {arr.shape!r} not convertible to RGB")


def _to_uint8_rgb(arr: np.ndarray, size: int) -> np.ndarray:
    return _resize_array(_to_rgb(arr), size)


def _resize_array(arr: np.ndarray, size: int) -> np.ndarray:
    img = Image.fromarray(_to_rgb(arr) if arr.ndim == 2 else arr)
    img = img.resize((size, size), resample=Image.Resampling.BILINEAR)
    out = np.asarray(img)
    if out.ndim == 2:
        out = _to_rgb(out)
    return out
