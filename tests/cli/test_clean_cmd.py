# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for ``datarefinery clean`` (Story D.i, FR-21)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from typer.testing import CliRunner

from datarefinery.cache.layout import TMP_DIR_NAME, instances_root
from datarefinery.cli.app import app
from datarefinery.core.errors import CacheError

runner = CliRunner()


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


def _write_recipe(tmp_path: Path, image_root: Path, *, seed: int = 7) -> Path:
    payload = {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": seed,
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": str(image_root)}]},
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [8, 8, 3]},
                "label": {"dtype": "str"},
                "path": {"dtype": "str"},
            }
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {
            "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
            "seed": 11,
            "stratify_by": "label",
        },
    }
    path = tmp_path / f"recipe_seed{seed}.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _materialize(cache: Path, recipe: Path) -> None:
    result = runner.invoke(app, ["--cache-root", str(cache), "materialize", str(recipe)])
    assert result.exit_code == 0, result.stdout


def _list_instances(cache: Path) -> list[Path]:
    iroot = instances_root(cache)
    return [
        seed_dir
        for recipe_shard in iroot.iterdir()
        if recipe_shard.is_dir() and not recipe_shard.name.startswith(".")
        for input_shard in recipe_shard.iterdir()
        if input_shard.is_dir()
        for seed_dir in input_shard.iterdir()
        if seed_dir.is_dir()
    ]


def test_clean_no_selector_errors(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    result = runner.invoke(app, ["--cache-root", str(cache), "clean"])
    assert result.exit_code != 0
    assert isinstance(result.exception, CacheError)


def test_clean_by_recipe_removes_only_matching(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    cache = tmp_path / "cache"
    r1 = _write_recipe(tmp_path, images, seed=7)
    r2 = _write_recipe(tmp_path, images, seed=8)
    _materialize(cache, r1)
    _materialize(cache, r2)
    assert len(_list_instances(cache)) == 2

    # Pick the recipe shard for r1 (read it from disk; skip the
    # `.tmp/` orphans dir which lives next to the materialized shards).
    iroot = instances_root(cache)
    shards = sorted(p.name for p in iroot.iterdir() if p.is_dir() and not p.name.startswith("."))
    target_shard = shards[0]

    result = runner.invoke(
        app,
        [
            "--cache-root",
            str(cache),
            "clean",
            "--by-recipe",
            target_shard,
        ],
    )
    assert result.exit_code == 0, result.stdout
    remaining = _list_instances(cache)
    assert len(remaining) == 1
    assert target_shard not in (p.parent.parent.name for p in remaining)


def test_clean_by_age_removes_old_instances(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    cache = tmp_path / "cache"
    recipe = _write_recipe(tmp_path, images)
    _materialize(cache, recipe)
    instances = _list_instances(cache)
    assert len(instances) == 1

    # Backdate every instance's mtime by 7 days.
    week_ago = time.time() - 7 * 86400
    for path in instances:
        os.utime(path, (week_ago, week_ago))

    result = runner.invoke(app, ["--cache-root", str(cache), "clean", "--by-age", "1"])
    assert result.exit_code == 0, result.stdout
    assert _list_instances(cache) == []


def test_clean_orphans_removes_old_temp_dirs(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    tmp_root = instances_root(cache) / TMP_DIR_NAME
    tmp_root.mkdir(parents=True)
    orphan = tmp_root / "20260101T000000Z-deadbeef"
    orphan.mkdir()
    week_ago = time.time() - 7 * 86400
    os.utime(orphan, (week_ago, week_ago))

    result = runner.invoke(app, ["--cache-root", str(cache), "clean", "--orphans"])
    assert result.exit_code == 0, result.stdout
    assert not orphan.exists()


def test_clean_all_requires_yes_in_non_tty(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    cache = tmp_path / "cache"
    recipe = _write_recipe(tmp_path, images)
    _materialize(cache, recipe)

    # CliRunner is non-TTY by default; --all without --yes must refuse.
    result = runner.invoke(app, ["--cache-root", str(cache), "clean", "--all"])
    assert result.exit_code != 0
    assert isinstance(result.exception, CacheError)
    assert "non-interactive" in str(result.exception)
    assert _list_instances(cache)  # nothing was removed


def test_clean_all_with_yes_wipes_cache(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    cache = tmp_path / "cache"
    recipe = _write_recipe(tmp_path, images)
    _materialize(cache, recipe)
    assert _list_instances(cache)

    result = runner.invoke(app, ["--cache-root", str(cache), "clean", "--all", "--yes"])
    assert result.exit_code == 0, result.stdout
    assert _list_instances(cache) == []


def test_clean_renders_summary_table(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    cache = tmp_path / "cache"
    recipe = _write_recipe(tmp_path, images)
    _materialize(cache, recipe)

    result = runner.invoke(app, ["--cache-root", str(cache), "clean", "--all", "--yes"])
    assert result.exit_code == 0, result.stdout
    assert "Removed" in result.stdout
    assert "Cache root" in result.stdout
