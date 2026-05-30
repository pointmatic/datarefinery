# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-1 recipe loader and schema-version gate.

The schema-version gate runs before model validation so users see a
"this DataRefinery version doesn't speak that schema" message before any
field-shape diagnostics. v1 recipes are auto-migrated to the v2 shape
via the chain registered in :mod:`datarefinery.recipe.migrations`
(Phase I bundle 4 — Stories I.x.1/I.x.2/I.x.3); the model itself only
accepts the latest shape. See ``project-essentials.md`` "Cache
identity is the reproducibility contract — invalidations are
ceremonious" for the bump ceremony.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from datarefinery.core.errors import RecipeError
from datarefinery.recipe.migrations import v1_to_v2
from datarefinery.recipe.models import Recipe

LATEST_SCHEMA_VERSION: int = 2
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2})

# Each migration key (from_version, to_version) maps to a callable that
# rewrites a recipe dict in place of any v<from> shape with the
# equivalent v<to> shape. The chain is registered in
# :mod:`datarefinery.recipe.migrations`.
migrations: dict[tuple[int, int], Callable[[dict[str, Any]], dict[str, Any]]] = {
    (1, 2): v1_to_v2,
}

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
        "Sinks",
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

    data = _migrate_to_latest(data, schema_version)

    try:
        return Recipe.model_validate(data)
    except ValidationError as exc:
        raise RecipeError(f"recipe at {path} failed validation: {exc}") from exc


def _migrate_to_latest(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Apply each registered migration step until ``data`` is at the
    latest supported schema_version. The chain is intentionally simple
    (one-hop today, single composed callable per pair); a multi-hop
    chain becomes useful when schema_version 3 lands."""
    current = from_version
    while current != LATEST_SCHEMA_VERSION:
        step = migrations.get((current, current + 1))
        if step is None:
            # Should never trigger today (only valid versions reach here),
            # but guards future gaps in the chain.
            raise RecipeError(
                f"no migration registered from schema_version={current} to "
                f"schema_version={current + 1}"
            )
        data = step(data)
        current += 1
    return data


def _yaml_error_location(exc: yaml.YAMLError) -> tuple[int, int]:
    mark: Any = getattr(exc, "problem_mark", None)
    if mark is None:
        return 0, 0
    return int(mark.line) + 1, int(mark.column) + 1
