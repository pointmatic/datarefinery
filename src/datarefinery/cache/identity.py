# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-4 cache identity: `CacheKey` + `compute_cache_key`.

The cache key is the triple (recipe_hash, input_hash, seed). Cache
directory paths use only the first 16 hex characters of `recipe_hash`
and `input_hash` (`.short`); the full hash is recorded in
`manifest.json`. See `project-essentials.md` "Cache identity is the
reproducibility contract - invalidations are ceremonious."
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from datarefinery.recipe.models import Recipe
from datarefinery.recipe.segments import recipe_identity_hash


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Identity tuple for a materialized instance."""

    recipe_hash: str
    input_hash: str
    seed: int

    @property
    def short(self) -> str:
        """First 16 hex characters of `recipe_hash` (cache directory shard)."""
        return self.recipe_hash[:16]


def compute_cache_key(
    recipe: Recipe,
    raw_input_hashes: Mapping[str, str],
    seed: int,
) -> CacheKey:
    """Compute the cache key for a (recipe, inputs, seed) triple.

    `raw_input_hashes` maps each input source name to a SHA-256 hex
    digest of that source's content. The combined `input_hash` is
    order-independent: keys are sorted by source name before
    concatenation.
    """
    recipe_hash = recipe_identity_hash(recipe)

    parts = [f"{name}={raw_input_hashes[name]};" for name in sorted(raw_input_hashes)]
    payload = "".join(parts).encode("utf-8")
    input_hash = hashlib.sha256(payload).hexdigest()

    return CacheKey(recipe_hash=recipe_hash, input_hash=input_hash, seed=seed)
