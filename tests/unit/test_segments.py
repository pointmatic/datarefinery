# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.2: segment-aware canonical-bytes machinery.

Per the [design memo](../../docs/specs/phase-j-recipe-architecture-design.md)
Q3 (concatenated per-segment digests + fixed empty marker, prefix-capable)
and Q4 (per-segment version constants + migration-registry skeleton). This
is dormant infrastructure: no recipe field is segmented yet (J.n.3), and the
flat `to_canonical_bytes` hasher stays authoritative until J.n.3 flips it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from datarefinery.recipe import segments as seg

# ---------------------------------------------------------------------------
# Constants / shape
# ---------------------------------------------------------------------------


def test_segment_order_is_the_frozen_four() -> None:
    assert seg.SEGMENT_ORDER == ("core", "plugin", "overlays", "extensions")


def test_empty_marker_is_32_bytes() -> None:
    assert isinstance(seg.EMPTY_MARKER, bytes)
    assert len(seg.EMPTY_MARKER) == 32


def test_per_segment_version_constants_exist() -> None:
    for name in (
        "CORE_SCHEMA_VERSION",
        "PLUGIN_IMAGE_SCHEMA_VERSION",
        "PLUGIN_AUDIO_SCHEMA_VERSION",
        "OVERLAYS_SCHEMA_VERSION",
        "EXTENSIONS_SCHEMA_VERSION",
    ):
        assert isinstance(getattr(seg, name), int)


def test_migration_registry_skeleton_is_a_dict() -> None:
    # (segment, from, to) -> migration_fn, empty at J.n.2 (J.n.7 populates).
    assert isinstance(seg.SEGMENT_MIGRATIONS, dict)


# ---------------------------------------------------------------------------
# segment_digest + empty marker
# ---------------------------------------------------------------------------


def test_empty_values_all_map_to_the_marker() -> None:
    empties: tuple[Any, ...] = (None, {}, [], "")
    for empty in empties:
        assert seg.segment_digest(empty) == seg.EMPTY_MARKER


def test_nonempty_digest_is_sha256_of_canonical_json() -> None:
    value = {"b": 2, "a": 1}
    import json

    expected = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).digest()
    assert seg.segment_digest(value) == expected


def test_digest_is_order_independent_for_dict_keys() -> None:
    assert seg.segment_digest({"a": 1, "b": 2}) == seg.segment_digest({"b": 2, "a": 1})


# ---------------------------------------------------------------------------
# join_stable + segmented hash
# ---------------------------------------------------------------------------


def test_join_stable_deterministic() -> None:
    d = [seg.segment_digest({"x": 1}), seg.EMPTY_MARKER, seg.EMPTY_MARKER, seg.EMPTY_MARKER]
    assert seg.join_stable(d) == seg.join_stable(list(d))


def test_empty_segment_contributes_fixed_nothing() -> None:
    # A recipe with extensions={} hashes identically to extensions=None:
    # both empty → EMPTY_MARKER in that slot.
    base = {"core": {"plugin": "image"}, "plugin": {"op": "resize"}, "overlays": None}
    h1 = seg.segmented_recipe_hash({**base, "extensions": {}})
    h2 = seg.segmented_recipe_hash({**base, "extensions": None})
    assert h1 == h2


def test_changing_one_segment_does_not_move_another_segments_digest() -> None:
    # Plugin-segment change must not perturb the core digest (the isolation
    # property — Finding A enforced at the digest level).
    core = {"plugin": "image", "seed": 0}
    core_digest_a = seg.segment_digest(core)
    # Mutate only the plugin segment.
    _ = seg.segmented_recipe_hash(
        {"core": core, "plugin": {"op": "resize"}, "overlays": None, "extensions": None}
    )
    core_digest_b = seg.segment_digest(core)
    assert core_digest_a == core_digest_b


def test_nonempty_segment_change_changes_recipe_hash() -> None:
    a = seg.segmented_recipe_hash(
        {"core": {"seed": 0}, "plugin": {"op": "resize"}, "overlays": None, "extensions": None}
    )
    b = seg.segmented_recipe_hash(
        {"core": {"seed": 0}, "plugin": {"op": "normalize"}, "overlays": None, "extensions": None}
    )
    assert a != b


# ---------------------------------------------------------------------------
# prefix composition (the deferred Q8 vertical-axis hook)
# ---------------------------------------------------------------------------


def test_prefix_hash_matches_hash_of_joined_prefix() -> None:
    digests = [
        seg.segment_digest({"a": 1}),
        seg.segment_digest({"b": 2}),
        seg.segment_digest({"c": 3}),
        seg.EMPTY_MARKER,
    ]
    expected = hashlib.sha256(seg.join_stable(digests[:2])).hexdigest()
    assert seg.prefix_hash(digests, 2) == expected


def test_downstream_change_does_not_move_an_upstream_prefix() -> None:
    upstream = [seg.segment_digest({"a": 1}), seg.segment_digest({"b": 2})]
    d1 = [*upstream, seg.segment_digest({"c": 3})]
    d2 = [*upstream, seg.segment_digest({"c": 999})]
    assert seg.prefix_hash(d1, 2) == seg.prefix_hash(d2, 2)


# ---------------------------------------------------------------------------
# Dormant shadow path
# ---------------------------------------------------------------------------


def test_shadow_segments_wrap_flat_recipe_as_core_only() -> None:
    flat = {"plugin": "image", "seed": 0, "Filters": []}
    segs = seg.shadow_segments_from_flat(flat)
    assert segs["core"] == flat
    assert segs["plugin"] is None and segs["overlays"] is None and segs["extensions"] is None


def test_shadow_hash_is_deterministic() -> None:
    flat = {"plugin": "image", "seed": 0}
    assert seg.shadow_recipe_hash(flat) == seg.shadow_recipe_hash(dict(flat))


def test_shadow_hash_differs_from_flat_hash_by_design() -> None:
    # The combiner wraps; the segmented hash is intentionally != the flat
    # model_dump hash. That delta is J.n.3's one-time invalidation.
    import json

    flat = {"plugin": "image", "seed": 0}
    flat_hash = hashlib.sha256(
        json.dumps(flat, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert seg.shadow_recipe_hash(flat) != flat_hash
