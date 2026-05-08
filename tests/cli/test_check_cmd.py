# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for ``datarefinery check``."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from datarefinery.cli.app import app
from datarefinery.core.errors import PluginError

runner = CliRunner()


def test_check_exits_zero_on_healthy_environment() -> None:
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0


def test_check_lists_installed_plugins() -> None:
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "image_classification" in result.stdout
    assert "tabular" in result.stdout
    assert "text" in result.stdout


def test_check_renders_environment_section() -> None:
    result = runner.invoke(app, ["check"])
    assert "DataRefinery version" in result.stdout
    assert "Python version" in result.stdout
    assert "Plugin entry-point group" in result.stdout


def test_check_lists_optional_extras_and_accelerators() -> None:
    result = runner.invoke(app, ["check"])
    assert "Optional extras" in result.stdout
    assert "Accelerators" in result.stdout
    assert "lmentry" in result.stdout


def test_check_exits_two_on_plugin_discovery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery failure → soundness failure → exit 2 (system error)."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise PluginError("forced discovery failure for tests")

    monkeypatch.setattr("datarefinery.core.check.discover_plugins", boom)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 2
    assert "forced discovery failure" in result.stdout


def test_check_does_not_require_a_recipe() -> None:
    """``check`` is a static-context verb — invoking it with no recipe and
    no other arguments succeeds."""
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
