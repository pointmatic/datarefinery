# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.m: the package version has exactly one source of truth.

`src/datarefinery/__init__.py.__version__` is canonical; Hatchling reads it
at build time via `[tool.hatch.version]`. `pyproject.toml` therefore declares
`version` as `dynamic` and carries no static literal. These tests trip if a
future change re-introduces a second hand-maintained version (the J.l drift:
`pyproject.toml` said 0.20.0 while `__init__.py` said 0.19.0, so
`datarefinery --version` and the wheel metadata disagreed).
"""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

import datarefinery

DIST_NAME = "ml-datarefinery"
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _pyproject() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_version_literal_is_well_formed() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+([.-].+)?", datarefinery.__version__), (
        datarefinery.__version__
    )


def test_pyproject_declares_version_dynamic() -> None:
    project = _pyproject()["project"]
    assert "version" in project.get("dynamic", []), (
        "[project].dynamic must list 'version' so Hatchling sources it from "
        "__init__.py — the single source of truth (Story J.m)."
    )
    assert "version" not in project, (
        "[project].version must NOT be a static literal — it drifted from "
        "__init__.py once (Story J.l). Keep the version in __init__.py only."
    )


def test_hatch_version_source_points_at_init() -> None:
    hatch_version = _pyproject()["tool"]["hatch"]["version"]
    assert hatch_version["path"] == "src/datarefinery/__init__.py"


def test_installed_metadata_matches_source_version() -> None:
    # CI installs the package fresh, so the wheel metadata reflects the current
    # __version__. A stale local *editable* install can lag — reprovision via
    # `pyve` (reinstall) so the env mirrors source before relying on this.
    try:
        installed = metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        pytest.skip(f"{DIST_NAME} is not installed in this environment")
    assert installed == datarefinery.__version__, (
        f"installed {DIST_NAME}=={installed} != source "
        f"__version__=={datarefinery.__version__}; reinstall to refresh "
        "metadata (stale editable install)."
    )
