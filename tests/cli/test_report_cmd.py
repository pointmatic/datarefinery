# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for ``datarefinery report`` (Story D.g, FR-15.4)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from typer.testing import CliRunner

from datarefinery.cache.layout import (
    recipe_path as recipe_path_for,
)
from datarefinery.cache.layout import (
    report_dir,
)
from datarefinery.cli.app import app
from datarefinery.core.errors import MaterializeError

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
                "name": "class_dist",
                "op": "class_distribution_histogram",
                "params": {},
                "stage": "post_pipeline",
                "mode": "reporting",
            },
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _materialize_and_get_instance(tmp_path: Path) -> Path:
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
    return instances[0]


def test_report_re_renders_in_place(tmp_path: Path) -> None:
    inst = _materialize_and_get_instance(tmp_path)
    rd = report_dir(inst)
    md = rd / "report.md"
    drift = rd / "drift.json"
    viz = rd / "visualizations" / "class_dist.png"

    original_md = md.read_text(encoding="utf-8")
    original_drift = drift.read_text(encoding="utf-8")
    original_viz_bytes = viz.read_bytes()

    # Clobber all three to confirm the verb actually rewrites them.
    md.write_text("clobbered", encoding="utf-8")
    drift.write_text("{}", encoding="utf-8")
    viz.write_bytes(b"")

    result = runner.invoke(app, ["report", str(inst)])
    assert result.exit_code == 0, result.stdout

    assert md.read_text(encoding="utf-8") == original_md
    assert drift.read_text(encoding="utf-8") == original_drift
    assert viz.read_bytes() == original_viz_bytes


def test_report_announces_each_artifact(tmp_path: Path) -> None:
    inst = _materialize_and_get_instance(tmp_path)
    result = runner.invoke(app, ["report", str(inst)])
    assert result.exit_code == 0, result.stdout
    assert "report.md" in result.stdout
    assert "drift.json" in result.stdout
    assert "visualizations" in result.stdout


def test_report_stale_recipe_hash_is_hard_error(tmp_path: Path) -> None:
    """FR-15 edge case: persisted recipe.json that doesn't canonicalize
    to the manifest's recipe_hash is rejected with `MaterializeError`."""
    inst = _materialize_and_get_instance(tmp_path)
    rp = recipe_path_for(inst)
    text = rp.read_text(encoding="utf-8")
    # Mutate the persisted recipe so its canonical hash drifts from
    # the manifest's recipe_hash. Switch the seed (part of canonical
    # bytes) from 7 to 999.
    rp.write_text(text.replace('"seed": 7', '"seed": 999'), encoding="utf-8")

    result = runner.invoke(app, ["report", str(inst)])
    assert result.exit_code != 0
    # Instance.load itself rejects the inconsistent instance dir, so we
    # see MaterializeError before re_render_report's stale-stats check.
    assert isinstance(result.exception, MaterializeError)


def test_report_missing_instance_dir_is_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["report", str(tmp_path / "nope")])
    assert result.exit_code != 0
