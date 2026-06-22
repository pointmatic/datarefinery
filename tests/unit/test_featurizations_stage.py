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


def _path_record(path: str) -> Mapping[str, Any]:
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
        params={"source": "parent_directory_name"},
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
        params={"source": "parent_directory_name"},
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
        params={"source": "parent_directory_name"},
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
        params={"source": "parent_directory_name"},
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
        params={"source": "parent_directory_name"},
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
        params={"source": "parent_directory_name"},
        splits=["train"],
    )
    splits: dict[str, list[Mapping[str, Any]]] = {
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
    splits: dict[str, list[Mapping[str, Any]]] = {
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

    def recommended_params(self, section: str, op_name: str) -> dict[str, object]:
        del section, op_name
        return {}

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
    splits: dict[str, list[Mapping[str, Any]]] = {
        "train": [{"x": 10}, {"x": 20}, {"x": 30}],  # mean = 20
        "val": [{"x": 99}],
    }
    fs = FittedStatistics(tmp_path)
    result = apply_featurizations(
        splits,
        [op],
        plugin=_FeatPlugin(),
        fitted_stats=fs,
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
            plugin=_FeatPlugin(),
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
        params={"source": "parent_directory_name"},
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
        params={"source": "parent_directory_name"},
        splits=["train"],
    )
    train = [_path_record("/x/c0/y.jpg")]
    splits = {"train": train}
    apply_featurizations(splits, [op], plugin=IMAGE_PLUGIN, fitted_stats=FittedStatistics(tmp_path))
    assert "label" not in train[0]  # original record unchanged


# ---------------------------------------------------------------------------
# categorical_encode (Story I.l / G3)
# ---------------------------------------------------------------------------


def _label_record(label: str) -> Mapping[str, Any]:
    return {"label": label, "image": _img()}


def test_categorical_encode_with_recipe_vocabulary_path(tmp_path: Path) -> None:
    """Recipe-declared vocabulary: deterministic encoding by recipe.

    Like ``NormalizeOp``'s recipe-pinned-mean/std pattern, the
    fit_on_train spec still routes through the stage runner's fit phase,
    but the fit returns the recipe-supplied vocab verbatim (persisted
    as the audit trail), and apply uses it.
    """
    op = FeaturizationOp(
        name="lbl_id",
        inputs=["label"],
        output_field="label_id",
        op="categorical_encode",
        params={
            "vocabulary": ["airplane", "automobile", "bird"],
            "ordering": "alphabetical",
            "output_dtype": "int32",
        },
        fit_source="train",
        splits=["train", "val"],
    )
    splits: dict[str, list[Mapping[str, Any]]] = {
        "train": [_label_record("airplane"), _label_record("bird")],
        "val": [_label_record("automobile")],
    }
    fs = FittedStatistics(tmp_path)
    result = apply_featurizations(splits, [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    assert [int(r["label_id"]) for r in result.splits["train"]] == [0, 2]
    assert [int(r["label_id"]) for r in result.splits["val"]] == [1]
    # Persisted vocab is the recipe-supplied one verbatim.
    vocab = fs.get_vector("lbl_id", "vocabulary").column("value").to_pylist()
    assert vocab == ["airplane", "automobile", "bird"]


def test_categorical_encode_output_dtype_is_honored(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl_id",
        inputs=["label"],
        output_field="label_id",
        op="categorical_encode",
        params={"vocabulary": ["a", "b"], "ordering": "alphabetical", "output_dtype": "int64"},
        fit_source="train",
        splits=["train"],
    )
    result = apply_featurizations(
        {"train": [_label_record("a"), _label_record("b")]},
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    encoded = result.splits["train"][0]["label_id"]
    assert isinstance(encoded, np.integer)
    assert encoded.dtype == np.int64


def test_categorical_encode_fit_on_train_persists_alphabetical_vocabulary(
    tmp_path: Path,
) -> None:
    """Fit-on-train path: vocab derived from train labels, persisted,
    and replayed identically on every other declared split.
    """
    op = FeaturizationOp(
        name="lbl_id",
        inputs=["label"],
        output_field="label_id",
        op="categorical_encode",
        params={"ordering": "alphabetical", "output_dtype": "int32"},
        fit_source="train",
        splits=["train", "val", "test"],
    )
    splits: dict[str, list[Mapping[str, Any]]] = {
        "train": [_label_record("cat"), _label_record("dog"), _label_record("bird")],
        "val": [_label_record("dog")],
        "test": [_label_record("cat"), _label_record("bird")],
    }
    fs = FittedStatistics(tmp_path)
    result = apply_featurizations(splits, [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    # Alphabetical default: bird=0, cat=1, dog=2.
    assert [int(r["label_id"]) for r in result.splits["train"]] == [1, 2, 0]
    assert [int(r["label_id"]) for r in result.splits["val"]] == [2]
    assert [int(r["label_id"]) for r in result.splits["test"]] == [1, 0]
    assert "lbl_id" in result.fitted_op_ids
    # Vocabulary persisted as a parquet vector under the op id.
    assert (tmp_path / "lbl_id" / "vocabulary.parquet").exists()
    vocab = fs.get_vector("lbl_id", "vocabulary").column("value").to_pylist()
    assert vocab == ["bird", "cat", "dog"]


def test_categorical_encode_first_seen_ordering(tmp_path: Path) -> None:
    """`ordering: first_seen` preserves the order labels first appear in train."""
    op = FeaturizationOp(
        name="lbl_id",
        inputs=["label"],
        output_field="label_id",
        op="categorical_encode",
        params={"ordering": "first_seen", "output_dtype": "int32"},
        fit_source="train",
        splits=["train"],
    )
    splits: dict[str, list[Mapping[str, Any]]] = {
        "train": [
            _label_record("cat"),
            _label_record("dog"),
            _label_record("cat"),
            _label_record("bird"),
        ],
    }
    fs = FittedStatistics(tmp_path)
    result = apply_featurizations(splits, [op], plugin=IMAGE_PLUGIN, fitted_stats=fs)
    assert [int(r["label_id"]) for r in result.splits["train"]] == [0, 1, 0, 2]
    vocab = fs.get_vector("lbl_id", "vocabulary").column("value").to_pylist()
    assert vocab == ["cat", "dog", "bird"]


def test_categorical_encode_unknown_label_reports_missing(tmp_path: Path) -> None:
    """Apply-time label not in the declared vocabulary surfaces clearly."""
    op = FeaturizationOp(
        name="lbl_id",
        inputs=["label"],
        output_field="label_id",
        op="categorical_encode",
        params={
            "vocabulary": ["airplane", "automobile"],
            "ordering": "alphabetical",
            "output_dtype": "int32",
        },
        fit_source="train",
        splits=["train"],
    )
    with pytest.raises(PluginError, match="bird"):
        apply_featurizations(
            {"train": [_label_record("airplane"), _label_record("bird")]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_categorical_encode_rejects_unknown_ordering(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="lbl_id",
        inputs=["label"],
        output_field="label_id",
        op="categorical_encode",
        params={"ordering": "rabbit", "output_dtype": "int32"},
        fit_source="train",
        splits=["train"],
    )
    with pytest.raises(PluginError, match="ordering"):
        apply_featurizations(
            {"train": [_label_record("a")]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


# ---------------------------------------------------------------------------
# flatten (Story I.m / G9)
# ---------------------------------------------------------------------------


def test_flatten_reshapes_image_to_one_dimensional_vector(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="img_flat",
        inputs=["image"],
        output_field="image_flat",
        op="flatten",
        splits=["train"],
    )
    src = np.arange(4 * 4 * 3, dtype=np.uint8).reshape(4, 4, 3)
    splits: dict[str, list[Mapping[str, Any]]] = {
        "train": [{"image": src, "label": 0}],
    }
    result = apply_featurizations(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    flat = result.splits["train"][0]["image_flat"]
    assert flat.shape == (48,)
    np.testing.assert_array_equal(flat, src.reshape(-1))


def test_flatten_preserves_dtype(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="img_flat",
        inputs=["image"],
        output_field="image_flat",
        op="flatten",
        splits=["train"],
    )
    src = np.full((2, 2, 3), 0.5, dtype=np.float32)
    result = apply_featurizations(
        {"train": [{"image": src, "label": 0}]},
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    flat = result.splits["train"][0]["image_flat"]
    assert flat.dtype == np.float32


def test_flatten_does_not_drop_original_input_field(tmp_path: Path) -> None:
    """The op writes ``output_field``; the source field stays in the record
    so a downstream consumer can still observe the multi-dimensional view.
    """
    op = FeaturizationOp(
        name="img_flat",
        inputs=["image"],
        output_field="image_flat",
        op="flatten",
        splits=["train"],
    )
    src = np.zeros((2, 2, 3), dtype=np.uint8)
    result = apply_featurizations(
        {"train": [{"image": src, "label": 0}]},
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=FittedStatistics(tmp_path),
    )
    record = result.splits["train"][0]
    assert "image" in record and "image_flat" in record
    assert record["image"].shape == (2, 2, 3)


def test_flatten_rejects_multiple_inputs(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="img_flat",
        inputs=["image", "extra"],
        output_field="image_flat",
        op="flatten",
        splits=["train"],
    )
    with pytest.raises(PluginError, match="exactly one"):
        apply_featurizations(
            {"train": [{"image": _img(), "extra": _img(), "label": 0}]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_flatten_rejects_zero_inputs(tmp_path: Path) -> None:
    op = FeaturizationOp(
        name="img_flat",
        inputs=[],
        output_field="image_flat",
        op="flatten",
        splits=["train"],
    )
    with pytest.raises(PluginError, match="exactly one"):
        apply_featurizations(
            {"train": [{"image": _img(), "label": 0}]},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path),
        )


def test_flatten_variant_overlay_round_trips_through_apply_variant() -> None:
    """A variant that introduces a `flatten` Featurization must parse
    and apply cleanly via `apply_variant`, producing a valid Recipe.
    """
    from datarefinery.recipe.models import Recipe
    from datarefinery.recipe.variants import apply_variant

    recipe = Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.6, "val": 0.2, "test": 0.2}, "seed": 11},
            "variants": {
                "mlp_flat": {
                    "Featurizations": [
                        {
                            "name": "img_flat",
                            "inputs": ["image"],
                            "output_field": "image_flat",
                            "op": "flatten",
                            "splits": ["train", "val", "test"],
                        }
                    ]
                }
            },
        }
    )
    selected = apply_variant(recipe, "mlp_flat")
    assert len(selected.Featurizations) == 1
    feat = selected.Featurizations[0]
    assert feat.op == "flatten"
    assert feat.inputs == ["image"]
    assert feat.output_field == "image_flat"
    # `apply_variant(None)` strips variants but leaves base unchanged.
    base = apply_variant(recipe, None)
    assert base.variants == {}
    assert base.Featurizations == []
