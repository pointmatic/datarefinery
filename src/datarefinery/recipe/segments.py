# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Segment-aware canonical-bytes machinery.

Implements the design frozen in
``docs/specs/phase-j-recipe-architecture-design.md``:

- **Q1** (Story J.n.3) — the flat :class:`~datarefinery.recipe.models.Recipe`
  is partitioned into the frozen four segments via :data:`RECIPE_FIELD_SEGMENTS`
  + :func:`segments_of`. This is an *internal* partition (Option 1): the
  author-facing recipe stays flat; segmentation drives hashing, per-segment
  versioning, validation dispatch, and pin-test boundaries — not author shape.
- **Q3** — canonical bytes = ordered concatenation of per-segment SHA-256
  digests, with a single fixed :data:`EMPTY_MARKER` for empty/absent
  segments, and an intrinsic *cumulative-prefix* form (:func:`prefix_hash`)
  that keeps the deferred vertical axis (Q8) adoptable without redesign.
- **Q4** — per-segment version constants and a ``(segment, from, to)``
  migration-registry skeleton (populated by J.n.7).

:func:`recipe_identity_hash` is the **authoritative** cache-identity hash as
of J.n.3 (it replaced the flat
:func:`datarefinery.recipe.canonical.to_canonical_bytes` sha256). The
segmented hash is intentionally != the flat hash — the combiner change is the
one-time pre-1.0 invalidation (and a canonical-form algorithm change, so it
rides the ``schema_version`` 2→3 bump per ``project-essentials.md``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datarefinery.recipe.models import Recipe

#: Fixed segment order for the horizontal axis. Vertical-axis *stage*
#: segments (Q8, deferred) would compose on top via :func:`prefix_hash`.
SEGMENT_ORDER: tuple[str, ...] = ("core", "plugin", "overlays", "extensions")

#: Declarative assignment of every :class:`~datarefinery.recipe.models.Recipe`
#: field to its owning segment (design Q1). A CI guard
#: (``test_every_recipe_field_is_assigned_exactly_one_segment``) pins that this
#: map covers the model exactly — so a new section *cannot* be added without
#: consciously choosing its segment (the Option-1 anti-footgun replacing the
#: structural enforcement author-facing nesting would have given). ``overlays``
#: and ``extensions`` are single-namespace segments contributed as their bare
#: mapping value by :func:`segments_of`; the others are field-keyed.
RECIPE_FIELD_SEGMENTS: dict[str, str] = {
    # core — identity, versions, and the structural sections
    "schema_version": "core",
    "plugin": "core",
    "seed": "core",
    "Input": "core",
    "Output": "core",
    "Labels": "core",
    "SampleData": "core",
    "InputContracts": "core",
    "Splits": "core",
    "OutputExpectations": "core",
    # plugin — the op-list sections whose op vocabulary is plugin-defined
    "Filters": "plugin",
    "Generation": "plugin",
    "Transformations": "plugin",
    "Augmentations": "plugin",
    "Featurizations": "plugin",
    "Visualizations": "plugin",
    "Sinks": "plugin",
    # overlays — variants reborn (Q2); contributed as the bare mapping
    "variants": "overlays",
    # extensions — the J.n.6 namespace; no Recipe field exists yet
}

#: Separator between per-segment digests in the stable join. ASCII Unit
#: Separator — cannot occur inside a hex/raw digest position ambiguously
#: because every joined element is a fixed-length 32-byte digest.
_JOIN_SEP: bytes = b"\x1f"

#: Domain-separated constant standing in for an empty/absent segment, so an
#: empty segment contributes a *fixed nothing* to the join. Distinct from any
#: real content digest with overwhelming probability (different preimage
#: space), so "empty" never collides with "a segment that hashes to X".
EMPTY_MARKER: bytes = hashlib.sha256(b"\x00datarefinery/empty-segment/v1").digest()

# --- Per-segment version constants (Q4). Each bumps independently; there is
# --- deliberately no global umbrella counter. ------------------------------
CORE_SCHEMA_VERSION: int = 1
PLUGIN_IMAGE_SCHEMA_VERSION: int = 1
PLUGIN_AUDIO_SCHEMA_VERSION: int = 1
OVERLAYS_SCHEMA_VERSION: int = 1
EXTENSIONS_SCHEMA_VERSION: int = 1

#: Migration registry skeleton, keyed ``(segment, from_version, to_version)``.
#: Empty at J.n.2; J.n.7 populates it (and the J.n.3 flat→segmented bootstrap
#: registers its own whole-recipe entry).
SEGMENT_MIGRATIONS: dict[tuple[str, int, int], Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _is_empty(value: Any) -> bool:
    """An empty/absent segment: ``None`` or an empty container/string."""
    if value is None:
        return True
    if isinstance(value, (dict, list, tuple, str, set)) and len(value) == 0:
        return True
    return False


def _canonical_subbytes(value: Any) -> bytes:
    """Sorted-compact JSON of a segment value — same algorithm as the flat
    :func:`...canonical.to_canonical_bytes`, applied per segment."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def segment_digest(value: Any) -> bytes:
    """SHA-256 digest of one segment, or :data:`EMPTY_MARKER` if empty."""
    if _is_empty(value):
        return EMPTY_MARKER
    return hashlib.sha256(_canonical_subbytes(value)).digest()


def join_stable(digests: Sequence[bytes]) -> bytes:
    """Stable concatenation of per-segment digests (the canonical join)."""
    return _JOIN_SEP.join(digests)


def segment_digests(segments: Mapping[str, Any]) -> list[bytes]:
    """Per-segment digests in :data:`SEGMENT_ORDER` (missing keys → empty)."""
    return [segment_digest(segments.get(name)) for name in SEGMENT_ORDER]


def segmented_canonical_bytes(segments: Mapping[str, Any]) -> bytes:
    """The canonical join for a full set of segments."""
    return join_stable(segment_digests(segments))


def segmented_recipe_hash(segments: Mapping[str, Any]) -> str:
    """Full external identity hash over all segments (hex SHA-256)."""
    return hashlib.sha256(segmented_canonical_bytes(segments)).hexdigest()


def prefix_hash(digests: Sequence[bytes], upto: int) -> str:
    """Cumulative-prefix hash over the first ``upto`` segment digests.

    The deferred vertical axis (Q8) keys an expensive stage's cache artifact
    on this prefix, so a downstream-only change leaves the upstream prefix
    byte-identical. Provided now purely so adopting the vertical axis later
    needs no combiner redesign; nothing uses it yet.
    """
    return hashlib.sha256(join_stable(list(digests[:upto]))).hexdigest()


# ---------------------------------------------------------------------------
# Recipe partition + authoritative identity (Story J.n.3)
# ---------------------------------------------------------------------------


def segments_of(recipe: Recipe) -> dict[str, Any]:
    """Partition a (flat, author-facing) recipe into the frozen four segments.

    ``core`` and ``plugin`` are field-keyed dicts of their assigned sections
    (per :data:`RECIPE_FIELD_SEGMENTS`); ``overlays`` and ``extensions`` are
    single-namespace segments contributed as their *bare* mapping value, so an
    empty/stripped namespace collapses to ``{}`` → :data:`EMPTY_MARKER`
    (additivity, Q3/Q5). At hash time ``variants`` is always stripped to ``{}``
    by :func:`~datarefinery.recipe.variants.apply_variant`, so ``overlays`` is
    empty for every v1 recipe — overlay *definitions* never enter identity.
    """
    dump = recipe.model_dump(mode="json")
    core: dict[str, Any] = {}
    plugin: dict[str, Any] = {}
    for field, value in dump.items():
        segment = RECIPE_FIELD_SEGMENTS[field]
        if segment == "core":
            core[field] = value
        elif segment == "plugin":
            plugin[field] = value
        # overlays/extensions are folded in as bare namespace values below.
    return {
        "core": core,
        "plugin": plugin,
        "overlays": dump.get("variants") or {},
        "extensions": dump.get("extensions") or {},
    }


def recipe_identity_hash(recipe: Recipe) -> str:
    """The authoritative recipe-side cache-identity hash (segmented join).

    This is the single source of truth for ``CacheKey.recipe_hash`` and every
    ``manifest.recipe_hash`` comparison. Replaced the flat
    ``sha256(to_canonical_bytes(recipe))`` in J.n.3.
    """
    return segmented_recipe_hash(segments_of(recipe))
