# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.6: the sanctioned ``extensions:`` namespace + plugin
extension-key declaration.

Per design memo Q5: a single top-level ``extensions: {<namespace>: {<key>:
<value>}}`` block where pydantic's ``extra="forbid"`` is relaxed *only inside*
the namespace; everywhere else stays strict. Plugins enumerate the extension
keys they consume via ``extension_keys()``; the validator (check 28) refuses
any namespace/key not declared by the recipe's bound plugin. The namespace
enters cache identity only when non-empty (additivity — covered in
``test_recipe_segmentation.py``). Extensions carry *declarative parameters*
only; recipe-activated code is explicitly out of scope (spike memo § 6).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import validate


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
# Model: extensions field shape + relaxation scope
# ---------------------------------------------------------------------------


def test_recipe_defaults_extensions_to_empty_mapping() -> None:
    assert _recipe().extensions == {}


def test_extensions_namespace_accepts_arbitrary_keys() -> None:
    # `extra="forbid"` is relaxed *inside* a namespace: arbitrary keys/values
    # are accepted there (the whole point of the experimental-config escape).
    recipe = _recipe(extensions={"audio_classification": {"experimental_vad": True, "k": [1, 2]}})
    assert recipe.extensions["audio_classification"]["experimental_vad"] is True
    assert recipe.extensions["audio_classification"]["k"] == [1, 2]


def test_extra_forbid_still_strict_outside_extensions() -> None:
    # Relaxation is scoped to the extensions namespace only — an unknown
    # top-level recipe key is still rejected.
    with pytest.raises(ValidationError):
        _recipe(some_unknown_top_level_key=123)


# ---------------------------------------------------------------------------
# Plugin extension-key declaration
# ---------------------------------------------------------------------------


def test_builtin_plugins_declare_no_extension_keys_by_default() -> None:
    from datarefinery.plugins.image_classification.plugin import PLUGIN

    assert PLUGIN.extension_keys() == {}


# ---------------------------------------------------------------------------
# Validator check 28 — undeclared extension namespace/key refused
# ---------------------------------------------------------------------------


class _ExtPlugin:
    """Minimal Plugin-protocol object declaring a set of extension keys."""

    def __init__(self, declared: dict[str, set[str]] | None = None) -> None:
        self.name = "image_classification"
        self.schema_version = 1
        self.supported_sections = frozenset({"Input", "Output", "Labels", "Splits", "Filters"})
        self.supported_operations: dict[str, Any] = {}
        self._declared = declared or {}

    def extension_keys(self) -> dict[str, set[str]]:
        return self._declared

    def recommended_params(self, section: str, op_name: str) -> dict[str, Any]:
        del section, op_name
        return {}

    def operation_factory(self, section: str, op_name: str) -> Any:
        del section, op_name
        return lambda record: record

    def is_stub(self) -> bool:
        return False


def _check_28(recipe: Recipe, plugin: _ExtPlugin) -> Any:
    report = validate(recipe, plugin)
    return next(r for r in report.results if r.check_id == 28)


def test_empty_extensions_passes_check_28_without_consulting_plugin() -> None:
    result = _check_28(_recipe(), _ExtPlugin())
    assert result.status == "pass"


def test_declared_namespace_and_keys_pass_check_28() -> None:
    plugin = _ExtPlugin({"audio_classification": {"experimental_vad", "hop"}})
    recipe = _recipe(extensions={"audio_classification": {"experimental_vad": True}})
    assert _check_28(recipe, plugin).status == "pass"


def test_undeclared_namespace_fails_check_28() -> None:
    plugin = _ExtPlugin({"audio_classification": {"experimental_vad"}})
    recipe = _recipe(extensions={"mystery_ns": {"experimental_vad": True}})
    result = _check_28(recipe, plugin)
    assert result.status == "fail"
    assert "mystery_ns" in result.message


def test_undeclared_key_within_declared_namespace_fails_check_28() -> None:
    plugin = _ExtPlugin({"audio_classification": {"experimental_vad"}})
    recipe = _recipe(extensions={"audio_classification": {"unknown_knob": 1}})
    result = _check_28(recipe, plugin)
    assert result.status == "fail"
    assert "unknown_knob" in result.message


def test_check_28_reports_every_offending_key() -> None:
    plugin = _ExtPlugin({"audio_classification": {"experimental_vad"}})
    recipe = _recipe(extensions={"audio_classification": {"bad_one": 1, "bad_two": 2}})
    result = _check_28(recipe, plugin)
    assert result.status == "fail"
    assert "bad_one" in result.message and "bad_two" in result.message
