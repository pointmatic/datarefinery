# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-VIZ-4 ``severity_ladder`` tests (Story H.w).

Renders ``n_examples`` train-split records across all five severities
of a single corruption type as an ``n_examples x 5`` figure. One PNG
per declared op (single-bytes return, persisted as ``<op.name>.png``).

Extras-gated via ``pytest.importorskip("cv2", ...)``; the friendly-
import-error test mocks the failure to exercise the error path
regardless.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
from pydantic import ValidationError

pytest.importorskip("cv2", reason="requires the [corruptions] extras (opencv-python-headless)")

from datarefinery.pipeline.stages.visualizations import (
    apply_reporting_visualizations,
)
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.image_classification.visualizations.severity_ladder import (
    CORRUPTIONS_EXTRAS_INSTALL_HINT,
    SeverityLadderOp,
    SeverityLadderParams,
    build_severity_ladder_figure,
)
from datarefinery.recipe.models import VisualizationOp


def _img(value: int = 128, size: int = 32) -> np.ndarray:
    return np.full((size, size, 3), value, dtype=np.uint8)


def _base_record(rid: str, value: int) -> dict[str, Any]:
    return {"record_id": rid, "image": _img(value), "label": "cat"}


def _splits(n: int = 4) -> dict[str, list[Mapping[str, Any]]]:
    return {"train": [_base_record(f"r{i}", 30 + 10 * i) for i in range(n)]}


def _viz(name: str, **params: Any) -> VisualizationOp:
    return VisualizationOp(
        name=name,
        op="severity_ladder",
        params=params,
        stage="post_pipeline",
        mode="reporting",
    )


def _is_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


# ---------------------------------------------------------------------------
# SeverityLadderParams
# ---------------------------------------------------------------------------


def test_params_requires_positive_n_examples() -> None:
    with pytest.raises(ValidationError):
        SeverityLadderParams(n_examples=0, corruption_type="gaussian_noise")


def test_params_requires_nonempty_corruption_type() -> None:
    with pytest.raises(ValidationError):
        SeverityLadderParams(n_examples=2, corruption_type="")


def test_params_rejects_unknown_corruption_name() -> None:
    with pytest.raises(ValidationError, match="unknown corruption"):
        SeverityLadderParams(n_examples=2, corruption_type="not_a_real_corruption")


def test_params_accepts_valid_input() -> None:
    p = SeverityLadderParams(n_examples=4, corruption_type="gaussian_noise")
    assert p.n_examples == 4
    assert p.corruption_type == "gaussian_noise"


# ---------------------------------------------------------------------------
# build_severity_ladder_figure: n_examples rows x 5 cols
# ---------------------------------------------------------------------------


def test_figure_subplot_count_is_n_examples_times_five() -> None:
    rows: list[list[np.ndarray]] = [[_img(50 + 10 * sev) for sev in range(1, 6)] for _ in range(4)]
    fig = build_severity_ladder_figure(rows, corruption_type="gaussian_noise")
    assert len(fig.axes) == 4 * 5


# ---------------------------------------------------------------------------
# Op handle: single PNG return
# ---------------------------------------------------------------------------


def test_render_returns_single_png_bytes() -> None:
    handle = SeverityLadderOp()
    out = handle.render(
        _splits(),
        {"n_examples": 2, "corruption_type": "gaussian_noise"},
        label_field="label",
        recipe=None,
    )
    assert isinstance(out, (bytes, bytearray))
    assert _is_png(out)


def test_render_raises_when_train_smaller_than_n_examples() -> None:
    handle = SeverityLadderOp()
    with pytest.raises(ValueError, match="fewer than n_examples=4"):
        handle.render(
            _splits(n=2),
            {"n_examples": 4, "corruption_type": "gaussian_noise"},
            label_field="label",
            recipe=None,
        )


def test_render_friendly_import_error_when_backend_missing() -> None:
    handle = SeverityLadderOp()
    with patch(
        "datarefinery.plugins.image_classification.visualizations.severity_ladder._load_backend",
        side_effect=ImportError(CORRUPTIONS_EXTRAS_INSTALL_HINT),
    ):
        with pytest.raises(ImportError, match=r"\[corruptions\]"):
            handle.render(
                _splits(),
                {"n_examples": 2, "corruption_type": "gaussian_noise"},
                label_field="label",
                recipe=None,
            )


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def test_plugin_registers_severity_ladder_spec() -> None:
    spec = IMAGE_PLUGIN.supported_operations["severity_ladder"]
    assert "Visualizations" in spec.applicable_sections
    assert spec.parameters["n_examples"].required is True
    assert spec.parameters["corruption_type"].required is True


def test_plugin_factory_returns_handle() -> None:
    handle = IMAGE_PLUGIN.operation_factory("Visualizations", "severity_ladder")
    assert isinstance(handle, SeverityLadderOp)


# ---------------------------------------------------------------------------
# Pipeline stage: writes single <op.name>.png + determinism
# ---------------------------------------------------------------------------


def test_stage_writes_single_png(tmp_path: Path) -> None:
    op = _viz("sev_ladder", n_examples=2, corruption_type="gaussian_noise")
    result = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path, label_field="label"
    )
    written = {p.name for p in result.written_paths}
    assert written == {"sev_ladder.png"}
    for path in result.written_paths:
        assert _is_png(path.read_bytes())


def test_stage_render_is_deterministic(tmp_path: Path) -> None:
    op = _viz("sev_ladder", n_examples=2, corruption_type="gaussian_noise")
    a = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "a", label_field="label"
    )
    b = apply_reporting_visualizations(
        _splits(), [op], plugin=IMAGE_PLUGIN, output_dir=tmp_path / "b", label_field="label"
    )
    assert a.rendered[0].png_bytes == b.rendered[0].png_bytes
