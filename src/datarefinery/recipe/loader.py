# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-1 recipe loader and schema-version gate.

The schema-version gate runs before model validation so users see a
"this DataRefinery version doesn't speak that schema" message before any
field-shape diagnostics. The `migrations` registry is empty for v1 and
reserved for post-production cache-invalidating schema-version bumps
(see `project-essentials.md` "Cache identity is the reproducibility
contract — invalidations are ceremonious").
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from datarefinery.core.errors import RecipeError
from datarefinery.recipe.models import Recipe

SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})

# Reserved for post-production migrations from older schema versions.
# Keyed by (from_version, to_version); each callable mutates a recipe dict.
migrations: dict[tuple[int, int], Callable[[dict[str, Any]], dict[str, Any]]] = {}

KNOWN_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "plugin",
        "seed",
        "Input",
        "Output",
        "Labels",
        "SampleData",
        "InputContracts",
        "Filters",
        "Generation",
        "Splits",
        "Transformations",
        "Augmentations",
        "Featurizations",
        "OutputExpectations",
        "Visualizations",
        "variants",
    }
)


def load(path: Path) -> Recipe:
    """Load a YAML recipe with the schema-version gate as the first check.

    Raises `RecipeError` for malformed YAML (with line/column), missing or
    unrecognized `schema_version`, and any subsequent pydantic validation
    failure. Emits a `UserWarning` for unknown top-level keys before the
    inevitable hard error from `Recipe`'s `extra="forbid"` config.
    """
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        line, col = _yaml_error_location(exc)
        raise RecipeError(f"malformed YAML in {path} at line {line}, column {col}: {exc}") from exc

    if not isinstance(data, dict):
        raise RecipeError(f"recipe at {path}: root must be a mapping; got {type(data).__name__}")

    schema_version = data.get("schema_version")
    if schema_version is None:
        raise RecipeError(
            f"recipe at {path}: missing required field 'schema_version'; "
            f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise RecipeError(
            f"recipe at {path}: 'schema_version' must be an integer, got "
            f"{type(schema_version).__name__}"
        )
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise RecipeError(
            f"recipe at {path}: unsupported schema_version={schema_version}; "
            f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}; "
            f"see features.md FR-1 for the documented migration path"
        )

    unknown = sorted(set(data.keys()) - KNOWN_TOP_LEVEL_KEYS)
    if unknown:
        warnings.warn(
            f"recipe at {path}: unknown top-level keys {unknown}; recipes are "
            f"not forward-compatible. Update DataRefinery to a version that "
            f"recognizes these keys.",
            UserWarning,
            stacklevel=2,
        )

    try:
        return Recipe.model_validate(data)
    except ValidationError as exc:
        raise RecipeError(f"recipe at {path} failed validation: {exc}") from exc


def _yaml_error_location(exc: yaml.YAMLError) -> tuple[int, int]:
    mark: Any = getattr(exc, "problem_mark", None)
    if mark is None:
        return 0, 0
    return int(mark.line) + 1, int(mark.column) + 1
