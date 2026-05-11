# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""End-to-end exit-code tests for the CLI wrapper.

Verifies that a deliberate raise of each `DataRefineryError` subclass through
`main_entry` produces the documented exit code, and that uncaught exceptions
exit 2.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def _run_raising(import_stmt: str, raise_stmt: str) -> subprocess.CompletedProcess[str]:
    """Spawn a subprocess that monkey-patches `app` to raise, then exits."""
    code = (
        f"{import_stmt}\n"
        "import datarefinery.cli.app as appmod\n"
        "def _raising_app(*args, **kwargs):\n"
        f"    {raise_stmt}\n"
        "appmod.app = _raising_app\n"
        "appmod.main_entry()\n"
    )
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)


@pytest.mark.parametrize(
    ("error_class", "expected"),
    [
        ("RecipeError", 1),
        ("ValidationError", 1),
        ("ContractError", 1),
        ("MaterializeError", 1),
        ("PluginError", 2),
        ("CacheError", 2),
    ],
)
def test_cli_maps_each_subclass_through_main_entry(error_class: str, expected: int) -> None:
    result = _run_raising(
        f"from datarefinery.core.errors import {error_class}",
        f"raise {error_class}('boom')",
    )
    assert result.returncode == expected, (
        f"expected {expected} got {result.returncode}\nstderr={result.stderr!r}"
    )


def test_cli_uncaught_exception_exits_2() -> None:
    result = _run_raising("", "raise RuntimeError('oops')")
    assert result.returncode == 2, result.stderr


def test_cli_keyboard_interrupt_exits_130() -> None:
    result = _run_raising("", "raise KeyboardInterrupt()")
    assert result.returncode == 130, result.stderr


def test_cli_help_still_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "datarefinery", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "datarefinery" in result.stdout.lower()


def test_cli_version_still_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "datarefinery", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
