# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-VIZ-3 ``corruption_severity_grid`` tests (Story H.v).

Renders a single ``K-corruption x L-severity`` figure: each subplot
shows the same ``n_images`` base records under that
``(corruption, severity)`` combination, side-by-side. Output is one PNG
per declared op (single-bytes return, persisted as ``<op.name>.png``).

The Hendrycks-Dietterich backend is in the ``[corruptions]`` extras
(``opencv-python-headless`` + ``scikit-image``); these tests skip
cleanly when the extras aren't installed. The friendly-import-error
test mocks the failure so it exercises the error path regardless.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
from pydantic import ValidationError

# Skip the whole module when extras absent (mirrors test_generation_imagecorruptions).
pytest.importorskip("cv2", reason="requires the [corruptions] extras (opencv-python-headless)")

from datarefinery.pipeline.stages.visualizations import (
    apply_reporting_visualizations,
)
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.image_classification.visualizations.corruption_severity_grid import (
    CORRUPTIONS_EXTRAS_INSTALL_HINT,
    CorruptionSeverityGridOp,
    CorruptionSeverityGridParams,
    build_corruption_severity_grid_figure,
)
from datarefinery.recipe.models import VisualizationOp


def _img(value: int = 128, size: int = 32) -> np.ndarray:
    return np.full((size, size, 3), value, dtype=np.uint8)


def _base_record(rid: str, value: int) -> dict[str, Any]:
    return {"record_id": rid, "image": _img(value), "label": "cat"}


def _splits(n: int = 6) -> dict[str, list[Mapping[str, Any]]]:
    return {
        "train": [_base_record(f"r{i}", 30 + 10 * i) for i in range(n)],
    }


def _viz(name: str, **params: Any) -> VisualizationOp:
    return VisualizationOp(
        name=name,
        op="corruption_severity_grid",
        params=params,
        stage="post_pipeline",
        mode="reporting",
    )


def _is_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


# ---------------------------------------------------------------------------
# CorruptionSeverityGridParams
# ---------------------------------------------------------------------------


def test_params_requires_positive_n_images() -> None:
    with pytest.raises(ValidationError):
        CorruptionSeverityGridParams(
            n_images=0, corruption_types=["gaussian_noise"], severities=[1]
        )


def test_params_requires_nonempty_corruption_types() -> None:
    with pytest.raises(ValidationError):
        CorruptionSeverityGridParams(n_images=2, corruption_types=[], severities=[1])


def test_params_rejects_unknown_corruption_name() -> None:
    with pytest.raises(ValidationError, match="unknown corruption"):
        CorruptionSeverityGridParams(
            n_images=2, corruption_types=["not_a_real_corruption"], severities=[1]
        )


def test_params_rejects_severity_out_of_range() -> None:
    with pytest.raises(ValidationError):
        CorruptionSeverityGridParams(
            n_images=2, corruption_types=["gaussian_noise"], severities=[6]
        )
    with pytest.raises(ValidationError):
        CorruptionSeverityGridParams(
            n_images=2, corruption_types=["gaussian_noise"], severities=[0]
        )


def test_params_rejects_duplicate_corruption_types() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        CorruptionSeverityGridParams(
            n_images=2,
            corruption_types=["gaussian_noise", "gaussian_noise"],
            severities=[1],
        )


def test_params_accepts_valid_input() -> None:
    p = CorruptionSeverityGridParams(
        n_images=4, corruption_types=["gaussian_noise", "shot_noise"], severities=[1, 3, 5]
    )
    assert p.n_images == 4
    assert p.corruption_types == ["gaussian_noise", "shot_noise"]
    assert p.severities == [1, 3, 5]


# ---------------------------------------------------------------------------
# build_corruption_severity_grid_figure: K rows x L cols of subplots
# ---------------------------------------------------------------------------


def test_figure_subplot_count_matches_grid_shape() -> None:
    # 2 corruptions x 3 severities x 4 base images (per story task list).
    cells: dict[tuple[str, int], list[np.ndarray]] = {
        ("gaussian_noise", 1): [_img(60) for _ in range(4)],
        ("gaussian_noise", 3): [_img(80) for _ in range(4)],
        ("gaussian_noise", 5): [_img(100) for _ in range(4)],
        ("shot_noise", 1): [_img(70) for _ in range(4)],
        ("shot_noise", 3): [_img(90) for _ in range(4)],
        ("shot_noise", 5): [_img(110) for _ in range(4)],
    }
    fig = build_corruption_severity_grid_figure(
        cells,
        corruption_types=["gaussian_noise", "shot_noise"],
        severities=[1, 3, 5],
    )
    assert len(fig.axes) == 2 * 3


# ---------------------------------------------------------------------------
# Op handle: single PNG return
# ---------------------------------------------------------------------------


def test_render_returns_single_png_bytes() -> None:
    handle = CorruptionSeverityGridOp()
    out = handle.render(
        _splits(),
        {
            "n_images": 2,
            "corruption_types": ["gaussian_noise"],
            "severities": [1, 3],
        },
        label_field="label",
        recipe=None,
    )
    assert isinstance(out, (bytes, bytearray))
    assert _is_png(out)


def test_render_raises_when_train_smaller_than_n_images() -> None:
    handle = CorruptionSeverityGridOp()
    with pytest.raises(ValueError, match="fewer than n_images=4"):
        handle.render(
            _splits(n=2),
            {"n_images": 4, "corruption_types": ["gaussian_noise"], "severities": [1]},
            label_field="label",
            recipe=None,
        )


def test_render_friendly_import_error_when_backend_missing() -> None:
    handle = CorruptionSeverityGridOp()
    # Mock the backend loader to simulate the extras-missing case so the
    # test runs whether or not [corruptions] is installed locally.
    with patch(
        "datarefinery.plugins.image_classification.visualizations."
        "corruption_severity_grid._load_backend",
        side_effect=ImportError(CORRUPTIONS_EXTRAS_INSTALL_HINT),
    ):
        with pytest.raises(ImportError, match=r"\[corruptions\]"):
            handle.render(
                _splits(),
                {
                    "n_images": 2,
                    "corruption_types": ["gaussian_noise"],
                    "severities": [1],
                },
                label_field="label",
                recipe=None,
            )


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def test_plugin_registers_corruption_severity_grid_spec() -> None:
    spec = IMAGE_PLUGIN.supported_operations["corruption_severity_grid"]
    assert "Visualizations" in spec.applicable_sections
    assert spec.parameters["n_images"].required is True
    assert spec.parameters["corruption_types"].required is True
    assert spec.parameters["severities"].required is True


def test_plugin_factory_returns_handle() -> None:
    handle = IMAGE_PLUGIN.operation_factory("Visualizations", "corruption_severity_grid")
    assert isinstance(handle, CorruptionSeverityGridOp)


# ---------------------------------------------------------------------------
# Pipeline stage: writes single <op.name>.png
# ---------------------------------------------------------------------------


def test_stage_writes_single_png(tmp_path: Path) -> None:
    op = _viz(
        "corr_grid",
        n_images=2,
        corruption_types=["gaussian_noise"],
        severities=[1, 3],
    )
    result = apply_reporting_visualizations(
        _splits(),
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
    )
    written = {p.name for p in result.written_paths}
    assert written == {"corr_grid.png"}
    for path in result.written_paths:
        assert _is_png(path.read_bytes())


def test_stage_render_is_deterministic(tmp_path: Path) -> None:
    op = _viz(
        "corr_grid",
        n_images=2,
        corruption_types=["gaussian_noise"],
        severities=[1],
    )
    a = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "a", label_field="label"
    )
    b = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "b", label_field="label"
    )
    assert a.rendered[0].png_bytes == b.rendered[0].png_bytes
