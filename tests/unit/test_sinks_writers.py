# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the `png_per_record` sink writer (Story I.d)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.sinks.writers import write_png_per_record


def _uint8_rgb(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8)


def test_writer_round_trip_rgb(tmp_path: Path) -> None:
    arr = _uint8_rgb(1)
    out = tmp_path / "subdir" / "x.png"
    write_png_per_record(
        record={"image": arr},
        field="image",
        output_path=out,
        sink_name="pngs",
        stage="post_Filters",
    )
    assert out.exists()
    decoded = np.array(Image.open(out))
    assert decoded.shape == arr.shape
    np.testing.assert_array_equal(decoded, arr)


def test_writer_matches_fromarray_baseline(tmp_path: Path) -> None:
    arr = _uint8_rgb(2)
    out = tmp_path / "y.png"
    write_png_per_record(
        record={"image": arr},
        field="image",
        output_path=out,
        sink_name="pngs",
        stage="post_Generation",
    )
    baseline_buf = io.BytesIO()
    Image.fromarray(arr).save(baseline_buf, format="PNG", optimize=False)
    assert out.read_bytes() == baseline_buf.getvalue(), (
        "Sink writer output must match PIL.Image.fromarray's PNG encoding byte-for-byte"
    )


def test_writer_grayscale_2d(tmp_path: Path) -> None:
    arr = np.random.default_rng(3).integers(0, 256, size=(4, 6), dtype=np.uint8)
    out = tmp_path / "g.png"
    write_png_per_record(
        record={"image": arr},
        field="image",
        output_path=out,
        sink_name="pngs",
        stage="post_Filters",
    )
    decoded = np.array(Image.open(out))
    np.testing.assert_array_equal(decoded, arr)


def test_writer_rejects_non_uint8(tmp_path: Path) -> None:
    arr = _uint8_rgb(0).astype(np.float32)
    with pytest.raises(MaterializeError, match="expects uint8"):
        write_png_per_record(
            record={"image": arr},
            field="image",
            output_path=tmp_path / "x.png",
            sink_name="pngs",
            stage="post_Transformations",
        )


def test_writer_rejects_missing_field(tmp_path: Path) -> None:
    with pytest.raises(MaterializeError, match="missing required field"):
        write_png_per_record(
            record={"label": "cat"},
            field="image",
            output_path=tmp_path / "x.png",
            sink_name="pngs",
            stage="post_Filters",
        )


def test_writer_rejects_non_ndarray(tmp_path: Path) -> None:
    with pytest.raises(MaterializeError, match="numpy ndarray"):
        write_png_per_record(
            record={"image": [[1, 2], [3, 4]]},
            field="image",
            output_path=tmp_path / "x.png",
            sink_name="pngs",
            stage="post_Filters",
        )


def test_writer_rejects_bad_ndim(tmp_path: Path) -> None:
    arr = np.zeros((2, 2, 2, 2), dtype=np.uint8)
    with pytest.raises(MaterializeError, match=r"HxW or HxWxC"):
        write_png_per_record(
            record={"image": arr},
            field="image",
            output_path=tmp_path / "x.png",
            sink_name="pngs",
            stage="post_Filters",
        )
