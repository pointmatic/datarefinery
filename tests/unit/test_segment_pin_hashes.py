# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.7: per-segment canonical-hash pin gate.

Where ``test_canonical_hash_pin.py`` pins one *whole-recipe* identity hash,
this file pins the **per-segment** digests of representative fixtures so the
isolation property is *enforced by CI, not merely asserted*: an unexpected move
of any single segment's digest is a blocking failure that forces a conscious,
per-segment ``schema_version`` bump + migration (design Q4/Q7; the
``project-essentials.md`` cache-identity ceremony).

The pins double as the J.n.5 (overlays) and J.n.6 (extensions) additivity
gates: an empty ``overlays``/``extensions`` segment must hash to the
``EMPTY_MARKER`` forever, so those mechanisms can never retroactively perturb a
recipe that doesn't use them.

**Updating a pin (legitimately).** A pin moves only when you are deliberately
shipping a cache-invalidating change to that segment. Bump the matching
per-segment version constant in ``recipe.segments``, register the migration,
and update the pinned digest in the SAME commit — the reviewer signing that
diff signs off on the invalidation.
"""

from __future__ import annotations

from typing import Any

from datarefinery.recipe import segments as seg
from datarefinery.recipe.models import Recipe


def _image(**overrides: Any) -> Recipe:
    d: dict[str, Any] = {
        "schema_version": 3,
        "plugin": "image_classification",
        "seed": 7,
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]},
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
        "Filters": [{"name": "f", "op": "drop_by_label", "params": {"labels": ["x"]}}],
    }
    d.update(overrides)
    return Recipe.model_validate(d)


def _audio(**overrides: Any) -> Recipe:
    d: dict[str, Any] = {
        "schema_version": 3,
        "plugin": "audio_classification",
        "seed": 7,
        "Input": {
            "sources": [
                {
                    "name": "clips",
                    "type": "audio_folder",
                    "path": "/data/clips",
                    "target_sample_rate": 16000,
                }
            ]
        },
        "Output": {"record_schema": {"audio": {"dtype": "float32"}, "label": {"dtype": "int32"}}},
        "Labels": {
            "field": "label",
            "source": {"kind": "derived", "derivation": "parent_directory_name"},
        },
        "Splits": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}},
        "Featurizations": [
            {
                "name": "mel",
                "inputs": ["audio"],
                "output_field": "spec",
                "op": "log_mel_spectrogram",
                "params": {"n_mels": 64},
            }
        ],
    }
    d.update(overrides)
    return Recipe.model_validate(d)


def _digest(recipe: Recipe, segment: str) -> str:
    return seg.segment_digest(seg.segments_of(recipe)[segment]).hex()


# Per-segment pinned digests. **Do not edit** without a deliberate per-segment
# invalidation (bump the segment's version constant + register a migration in
# the same commit). See project-essentials.md cache-identity ceremony.
_EMPTY_MARKER_HEX = "26f35dce366b24a33a3951162c30ea2c3e72bfe307fd1c0a480fc584245649f7"

_IMAGE_CORE = "db7ea9254a12fdb8a509334053e61036da0988f12dcb73ab229d7e162a66fef2"
_IMAGE_PLUGIN = "f35ccd20913849d3192fbded3cd9262240ae8e4f84b97d1ba6a257982195ab80"

_AUDIO_CORE = "039925e0b3ad1ecb261d36984983b2d0e254adcc40d83382ab8b4bf9763089d3"
_AUDIO_PLUGIN = "0a32f5152bae762cefd2215c191ff2b99d8567b66d2d3e7c8262be67db1310cb"


def test_empty_marker_is_pinned() -> None:
    # The fixed "empty segment" digest is part of the contract: every recipe
    # that omits overlays/extensions hashes them to this value.
    assert seg.EMPTY_MARKER.hex() == _EMPTY_MARKER_HEX


# ---------------------------------------------------------------------------
# Image fixture — per-segment pins
# ---------------------------------------------------------------------------


def test_image_core_digest_is_pinned() -> None:
    assert _digest(_image(), "core") == _IMAGE_CORE


def test_image_plugin_digest_is_pinned() -> None:
    assert _digest(_image(), "plugin") == _IMAGE_PLUGIN


def test_image_overlays_and_extensions_are_empty_markers() -> None:
    assert _digest(_image(), "overlays") == _EMPTY_MARKER_HEX
    assert _digest(_image(), "extensions") == _EMPTY_MARKER_HEX


# ---------------------------------------------------------------------------
# Audio fixture — per-segment pins (Finding A boundary)
# ---------------------------------------------------------------------------


def test_audio_core_digest_is_pinned() -> None:
    assert _digest(_audio(), "core") == _AUDIO_CORE


def test_audio_plugin_digest_is_pinned() -> None:
    assert _digest(_audio(), "plugin") == _AUDIO_PLUGIN


# ---------------------------------------------------------------------------
# Cross-plugin isolation — Finding A enforced at segment granularity
# ---------------------------------------------------------------------------


def test_image_segments_unmoved_by_an_audio_surface_change() -> None:
    # Changing the audio plugin surface must not move ANY image segment digest.
    _ = _audio(
        Input={
            "sources": [
                {
                    "name": "clips",
                    "type": "audio_folder",
                    "path": "/data/clips",
                    "target_sample_rate": 22050,
                }
            ]
        }
    )
    assert _digest(_image(), "core") == _IMAGE_CORE
    assert _digest(_image(), "plugin") == _IMAGE_PLUGIN


def test_audio_segments_unmoved_by_an_image_surface_change() -> None:
    _ = _image(Filters=[{"name": "g", "op": "drop_by_label", "params": {"labels": ["y", "z"]}}])
    assert _digest(_audio(), "core") == _AUDIO_CORE
    assert _digest(_audio(), "plugin") == _AUDIO_PLUGIN


# ---------------------------------------------------------------------------
# Overlays (J.n.5) + extensions (J.n.6) additivity, pinned
# ---------------------------------------------------------------------------


def test_unused_overlay_does_not_move_identity_or_any_segment() -> None:
    from datarefinery.recipe.overlays import apply_overlays

    plain = _image()
    # Overlay *definitions* are stripped by the canonical pre-hash pass
    # (`apply_overlays(recipe, None)`), so a recipe carrying an unused overlay
    # resolves to byte-identical identity — and every per-segment digest, the
    # overlays segment included, is unchanged.
    resolved = apply_overlays(_image(overlays={"no_aug": {"Augmentations": []}}), None)
    assert seg.recipe_identity_hash(resolved) == seg.recipe_identity_hash(plain)
    for segment in seg.SEGMENT_ORDER:
        assert _digest(resolved, segment) == _digest(plain, segment)


def test_extensions_perturb_only_the_extensions_segment() -> None:
    with_ext = _image(extensions={"image_classification": {"experimental_knob": 1}})
    assert _digest(with_ext, "core") == _IMAGE_CORE
    assert _digest(with_ext, "plugin") == _IMAGE_PLUGIN
    assert _digest(with_ext, "overlays") == _EMPTY_MARKER_HEX
    assert _digest(with_ext, "extensions") != _EMPTY_MARKER_HEX
