# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for the ``datarefinery`` CLI entry point."""

from __future__ import annotations

from typer.testing import CliRunner

from datarefinery import __version__
from datarefinery.cli.app import app

runner = CliRunner()


def test_version_flag_exits_zero_and_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_flag_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "datarefinery" in result.stdout.lower()
