# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-12 + FR-22 featurizations stage tests (Story C.i)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

from datarefinery.core.errors import MaterializeError, PluginError
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.stages.featurizations import (
    FeaturizationsResult,
    apply_featurizations,
)
from datarefinery.pipeline.stages.transformations import FittedValues
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import FeaturizationOp


def _img(value: int = 0) -> np.ndarray:
    return np.full((4, 4, 3), value, dtype=np.uint8)


def _path_record(path: str) -> dict[str, Any]:
    return {"path": path, "image": _img()}


# ---------------------------------------------------------------------------
# label_from_path - derived label via featurization machinery (FR-22)
# ---------------------------------------------------------------------------


def test_label_from_path_derives_from_parent_directory_name(
    tmp_path: Path,
) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=["path"],
        output_field="label",
        op="label_from_path",
        splits=["train", "val"],
    )
    splits = {
        "train": [
            _path_record("/data/cats/cat_001.jpg"),
            _path_record("/data/dogs/dog_007.jpg"),
        ],
        "val": [_path_record("/data/cats/cat_900.jpg")],
    }
    result = apply_featurizations(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    assert isinstance(result, FeaturizationsResult)
    assert [r["label"] for r in result.splits["train"]] == ["cats", "dogs"]
    assert result.splits["val"][0]["label"] == "cats"


def test_label_from_path_filename_source(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=["path"],
        output_field="filename",
        op="label_from_path",
        params={"source": "filename"},
        splits=["train"],
    )
    result = apply_featurizations(
        {"train": [_path_record("/data/x/foo.png")]},
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    assert result.splits["train"][0]["filename"] == "foo.png"


def test_label_from_path_unknown_source_raises(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=["path"],
        output_field="label",
        op="label_from_path",
        params={"source": "made_up"},
        splits=["train"],
    )
    with pytest.raises(PluginError, match="source"):
        apply_featurizations(
            {"train": [_path_record("/data/cats/x.jpg")]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_label_from_path_missing_input_field_raises(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=["path"],
        output_field="label",
        op="label_from_path",
        splits=["train"],
    )
    with pytest.raises(PluginError, match="missing input field"):
        apply_featurizations(
            {"train": [{"image": _img()}]},  # no path
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_label_from_path_requires_at_least_one_input(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=[],
        output_field="label",
        op="label_from_path",
        splits=["train"],
    )
    with pytest.raises(PluginError, match="at least one input"):
        apply_featurizations(
            {"train": [_path_record("/data/cats/x.jpg")]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


# ---------------------------------------------------------------------------
# image_size_stats
# ---------------------------------------------------------------------------


def test_image_size_stats_writes_shape_list(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="sz",
        inputs=["image"],
        output_field="image_size",
        op="image_size_stats",
        splits=["train"],
    )
    result = apply_featurizations(
        {"train": [{"image": np.zeros((8, 16, 3), dtype=np.uint8)}]},
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    assert result.splits["train"][0]["image_size"] == [8, 16, 3]


def test_image_size_stats_supports_2d_images(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="sz",
        inputs=["image"],
        output_field="size",
        op="image_size_stats",
        splits=["train"],
    )
    result = apply_featurizations(
        {"train": [{"image": np.zeros((10, 20), dtype=np.uint8)}]},
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    assert result.splits["train"][0]["size"] == [10, 20]


def test_image_size_stats_rejects_invalid_ndim(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="sz",
        inputs=["image"],
        output_field="size",
        op="image_size_stats",
        splits=["train"],
    )
    with pytest.raises(PluginError, match="ndim"):
        apply_featurizations(
            {"train": [{"image": np.zeros((4, 4, 3, 1), dtype=np.uint8)}]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


# ---------------------------------------------------------------------------
# Determinism + multi-split
# ---------------------------------------------------------------------------


def test_featurization_is_deterministic(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=["path"],
        output_field="label",
        op="label_from_path",
        splits=["train"],
    )
    splits1 = {"train": [_path_record(f"/x/c{i % 2}/img_{i}.jpg") for i in range(8)]}
    splits2 = {"train": [_path_record(f"/x/c{i % 2}/img_{i}.jpg") for i in range(8)]}
    a = apply_featurizations(
        splits1, [op], plugin=IMAGE_PLUGIN, fitted_stats=FittedStatistics(tmp_path / "a")
    )
    b = apply_featurizations(
        splits2, [op], plugin=IMAGE_PLUGIN, fitted_stats=FittedStatistics(tmp_path / "b")
    )
    assert [r["label"] for r in a.splits["train"]] == [r["label"] for r in b.splits["train"]]


def test_apply_to_multiple_splits_uses_same_op(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=["path"],
        output_field="label",
        op="label_from_path",
        splits=["train", "val", "test"],
    )
    splits = {
        "train": [_path_record("/data/c0/x.jpg")],
        "val": [_path_record("/data/c1/y.jpg")],
        "test": [_path_record("/data/c2/z.jpg")],
    }
    result = apply_featurizations(
        splits, [op], plugin=IMAGE_PLUGIN, fitted_stats=FittedStatistics(tmp_path)
    )
    assert result.splits["train"][0]["label"] == "c0"
    assert result.splits["val"][0]["label"] == "c1"
    assert result.splits["test"][0]["label"] == "c2"


# ---------------------------------------------------------------------------
# Field-collision hard error (FR-12 edge case)
# ---------------------------------------------------------------------------


def test_collision_with_existing_field_raises_materialize_error(
    tmp_path: Path,
) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=["path"],
        output_field="label",  # already present
        op="label_from_path",
        splits=["train"],
    )
    splits = {
        "train": [{"path": "/data/c0/x.jpg", "label": "preexisting"}],
    }
    with pytest.raises(MaterializeError, match="collides with"):
        apply_featurizations(
            splits, [op], plugin=IMAGE_PLUGIN, fitted_stats=FittedStatistics(tmp_path)
        )


def test_no_collision_when_field_is_introduced_by_another_split(
    tmp_path: Path,
) -> None:
    """Empty splits never collide; under the uniform-schema invariant
    only the first record of each target split is checked."""
    op = FeaturizationOp(
        name="sz",
        inputs=["image"],
        output_field="image_size",
        op="image_size_stats",
        splits=["train", "val"],
    )
    splits = {
        "train": [{"image": np.zeros((4, 4, 3), dtype=np.uint8)}],
        "val": [],  # empty - no first record to collide
    }
    result = apply_featurizations(
        splits, [op], plugin=IMAGE_PLUGIN, fitted_stats=FittedStatistics(tmp_path)
    )
    assert result.splits["val"] == []


# ---------------------------------------------------------------------------
# Fit-on-train support (via a fixture plugin since image ops are no-fit)
# ---------------------------------------------------------------------------


class _MeanFeaturizer:
    """A fit-on-train featurizer: writes per-record train-mean to output_field."""

    fit_on_train: bool = True

    def fit(
        self,
        records: list[Mapping[str, Any]],
        params: Mapping[str, Any],
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> FittedValues:
        del params, output_field, label_field
        values = [float(r[inputs[0]]) for r in records]
        mean = sum(values) / len(values) if values else 0.0
        return FittedValues(
            scalars={},
            vectors={"mean": pa.table({"value": [mean]})},
        )

    def apply(
        self,
        records: list[Mapping[str, Any]],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> list[Mapping[str, Any]]:
        del params, inputs, label_field
        mean = fitted.vectors["mean"].column("value").to_pylist()[0]
        out: list[Mapping[str, Any]] = []
        for r in records:
            new = dict(r)
            new[output_field] = mean
            out.append(new)
        return out


from dataclasses import dataclass  # noqa: E402

from datarefinery.plugins.base import OperationSpec  # noqa: E402


@dataclass
class _FeatPlugin:
    name: str = "feat_test"
    schema_version: int = 1
    supported_sections: frozenset[str] = frozenset({"Featurizations"})

    def __post_init__(self) -> None:
        self.supported_operations: dict[str, OperationSpec] = {
            "mean_feat": OperationSpec(
                applicable_sections=frozenset({"Featurizations"}),
                fit_on_train=True,
            ),
        }

    def operation_factory(self, section: str, op_name: str) -> Any:
        del section
        if op_name == "mean_feat":
            return _MeanFeaturizer()
        raise NotImplementedError(op_name)

    def is_stub(self) -> bool:
        return False


def test_fit_on_train_featurizer_persists_and_applies_across_splits(
    tmp_path: Path,
) -> None:
    op = FeaturizationOp(
        name="mf",
        inputs=["x"],
        output_field="x_mean",
        op="mean_feat",
        fit_source="train",
        splits=["train", "val"],
    )
    splits = {
        "train": [{"x": 10}, {"x": 20}, {"x": 30}],  # mean = 20
        "val": [{"x": 99}],
    }
    fs = FittedStatistics(tmp_path)
    result = apply_featurizations(
        splits,
        [op],
        plugin=_FeatPlugin(),
        fitted_stats=fs,  # type: ignore[arg-type]
    )
    assert "mf" in result.fitted_op_ids
    # Every record - train and val - sees the train-fitted mean.
    assert all(r["x_mean"] == 20.0 for r in result.splits["train"])
    assert all(r["x_mean"] == 20.0 for r in result.splits["val"])
    # Persisted to fitted_statistics.
    assert fs.get_vector("mf", "mean").column("value").to_pylist()[0] == 20.0


def test_fit_on_train_without_fit_source_raises(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="mf",
        inputs=["x"],
        output_field="x_mean",
        op="mean_feat",
        fit_source=None,
        splits=["train"],
    )
    with pytest.raises(MaterializeError, match="fit_source"):
        apply_featurizations(
            {"train": [{"x": 1}]},
            [op],
            plugin=_FeatPlugin(),  # type: ignore[arg-type]
            fitted_stats=FittedStatistics(tmp_path),
        )


# ---------------------------------------------------------------------------
# Stage-runner error paths
# ---------------------------------------------------------------------------


def test_unknown_op_raises(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="x",
        inputs=["image"],
        output_field="y",
        op="made_up",
        splits=["train"],
    )
    with pytest.raises(MaterializeError, match="not declared"):
        apply_featurizations(
            {"train": [{"image": _img()}]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_undeclared_split_raises(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=["path"],
        output_field="label",
        op="label_from_path",
        splits=["train", "wat"],
    )
    with pytest.raises(MaterializeError, match="undeclared split"):
        apply_featurizations(
            {"train": [_path_record("/data/c0/x.jpg")]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_empty_op_list_is_passthrough(tmp_path: Path) -> None:
    splits = {"train": [_path_record("/x/c0/y.jpg")]}
    result = apply_featurizations(
        splits, [], plugin=IMAGE_PLUGIN, fitted_stats=FittedStatistics(tmp_path)
    )
    assert result.splits["train"][0]["path"] == "/x/c0/y.jpg"
    assert result.fitted_op_ids == ()


def test_input_split_lists_are_not_mutated(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl",
        inputs=["path"],
        output_field="label",
        op="label_from_path",
        splits=["train"],
    )
    train = [_path_record("/x/c0/y.jpg")]
    splits = {"train": train}
    apply_featurizations(splits, [op], plugin=IMAGE_PLUGIN, fitted_stats=FittedStatistics(tmp_path))
    assert "label" not in train[0]  # original record unchanged
