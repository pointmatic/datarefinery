# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-14 recipe overlays (Story J.n.5 — generalizes the former `variants`).

`apply_overlays(recipe, names)` returns a new `Recipe` with the named overlays
applied **in selection order, last-writer-wins per section**. Each overlay
entry replaces the target section wholesale (e.g., `Augmentations: []` clears
the section, `seed: 99` replaces the scalar) — there is no deep merge within a
section. When two selected overlays touch the same section, the later one in
the list wins (override semantics, generalized from the single-variant case).

The returned recipe always has `overlays={}`. This makes cache identity reflect
only the *resolved* recipe (base + applied overlays): editing or adding an
unused overlay does not invalidate cached instances of other selections, and a
recipe with no overlays selected hashes identically to one with none defined
(the `overlays` segment collapses to the empty marker — see `recipe.segments`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from datarefinery.core.errors import RecipeError
from datarefinery.recipe.models import Recipe


def apply_overlays(recipe: Recipe, names: Sequence[str] | None) -> Recipe:
    """Apply the named overlays in order and return a new Recipe.

    `names=None` (or an empty sequence) returns the recipe with `overlays`
    cleared but no overlay applied — the canonical "strip overlays before
    hashing" path. An unknown overlay name raises `RecipeError`.
    """
    selected = list(names or [])

    base = recipe.model_dump(mode="python")
    for name in selected:
        if name not in recipe.overlays:
            raise RecipeError(
                f"unknown overlay {name!r}; declared overlays: {sorted(recipe.overlays.keys())}"
            )
        overlay: dict[str, Any] = dict(recipe.overlays[name])
        # Last-writer-wins per section: a later overlay's section replaces an
        # earlier one's wholesale (the single-section override semantics,
        # applied left to right).
        for section_name, section_value in overlay.items():
            base[section_name] = section_value
    base["overlays"] = {}

    try:
        return Recipe.model_validate(base)
    except ValidationError as exc:
        raise RecipeError(f"overlays {selected!r} produced an invalid recipe: {exc}") from exc
