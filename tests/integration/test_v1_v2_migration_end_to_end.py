# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Phase I bundle 4 (Story I.y) — v1 recipe loaded from disk migrates to v2
canonical bytes and runs all the way through to a materialized instance.

Every individual reshape (I.x.1 Filters, I.x.2 Generation, I.x.3 assertion
naming) is pinned by unit tests in ``tests/unit/test_migrations.py``. This
test is the bundle-level end-to-end: a single v1 YAML that exercises all
three reshapes loads through ``recipe.loader.load``, the migration chain
runs implicitly, and ``PipelineRunner`` materializes a complete instance
against the migrated shape. Re-loading the same YAML and re-running
produces a cache hit — the recipe_hash is stable across the migration.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from datarefinery.cache.layout import dataset_dir, manifest_path
from datarefinery.cache.layout import tmp_dir as tmp_dir_for
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.loader import load
from datarefinery.recipe.models import FilterOp, GenerationOp

_V1_RECIPE_YAML = """\
schema_version: 1
plugin: image_classification
seed: 7
Input:
  sources:
    - name: train
      type: image_folder
      path: /data/train
Output:
  record_schema:
    image: { dtype: uint8, shape: [4, 4, 3] }
    label: { dtype: str }
Labels:
  field: label
  source: { kind: direct }
InputContracts:
  # G16a: v1 names dtype / range / record_count migrate to dtype_equals /
  # value_range / record_count_in_range.
  - assertion: { kind: record_count, min: 4 }
  - field: image
    assertion: { kind: dtype, expected: uint8 }
Filters:
  # G15: v1 predicate-nested shape migrates to flat top-level op + params + seed.
  - name: keep_some
    predicate:
      op: random_sample
      fraction: 0.8
      seed: 17
    stages: [pre_split]
Generation:
  # G12: v1 implicit op (name doubles as op) + applies_at migrates to
  # top-level op + splits.
  - name: duplicate_minority_class
    inputs: [image, label]
    output_schema:
      image: { dtype: uint8, shape: [4, 4, 3] }
      label: { dtype: str }
    seed: 99
    applies_at: [train]
    params:
      factor: 2
Splits:
  ratios: { train: 0.6, val: 0.2, test: 0.2 }
  seed: 11
OutputExpectations:
  - field: label
    assertion: { kind: required_field }
"""


def _records(n: int = 12, classes: int = 2) -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": np.full((4, 4, 3), 20 + i * 5, dtype=np.uint8),
            "label": f"c{i % classes}",
            "path": f"/data/c{i % classes}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def test_v1_recipe_migrates_in_loader_and_materializes_to_instance(tmp_path: Path) -> None:
    """v1 YAML on disk loads + auto-migrates + materializes end-to-end."""
    recipe_path = tmp_path / "v1.yaml"
    recipe_path.write_text(_V1_RECIPE_YAML, encoding="utf-8")
    recipe = load(recipe_path)

    # The migration chain ran: every field on disk is v1 shape but the
    # loaded model is at the latest schema_version throughout (1→2→3; v3 is
    # the J.n.3 segmented-canonical era).
    assert recipe.schema_version == 3
    # G15 — Filters.
    assert isinstance(recipe.Filters[0], FilterOp)
    assert recipe.Filters[0].op == "random_sample"
    assert recipe.Filters[0].params == {"fraction": 0.8}
    assert recipe.Filters[0].seed == 17
    # G12 — Generation.
    assert isinstance(recipe.Generation[0], GenerationOp)
    assert recipe.Generation[0].op == "duplicate_minority_class"
    assert recipe.Generation[0].splits == ["train"]
    # G16a — assertion naming.
    assert recipe.InputContracts[0].assertion["kind"] == "record_count_in_range"
    assert recipe.InputContracts[1].assertion["kind"] == "dtype_equals"

    cache_root = tmp_path / "cache"
    records = _records(12)
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    assert result.cache_hit is False
    inst = result.instance_dir
    assert manifest_path(inst).exists()
    for split in ("train", "val", "test"):
        assert (dataset_dir(inst) / f"{split}.jsonl").exists()

    m = read_manifest(manifest_path(inst))
    assert m.plugin == "image_classification"
    assert m.is_partial is False
    assert m.failed_stage is None
    assert set(m.record_counts.keys()) == {"train", "val", "test"}


def test_v1_recipe_reload_produces_cache_hit(tmp_path: Path) -> None:
    """Reloading the v1 YAML and re-running produces a cache hit — the
    migrated recipe_hash is stable, so the second materialize finds the
    same instance directory on disk."""
    recipe_path = tmp_path / "v1.yaml"
    recipe_path.write_text(_V1_RECIPE_YAML, encoding="utf-8")
    cache_root = tmp_path / "cache"
    records = _records(12)
    raw_hashes = _input_hashes(records)
    config = RuntimeConfig(cache_root=cache_root)

    first = PipelineRunner(recipe=load(recipe_path), plugin=IMAGE_PLUGIN, config=config, seed=7)
    first_result = first.run(
        tmp_dir_for(cache_root, "run-1"),
        raw_records=records,
        raw_input_hashes=raw_hashes,
    )
    assert first_result.cache_hit is False

    second = PipelineRunner(recipe=load(recipe_path), plugin=IMAGE_PLUGIN, config=config, seed=7)
    second_result = second.run(
        tmp_dir_for(cache_root, "run-2"),
        raw_records=records,
        raw_input_hashes=raw_hashes,
    )
    assert second_result.cache_hit is True
    assert second_result.instance_dir == first_result.instance_dir
