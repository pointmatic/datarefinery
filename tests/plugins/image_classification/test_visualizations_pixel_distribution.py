# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-VIZ-1 ``pixel_distribution`` tests (Story H.t).

Covers the new per-channel pixel-value histogram visualization,
including:

* Pydantic param validation (``PixelDistributionParams``).
* The shared matplotlib helpers in ``_render.py`` (figure construction
  + deterministic PNG encoding).
* The op handle returning ``Mapping[str, bytes]`` (one PNG per split).
* Plugin registration.
* Pipeline-stage support for the multi-PNG return type, writing
  ``<op.name>_<split>.png`` per entry.
* Exploration-mode rendering preserving the mapping.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from datarefinery.pipeline.stages.visualizations import (
    apply_reporting_visualizations,
)
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.image_classification.visualizations._render import (
    encode_png,
    new_figure,
)
from datarefinery.plugins.image_classification.visualizations.pixel_distribution import (
    PixelDistributionOp,
    PixelDistributionParams,
    build_pixel_distribution_figure,
)
from datarefinery.recipe.models import VisualizationOp
from datarefinery.reporting.visualizations import render_visualization


def _img(value: int = 0) -> np.ndarray:
    return np.full((8, 8, 3), value, dtype=np.uint8)


def _splits() -> dict[str, list[Mapping[str, Any]]]:
    return {
        "train": [
            {"image": _img(20), "label": "cat"},
            {"image": _img(60), "label": "dog"},
            {"image": _img(120), "label": "cat"},
        ],
        "val": [
            {"image": _img(40), "label": "cat"},
            {"image": _img(200), "label": "dog"},
        ],
    }


def _viz(name: str, op: str, mode: str, **params: Any) -> VisualizationOp:
    return VisualizationOp(name=name, op=op, params=params, stage="post_pipeline", mode=mode)


def _is_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


# ---------------------------------------------------------------------------
# PixelDistributionParams
# ---------------------------------------------------------------------------


def test_params_defaults_bins_to_64() -> None:
    p = PixelDistributionParams(splits=["train"])
    assert p.bins == 64
    assert p.splits == ["train"]


def test_params_rejects_empty_splits() -> None:
    with pytest.raises(ValidationError):
        PixelDistributionParams(splits=[])


def test_params_accepts_custom_bins() -> None:
    p = PixelDistributionParams(splits=["train", "val"], bins=32)
    assert p.bins == 32


# ---------------------------------------------------------------------------
# build_pixel_distribution_figure: 3 subplots (R, G, B)
# ---------------------------------------------------------------------------


def test_figure_has_three_subplots() -> None:
    records = _splits()["train"]
    fig = build_pixel_distribution_figure(records, bins=64)
    assert len(fig.axes) == 3


def test_figure_subplots_titled_per_channel() -> None:
    records = _splits()["train"]
    fig = build_pixel_distribution_figure(records, bins=64)
    titles = [ax.get_title() for ax in fig.axes]
    # Channel labels must appear in order R, G, B.
    assert titles[0].upper().startswith("R")
    assert titles[1].upper().startswith("G")
    assert titles[2].upper().startswith("B")


# ---------------------------------------------------------------------------
# Shared render helpers: deterministic PNG bytes
# ---------------------------------------------------------------------------


def test_encode_png_is_byte_deterministic() -> None:
    records = _splits()["train"]
    fig_a = build_pixel_distribution_figure(records, bins=64)
    fig_b = build_pixel_distribution_figure(records, bins=64)
    assert encode_png(fig_a) == encode_png(fig_b)


def test_new_figure_returns_matplotlib_figure() -> None:
    fig = new_figure(width_in=6.0, height_in=2.0)
    # Has the matplotlib Figure API surface we depend on.
    assert hasattr(fig, "add_subplot")
    assert hasattr(fig, "savefig")


# ---------------------------------------------------------------------------
# PixelDistributionOp: render returns Mapping[str, bytes]
# ---------------------------------------------------------------------------


def test_op_render_returns_mapping_keyed_by_split() -> None:
    op_handle = PixelDistributionOp()
    out = op_handle.render(
        _splits(),
        {"bins": 64, "splits": ["train", "val"]},
        label_field="label",
    )
    assert isinstance(out, Mapping)
    assert set(out.keys()) == {"train", "val"}
    for png in out.values():
        assert _is_png(png)


def test_op_render_only_requested_splits() -> None:
    op_handle = PixelDistributionOp()
    out = op_handle.render(
        _splits(),
        {"bins": 32, "splits": ["train"]},
        label_field="label",
    )
    assert set(out.keys()) == {"train"}


def test_op_render_missing_split_raises() -> None:
    op_handle = PixelDistributionOp()
    with pytest.raises(KeyError, match="absent"):
        op_handle.render(
            _splits(),
            {"bins": 64, "splits": ["absent"]},
            label_field="label",
        )


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def test_plugin_registers_pixel_distribution_spec() -> None:
    spec = IMAGE_PLUGIN.supported_operations["pixel_distribution"]
    assert "Visualizations" in spec.applicable_sections
    assert "bins" in spec.parameters
    assert "splits" in spec.parameters
    assert spec.parameters["splits"].required is True


def test_plugin_operation_factory_returns_pixel_distribution_handle() -> None:
    handle = IMAGE_PLUGIN.operation_factory("Visualizations", "pixel_distribution")
    assert isinstance(handle, PixelDistributionOp)


# ---------------------------------------------------------------------------
# Pipeline stage: writes <op.name>_<split>.png per mapping entry
# ---------------------------------------------------------------------------


def test_reporting_writes_one_png_per_split(tmp_path: Path) -> None:
    op = _viz(
        "px_dist",
        "pixel_distribution",
        "reporting",
        bins=64,
        splits=["train", "val"],
    )
    result = apply_reporting_visualizations(
        _splits(),
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    written = {p.name for p in result.written_paths}
    assert written == {"px_dist_train.png", "px_dist_val.png"}
    for path in result.written_paths:
        assert _is_png(path.read_bytes())


def test_reporting_pixel_distribution_is_deterministic(tmp_path: Path) -> None:
    op = _viz("px_dist", "pixel_distribution", "reporting", splits=["train"])
    a = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "a", label_field="label"
    )
    b = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "b", label_field="label"
    )
    assert a.rendered[0].png_bytes == b.rendered[0].png_bytes


# ---------------------------------------------------------------------------
# Exploration-mode library API: preserves mapping
# ---------------------------------------------------------------------------


def test_exploration_render_returns_rendered_with_no_path() -> None:
    op = _viz(
        "px_dist",
        "pixel_distribution",
        "exploration",
        splits=["train", "val"],
    )
    rendered = render_visualization(_splits(), op, plugin=IMAGE_PLUGIN, label_field="label")
    assert rendered.path is None
    assert _is_png(rendered.png_bytes)
    # Exploration mode collapses to the first split for the in-memory hook,
    # but the full mapping is exposed under .extras.
    assert set(rendered.extras.keys()) == {"train", "val"}
    for png in rendered.extras.values():
        assert _is_png(png)


# ---------------------------------------------------------------------------
# Pixel-level smoke check
# ---------------------------------------------------------------------------


def test_rendered_pngs_decode_to_valid_image(tmp_path: Path) -> None:
    op = _viz("px_dist", "pixel_distribution", "reporting", splits=["train"])
    result = apply_reporting_visualizations(
        _splits(),
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    img = Image.open(io.BytesIO(result.rendered[0].png_bytes))
    img.load()
    assert img.mode in {"RGB", "RGBA"}
    assert img.size[0] > 0 and img.size[1] > 0
