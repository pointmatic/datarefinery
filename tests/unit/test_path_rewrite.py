# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.g: shared pixel-altering / path-rewrite helpers.

These helpers are consumed by validator check 26 (refuse the silent
``path``-vs-transformed-pixels divergence) and by the runner's lazy-mode
``path`` rewrite. Tests pin the closed-set lookup, the qualifying-sink
filter, the per-split rewrite plan, and the validator's coverage-gap
computation.
"""

from __future__ import annotations

from typing import Any

from datarefinery.pipeline.path_rewrite import (
    feature_path_rewrite_plan,
    path_rewrite_plan,
    pixel_altering_transformations,
    uncovered_pixel_altering_splits,
)
from datarefinery.plugins.image_classification import PLUGIN
from datarefinery.recipe.models import Recipe


def _recipe(
    *,
    transformations: list[dict[str, Any]] | None = None,
    augmentations: list[dict[str, Any]] | None = None,
    sinks: list[dict[str, Any]] | None = None,
) -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 2,
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
            "Transformations": transformations or [],
            "Augmentations": augmentations or [],
            "Sinks": sinks or [],
        }
    )


_RESIZE_ALL = {
    "name": "r",
    "op": "resize",
    "params": {"size": 8},
    "splits": ["train", "val", "test"],
}
_NORMALIZE_ALL = {
    "name": "n",
    "op": "normalize",
    "fit_source": "train",
    "splits": ["train", "val", "test"],
}
_IMAGE_SINK = {
    "name": "transformed",
    "stage": "post_Transformations",
    "field": "image",
    "format": "png_per_record",
    "path_template": "transformed/{split}/{record_id}.png",
}


# ---------------------------------------------------------------------------
# pixel_altering_transformations
# ---------------------------------------------------------------------------


def test_pixel_altering_transformations_finds_resize() -> None:
    recipe = _recipe(transformations=[_RESIZE_ALL])
    ops = pixel_altering_transformations(recipe, PLUGIN)
    assert [op.name for op in ops] == ["r"]


def test_pixel_altering_transformations_excludes_normalize() -> None:
    recipe = _recipe(transformations=[_NORMALIZE_ALL])
    assert pixel_altering_transformations(recipe, PLUGIN) == []


# ---------------------------------------------------------------------------
# uncovered_pixel_altering_splits (validator-side)
# ---------------------------------------------------------------------------


def test_uncovered_when_no_sink() -> None:
    recipe = _recipe(transformations=[_RESIZE_ALL])
    assert uncovered_pixel_altering_splits(recipe, PLUGIN) == {"train", "val", "test"}


def test_covered_when_image_sink_spans_all_splits() -> None:
    recipe = _recipe(transformations=[_RESIZE_ALL], sinks=[_IMAGE_SINK])
    assert uncovered_pixel_altering_splits(recipe, PLUGIN) == set()


def test_partial_sink_coverage_leaves_gap() -> None:
    sink = {**_IMAGE_SINK, "splits": ["train"]}
    recipe = _recipe(transformations=[_RESIZE_ALL], sinks=[sink])
    assert uncovered_pixel_altering_splits(recipe, PLUGIN) == {"val", "test"}


def test_non_image_sink_does_not_cover() -> None:
    sink = {**_IMAGE_SINK, "field": "label"}
    recipe = _recipe(transformations=[_RESIZE_ALL], sinks=[sink])
    assert uncovered_pixel_altering_splits(recipe, PLUGIN) == {"train", "val", "test"}


def test_pre_transform_sink_does_not_cover() -> None:
    sink = {**_IMAGE_SINK, "stage": "post_Filters"}
    recipe = _recipe(transformations=[_RESIZE_ALL], sinks=[sink])
    assert uncovered_pixel_altering_splits(recipe, PLUGIN) == {"train", "val", "test"}


def test_normalize_only_has_no_gap() -> None:
    recipe = _recipe(transformations=[_NORMALIZE_ALL])
    assert uncovered_pixel_altering_splits(recipe, PLUGIN) == set()


def test_aggressive_train_split_excluded_from_required_coverage() -> None:
    # resize only on train, but train is realized as aggressive variants
    # (image persisted as a sidecar PNG) — no lazy divergence on train.
    recipe = _recipe(
        transformations=[{**_RESIZE_ALL, "splits": ["train"]}],
        augmentations=[
            {
                "name": "flip",
                "op": "horizontal_flip",
                "splits": ["train"],
                "materialization": "aggressive",
            }
        ],
    )
    assert uncovered_pixel_altering_splits(recipe, PLUGIN) == set()


# ---------------------------------------------------------------------------
# path_rewrite_plan (runner-side)
# ---------------------------------------------------------------------------


def test_rewrite_plan_maps_each_split_to_sink() -> None:
    recipe = _recipe(transformations=[_RESIZE_ALL], sinks=[_IMAGE_SINK])
    plan = path_rewrite_plan(recipe, PLUGIN)
    assert set(plan.keys()) == {"train", "val", "test"}
    assert all(sink.name == "transformed" for sink in plan.values())


def test_rewrite_plan_empty_without_pixel_altering() -> None:
    recipe = _recipe(transformations=[_NORMALIZE_ALL], sinks=[_IMAGE_SINK])
    assert path_rewrite_plan(recipe, PLUGIN) == {}


def test_rewrite_plan_picks_first_qualifying_sink_in_recipe_order() -> None:
    second = {**_IMAGE_SINK, "name": "second", "path_template": "second/{split}/{record_id}.png"}
    recipe = _recipe(transformations=[_RESIZE_ALL], sinks=[_IMAGE_SINK, second])
    plan = path_rewrite_plan(recipe, PLUGIN)
    assert {sink.name for sink in plan.values()} == {"transformed"}


# ---------------------------------------------------------------------------
# feature_path_rewrite_plan (Story K.c — npy_per_record sinks)
# ---------------------------------------------------------------------------

_NPY_SINK = {
    "name": "feats",
    "stage": "post_Featurizations",
    "field": "mel",
    "format": "npy_per_record",
    "path_template": "features/{split}/{record_id}.npy",
}


def test_feature_plan_maps_each_split_to_npy_sink() -> None:
    recipe = _recipe(sinks=[_NPY_SINK])
    plan = feature_path_rewrite_plan(recipe, ["train", "val", "test"])
    assert set(plan.keys()) == {"train", "val", "test"}
    assert all(sink.name == "feats" for sink in plan.values())


def test_feature_plan_empty_without_npy_sink() -> None:
    recipe = _recipe(sinks=[_IMAGE_SINK])
    assert feature_path_rewrite_plan(recipe, ["train", "val", "test"]) == {}


def test_feature_plan_respects_sink_splits_filter() -> None:
    recipe = _recipe(sinks=[{**_NPY_SINK, "splits": ["train"]}])
    plan = feature_path_rewrite_plan(recipe, ["train", "val", "test"])
    assert set(plan.keys()) == {"train"}


def test_feature_plan_picks_first_npy_sink_in_recipe_order() -> None:
    second = {**_NPY_SINK, "name": "second", "path_template": "other/{split}/{record_id}.npy"}
    recipe = _recipe(sinks=[_NPY_SINK, second])
    plan = feature_path_rewrite_plan(recipe, ["train"])
    assert plan["train"].name == "feats"
