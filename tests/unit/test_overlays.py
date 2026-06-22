# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-14 recipe-overlay tests (Story J.n.5 — generalizes the former variants).

Covers single- and multi-overlay application (ordered, last-writer-wins per
section), identity isolation (unused/other overlay definitions don't move a
selection's hash), and additivity (no overlays ⇒ empty `overlays` segment).
"""

from __future__ import annotations

from typing import Any

import pytest

from datarefinery.core.errors import RecipeError
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.overlays import apply_overlays
from datarefinery.recipe.segments import recipe_identity_hash


def _base_recipe_dict() -> dict[str, Any]:
    return {
        "schema_version": 3,
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
            {
                "name": "flip",
                "op": "horizontal_flip",
                "params": {"p": 0.5},
                "splits": ["train"],
                "seed": 1,
            },
        ],
        "overlays": {
            "no_augment": {"Augmentations": []},
            "extra_seed": {"seed": 99},
            "other_seed": {"seed": 7},
        },
    }


def _base_recipe() -> Recipe:
    return Recipe.model_validate(_base_recipe_dict())


# ---------------------------------------------------------------------------
# Selection / stripping
# ---------------------------------------------------------------------------


def test_apply_none_clears_overlays_but_preserves_pipeline() -> None:
    base = _base_recipe()
    applied = apply_overlays(base, None)
    assert applied.overlays == {}
    assert applied.Augmentations == base.Augmentations
    assert applied.seed == base.seed


def test_apply_empty_list_is_the_strip_path() -> None:
    applied = apply_overlays(_base_recipe(), [])
    assert applied.overlays == {}
    assert applied.seed == 0


def test_apply_clears_section_via_empty_list_overlay() -> None:
    applied = apply_overlays(_base_recipe(), ["no_augment"])
    assert applied.Augmentations == []


def test_apply_replaces_scalar() -> None:
    applied = apply_overlays(_base_recipe(), ["extra_seed"])
    assert applied.seed == 99


def test_apply_returns_recipe_with_empty_overlays() -> None:
    applied = apply_overlays(_base_recipe(), ["extra_seed"])
    assert applied.overlays == {}


# ---------------------------------------------------------------------------
# Multi-overlay composition (ordered, last-writer-wins per section)
# ---------------------------------------------------------------------------


def test_multi_overlay_applies_each_section() -> None:
    applied = apply_overlays(_base_recipe(), ["no_augment", "extra_seed"])
    assert applied.Augmentations == []  # from no_augment
    assert applied.seed == 99  # from extra_seed


def test_multi_overlay_last_writer_wins_per_section() -> None:
    # Both overlays touch `seed`; the later one in the list wins.
    a = apply_overlays(_base_recipe(), ["extra_seed", "other_seed"])
    assert a.seed == 7
    b = apply_overlays(_base_recipe(), ["other_seed", "extra_seed"])
    assert b.seed == 99


def test_overlay_order_changes_identity_on_conflict() -> None:
    # Order matters when overlays conflict → different resolved recipe → hash.
    ab = recipe_identity_hash(apply_overlays(_base_recipe(), ["extra_seed", "other_seed"]))
    ba = recipe_identity_hash(apply_overlays(_base_recipe(), ["other_seed", "extra_seed"]))
    assert ab != ba


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_unknown_overlay_raises_listing_declared_names() -> None:
    with pytest.raises(RecipeError, match="unknown overlay 'nonexistent'") as info:
        apply_overlays(_base_recipe(), ["nonexistent"])
    assert "extra_seed" in str(info.value)
    assert "no_augment" in str(info.value)


def test_invalid_overlay_raises_recipe_error() -> None:
    bad_dict = _base_recipe_dict()
    bad_dict["overlays"]["bad"] = {"seed": "not-an-int"}
    recipe = Recipe.model_validate(bad_dict)
    with pytest.raises(RecipeError, match="produced an invalid"):
        apply_overlays(recipe, ["bad"])


# ---------------------------------------------------------------------------
# Identity isolation + additivity
# ---------------------------------------------------------------------------


def test_each_overlay_produces_different_identity() -> None:
    base = _base_recipe()
    a = recipe_identity_hash(apply_overlays(base, ["no_augment"]))
    b = recipe_identity_hash(apply_overlays(base, ["extra_seed"]))
    assert a != b


def test_identity_neutral_to_unused_overlay_definitions() -> None:
    # Adding/modifying an unused overlay does not move a selection's identity.
    base = _base_recipe()
    extended_dict = _base_recipe_dict()
    extended_dict["overlays"]["new_overlay"] = {"seed": 123}
    extended = Recipe.model_validate(extended_dict)
    a = recipe_identity_hash(apply_overlays(base, ["no_augment"]))
    b = recipe_identity_hash(apply_overlays(extended, ["no_augment"]))
    assert a == b


def test_no_overlays_selected_hashes_like_no_overlays_defined() -> None:
    # Additivity: the resolved recipe with no overlays applied is identity-equal
    # whether or not overlay *definitions* exist (overlays segment → empty).
    with_defs = recipe_identity_hash(apply_overlays(_base_recipe(), None))
    no_defs_dict = _base_recipe_dict()
    no_defs_dict.pop("overlays")
    without_defs = recipe_identity_hash(apply_overlays(Recipe.model_validate(no_defs_dict), None))
    assert with_defs == without_defs


def test_apply_does_not_mutate_input_recipe() -> None:
    base = _base_recipe()
    base_hash = recipe_identity_hash(base)
    _ = apply_overlays(base, ["no_augment"])
    assert recipe_identity_hash(base) == base_hash
    assert len(base.Augmentations) == 1
