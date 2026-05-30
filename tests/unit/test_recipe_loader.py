# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-1 edge-case tests for `recipe.loader`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from datarefinery.core.errors import RecipeError
from datarefinery.recipe.loader import (
    SUPPORTED_SCHEMA_VERSIONS,
    load,
    migrations,
)


def _minimal_recipe_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "image_classification",
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
        "Splits": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}, "seed": 7},
    }


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "recipe.yaml"
    text = payload if isinstance(payload, str) else yaml.safe_dump(payload)
    path.write_text(text, encoding="utf-8")
    return path


def test_load_minimal_recipe_succeeds(tmp_path: Path) -> None:
    path = _write(tmp_path, _minimal_recipe_dict())
    recipe = load(path)
    # Authored as v1; loader migrates to the latest schema_version on load.
    assert recipe.schema_version == 2
    assert recipe.plugin == "image_classification"


def test_missing_schema_version_raises(tmp_path: Path) -> None:
    data = _minimal_recipe_dict()
    del data["schema_version"]
    path = _write(tmp_path, data)
    with pytest.raises(RecipeError, match="missing required field 'schema_version'"):
        load(path)


def test_unrecognized_schema_version_raises_with_supported_list(tmp_path: Path) -> None:
    data = _minimal_recipe_dict()
    data["schema_version"] = 99
    path = _write(tmp_path, data)
    with pytest.raises(RecipeError) as info:
        load(path)
    msg = str(info.value)
    assert "unsupported schema_version=99" in msg
    assert "supported versions: [1, 2]" in msg
    assert "FR-1" in msg


def test_non_integer_schema_version_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "schema_version: 'one'\nplugin: x\n")
    with pytest.raises(RecipeError, match="'schema_version' must be an integer"):
        load(path)


def test_boolean_is_not_accepted_as_schema_version(tmp_path: Path) -> None:
    data = _minimal_recipe_dict()
    data["schema_version"] = True  # bool is technically int in Python; reject anyway
    path = _write(tmp_path, data)
    with pytest.raises(RecipeError, match="'schema_version' must be an integer"):
        load(path)


def test_malformed_yaml_raises_with_line_and_column(tmp_path: Path) -> None:
    path = _write(tmp_path, "schema_version: 1\nplugin: [unclosed\n")
    with pytest.raises(RecipeError) as info:
        load(path)
    msg = str(info.value)
    assert "malformed YAML" in msg
    assert "line " in msg
    assert "column " in msg


def test_non_mapping_root_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "- a\n- b\n")
    with pytest.raises(RecipeError, match="root must be a mapping"):
        load(path)


def test_unknown_top_level_key_emits_warning_and_then_fails_validation(
    tmp_path: Path,
) -> None:
    data = _minimal_recipe_dict()
    data["future_section"] = {"x": 1}
    path = _write(tmp_path, data)
    with pytest.warns(UserWarning, match="unknown top-level keys"):
        with pytest.raises(RecipeError, match="failed validation"):
            load(path)


def test_supported_schema_versions_constant() -> None:
    assert 1 in SUPPORTED_SCHEMA_VERSIONS
    assert 2 in SUPPORTED_SCHEMA_VERSIONS


def test_migrations_registry_has_v1_to_v2() -> None:
    """G15 / Story I.x.1: the v1->v2 migration chain is the entry point
    for the schema_version 2 reshape bundle."""
    assert (1, 2) in migrations
