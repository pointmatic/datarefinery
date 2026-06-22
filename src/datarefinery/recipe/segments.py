# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Segment-aware canonical-bytes machinery (Story J.n.2, dormant infrastructure).

Implements the design frozen in
``docs/specs/phase-j-recipe-architecture-design.md``:

- **Q3** — canonical bytes = ordered concatenation of per-segment SHA-256
  digests, with a single fixed :data:`EMPTY_MARKER` for empty/absent
  segments, and an intrinsic *cumulative-prefix* form (:func:`prefix_hash`)
  that keeps the deferred vertical axis (Q8) adoptable without redesign.
- **Q4** — per-segment version constants and a ``(segment, from, to)``
  migration-registry skeleton (populated by J.n.7).

This is **dormant**: no recipe field is segmented yet (J.n.3 owns the model
refactor + the authoritative flip). The flat
:func:`datarefinery.recipe.canonical.to_canonical_bytes` hasher remains
authoritative until then. The segmented hash is *intentionally* not equal to
the flat hash — the uniform-wrapping combiner is precisely the one-time
invalidation J.n.3 lands; shadow mode therefore verifies determinism and
dormancy, never flat==segmented.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

#: Fixed segment order for the horizontal axis. Vertical-axis *stage*
#: segments (Q8, deferred) would compose on top via :func:`prefix_hash`.
SEGMENT_ORDER: tuple[str, ...] = ("core", "plugin", "overlays", "extensions")

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
# Dormant shadow path
# ---------------------------------------------------------------------------


def shadow_segments_from_flat(flat_recipe: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap a flat (pre-segmentation) recipe dump as a degenerate single-``core``
    segment set, so the segmented machinery can be exercised end-to-end before
    J.n.3 distributes fields. No real field assignment happens here."""
    return {"core": dict(flat_recipe), "plugin": None, "overlays": None, "extensions": None}


def shadow_recipe_hash(flat_recipe: Mapping[str, Any]) -> str:
    """Segmented hash of the degenerate single-``core`` wrapping of a flat
    recipe. Deterministic and intentionally != the flat hash; dormant (does
    not drive the cache key in J.n.2)."""
    return segmented_recipe_hash(shadow_segments_from_flat(flat_recipe))
