# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-10 + FR-6 transformations stage tests (Story C.h).

Covers the stage runner (fit-on-train flow, persistence, apply across
splits) and the image plugin's resize / normalize / mean_subtract ops
end-to-end through `plugin.operation_factory("Transformations", op)`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.stages.transformations import (
    FittedValues,
    apply_transformations,
)
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import TransformationOp


def _img(value: int, *, h: int = 4, w: int = 4, c: int = 3) -> np.ndarray:
    return np.full((h, w, c), value, dtype=np.uint8)


def _record(label: int, value: int) -> dict[str, Any]:
    return {"image": _img(value), "label": label}


def _splits() -> dict[str, list[Mapping[str, Any]]]:
    return {
        "train": [_record(0, 10), _record(1, 50), _record(0, 90)],
        "val": [_record(0, 30), _record(1, 70)],
        "test": [_record(0, 0), _record(1, 100)],
    }


# ---------------------------------------------------------------------------
# resize (no fit)
# ---------------------------------------------------------------------------


def test_resize_changes_image_shape(tmp_path: Path) -> None:
    op = TransformationOp(
        name="r",
        op="resize",
        params={"size": 8},
        splits=["train", "val", "test"],
    )
    fs = FittedStatistics(tmp_path)
    result = apply_transformations(_splits(), [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    for split in result.splits.values():
        for r in split:
            assert r["image"].shape == (8, 8, 3)


def test_resize_does_not_persist_fitted_stats(tmp_path: Path) -> None:
    op = TransformationOp(name="r", op="resize", params={"size": 8}, splits=["train"])
    fs = FittedStatistics(tmp_path)
    apply_transformations(_splits(), [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    assert not (tmp_path / "r").exists()


def test_resize_invalid_size_raises() -> None:
    from datarefinery.core.errors import PluginError

    op = TransformationOp(name="r", op="resize", params={"size": 0}, splits=["train"])
    with pytest.raises(PluginError, match="positive integer"):
        apply_transformations(
            {"train": [_record(0, 0)]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(Path(".")),  # unused
        )


def test_resize_unknown_method_raises() -> None:
    from datarefinery.core.errors import PluginError

    op = TransformationOp(
        name="r",
        op="resize",
        params={"size": 8, "method": "warp"},
        splits=["train"],
    )
    with pytest.raises(PluginError, match="method"):
        apply_transformations(
            {"train": [_record(0, 0)]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(Path(".")),
        )


# ---------------------------------------------------------------------------
# normalize (fit-on-train)
# ---------------------------------------------------------------------------


def test_normalize_fits_on_train_only_and_persists(tmp_path: Path) -> None:
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={},
        fit_source="train",
        splits=["train", "val", "test"],
    )
    fs = FittedStatistics(tmp_path)
    result = apply_transformations(_splits(), [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)

    # Persisted layout: <root>/<op_id>/{mean,std}.parquet
    assert (tmp_path / "norm" / "mean.parquet").exists()
    assert (tmp_path / "norm" / "std.parquet").exists()
    assert "norm" in result.fitted_op_ids

    # Train mean is mean of [10, 50, 90] = 50; std non-zero.
    mean = fs.get_vector("norm", "mean").column("value").to_pylist()
    assert all(abs(m - 50.0) < 1e-9 for m in mean)


def test_normalize_apply_uses_persisted_train_stats(tmp_path: Path) -> None:
    """Same fitted stats apply to train, val, and test - val/test do not
    refit on their own data (FR-10 #2)."""
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={},
        fit_source="train",
        splits=["train", "val", "test"],
    )
    fs = FittedStatistics(tmp_path)
    result = apply_transformations(_splits(), [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    # val image value 30, train mean 50 -> normalized first val record around -20/std
    val_image = result.splits["val"][0]["image"]
    train_mean = np.asarray(fs.get_vector("norm", "mean").column("value").to_pylist())
    expected_offset = 30.0 - float(train_mean[0])  # before /std
    train_std = np.asarray(fs.get_vector("norm", "std").column("value").to_pylist())
    std0 = float(train_std[0])
    expected = expected_offset / (std0 if std0 != 0 else 1.0)
    assert abs(float(val_image[0, 0, 0]) - expected) < 1e-9


def test_normalize_is_deterministic_for_same_inputs(tmp_path: Path) -> None:
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={},
        fit_source="train",
        splits=["train", "val"],
    )
    a = apply_transformations(
        _splits(),
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path / "a"),
    )
    b = apply_transformations(
        _splits(),
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path / "b"),
    )
    for split in ("train", "val"):
        for ra, rb in zip(a.splits[split], b.splits[split], strict=True):
            np.testing.assert_array_equal(ra["image"], rb["image"])


def test_normalize_handles_zero_variance_channel(tmp_path: Path) -> None:
    """When a channel's std is 0 we divide by 1 instead of NaN-blowing-up."""
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={},
        fit_source="train",
        splits=["train"],
    )
    constant: dict[str, list[Mapping[str, Any]]] = {
        "train": [_record(0, 7), _record(0, 7), _record(0, 7)]
    }
    fs = FittedStatistics(tmp_path)
    result = apply_transformations(constant, [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    img = result.splits["train"][0]["image"]
    assert not np.isnan(img).any()


def test_normalize_with_recipe_pinned_mean_std(tmp_path: Path) -> None:
    """Recipe-supplied mean/std overrides per-split fitting at fit time."""
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={"mean": [128.0, 128.0, 128.0], "std": [64.0, 64.0, 64.0]},
        fit_source="train",
        splits=["train"],
    )
    fs = FittedStatistics(tmp_path)
    apply_transformations(_splits(), [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    mean = fs.get_vector("norm", "mean").column("value").to_pylist()
    assert mean == [128.0, 128.0, 128.0]


# ---------------------------------------------------------------------------
# mean_subtract (fit-on-train, mean only)
# ---------------------------------------------------------------------------


def test_mean_subtract_persists_only_mean(tmp_path: Path) -> None:
    op = TransformationOp(
        name="ms",
        op="mean_subtract",
        params={},
        fit_source="train",
        splits=["train"],
    )
    fs = FittedStatistics(tmp_path)
    apply_transformations(_splits(), [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    assert (tmp_path / "ms" / "mean.parquet").exists()
    assert not (tmp_path / "ms" / "std.parquet").exists()


def test_mean_subtract_centers_around_zero(tmp_path: Path) -> None:
    op = TransformationOp(
        name="ms",
        op="mean_subtract",
        params={},
        fit_source="train",
        splits=["train"],
    )
    fs = FittedStatistics(tmp_path)
    result = apply_transformations(_splits(), [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    train_mean = np.mean([r["image"] for r in result.splits["train"]])
    assert abs(train_mean) < 1e-9


# ---------------------------------------------------------------------------
# Stage runner: error paths
# ---------------------------------------------------------------------------


def test_unknown_op_raises_materialize_error(tmp_path: Path) -> None:
    op = TransformationOp(name="x", op="made_up", params={}, splits=["train"])
    with pytest.raises(MaterializeError, match="not declared"):
        apply_transformations(
            _splits(),
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_fit_on_train_op_without_fit_source_raises(tmp_path: Path) -> None:
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={},
        fit_source=None,
        splits=["train"],
    )
    with pytest.raises(MaterializeError, match="fit_source"):
        apply_transformations(
            _splits(),
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_fit_source_must_be_a_declared_split(tmp_path: Path) -> None:
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={},
        fit_source="wat",
        splits=["train"],
    )
    with pytest.raises(MaterializeError, match="fit_source"):
        apply_transformations(
            _splits(),
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_apply_split_must_be_declared(tmp_path: Path) -> None:
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={},
        fit_source="train",
        splits=["train", "wat"],
    )
    with pytest.raises(MaterializeError, match="undeclared split"):
        apply_transformations(
            _splits(),
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


# ---------------------------------------------------------------------------
# Misc / pass-through
# ---------------------------------------------------------------------------


def test_empty_op_list_is_passthrough(tmp_path: Path) -> None:
    splits = _splits()
    result = apply_transformations(
        splits,
        [],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    for name in splits:
        for ra, rb in zip(splits[name], result.splits[name], strict=True):
            np.testing.assert_array_equal(ra["image"], rb["image"])
    assert result.fitted_op_ids == ()


def test_fitted_values_is_empty_default() -> None:
    fv = FittedValues()
    assert fv.is_empty


def test_input_split_lists_are_not_mutated(tmp_path: Path) -> None:
    op = TransformationOp(name="r", op="resize", params={"size": 8}, splits=["train"])
    splits = _splits()
    original_train_image = splits["train"][0]["image"].copy()
    apply_transformations(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    np.testing.assert_array_equal(splits["train"][0]["image"], original_train_image)


def test_persisted_stats_are_pyarrow_tables(tmp_path: Path) -> None:
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={},
        fit_source="train",
        splits=["train"],
    )
    fs = FittedStatistics(tmp_path)
    apply_transformations(_splits(), [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    assert isinstance(fs.get_vector("norm", "mean"), pa.Table)
