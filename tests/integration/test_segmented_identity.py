# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.3: segmented cache identity — Finding A end-to-end.

Exercises the authoritative cache-identity surface (``compute_cache_key`` →
``recipe_identity_hash`` → ``segments_of`` → ``join_stable``) and pins the
property that *resolves J.n Finding A*: a plugin-specific source field
(``AudioSource.target_sample_rate``) can never enter an image recipe's
canonical bytes, so an audio-plugin-surface change leaves every image
recipe's cache identity byte-for-byte unchanged.

The audio recipe is built directly (the audio plugin proper lands in J.o);
identity hashing operates on the recipe model, not the plugin registry.
"""

from __future__ import annotations

from typing import Any

from datarefinery.cache.identity import compute_cache_key
from datarefinery.recipe.models import Recipe


def _image_recipe(**overrides: Any) -> Recipe:
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
    }
    d.update(overrides)
    return Recipe.model_validate(d)


def _audio_recipe(*, target_sample_rate: int = 16000, mel_bins: int = 64) -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 3,
            "plugin": "audio_classification",
            "seed": 7,
            "Input": {
                "sources": [
                    {
                        "name": "clips",
                        "type": "audio_folder",
                        "path": "/data/clips",
                        "target_sample_rate": target_sample_rate,
                    }
                ]
            },
            "Output": {
                "record_schema": {"audio": {"dtype": "float32"}, "label": {"dtype": "int32"}}
            },
            "Labels": {
                "field": "label",
                "source": {"kind": "derived", "derivation": "parent_directory_name"},
            },
            "Splits": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}},
            "Featurizations": [
                {
                    "name": "mel",
                    "inputs": ["audio"],
                    "output_field": "spectrogram",
                    "op": "log_mel_spectrogram",
                    "params": {"n_mels": mel_bins},
                }
            ],
        }
    )


def _rh(recipe: Recipe) -> str:
    return compute_cache_key(recipe, {"train": "a" * 64}, seed=0).recipe_hash


# Pinned segmented identity of the representative image recipe above. **Do not
# edit** without consciously signing off on a cache invalidation (see
# project-essentials.md). A future audio-plugin-surface change that moves this
# value is a Finding-A regression — audio fields must never touch image bytes.
_PINNED_IMAGE_HASH = "a7cd17b27ebfda7eec7ac0e00a61fdef16d4b49dc5a931f17facdcea411dd46f"
_PINNED_AUDIO_HASH = "655339533002df6b7d2aafa4feedd51b977d2a98c9cacc18d71b8b2f38f658b8"


def test_image_recipe_identity_is_pinned() -> None:
    assert _rh(_image_recipe()) == _PINNED_IMAGE_HASH


def test_audio_recipe_identity_is_pinned() -> None:
    assert _rh(_audio_recipe()) == _PINNED_AUDIO_HASH


def test_image_identity_unchanged_across_an_audio_surface_change() -> None:
    # Changing the audio plugin surface (a new sample rate, a different mel
    # featurization) must not perturb the image recipe's identity at all.
    image_before = _rh(_image_recipe())
    _ = _rh(_audio_recipe(target_sample_rate=22050, mel_bins=128))
    assert _rh(_image_recipe()) == image_before == _PINNED_IMAGE_HASH


def test_audio_identity_moves_only_on_audio_segment_changes() -> None:
    base = _rh(_audio_recipe())
    # target_sample_rate (audio-only source field) → identity moves.
    assert _rh(_audio_recipe(target_sample_rate=22050)) != base
    # audio featurization op (plugin segment) → identity moves.
    assert _rh(_audio_recipe(mel_bins=128)) != base
    # The image recipe is wholly unaffected by either.
    assert _rh(_image_recipe()) != base


def test_image_recipe_canonical_bytes_carry_no_audio_field() -> None:
    from datarefinery.recipe.segments import _canonical_subbytes, segments_of

    for segment in segments_of(_image_recipe()).values():
        assert b"target_sample_rate" not in _canonical_subbytes(segment)
