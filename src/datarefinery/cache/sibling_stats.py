# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-TRANS-1 sibling-instance fitted-stats resolver (Story H.n.1).

Locates the most-recent promoted instance whose recipe matches a given
sibling recipe path and returns a read-only ``FittedStatistics`` handle
to its ``fitted_statistics/<op_id>/`` directory. Used by ``normalize``
(and any future fit-phase op) to import statistics across recipes for
train/inference parity in distribution-shift / A-B / cross-team /
longitudinal evaluation workflows.

**Intentional loose coupling.** The sibling's ``recipe_hash`` is NOT
mixed into the *consuming* recipe's cache identity. Re-materializing
upstream does NOT auto-invalidate downstream — the user is responsible
for re-materializing downstream when upstream changes. Tight coupling
(sibling ``recipe_hash`` participating in cache identity, so upstream
changes auto-invalidate downstream) is tracked in Future as a
schema-version-bumped upgrade for multi-team and longitudinal workflows
where the loose-coupling failure mode is harder to catch by inspection.

Three explicit failure modes, each a distinct subclass of
``MaterializeError`` so callers can branch on the failure shape:

- ``SiblingInstanceNotFoundError`` — no promoted instance found under
  ``<cache_root>/instances/<recipe_hash16>/`` for the supplied recipe.
- ``SiblingOpNotFoundError`` — instance located, but no
  ``fitted_statistics/<op_id>/`` directory inside it.
- ``SiblingStatsIncompatibleError`` — instance + op_id located, but a
  required statistic is missing or unreadable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from datarefinery.cache.layout import (
    fitted_stats_dir,
    instances_root,
    manifest_path,
)
from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.recipe.loader import load as load_recipe
from datarefinery.recipe.overlays import apply_overlays
from datarefinery.recipe.segments import recipe_identity_hash


class SiblingInstanceNotFoundError(MaterializeError):
    """No promoted instance found in the cache for the sibling recipe."""


class SiblingOpNotFoundError(MaterializeError):
    """Sibling instance exists but contains no ``fitted_statistics/<op_id>/``."""


class SiblingStatsIncompatibleError(MaterializeError):
    """Sibling op directory exists but a required statistic is missing/unreadable."""


def resolve_sibling_stats(
    cache_root: Path,
    recipe_path: Path,
    op_id: str,
    *,
    required_vectors: tuple[str, ...] = (),
    required_scalars: tuple[str, ...] = (),
) -> FittedStatistics:
    """Resolve sibling fitted statistics and return a read-only handle.

    Resolution path:

    1. Load the sibling recipe at ``recipe_path`` and compute its
       canonical SHA-256 hash.
    2. Locate candidate promoted instances under
       ``<cache_root>/instances/<recipe_hash16>/<input16>/<seed>/``.
    3. Among candidates whose ``manifest.json`` is readable, pick the
       most-recent by ``Manifest.created_at`` (ties broken by path).
    4. Verify ``fitted_statistics/<op_id>/`` exists.
    5. Verify each name in ``required_vectors`` / ``required_scalars``
       is present and readable.

    Returns a ``FittedStatistics`` rooted at the sibling instance's
    ``fitted_statistics/`` directory. The caller then reads stats via
    ``stats.get_vector(op_id, name)`` / ``stats.get_scalar(op_id, name)``.
    """
    # Strip overlays before hashing so the lookup matches the
    # materialize path (core/datarefinery.py), which always runs
    # apply_overlays(recipe, None) before computing the cache key. Without
    # this, any sibling recipe declaring `overlays:` produces a hash
    # mismatch and the shard lookup fails (G19).
    sibling_recipe = apply_overlays(load_recipe(recipe_path), None)
    sibling_hash = recipe_identity_hash(sibling_recipe)
    shard = sibling_hash[:16]

    shard_dir = instances_root(cache_root) / shard
    if not shard_dir.is_dir():
        raise SiblingInstanceNotFoundError(
            f"sibling_stats: no promoted instance for recipe at {recipe_path!s} "
            f"(expected shard {shard_dir!s} not found)"
        )

    candidates: list[Path] = []
    for input_shard in shard_dir.iterdir():
        if not input_shard.is_dir() or input_shard.name.startswith("."):
            continue
        for seed_dir in input_shard.iterdir():
            if seed_dir.is_dir() and manifest_path(seed_dir).exists():
                candidates.append(seed_dir)

    if not candidates:
        raise SiblingInstanceNotFoundError(
            f"sibling_stats: shard {shard_dir!s} exists but contains no "
            f"promoted instance (no <input>/<seed>/manifest.json)"
        )

    best = _pick_most_recent(candidates)
    fitted_root = fitted_stats_dir(best)
    op_dir = fitted_root / op_id
    if not op_dir.is_dir():
        raise SiblingOpNotFoundError(
            f"sibling_stats: instance {best!s} has no fitted_statistics/{op_id}/ "
            f"directory (this op did not produce fitted statistics in the sibling)"
        )

    stats = FittedStatistics(fitted_root)
    for name in required_vectors:
        try:
            stats.get_vector(op_id, name)
        except Exception as exc:  # MaterializeError + pyarrow ArrowInvalid + IO
            raise SiblingStatsIncompatibleError(
                f"sibling_stats: required vector {name!r} for op {op_id!r} in "
                f"{best!s} is missing or unreadable: {exc}"
            ) from exc
    for name in required_scalars:
        try:
            stats.get_scalar(op_id, name)
        except Exception as exc:  # MaterializeError + json.JSONDecodeError + IO
            raise SiblingStatsIncompatibleError(
                f"sibling_stats: required scalar {name!r} for op {op_id!r} in "
                f"{best!s} is missing or unreadable: {exc}"
            ) from exc

    return stats


def _pick_most_recent(candidates: list[Path]) -> Path:
    """Return the candidate with the latest manifest ``created_at``.

    Manifests that fail to parse fall back to ``datetime.min``; path
    lexicographic order breaks ties so the choice is deterministic.
    """

    def key(c: Path) -> tuple[datetime, str]:
        try:
            ts = read_manifest(manifest_path(c)).created_at
        except Exception:
            ts = datetime.min.replace(tzinfo=UTC)
        return (ts, str(c))

    return max(candidates, key=key)
