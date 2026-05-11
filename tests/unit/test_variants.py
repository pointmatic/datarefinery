# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-14 variant-overlay tests."""

from __future__ import annotations

from typing import Any

import pytest

from datarefinery.core.errors import RecipeError
from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.variants import apply_variant


def _base_recipe_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 0,
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]},
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                "label": {"dtype": "int32"},
            }
        },
        "Labels": {
            "field": "label",
            "source": {"kind": "derived", "derivation": "parent_directory_name"},
        },
        "Splits": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}, "seed": 7},
        "Augmentations": [
            {"name": "flip", "op": "horizontal_flip", "splits": ["train"], "seed": 1},
        ],
        "variants": {
            "no_augment": {"Augmentations": []},
            "extra_seed": {"seed": 99},
        },
    }


def _base_recipe() -> Recipe:
    return Recipe.model_validate(_base_recipe_dict())


def test_apply_none_clears_variants_but_preserves_pipeline() -> None:
    base = _base_recipe()
    applied = apply_variant(base, None)
    assert applied.variants == {}
    assert applied.Augmentations == base.Augmentations
    assert applied.seed == base.seed


def test_apply_clears_section_via_empty_list_overlay() -> None:
    applied = apply_variant(_base_recipe(), "no_augment")
    assert applied.Augmentations == []


def test_apply_replaces_scalar() -> None:
    applied = apply_variant(_base_recipe(), "extra_seed")
    assert applied.seed == 99


def test_unknown_variant_raises() -> None:
    with pytest.raises(RecipeError, match="unknown variant 'nonexistent'"):
        apply_variant(_base_recipe(), "nonexistent")


def test_unknown_variant_lists_declared_names() -> None:
    with pytest.raises(RecipeError) as info:
        apply_variant(_base_recipe(), "nonexistent")
    assert "extra_seed" in str(info.value)
    assert "no_augment" in str(info.value)


def test_each_variant_produces_different_canonical_bytes() -> None:
    base = _base_recipe()
    a = to_canonical_bytes(apply_variant(base, "no_augment"))
    b = to_canonical_bytes(apply_variant(base, "extra_seed"))
    assert a != b


def test_canonical_neutrality_to_unused_variants() -> None:
    """Adding or modifying an unused variant does not change cache identity."""
    base = _base_recipe()
    extended_dict = _base_recipe_dict()
    extended_dict["variants"]["new_variant"] = {"seed": 123}
    extended = Recipe.model_validate(extended_dict)

    # Selected variant unchanged: applied canonical bytes must match.
    a = to_canonical_bytes(apply_variant(base, "no_augment"))
    b = to_canonical_bytes(apply_variant(extended, "no_augment"))
    assert a == b


def test_apply_returns_recipe_with_empty_variants() -> None:
    applied = apply_variant(_base_recipe(), "extra_seed")
    assert applied.variants == {}


def test_invalid_overlay_raises_recipe_error() -> None:
    bad_dict = _base_recipe_dict()
    bad_dict["variants"]["bad"] = {"seed": "not-an-int"}
    recipe = Recipe.model_validate(bad_dict)
    with pytest.raises(RecipeError, match="variant 'bad' produced an invalid"):
        apply_variant(recipe, "bad")


def test_apply_does_not_mutate_input_recipe() -> None:
    base = _base_recipe()
    base_canonical = to_canonical_bytes(base)
    _ = apply_variant(base, "no_augment")
    assert to_canonical_bytes(base) == base_canonical
    assert len(base.Augmentations) == 1
