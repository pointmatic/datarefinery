# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-14 variant overlay.

`apply_variant(recipe, name)` returns a new `Recipe` with the named
variant's per-section overrides applied. Overlay entries replace the
target section wholesale (e.g., `Augmentations: []` clears the section,
`seed: 99` replaces the scalar). Each section is replaced — there is no
deep merge within a section.

The returned recipe always has `variants={}`. This makes cache identity
reflect only the selected/applied semantics: editing or adding an unused
variant does not invalidate cached instances of other variants.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from datarefinery.core.errors import RecipeError
from datarefinery.recipe.models import Recipe


def apply_variant(recipe: Recipe, variant_name: str | None) -> Recipe:
    """Apply the named variant overlay and return a new Recipe.

    `variant_name=None` returns the recipe with `variants` cleared but no
    overlay applied. An unknown variant name raises `RecipeError`.
    """
    overlay: dict[str, Any] = {}
    if variant_name is not None:
        if variant_name not in recipe.variants:
            raise RecipeError(
                f"unknown variant {variant_name!r}; declared variants: "
                f"{sorted(recipe.variants.keys())}"
            )
        overlay = dict(recipe.variants[variant_name])

    base = recipe.model_dump(mode="python")
    for section_name, section_value in overlay.items():
        base[section_name] = section_value
    base["variants"] = {}

    try:
        return Recipe.model_validate(base)
    except ValidationError as exc:
        raise RecipeError(
            f"variant {variant_name!r} produced an invalid recipe: {exc}"
        ) from exc
