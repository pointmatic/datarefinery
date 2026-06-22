# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.6: extensions-namespace end-to-end.

Exercises the full stack — YAML loader → ``Recipe`` → validator → cache
identity — for the ``extensions:`` namespace:

- a recipe declaring ``extensions:`` round-trips through the on-disk loader
  without the unknown-top-level-key warning;
- an empty/absent ``extensions`` block leaves the cache identity byte-identical
  (additive landing, design Q5);
- a non-empty block moves identity (it enters canonical bytes);
- an extensions key the bound plugin declares via ``extension_keys()`` passes
  validation; an undeclared namespace/key is refused (check 28), even against a
  real built-in plugin that consumes no extensions.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import yaml

from datarefinery.cache.identity import compute_cache_key
from datarefinery.plugins.discovery import discover_plugins
from datarefinery.plugins.image_classification.plugin import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.loader import load
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import validate

# An extra-path plugin module that declares the image plugin's name plus a
# consumed extensions namespace — so a recipe carrying that namespace validates
# clean end-to-end through discovery.
_DECLARING_PLUGIN_SRC = """
# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
from typing import Any


class _DeclaringPlugin:
    name = "extky_demo"
    schema_version = 1
    supported_sections = frozenset({"Input", "Output", "Labels", "Splits"})

    def __init__(self) -> None:
        self.supported_operations: dict[str, Any] = {}

    def operation_factory(self, section: str, op_name: str) -> Any:
        return lambda record: record

    def is_stub(self) -> bool:
        return False

    def recommended_params(self, section: str, op_name: str) -> dict[str, Any]:
        return {}

    def extension_keys(self) -> dict[str, set[str]]:
        return {"extky_demo": {"experimental_vad", "hop_length"}}


PLUGIN = _DeclaringPlugin()
"""


def _recipe_dict(**overrides: Any) -> dict[str, Any]:
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
    return d


def _rh(recipe: Recipe) -> str:
    return compute_cache_key(recipe, {"train": "a" * 64}, seed=0).recipe_hash


def test_recipe_with_extensions_round_trips_through_the_loader(tmp_path: Path) -> None:
    path = tmp_path / "recipe.yaml"
    path.write_text(
        yaml.safe_dump(_recipe_dict(extensions={"extky_demo": {"experimental_vad": True}})),
        encoding="utf-8",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no spurious unknown-top-level-key warning
        recipe = load(path)
    assert recipe.extensions == {"extky_demo": {"experimental_vad": True}}


def test_empty_extensions_leaves_cache_identity_unchanged() -> None:
    baseline = _rh(Recipe.model_validate(_recipe_dict()))
    assert _rh(Recipe.model_validate(_recipe_dict(extensions={}))) == baseline


def test_nonempty_extensions_moves_cache_identity() -> None:
    baseline = _rh(Recipe.model_validate(_recipe_dict()))
    with_ext = _rh(
        Recipe.model_validate(_recipe_dict(extensions={"extky_demo": {"experimental_vad": True}}))
    )
    assert with_ext != baseline


def test_declared_extensions_validate_clean_via_discovered_plugin(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "declaring_plugin.py").write_text(_DECLARING_PLUGIN_SRC, encoding="utf-8")
    plugins = discover_plugins(extra_paths=[plugin_dir])
    plugin = plugins["extky_demo"]

    recipe = Recipe.model_validate(
        _recipe_dict(
            plugin="extky_demo",
            extensions={"extky_demo": {"experimental_vad": True, "hop_length": 256}},
        )
    )
    report = validate(recipe, plugin)
    check_28 = next(r for r in report.results if r.check_id == 28)
    assert check_28.status == "pass", check_28.message


def test_real_image_plugin_refuses_an_undeclared_extensions_block() -> None:
    recipe = Recipe.model_validate(
        _recipe_dict(extensions={"audio_classification": {"experimental_vad": True}})
    )
    report = validate(recipe, IMAGE_PLUGIN)
    assert not report.passed
    check_28 = next(r for r in report.results if r.check_id == 28)
    assert check_28.status == "fail"
    assert "audio_classification" in check_28.message
