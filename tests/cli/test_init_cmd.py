# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for ``datarefinery init`` (Story D.d)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image
from typer.testing import CliRunner

from datarefinery.cli.app import app
from datarefinery.core.errors import PluginError

runner = CliRunner()


def _has_lmentry_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("lmentry") is not None


def _build_image_folder(
    root: Path,
    *,
    classes: tuple[str, ...] = ("cats", "dogs"),
    per_class: int = 4,
    size: int = 8,
) -> Path:
    rng = np.random.default_rng(0)
    for cls in classes:
        cls_dir = root / cls
        cls_dir.mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            arr = rng.integers(0, 255, (size, size, 3), dtype=np.uint8)
            Image.fromarray(arr).save(cls_dir / f"{cls}_{i:03d}.png")
    return root


def test_init_writes_a_recipe_file(tmp_path: Path) -> None:
    inp = _build_image_folder(tmp_path / "data")
    out = tmp_path / "recipe.yaml"
    result = runner.invoke(
        app, ["init", "--input", str(inp), "--output", str(out)]
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "image_classification" in text
    assert "schema_version: 1" in text


def test_init_then_validate_round_trip(tmp_path: Path) -> None:
    """The scaffolded recipe parses cleanly through ``datarefinery validate``."""
    inp = _build_image_folder(tmp_path / "data")
    out = tmp_path / "recipe.yaml"
    init_result = runner.invoke(
        app, ["init", "--input", str(inp), "--output", str(out)]
    )
    assert init_result.exit_code == 0, init_result.stdout

    validate_result = runner.invoke(app, ["validate", str(out)])
    assert validate_result.exit_code == 0, validate_result.stdout
    assert "passed" in validate_result.stdout


def test_init_creates_parent_directory(tmp_path: Path) -> None:
    inp = _build_image_folder(tmp_path / "data")
    out = tmp_path / "nested" / "subdir" / "recipe.yaml"
    result = runner.invoke(
        app, ["init", "--input", str(inp), "--output", str(out)]
    )
    assert result.exit_code == 0
    assert out.exists()


def test_init_enhance_without_lmentry_raises_plugin_error(tmp_path: Path) -> None:
    """``--enhance`` with no `lmentry` raises ``PluginError`` with the
    documented install snippet. CliRunner doesn't route through
    ``main_entry`` so we assert on the propagated exception; exit-code
    mapping is covered separately by ``tests/cli/test_exit_codes.py``."""
    inp = _build_image_folder(tmp_path / "data")
    out = tmp_path / "recipe.yaml"

    # If `lmentry` happens to be installed in this environment, skip:
    # the CLI verb does not need to exercise the lazy-import path here,
    # the scaffolder already covers it in ``tests/unit/test_scaffolder.py``.
    if "lmentry" in sys.modules or _has_lmentry_installed():
        import pytest

        pytest.skip("lmentry is installed; test covers the missing-extra path")

    result = runner.invoke(
        app,
        ["init", "--input", str(inp), "--output", str(out), "--enhance"],
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, PluginError)
    msg = str(result.exception)
    assert "lmentry" in msg
    assert "datarefinery[llm]" in msg
    assert not out.exists()  # scaffolder must not write a partial recipe


def test_init_refuses_non_image_plugin(tmp_path: Path) -> None:
    inp = _build_image_folder(tmp_path / "data")
    out = tmp_path / "recipe.yaml"
    result = runner.invoke(
        app,
        [
            "init",
            "--input",
            str(inp),
            "--output",
            str(out),
            "--plugin",
            "tabular",
        ],
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, PluginError)
    assert "v1" in str(result.exception)
    assert not out.exists()


def test_init_missing_input_dir_is_usage_error(tmp_path: Path) -> None:
    out = tmp_path / "recipe.yaml"
    result = runner.invoke(
        app,
        [
            "init",
            "--input",
            str(tmp_path / "does-not-exist"),
            "--output",
            str(out),
        ],
    )
    assert result.exit_code != 0
    assert not out.exists()
