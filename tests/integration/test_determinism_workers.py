# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""End-to-end byte-identity check across worker counts (Story E.d).

Runs the same fixture pipeline three times at ``workers=1``, ``2``,
``4`` (each into a fresh cache root so the second and third runs do
not short-circuit on cache hit) and asserts the resulting instance
directories are byte-identical except for two intrinsically run-
specific fields:

- ``manifest.created_at``
- ``manifest.elapsed_seconds``

These fields are stripped from ``manifest.json`` and the corresponding
"Created at" / "Elapsed" lines are stripped from ``report.md`` before
the byte-comparison.

This test is the regression guard for the determinism contract
documented in ``project-essentials.md`` ("Determinism contract in
``pipeline.workers``"): worker count must not leak into materialized
output bytes. v1 stage drivers run sequentially so the test
is informational today; it becomes load-bearing as soon as any stage
starts threading work through ``pipeline.workers.run_parallel``.

Marked ``slow`` so CI can opt to run it on demand
(``pytest -m 'not slow'`` to skip).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from datarefinery.cache.layout import (
    instances_root,
    manifest_path,
    report_dir,
)
from datarefinery.cli.app import app

runner = CliRunner()

_NORMALIZED_MANIFEST_FIELDS = ("created_at", "elapsed_seconds")
_NORMALIZED_REPORT_LINE_PREFIXES = (
    "- Created at:",
    "- Elapsed:",
)


def _write_recipe(tmp_path: Path, image_root: Path) -> Path:
    payload: dict[str, Any] = {
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
        "Transformations": [
            {
                "name": "norm",
                "op": "normalize",
                "params": {},
                "fit_source": "train",
                "splits": ["train", "val", "test"],
            }
        ],
        "Visualizations": [
            {
                "name": "class_dist",
                "op": "class_distribution_histogram",
                "params": {},
                "stage": "post_pipeline",
                "mode": "reporting",
            }
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _materialize(cache: Path, recipe: Path, *, workers: int) -> Path:
    """Run materialize with a worker count override; return the instance dir."""
    result = runner.invoke(
        app,
        [
            "--cache-root",
            str(cache),
            "--workers",
            str(workers),
            "materialize",
            str(recipe),
        ],
    )
    assert result.exit_code == 0, result.stdout

    iroot = instances_root(cache)
    instances = [
        seed_dir
        for recipe_shard in iroot.iterdir()
        if recipe_shard.is_dir() and not recipe_shard.name.startswith(".")
        for input_shard in recipe_shard.iterdir()
        if input_shard.is_dir()
        for seed_dir in input_shard.iterdir()
        if seed_dir.is_dir()
    ]
    assert len(instances) == 1, instances
    return instances[0]


def _relative_files(root: Path) -> list[Path]:
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


def _normalize_manifest(path: Path) -> bytes:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for field in _NORMALIZED_MANIFEST_FIELDS:
        payload.pop(field, None)
    return json.dumps(payload, sort_keys=True, indent=2).encode("utf-8")


def _normalize_report_md(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    kept = [
        line
        for line in text.splitlines()
        if not any(line.startswith(p) for p in _NORMALIZED_REPORT_LINE_PREFIXES)
    ]
    return "\n".join(kept).encode("utf-8")


def _normalized_bytes(root: Path, rel: Path) -> bytes:
    abs_path = root / rel
    if abs_path.name == "manifest.json" and abs_path.parent == root:
        return _normalize_manifest(abs_path)
    if abs_path.name == "report.md" and abs_path.parent == report_dir(root):
        return _normalize_report_md(abs_path)
    return abs_path.read_bytes()


@pytest.mark.slow
def test_pipeline_is_byte_identical_across_worker_counts(
    tmp_path: Path, cifar10_shaped_dir: Path
) -> None:
    images = tmp_path / "images"
    shutil.copytree(cifar10_shaped_dir, images)
    recipe = _write_recipe(tmp_path, images)

    instance_dirs: list[Path] = []
    for workers in (1, 2, 4):
        cache = tmp_path / f"cache_w{workers}"
        instance_dirs.append(_materialize(cache, recipe, workers=workers))

    # Same set of files in every instance directory.
    rels = [_relative_files(d) for d in instance_dirs]
    assert rels[0] == rels[1] == rels[2], (
        f"instance file lists differ across worker counts: {rels}"
    )

    # Every file is byte-identical after normalizing the two
    # documented run-specific manifest fields (and their report.md
    # echoes).
    for rel in rels[0]:
        bytes_w1 = _normalized_bytes(instance_dirs[0], rel)
        bytes_w2 = _normalized_bytes(instance_dirs[1], rel)
        bytes_w4 = _normalized_bytes(instance_dirs[2], rel)
        assert bytes_w1 == bytes_w2 == bytes_w4, (
            f"byte mismatch at {rel} across worker counts"
        )


@pytest.mark.slow
def test_manifest_run_specific_fields_actually_vary(
    tmp_path: Path, cifar10_shaped_dir: Path
) -> None:
    """Sanity guard: if `created_at` were also stable across runs, the
    main test's normalization would be a no-op and we'd be passing the
    determinism check for the wrong reason. This test confirms the two
    fields we strip really do vary across independent runs."""
    images = tmp_path / "images"
    shutil.copytree(cifar10_shaped_dir, images)
    recipe = _write_recipe(tmp_path, images)

    cache_a = tmp_path / "cache_a"
    cache_b = tmp_path / "cache_b"
    inst_a = _materialize(cache_a, recipe, workers=1)
    inst_b = _materialize(cache_b, recipe, workers=1)

    a = json.loads(manifest_path(inst_a).read_text(encoding="utf-8"))
    b = json.loads(manifest_path(inst_b).read_text(encoding="utf-8"))
    # Same recipe + inputs + seed -> identical hashes.
    assert a["recipe_hash"] == b["recipe_hash"]
    assert a["input_hash"] == b["input_hash"]
    # Two independent runs almost always differ on at least one of
    # these two intrinsically run-specific fields.
    assert (a["created_at"], a["elapsed_seconds"]) != (
        b["created_at"],
        b["elapsed_seconds"],
    )
