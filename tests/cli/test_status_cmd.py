# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for ``datarefinery status`` (Story D.f, FR-19)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from typer.testing import CliRunner

from datarefinery.cache.layout import manifest_path
from datarefinery.cli.app import app

runner = CliRunner()


def _build_image_folder(
    root: Path,
    *,
    classes: tuple[str, ...] = ("cats", "dogs"),
    per_class: int = 6,
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


def _write_recipe(tmp_path: Path, image_root: Path) -> Path:
    payload = {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 7,
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
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _materialize(cache: Path, recipe: Path) -> None:
    result = runner.invoke(app, ["--cache-root", str(cache), "materialize", str(recipe)])
    assert result.exit_code == 0, result.stdout


def test_status_with_recipe_path_reports_hit(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"
    _materialize(cache, recipe)

    result = runner.invoke(app, ["--cache-root", str(cache), "status", str(recipe)])
    assert result.exit_code == 0, result.stdout
    assert "hit" in result.stdout
    assert "image_classification" in result.stdout
    assert "Records per split" in result.stdout


def test_status_with_recipe_path_reports_miss_when_not_materialized(
    tmp_path: Path,
) -> None:
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"

    result = runner.invoke(app, ["--cache-root", str(cache), "status", str(recipe)])
    # Cache miss is not an error.
    assert result.exit_code == 0, result.stdout
    assert "miss" in result.stdout
    assert "Recipe hash" in result.stdout


def test_status_with_instance_path(tmp_path: Path) -> None:
    """Pass the materialized instance directory directly."""
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"
    _materialize(cache, recipe)

    instance_root = cache / "instances"
    instances = [
        seed_dir
        for recipe_shard in instance_root.iterdir()
        if recipe_shard.is_dir() and not recipe_shard.name.startswith(".")
        for input_shard in recipe_shard.iterdir()
        if input_shard.is_dir()
        for seed_dir in input_shard.iterdir()
        if seed_dir.is_dir()
    ]
    assert len(instances) == 1
    inst = instances[0]

    result = runner.invoke(app, ["--cache-root", str(cache), "status", str(inst)])
    assert result.exit_code == 0, result.stdout
    assert "hit" in result.stdout
    # Manifest fields render in the table.
    assert "Plugin" in result.stdout
    assert "Recipe hash" in result.stdout


def test_status_corrupt_instance_reports_corrupt(tmp_path: Path) -> None:
    """An instance dir with a missing manifest.json reports `corrupt`
    when reached via the recipe path (which knows the cache key)."""
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"
    _materialize(cache, recipe)

    instance_root = cache / "instances"
    instances = [
        seed_dir
        for recipe_shard in instance_root.iterdir()
        if recipe_shard.is_dir() and not recipe_shard.name.startswith(".")
        for input_shard in recipe_shard.iterdir()
        if input_shard.is_dir()
        for seed_dir in input_shard.iterdir()
        if seed_dir.is_dir()
    ]
    inst = instances[0]
    manifest_path(inst).unlink()

    result = runner.invoke(app, ["--cache-root", str(cache), "status", str(recipe)])
    assert result.exit_code == 0, result.stdout
    assert "corrupt" in result.stdout
    # The note suggests `datarefinery clean`; rich may wrap the long
    # note text across terminal widths, so check for the verb token.
    assert "clean" in result.stdout


def test_status_renders_sinks_skipped_table_on_partial_run(tmp_path: Path) -> None:
    """Story I.f.1: ``status`` against a partial-run temp dir with
    sinks declared at later stages renders the "Sinks skipped" table."""
    images = _build_image_folder(tmp_path / "data")
    cache = tmp_path / "cache"

    payload = {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 7,
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": str(images)}]},
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
        "Sinks": [
            {
                "name": "viz_pngs",
                "stage": "post_Visualizations",
                "field": "image",
                "format": "png_per_record",
                "path_template": "viz/{record_id}.png",
            },
        ],
    }
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(yaml.safe_dump(payload), encoding="utf-8")

    res = runner.invoke(
        app,
        ["--cache-root", str(cache), "materialize", str(recipe), "--stage", "Splits"],
    )
    assert res.exit_code == 0, res.stdout

    # Find the partial temp dir under instances/.tmp/.
    temp_dirs = list((cache / "instances" / ".tmp").iterdir())
    assert len(temp_dirs) == 1
    partial = temp_dirs[0]

    res = runner.invoke(app, ["--cache-root", str(cache), "status", str(partial)])
    assert res.exit_code == 0, res.stdout
    assert "partial" in res.stdout
    assert "Sinks skipped" in res.stdout
    assert "viz_pngs" in res.stdout
    assert "post_Visualizations" in res.stdout
