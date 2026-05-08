# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for ``datarefinery inspect`` (Story D.h, FR-20)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from typer.testing import CliRunner

from datarefinery.cache.layout import manifest_path
from datarefinery.cli.app import app
from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.manifest import Manifest, write_manifest

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
                {"name": "train", "type": "image_folder", "path": str(image_root)}
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
        "Visualizations": [
            {
                "name": "explore_dist",
                "op": "class_distribution_histogram",
                "params": {},
                "stage": "post_pipeline",
                "mode": "exploration",
            },
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _materialize(tmp_path: Path) -> tuple[Path, Path, Path]:
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"
    result = runner.invoke(
        app, ["--cache-root", str(cache), "materialize", str(recipe)]
    )
    assert result.exit_code == 0, result.stdout

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
    return cache, recipe, instances[0]


def test_inspect_lists_exploration_views_and_peek(tmp_path: Path) -> None:
    cache, _, inst = _materialize(tmp_path)
    result = runner.invoke(
        app, ["--cache-root", str(cache), "inspect", str(inst)]
    )
    assert result.exit_code == 0, result.stdout
    assert "explore_dist" in result.stdout
    assert "Records per split" in result.stdout
    assert "Sample records" in result.stdout


def test_inspect_renders_view_to_file(tmp_path: Path) -> None:
    cache, _, inst = _materialize(tmp_path)
    out = tmp_path / "out" / "explore.png"
    result = runner.invoke(
        app,
        [
            "--cache-root",
            str(cache),
            "inspect",
            str(inst),
            "--view",
            "explore_dist",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    # PNG signature
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_inspect_renders_view_without_out_prints_byte_count(
    tmp_path: Path,
) -> None:
    cache, _, inst = _materialize(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cache-root",
            str(cache),
            "inspect",
            str(inst),
            "--view",
            "explore_dist",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "bytes" in result.stdout


def test_inspect_unknown_view_errors(tmp_path: Path) -> None:
    cache, _, inst = _materialize(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cache-root",
            str(cache),
            "inspect",
            str(inst),
            "--view",
            "no_such_view",
        ],
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, MaterializeError)


def test_inspect_refuses_partial_instance(tmp_path: Path) -> None:
    """FR-20 edge case: inspect against a partial instance must refuse."""
    cache, _, inst = _materialize(tmp_path)
    # Mutate the manifest in place to mark the instance partial.
    from datarefinery.pipeline.manifest import read_manifest

    m = read_manifest(manifest_path(inst))
    partial = Manifest(
        **{**m.model_dump(), "is_partial": True, "completed_through": "Splits"}
    )
    write_manifest(manifest_path(inst), partial)

    result = runner.invoke(
        app, ["--cache-root", str(cache), "inspect", str(inst)]
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, MaterializeError)
    assert "partial" in str(result.exception).lower()


def test_inspect_recipe_path_resolves_instance(tmp_path: Path) -> None:
    cache, recipe, _inst = _materialize(tmp_path)
    result = runner.invoke(
        app, ["--cache-root", str(cache), "inspect", str(recipe)]
    )
    assert result.exit_code == 0, result.stdout
    # Same exploration views surface regardless of how we reach the instance.
    assert "explore_dist" in result.stdout


def test_inspect_recipe_path_cache_miss_errors(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    recipe = _write_recipe(tmp_path, images)
    cache = tmp_path / "cache"  # not materialized
    result = runner.invoke(
        app, ["--cache-root", str(cache), "inspect", str(recipe)]
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, MaterializeError)


def test_inspect_out_without_view_errors(tmp_path: Path) -> None:
    cache, _, inst = _materialize(tmp_path)
    result = runner.invoke(
        app,
        [
            "--cache-root",
            str(cache),
            "inspect",
            str(inst),
            "--out",
            str(tmp_path / "x.png"),
        ],
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, MaterializeError)
