# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for `datarefinery.recipe.models`."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from datarefinery.recipe.models import (
    InputSection,
    Recipe,
    SplitsSection,
)


def _minimal_recipe_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 42,
        "Input": {
            "sources": [
                {
                    "name": "train",
                    "type": "image_folder",
                    "path": "/data/train",
                    "label_from": "parent_directory_name",
                }
            ],
        },
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                "label": {"dtype": "int32"},
            },
        },
        "Labels": {
            "field": "label",
            "source": {"kind": "derived", "derivation": "parent_directory_name"},
        },
        "Splits": {
            "ratios": {"train": 0.8, "val": 0.1, "test": 0.1},
            "stratify_by": "label",
            "seed": 7,
        },
    }


def test_minimal_recipe_validates() -> None:
    recipe = Recipe.model_validate(_minimal_recipe_dict())
    assert recipe.plugin == "image_classification"
    assert recipe.schema_version == 1
    assert recipe.seed == 42
    assert recipe.Input.sources[0].name == "train"
    assert recipe.Splits.ratios == {"train": 0.8, "val": 0.1, "test": 0.1}
    # Optional collections default to empty.
    assert recipe.Filters == []
    assert recipe.Augmentations == []
    assert recipe.variants == {}


def test_round_trip_via_model_dump() -> None:
    original = _minimal_recipe_dict()
    recipe = Recipe.model_validate(original)
    dumped = recipe.model_dump(mode="json")
    rebuilt = Recipe.model_validate(dumped)
    assert rebuilt == recipe


def test_unknown_top_level_key_raises() -> None:
    bad = _minimal_recipe_dict()
    bad["mystery_section"] = {"x": 1}
    with pytest.raises(ValidationError):
        Recipe.model_validate(bad)


def test_unknown_field_in_section_raises() -> None:
    bad = _minimal_recipe_dict()
    bad["Splits"]["unknown_strategy"] = "x"
    with pytest.raises(ValidationError):
        Recipe.model_validate(bad)


@pytest.mark.parametrize("missing", ["Input", "Output", "Labels", "Splits"])
def test_missing_required_section_raises(missing: str) -> None:
    bad = _minimal_recipe_dict()
    del bad[missing]
    with pytest.raises(ValidationError):
        Recipe.model_validate(bad)


@pytest.mark.parametrize("missing", ["schema_version", "plugin"])
def test_missing_required_top_level_field_raises(missing: str) -> None:
    bad = _minimal_recipe_dict()
    del bad[missing]
    with pytest.raises(ValidationError):
        Recipe.model_validate(bad)


def test_recipe_instances_are_frozen() -> None:
    recipe = Recipe.model_validate(_minimal_recipe_dict())
    with pytest.raises((ValidationError, TypeError, AttributeError)):
        recipe.seed = 99  # type: ignore[misc]


def test_per_section_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        InputSection.model_validate(
            {"sources": [], "unexpected": True},
        )


def test_visualization_mode_must_be_exploration_or_reporting() -> None:
    bad = _minimal_recipe_dict()
    bad["Visualizations"] = [
        {
            "name": "hist",
            "op": "histogram",
            "stage": "post_split",
            "mode": "neither",
        }
    ]
    with pytest.raises(ValidationError):
        Recipe.model_validate(bad)


def test_splits_section_supports_key_assignment_only() -> None:
    section = SplitsSection.model_validate(
        {
            "key_assignment": {
                "field": "split_id",
                "mapping": {"a": "train", "b": "val"},
            },
        }
    )
    assert section.key_assignment is not None
    assert section.key_assignment.mapping == {"a": "train", "b": "val"}
    assert section.ratios is None
