# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-4 cache identity tests."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from datarefinery.cache.identity import CacheKey, compute_cache_key
from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.models import Recipe


def _base_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "Input": {
            "sources": [
                {"name": "train", "type": "image_folder", "path": "/data/train"},
                {"name": "val", "type": "image_folder", "path": "/data/val"},
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


def _recipe(**overrides: Any) -> Recipe:
    d = _base_dict()
    d.update(overrides)
    return Recipe.model_validate(d)


def test_short_returns_first_16_hex_of_recipe_hash() -> None:
    key = CacheKey(recipe_hash="a" * 64, input_hash="b" * 64, seed=0)
    assert key.short == "a" * 16


def test_cache_key_is_frozen() -> None:
    key = CacheKey(recipe_hash="a", input_hash="b", seed=1)
    with pytest.raises((AttributeError, Exception)):
        key.seed = 2  # type: ignore[misc]


def test_identical_inputs_yield_identical_key() -> None:
    recipe = _recipe()
    hashes = {"train": "a" * 64, "val": "b" * 64}
    a = compute_cache_key(recipe, hashes, seed=0)
    b = compute_cache_key(recipe, hashes, seed=0)
    assert a == b


def test_recipe_change_yields_different_recipe_hash() -> None:
    hashes = {"train": "a" * 64, "val": "b" * 64}
    a = compute_cache_key(_recipe(), hashes, seed=0)
    b = compute_cache_key(_recipe(seed=99), hashes, seed=0)
    assert a.recipe_hash != b.recipe_hash


def test_input_hash_change_yields_different_input_hash() -> None:
    recipe = _recipe()
    a = compute_cache_key(recipe, {"train": "a" * 64}, seed=0)
    b = compute_cache_key(recipe, {"train": "c" * 64}, seed=0)
    assert a.input_hash != b.input_hash


def test_seed_change_yields_different_key() -> None:
    recipe = _recipe()
    hashes = {"train": "a" * 64}
    a = compute_cache_key(recipe, hashes, seed=0)
    b = compute_cache_key(recipe, hashes, seed=1)
    assert a != b
    assert a.seed != b.seed
    # recipe_hash and input_hash unchanged across seed.
    assert a.recipe_hash == b.recipe_hash
    assert a.input_hash == b.input_hash


def test_input_hash_is_order_independent() -> None:
    recipe = _recipe()
    a_dict = {"train": "a" * 64, "val": "b" * 64}
    b_dict = {"val": "b" * 64, "train": "a" * 64}  # different insertion order
    a = compute_cache_key(recipe, a_dict, seed=0)
    b = compute_cache_key(recipe, b_dict, seed=0)
    assert a.input_hash == b.input_hash


def test_input_hash_includes_source_names() -> None:
    """Different source names with the same content hash must not collide."""
    recipe = _recipe()
    a = compute_cache_key(recipe, {"train": "a" * 64}, seed=0)
    b = compute_cache_key(recipe, {"validation": "a" * 64}, seed=0)
    assert a.input_hash != b.input_hash


def test_no_inputs_yields_stable_input_hash() -> None:
    recipe = _recipe()
    a = compute_cache_key(recipe, {}, seed=0)
    b = compute_cache_key(recipe, {}, seed=0)
    assert a == b


def test_adding_a_source_changes_input_hash() -> None:
    recipe = _recipe()
    a = compute_cache_key(recipe, {"train": "a" * 64}, seed=0)
    b = compute_cache_key(recipe, {"train": "a" * 64, "val": "b" * 64}, seed=0)
    assert a.input_hash != b.input_hash


def test_recipe_hash_matches_canonical_bytes_sha256() -> None:
    recipe = _recipe()
    expected = hashlib.sha256(to_canonical_bytes(recipe)).hexdigest()
    key = compute_cache_key(recipe, {}, seed=0)
    assert key.recipe_hash == expected


def test_recipe_hashes_are_64_hex_chars() -> None:
    key = compute_cache_key(_recipe(), {}, seed=0)
    assert len(key.recipe_hash) == 64
    assert len(key.input_hash) == 64
    assert all(c in "0123456789abcdef" for c in key.recipe_hash)
