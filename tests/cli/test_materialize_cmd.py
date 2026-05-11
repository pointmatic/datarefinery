# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for ``datarefinery materialize`` (Story D.e).

These tests exercise the full critical path: disk-backed input loading
(via the image_classification ImageFolder loader), pipeline runner,
manifest write + atomic promote, and cache-hit short-circuit on rerun.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from typer.testing import CliRunner

from datarefinery.cache.layout import (
    dataset_dir,
    manifest_path,
    recipe_path,
    report_dir,
)
from datarefinery.cli.app import app
from datarefinery.pipeline.manifest import read_manifest

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
        "Input": {
            "sources": [
                {
                    "name": "train",
                    "type": "image_folder",
                    "path": str(image_root),
                }
            ]
        },
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


def test_materialize_end_to_end(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"

    result = runner.invoke(app, ["--cache-root", str(cache), "materialize", str(recipe)])
    assert result.exit_code == 0, result.stdout

    # The summary calls out the cache miss and the instance path.
    assert "miss" in result.stdout
    assert "Materialize summary" in result.stdout

    # The cache root contains exactly one instance with all artifacts.
    instance_root = cache / "instances"
    assert instance_root.is_dir()
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
    assert manifest_path(inst).exists()
    assert recipe_path(inst).exists()
    assert (dataset_dir(inst) / "train.jsonl").exists()
    assert (dataset_dir(inst) / "val.jsonl").exists()
    assert (dataset_dir(inst) / "test.jsonl").exists()
    assert (report_dir(inst) / "report.md").exists()
    assert (report_dir(inst) / "drift.json").exists()
    # fitted_statistics/ is created on first put_*; this minimal recipe
    # has no transformations, so the directory is allowed to be absent.


def test_materialize_rerun_hits_cache(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"

    first = runner.invoke(app, ["--cache-root", str(cache), "materialize", str(recipe)])
    assert first.exit_code == 0, first.stdout
    assert "miss" in first.stdout

    second = runner.invoke(app, ["--cache-root", str(cache), "materialize", str(recipe)])
    assert second.exit_code == 0, second.stdout
    assert "hit" in second.stdout
    # Cache hits do not run any pipeline stage; the manifest's
    # elapsed_seconds reflects the original run time.


def test_materialize_partial_stage_run(tmp_path: Path) -> None:
    """``--stage Splits`` runs through Splits and stops without promoting."""
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"

    result = runner.invoke(
        app,
        [
            "--cache-root",
            str(cache),
            "materialize",
            str(recipe),
            "--stage",
            "Splits",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "partial" in result.stdout

    # Final cache layout was NOT populated.
    instance_root = cache / "instances"
    promoted = [
        seed_dir
        for recipe_shard in instance_root.iterdir()
        if recipe_shard.is_dir() and not recipe_shard.name.startswith(".")
        for input_shard in recipe_shard.iterdir()
        if input_shard.is_dir()
        for seed_dir in input_shard.iterdir()
        if seed_dir.is_dir()
    ]
    assert promoted == []

    # The temp dir under .tmp/ has the partial manifest + recipe.
    tmp_root = instance_root / ".tmp"
    assert tmp_root.is_dir()
    temp_runs = list(tmp_root.iterdir())
    assert len(temp_runs) == 1
    partial_dir = temp_runs[0]
    manifest = read_manifest(manifest_path(partial_dir))
    assert manifest.is_partial is True
    assert manifest.completed_through == "Splits"
    assert manifest.failed_stage is None


def test_materialize_invalid_stage_name(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"

    result = runner.invoke(
        app,
        [
            "--cache-root",
            str(cache),
            "materialize",
            str(recipe),
            "--stage",
            "NotARealStage",
        ],
    )
    # MaterializeError -> EXIT_USER (1)
    assert result.exit_code != 0
    assert result.exception is not None


def test_materialize_missing_recipe_file_is_usage_error(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    result = runner.invoke(
        app,
        [
            "--cache-root",
            str(cache),
            "materialize",
            str(tmp_path / "nope.yaml"),
        ],
    )
    assert result.exit_code != 0
