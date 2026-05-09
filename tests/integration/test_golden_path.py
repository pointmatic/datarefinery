# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Phase D golden-path integration test (Story D.j).

Exercises the documented user journey end-to-end through the typer CLI:

    datarefinery init        → produce a starter recipe from raw images
    (review/edit)            → uncomment the suggested Transformations
    datarefinery validate    → recipe parses through every FR-2 check
    datarefinery materialize → pipeline runs, instance is promoted
    datarefinery status      → the cached instance reports `cache=hit`

The fixture is a CIFAR-10-shaped synthetic dataset (10 classes x 3
images, 8x8 RGB) generated with seeded NumPy randomness so the test is
fast and self-contained. Asserts every artifact called out in the
story task is present in the final instance: ``manifest.json``,
``recipe.json``, ``dataset/<split>.jsonl``, ``fitted_statistics/``,
``report/report.md``, ``report/drift.json``,
``report/visualizations/``.

This closes Phase D.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from typer.testing import CliRunner

from datarefinery.cache.layout import (
    dataset_dir,
    fitted_stats_dir,
    instances_root,
    manifest_path,
    recipe_path,
    report_dir,
)
from datarefinery.cli.app import app

runner = CliRunner()


def _enable_normalize_transformation(recipe_path_yaml: Path) -> None:
    """Edit the scaffolded recipe to add a fit-on-train normalize op.

    The scaffolder ships ``Transformations`` as a commented-out
    suggestion block; this helper simulates the user's review step
    (`# uncomment & adjust as needed`) by inserting an active
    Transformations entry. Without a fit-on-train op the
    ``fitted_statistics/`` directory is never created and the
    golden-path artifact set would be incomplete.
    """
    payload = yaml.safe_load(recipe_path_yaml.read_text(encoding="utf-8"))
    payload["Transformations"] = [
        {
            "name": "norm",
            "op": "normalize",
            "params": {},
            "fit_source": "train",
            "splits": ["train", "val", "test"],
        }
    ]
    recipe_path_yaml.write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )


def _list_promoted_instances(cache_root: Path) -> list[Path]:
    """Walk the cache layout for every promoted ``<seed>/`` directory."""
    iroot = instances_root(cache_root)
    if not iroot.is_dir():
        return []
    return [
        seed_dir
        for recipe_shard in iroot.iterdir()
        if recipe_shard.is_dir() and not recipe_shard.name.startswith(".")
        for input_shard in recipe_shard.iterdir()
        if input_shard.is_dir()
        for seed_dir in input_shard.iterdir()
        if seed_dir.is_dir()
    ]


def test_golden_path_init_validate_materialize_status(
    tmp_path: Path, cifar10_shaped_dir: Path
) -> None:
    # Copy the session-scoped fixture into this test's tmp_path so the
    # golden-path test stays isolated from any future test that mutates
    # the source tree.
    images = tmp_path / "images"
    shutil.copytree(cifar10_shaped_dir, images)
    recipe = tmp_path / "recipe.yaml"
    cache = tmp_path / "cache"

    # 1. init
    init_result = runner.invoke(
        app, ["init", "--input", str(images), "--output", str(recipe)]
    )
    assert init_result.exit_code == 0, init_result.stdout
    assert recipe.exists()

    # Simulate the user's review: enable the suggested normalize op so
    # the run produces fitted statistics.
    _enable_normalize_transformation(recipe)

    # 2. validate
    validate_result = runner.invoke(app, ["validate", str(recipe)])
    assert validate_result.exit_code == 0, validate_result.stdout
    assert "passed" in validate_result.stdout

    # 3. materialize
    materialize_result = runner.invoke(
        app, ["--cache-root", str(cache), "materialize", str(recipe)]
    )
    assert materialize_result.exit_code == 0, materialize_result.stdout
    assert "miss" in materialize_result.stdout

    # Exactly one instance promoted.
    instances = _list_promoted_instances(cache)
    assert len(instances) == 1
    instance = instances[0]

    # Every artifact called out in the story task is present.
    assert manifest_path(instance).exists()
    assert recipe_path(instance).exists()
    ds = dataset_dir(instance)
    assert (ds / "train.jsonl").exists()
    assert (ds / "val.jsonl").exists()
    assert (ds / "test.jsonl").exists()
    fs = fitted_stats_dir(instance)
    assert fs.is_dir()
    # fit-on-train normalize persists mean/std vectors under <op_id>/.
    assert (fs / "norm" / "mean.parquet").exists()
    assert (fs / "norm" / "std.parquet").exists()
    rd = report_dir(instance)
    assert (rd / "report.md").exists()
    assert (rd / "drift.json").exists()
    assert (rd / "visualizations").is_dir()
    # The scaffolder declares two reporting visualizations.
    viz_files = sorted(p.name for p in (rd / "visualizations").glob("*.png"))
    assert "class_distribution.png" in viz_files
    assert "samples.png" in viz_files

    # 4. status against the recipe path resolves to the cached instance.
    status_result = runner.invoke(
        app, ["--cache-root", str(cache), "status", str(recipe)]
    )
    assert status_result.exit_code == 0, status_result.stdout
    assert "hit" in status_result.stdout
    # The summary table calls out the plugin and the record counts.
    assert "image_classification" in status_result.stdout
    assert "Records per split" in status_result.stdout

    # Sanity: total records across splits matches the fixture size.
    from tests.fixtures.build_cifar10_shaped import (
        DEFAULT_NUM_CLASSES,
        DEFAULT_PER_CLASS,
    )

    from datarefinery.pipeline.manifest import read_manifest

    manifest = read_manifest(manifest_path(instance))
    assert (
        sum(manifest.record_counts.values())
        == DEFAULT_NUM_CLASSES * DEFAULT_PER_CLASS
    )

    # 5. Rerun materialize hits the cache (no new pipeline work).
    rerun = runner.invoke(
        app, ["--cache-root", str(cache), "materialize", str(recipe)]
    )
    assert rerun.exit_code == 0, rerun.stdout
    assert "hit" in rerun.stdout
    # Cache was hit, not re-promoted: still exactly one instance.
    assert len(_list_promoted_instances(cache)) == 1
