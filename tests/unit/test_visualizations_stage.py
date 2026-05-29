# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-13 visualizations tests (Story C.k).

Covers the reporting-mode pipeline stage and the exploration-mode
library API, plus the image plugin's three viz ops.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.stages.visualizations import (
    RenderedVisualization,
    VisualizationsResult,
    apply_reporting_visualizations,
)
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import VisualizationOp
from datarefinery.reporting.visualizations import render_visualization


def _img(value: int = 0, c: int = 3) -> np.ndarray:
    return np.full((16, 16, c), value, dtype=np.uint8)


def _splits() -> dict[str, list[Mapping[str, Any]]]:
    return {
        "train": [
            {"image": _img(20), "label": "cat"},
            {"image": _img(40), "label": "dog"},
            {"image": _img(60), "label": "cat"},
            {"image": _img(80), "label": "dog"},
            {"image": _img(100), "label": "fish"},
        ],
        "val": [
            {"image": _img(30), "label": "cat"},
            {"image": _img(70), "label": "dog"},
        ],
    }


def _viz(name: str, op: str, mode: str, **params: Any) -> VisualizationOp:
    return VisualizationOp(name=name, op=op, params=params, stage="post_pipeline", mode=mode)


def _is_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


# ---------------------------------------------------------------------------
# Reporting-mode stage: writes PNGs under output_dir
# ---------------------------------------------------------------------------


def test_reporting_writes_png_per_op(tmp_path: Path) -> None:
    ops = [
        _viz("hist", "class_distribution_histogram", "reporting"),
        _viz("grid", "sample_grid", "reporting", n=4),
        _viz("means", "mean_image_per_class", "reporting"),
    ]
    out_dir = tmp_path / "report" / "visualizations"
    result = apply_reporting_visualizations(
        _splits(), ops, plugin=IMAGE_PLUGIN, output_dir=out_dir, label_field="label"
    )
    assert isinstance(result, VisualizationsResult)
    assert result.output_dir == out_dir
    assert {p.name for p in result.written_paths} == {
        "hist.png",
        "grid.png",
        "means.png",
    }
    for path in result.written_paths:
        assert _is_png(path.read_bytes())


def test_reporting_skips_exploration_mode_ops(tmp_path: Path) -> None:
    ops = [
        _viz("hist_r", "class_distribution_histogram", "reporting"),
        _viz("hist_e", "class_distribution_histogram", "exploration"),
    ]
    result = apply_reporting_visualizations(
        _splits(),
        ops,
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    names = [r.name for r in result.rendered]
    assert names == ["hist_r"]
    assert not (tmp_path / "hist_e.png").exists()


def test_reporting_creates_output_directory(tmp_path: Path) -> None:
    op = _viz("hist", "class_distribution_histogram", "reporting")
    out_dir = tmp_path / "deep" / "nested" / "report" / "visualizations"
    apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=out_dir, label_field="label"
    )
    assert out_dir.is_dir()


def test_reporting_empty_op_list_is_passthrough(tmp_path: Path) -> None:
    result = apply_reporting_visualizations(
        _splits(),
        [],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    assert result.rendered == ()
    assert result.written_paths == ()


# ---------------------------------------------------------------------------
# Determinism: same input -> same PNG bytes
# ---------------------------------------------------------------------------


def test_class_distribution_histogram_is_deterministic(tmp_path: Path) -> None:
    op = _viz("hist", "class_distribution_histogram", "reporting")
    a = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "a", label_field="label"
    )
    b = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "b", label_field="label"
    )
    assert a.rendered[0].png_bytes == b.rendered[0].png_bytes


def test_sample_grid_is_deterministic(tmp_path: Path) -> None:
    op = _viz("grid", "sample_grid", "reporting", n=4)
    a = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "a", label_field="label"
    )
    b = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "b", label_field="label"
    )
    assert a.rendered[0].png_bytes == b.rendered[0].png_bytes


def test_mean_image_per_class_is_deterministic(tmp_path: Path) -> None:
    op = _viz("means", "mean_image_per_class", "reporting")
    a = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "a", label_field="label"
    )
    b = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "b", label_field="label"
    )
    assert a.rendered[0].png_bytes == b.rendered[0].png_bytes


def test_different_inputs_produce_different_pngs(tmp_path: Path) -> None:
    op = _viz("hist", "class_distribution_histogram", "reporting")
    a = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "a", label_field="label"
    )
    # Add a class that wasn't there.
    splits_b = _splits()
    splits_b["train"].append({"image": _img(0), "label": "bird"})
    b = apply_reporting_visualizations(
        splits_b, [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "b", label_field="label"
    )
    assert a.rendered[0].png_bytes != b.rendered[0].png_bytes


# ---------------------------------------------------------------------------
# Visualization op behavior
# ---------------------------------------------------------------------------


def test_sample_grid_per_class_picks_first_n_per_class(tmp_path: Path) -> None:
    op = _viz("grid", "sample_grid", "reporting", n=2, per_class=True)
    result = apply_reporting_visualizations(
        _splits(),
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    assert _is_png(result.rendered[0].png_bytes)


def test_sample_grid_with_no_records_returns_blank(tmp_path: Path) -> None:
    op = _viz("grid", "sample_grid", "reporting", n=4)
    result = apply_reporting_visualizations(
        {"train": []},
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    assert _is_png(result.rendered[0].png_bytes)


def test_class_distribution_with_no_records_renders_axes_only(
    tmp_path: Path,
) -> None:
    op = _viz("hist", "class_distribution_histogram", "reporting")
    result = apply_reporting_visualizations(
        {"train": []},
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    assert _is_png(result.rendered[0].png_bytes)


def test_visualizations_require_label_field(tmp_path: Path) -> None:
    op = _viz("hist", "class_distribution_histogram", "reporting")
    with pytest.raises(MaterializeError, match=r"Labels\.field"):
        apply_reporting_visualizations(_splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path)


# ---------------------------------------------------------------------------
# FR-13 hard-error: reporting failure raises MaterializeError
# ---------------------------------------------------------------------------


class _FailingPlugin:
    name = "failing"
    schema_version = 1
    supported_sections = frozenset({"Visualizations"})

    def __init__(self) -> None:
        self.supported_operations: dict[str, Any] = {}

    def operation_factory(self, section: str, op_name: str) -> Any:
        del section, op_name

        class _Fail:
            def render(
                self,
                splits: Mapping[str, list[Mapping[str, Any]]],
                params: Mapping[str, Any],
                *,
                label_field: str | None,
                recipe: Any = None,
            ) -> bytes:
                del splits, params, label_field, recipe
                raise RuntimeError("kaboom")

        return _Fail()

    def is_stub(self) -> bool:
        return False


def test_reporting_failure_raises_materialize_error(tmp_path: Path) -> None:
    op = _viz("bad", "any", "reporting")
    with pytest.raises(MaterializeError, match="kaboom"):
        apply_reporting_visualizations(
            _splits(),
            [op],
            plugin=_FailingPlugin(),
            output_dir=tmp_path,
            label_field="label",
        )


class _BadReturnPlugin:
    name = "bad_return"
    schema_version = 1
    supported_sections = frozenset({"Visualizations"})

    def __init__(self) -> None:
        self.supported_operations: dict[str, Any] = {}

    def operation_factory(self, section: str, op_name: str) -> Any:
        del section, op_name

        class _BadReturn:
            def render(
                self,
                splits: Mapping[str, list[Mapping[str, Any]]],
                params: Mapping[str, Any],
                *,
                label_field: str | None,
                recipe: Any = None,
            ) -> str:
                del splits, params, label_field, recipe
                return "not bytes"

        return _BadReturn()

    def is_stub(self) -> bool:
        return False


def test_reporting_op_returning_non_bytes_raises_materialize_error(
    tmp_path: Path,
) -> None:
    op = _viz("bad", "any", "reporting")
    with pytest.raises(MaterializeError, match="PNG bytes required"):
        apply_reporting_visualizations(
            _splits(),
            [op],
            plugin=_BadReturnPlugin(),
            output_dir=tmp_path,
            label_field="label",
        )


# ---------------------------------------------------------------------------
# Exploration-mode library API
# ---------------------------------------------------------------------------


def test_render_visualization_returns_rendered_with_no_path() -> None:
    op = _viz("hist", "class_distribution_histogram", "exploration")
    rendered = render_visualization(_splits(), op, plugin=IMAGE_PLUGIN, label_field="label")
    assert isinstance(rendered, RenderedVisualization)
    assert rendered.path is None
    assert _is_png(rendered.png_bytes)


def test_exploration_does_not_write_to_disk(tmp_path: Path) -> None:
    op = _viz("hist", "class_distribution_histogram", "exploration")
    render_visualization(_splits(), op, plugin=IMAGE_PLUGIN, label_field="label")
    assert list(tmp_path.iterdir()) == []  # nothing persisted


def test_exploration_propagates_plugin_errors_unwrapped() -> None:
    op = _viz("bad", "any", "exploration")
    with pytest.raises(RuntimeError, match="kaboom"):
        render_visualization(
            _splits(),
            op,
            plugin=_FailingPlugin(),
            label_field="label",
        )


def test_exploration_non_bytes_raises_typeerror() -> None:
    op = _viz("bad", "any", "exploration")
    with pytest.raises(TypeError, match="PNG bytes required"):
        render_visualization(
            _splits(),
            op,
            plugin=_BadReturnPlugin(),
            label_field="label",
        )


# ---------------------------------------------------------------------------
# Pixel-level smoke check on rendered images
# ---------------------------------------------------------------------------


def test_rendered_pngs_decode_to_valid_image(tmp_path: Path) -> None:
    op = _viz("hist", "class_distribution_histogram", "reporting")
    result = apply_reporting_visualizations(
        _splits(),
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    img = Image.open(io.BytesIO(result.rendered[0].png_bytes))
    img.load()
    assert img.size == (400, 300)
    assert img.mode == "RGB"


def test_mean_image_per_class_canvas_shape(tmp_path: Path) -> None:
    op = _viz("means", "mean_image_per_class", "reporting")
    result = apply_reporting_visualizations(
        _splits(),
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    img = Image.open(io.BytesIO(result.rendered[0].png_bytes))
    # 3 classes * 32px wide tile, 32px tall.
    assert img.size == (3 * 32, 32)


# ---------------------------------------------------------------------------
# class_distribution_histogram group_by (G17, Story I.p)
# ---------------------------------------------------------------------------


def _grouped_splits() -> dict[str, list[Mapping[str, Any]]]:
    # Distinct distributions for `label` vs `corruption` so the two
    # histograms differ in their bar layout.
    return {
        "train": [
            {"image": _img(20), "label": "cat", "corruption": "fog"},
            {"image": _img(40), "label": "cat", "corruption": "blur"},
            {"image": _img(60), "label": "dog", "corruption": "fog"},
            {"image": _img(80), "label": "dog", "corruption": "fog"},
        ],
    }


def test_histogram_group_by_buckets_on_named_field() -> None:
    from datarefinery.plugins.image_classification.operations.visualizations import (
        ClassDistributionHistogramOp,
    )

    op = ClassDistributionHistogramOp()
    splits = _grouped_splits()
    by_label = op.render(splits, {}, label_field="label")
    by_corruption = op.render(splits, {"group_by": "corruption"}, label_field="label")
    assert _is_png(by_label) and _is_png(by_corruption)
    # label: cat=2, dog=2 (two equal bars). corruption: fog=3, blur=1
    # (two unequal bars). Different distributions → different PNG bytes.
    assert by_label != by_corruption


def test_histogram_group_by_falls_back_to_label_when_absent() -> None:
    from datarefinery.plugins.image_classification.operations.visualizations import (
        ClassDistributionHistogramOp,
    )

    op = ClassDistributionHistogramOp()
    splits = _grouped_splits()
    default = op.render(splits, {}, label_field="label")
    explicit = op.render(splits, {"group_by": "label"}, label_field="label")
    # `group_by: label` is identical to the implicit Labels.field default.
    assert default == explicit


def test_histogram_requires_group_field_when_no_label_and_no_group_by() -> None:
    from datarefinery.core.errors import PluginError
    from datarefinery.plugins.image_classification.operations.visualizations import (
        ClassDistributionHistogramOp,
    )

    op = ClassDistributionHistogramOp()
    with pytest.raises(PluginError):
        op.render(_grouped_splits(), {}, label_field=None)


def test_histogram_group_by_works_without_label_field() -> None:
    from datarefinery.plugins.image_classification.operations.visualizations import (
        ClassDistributionHistogramOp,
    )

    op = ClassDistributionHistogramOp()
    # No Labels.field, but an explicit group_by → renders on that field.
    out = op.render(_grouped_splits(), {"group_by": "corruption"}, label_field=None)
    assert _is_png(out)
