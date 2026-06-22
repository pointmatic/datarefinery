# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.3: segmented recipe identity + plugin-surface representation.

The flat `Recipe` is partitioned into the frozen four segments
(`core`/`plugin`/`overlays`/`extensions`) for hashing/versioning/validation
dispatch — an *internal* partition; the author-facing recipe stays flat
(Option 1, confirmed at the J.n.3 design gate). Segmented canonical bytes
(the `join_stable` combiner) become the authoritative cache identity, which
is the one-time pre-1.0 invalidation. See the
[design memo](../../docs/specs/phase-j-recipe-architecture-design.md) Q1/Q3.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from datarefinery.recipe import segments as seg
from datarefinery.recipe.models import AudioSource, InputSource, Recipe


def _base_dict(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "schema_version": 3,
        "plugin": "image_classification",
        "Input": {
            "sources": [
                {"name": "train", "type": "image_folder", "path": "/data/train"},
            ]
        },
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
        "Splits": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}},
    }
    d.update(overrides)
    return d


def _recipe(**overrides: Any) -> Recipe:
    return Recipe.model_validate(_base_dict(**overrides))


# ---------------------------------------------------------------------------
# Field→segment coverage guard (the anti-footgun for Option 1)
# ---------------------------------------------------------------------------


def test_every_recipe_field_is_assigned_exactly_one_segment() -> None:
    assert set(seg.RECIPE_FIELD_SEGMENTS) == set(Recipe.model_fields)
    assert set(seg.RECIPE_FIELD_SEGMENTS.values()) <= set(seg.SEGMENT_ORDER)


def test_op_list_sections_live_in_the_plugin_segment() -> None:
    for section in (
        "Filters",
        "Generation",
        "Transformations",
        "Augmentations",
        "Featurizations",
        "Visualizations",
        "Sinks",
    ):
        assert seg.RECIPE_FIELD_SEGMENTS[section] == "plugin"


def test_structural_sections_live_in_core() -> None:
    for section in ("schema_version", "plugin", "seed", "Input", "Output", "Labels", "Splits"):
        assert seg.RECIPE_FIELD_SEGMENTS[section] == "core"


def test_variants_live_in_the_overlays_segment() -> None:
    assert seg.RECIPE_FIELD_SEGMENTS["variants"] == "overlays"


# ---------------------------------------------------------------------------
# segments_of partition
# ---------------------------------------------------------------------------


def test_segments_of_routes_input_to_core_and_filters_to_plugin() -> None:
    recipe = _recipe(Filters=[{"name": "f", "op": "drop_by_label", "params": {"labels": ["x"]}}])
    segs = seg.segments_of(recipe)
    assert "Input" in segs["core"] and "Filters" not in segs["core"]
    assert "Filters" in segs["plugin"] and "Input" not in segs["plugin"]


def test_segments_of_overlays_is_the_bare_variants_mapping() -> None:
    # At hash time variants are always stripped to {}, so overlays is empty →
    # the bare value, not a {"variants": {}} wrapper (additivity, Q3/Q5).
    recipe = _recipe()
    assert seg.segments_of(recipe)["overlays"] == {}


def test_segments_of_extensions_is_empty_until_jn6() -> None:
    assert seg.segments_of(_recipe())["extensions"] == {}


# ---------------------------------------------------------------------------
# recipe_identity_hash — the authoritative segmented cache identity
# ---------------------------------------------------------------------------


def test_identity_hash_is_the_segmented_join_over_segments_of() -> None:
    recipe = _recipe()
    assert seg.recipe_identity_hash(recipe) == seg.segmented_recipe_hash(seg.segments_of(recipe))


def test_identity_hash_is_deterministic() -> None:
    assert seg.recipe_identity_hash(_recipe()) == seg.recipe_identity_hash(_recipe())


def test_identity_hash_is_64_hex_chars() -> None:
    h = seg.recipe_identity_hash(_recipe())
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def test_core_field_change_moves_identity_hash() -> None:
    assert seg.recipe_identity_hash(_recipe()) != seg.recipe_identity_hash(_recipe(seed=99))


def test_plugin_segment_change_moves_identity_hash() -> None:
    plain = _recipe()
    with_filter = _recipe(
        Filters=[{"name": "f", "op": "drop_by_label", "params": {"labels": ["x"]}}]
    )
    assert seg.recipe_identity_hash(plain) != seg.recipe_identity_hash(with_filter)


def test_segmented_hash_differs_from_flat_dump_hash() -> None:
    # The combiner change *is* the one-time invalidation: the segmented join
    # is intentionally != the flat model_dump sha256.
    import hashlib

    from datarefinery.recipe.canonical import to_canonical_bytes

    recipe = _recipe()
    flat = hashlib.sha256(to_canonical_bytes(recipe)).hexdigest()
    assert seg.recipe_identity_hash(recipe) != flat


# ---------------------------------------------------------------------------
# Finding A — plugin-specific source fields (AudioSource.target_sample_rate)
# never enter an image recipe's canonical bytes.
# ---------------------------------------------------------------------------


def _audio_source_dict() -> dict[str, Any]:
    return {"name": "clips", "type": "audio_folder", "path": "/data", "target_sample_rate": 16000}


def test_audio_source_carries_target_sample_rate() -> None:
    recipe = _recipe(Input={"sources": [_audio_source_dict()]})
    src = recipe.Input.sources[0]
    assert isinstance(src, AudioSource)
    assert src.target_sample_rate == 16000


def test_image_source_rejects_target_sample_rate() -> None:
    # extra="forbid" on the base structurally enforces Finding A: an image
    # source literally cannot carry an audio-only field.
    with pytest.raises(ValidationError):
        InputSource.model_validate(
            {"name": "x", "type": "image_folder", "path": "/d", "target_sample_rate": 16000}
        )


def test_image_recipe_canonical_bytes_have_no_audio_fields() -> None:
    recipe = _recipe()
    core_bytes = seg._canonical_subbytes(seg.segments_of(recipe)["core"])
    assert b"target_sample_rate" not in core_bytes


def test_audio_recipe_canonical_bytes_do_carry_target_sample_rate() -> None:
    recipe = _recipe(Input={"sources": [_audio_source_dict()]})
    core_bytes = seg._canonical_subbytes(seg.segments_of(recipe)["core"])
    assert b"target_sample_rate" in core_bytes


def test_changing_target_sample_rate_moves_the_audio_recipe_hash() -> None:
    a = _recipe(Input={"sources": [{**_audio_source_dict(), "target_sample_rate": 16000}]})
    b = _recipe(Input={"sources": [{**_audio_source_dict(), "target_sample_rate": 22050}]})
    assert seg.recipe_identity_hash(a) != seg.recipe_identity_hash(b)
