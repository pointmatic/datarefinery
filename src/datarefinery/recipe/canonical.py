# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-4 canonical bytes — the recipe-side input to cache identity.

This is the cache reproducibility contract. See `project-essentials.md`
"Cache identity is the reproducibility contract — invalidations are
ceremonious." Every pydantic field default contributes to the canonical
bytes — a "no-op refactor" that changes a default silently shifts the
canonical hash for every recipe that omits that field, invalidating
every cached instance for every user.
"""

from __future__ import annotations

import json

from datarefinery.recipe.models import Recipe


def to_canonical_bytes(recipe: Recipe) -> bytes:
    """Render `recipe` to canonical UTF-8 JSON bytes.

    Algorithm:

    1. `Recipe.model_dump(mode="json")` to get a JSON-safe dict.
    2. `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
       to produce a compact, deterministic textual form.
    3. UTF-8 encode.
    """
    payload = recipe.model_dump(mode="json")
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return text.encode("utf-8")
