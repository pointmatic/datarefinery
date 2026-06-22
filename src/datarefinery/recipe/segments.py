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
    # overlays — the recipe's overlay definitions (Q2); contributed as the
    # bare mapping. Stripped to {} at hash time, so it never enters identity.
    "overlays": "overlays",
    # extensions — the J.n.6 namespace (design Q5); contributed as the bare
    # namespace mapping, empty → EMPTY_MARKER (additive landing).
    "extensions": "extensions",
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

#: The version-keyed segments for migration/version dispatch. ``plugin`` is
#: split per plugin family (``plugin:image`` / ``plugin:audio``) because the
#: two bump independently (Finding A: an audio-surface change must never touch
#: an image recipe). ``core``/``overlays``/``extensions`` are single-keyed.
SEGMENT_VERSION_KEYS: tuple[str, ...] = (
    "core",
    "plugin:image",
    "plugin:audio",
    "overlays",
    "extensions",
)

#: The first flat ``schema_version`` of the *segmented-canonical era* — the J.n.3
#: combiner switch. Flat eras 1/2 are pre-segmented and are lifted to era 3 by
#: the flat ``(int, int)`` chain in ``recipe.loader`` *before* any per-segment
#: migration runs, so segment migrations only ever see era-3+ recipes.
SEGMENTED_ERA: int = 3

#: Structural era-detection table (design Q4): the flat ``schema_version`` on
#: disk stays the era marker (Option 1 keeps the recipe flat — no on-disk
#: segment-version block, no extra invalidation), and each era pins the version
#: of every segment at that era. A new era is appended whenever any segment
#: bumps; the loader diffs the recipe's era against :func:`current_segment_versions`
#: and runs the registered per-segment migrations to close the gap.
SCHEMA_ERA_SEGMENT_VERSIONS: dict[int, dict[str, int]] = {
    3: {"core": 1, "plugin:image": 1, "plugin:audio": 1, "overlays": 1, "extensions": 1},
}


def current_segment_versions() -> dict[str, int]:
    """The version each segment is at *in this build* (the per-segment constants)."""
    return {
        "core": CORE_SCHEMA_VERSION,
        "plugin:image": PLUGIN_IMAGE_SCHEMA_VERSION,
        "plugin:audio": PLUGIN_AUDIO_SCHEMA_VERSION,
        "overlays": OVERLAYS_SCHEMA_VERSION,
        "extensions": EXTENSIONS_SCHEMA_VERSION,
    }


def segment_versions_for_era(schema_version: int) -> dict[str, int]:
    """The per-segment versions a recipe at flat ``schema_version`` carries.

    Raises ``KeyError`` for a non-segmented era (< :data:`SEGMENTED_ERA`): such a
    recipe must first be lifted to the segmented era by the flat migration chain.
    """
    return dict(SCHEMA_ERA_SEGMENT_VERSIONS[schema_version])


def _partition_flat(flat: dict[str, Any]) -> dict[str, Any]:
    """Split a flat recipe dict into its four hash segments (field-keyed
    ``core``/``plugin``; bare-mapping ``overlays``/``extensions``)."""
    core: dict[str, Any] = {}
    plugin: dict[str, Any] = {}
    for field, value in flat.items():
        segment = RECIPE_FIELD_SEGMENTS.get(field)
        if segment == "core":
            core[field] = value
        elif segment == "plugin":
            plugin[field] = value
    return {
        "core": core,
        "plugin": plugin,
        "overlays": flat.get("overlays") or {},
        "extensions": flat.get("extensions") or {},
    }


def _partition_for_key(version_key: str) -> str:
    """Map a :data:`SEGMENT_VERSION_KEYS` entry to its hash-segment partition."""
    if version_key.startswith("plugin"):
        return "plugin"
    return version_key


def apply_segment_migrations(
    flat: dict[str, Any],
    from_versions: Mapping[str, int],
    to_versions: Mapping[str, int],
) -> dict[str, Any]:
    """Bring each segment of a flat recipe dict from its on-disk era version up
    to the current build version by replaying the registered per-segment
    migrations in :data:`SEGMENT_MIGRATIONS`.

    The dispatch is per *segment-version key* (:data:`SEGMENT_VERSION_KEYS`):
    a ``("core", v, v+1)`` migration rewrites the core fields; a
    ``("plugin:image", v, v+1)`` migration rewrites the plugin fields only when
    the recipe's ``plugin`` matches that family. ``overlays``/``extensions``
    migrate their bare namespace mapping.

    When ``from_versions == to_versions`` (the steady state — every recipe sits
    at the current era, which is true for the whole pre-1.0 lifetime until a
    segment first bumps) this is an **exact pass-through**: the flat dict is
    returned unchanged, so the read path can never perturb canonical bytes while
    the registry is dormant.
    """
    if dict(from_versions) == dict(to_versions):
        return flat

    parts = _partition_flat(flat)
    plugin_name = flat.get("plugin")
    for version_key in SEGMENT_VERSION_KEYS:
        start = from_versions.get(version_key, 1)
        end = to_versions.get(version_key, 1)
        if start >= end:
            continue
        # A plugin-family migration only applies to a recipe of that family.
        if version_key == "plugin:image" and plugin_name not in _IMAGE_PLUGIN_NAMES:
            continue
        if version_key == "plugin:audio" and plugin_name not in _AUDIO_PLUGIN_NAMES:
            continue
        partition = _partition_for_key(version_key)
        for v in range(start, end):
            step = SEGMENT_MIGRATIONS.get((version_key, v, v + 1))
            if step is None:
                raise ValueError(
                    f"no segment migration registered for {version_key!r} "
                    f"{v} -> {v + 1}; a segment-version bump requires a migration "
                    f"(see project-essentials.md cache-identity ceremony)"
                )
            parts[partition] = step(parts[partition])

    # Re-flatten: core/plugin fields overwrite their slots; overlays/extensions
    # are set back as bare mappings (dropped entirely if migrated to empty).
    out = {k: v for k, v in flat.items() if RECIPE_FIELD_SEGMENTS.get(k) not in ("core", "plugin")}
    out.update(parts["core"])
    out.update(parts["plugin"])
    for namespace_segment in ("overlays", "extensions"):
        if parts[namespace_segment]:
            out[namespace_segment] = parts[namespace_segment]
        else:
            out.pop(namespace_segment, None)
    return out


#: Plugin ``name`` values that belong to each plugin family for segment-migration
#: dispatch. Kept small and explicit; extended when a new plugin of a family ships.
_IMAGE_PLUGIN_NAMES: frozenset[str] = frozenset({"image_classification"})
_AUDIO_PLUGIN_NAMES: frozenset[str] = frozenset({"audio_classification"})


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
    (additivity, Q3/Q5). At hash time ``overlays`` is always stripped to ``{}``
    by :func:`~datarefinery.recipe.overlays.apply_overlays`, so the ``overlays``
    segment is empty for every recipe — overlay *definitions* never enter
    identity.
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
        "overlays": dump.get("overlays") or {},
        "extensions": dump.get("extensions") or {},
    }


def recipe_identity_hash(recipe: Recipe) -> str:
    """The authoritative recipe-side cache-identity hash (segmented join).

    This is the single source of truth for ``CacheKey.recipe_hash`` and every
    ``manifest.recipe_hash`` comparison. Replaced the flat
    ``sha256(to_canonical_bytes(recipe))`` in J.n.3.
    """
    return segmented_recipe_hash(segments_of(recipe))
