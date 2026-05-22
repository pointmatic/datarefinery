# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-GEN-1 / Story H.m.3 end-to-end integration test.

Runs a recipe with an ``imagecorruptions_apply`` Generation op through
the full materialization pipeline. Asserts the instance directory,
manifest record counts, dataset shards, and report all reflect the
corruption sweep.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from datarefinery.cache.layout import (
    dataset_dir,
    manifest_path,
    report_dir,
)
from datarefinery.cache.layout import (
    tmp_dir as tmp_dir_for,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe


def _img(value: int) -> np.ndarray:
    # 32x32 RGB — corrupt() requires H,W >= 32.
    return np.full((32, 32, 3), value, dtype=np.uint8)


def _records(n: int = 12, classes: int = 2) -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": _img(20 + i * 5),
            "label": f"c{i % classes}",
            "path": f"/data/c{i % classes}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _recipe() -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {
                "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
                "seed": 11,
            },
            "Generation": [
                {
                    "name": "imagecorruptions_apply",
                    "inputs": ["image"],
                    "output_schema": {
                        "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                        "label": {"dtype": "str"},
                    },
                    "seed": 42,
                    "applies_at": ["train"],
                    "params": {
                        "corruption_types": ["gaussian_noise", "fog"],
                        "severities": [1, 3],
                        "preserve_original": False,
                        "tag_fields": ["corruption", "severity", "source_path"],
                    },
                }
            ],
        }
    )


def test_imagecorruptions_apply_end_to_end_materialization(tmp_path: Path) -> None:
    """A 2x2 (corruption_types x severities) sweep materializes cleanly.

    Train ends with the original 8 records plus 8 * 2 * 2 = 32 corrupted
    records (40 total). Val / test are untouched. Manifest record counts,
    dataset shards, and report.md all reflect the sweep.
    """
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(12)
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-imagecorruptions")
    result = runner.run(
        temp,
        raw_records=records,
        raw_input_hashes=_input_hashes(records),
    )

    assert result.cache_hit is False
    inst = result.instance_dir

    # Instance layout.
    assert manifest_path(inst).exists()
    ds = dataset_dir(inst)
    assert (ds / "train.jsonl").exists()
    assert (ds / "val.jsonl").exists()
    assert (ds / "test.jsonl").exists()

    # Manifest record counts: train ballooned by the 2x2 corruption sweep.
    manifest = read_manifest(manifest_path(inst))
    train_count = manifest.record_counts["train"]
    val_count = manifest.record_counts["val"]
    test_count = manifest.record_counts["test"]
    # 12 inputs total post-split (regardless of exact 0.6/0.2/0.2 rounding).
    n_train_pre_generation = val_count + test_count  # implied via the 12-input total
    n_train_pre_generation = 12 - val_count - test_count
    # Train: <n_train_pre> original + <n_train_pre> * 2 corruption_types
    # * 2 severities = <n_train_pre> * 5.
    assert train_count == n_train_pre_generation * 5

    # Train shard contains the corrupted records with their tag fields.
    train_lines = (ds / "train.jsonl").read_text().splitlines()
    assert len(train_lines) == train_count
    corrupted_records = [
        json.loads(line) for line in train_lines if "corruption" in json.loads(line)
    ]
    assert len(corrupted_records) == n_train_pre_generation * 2 * 2

    corruption_types_seen = {r["corruption"] for r in corrupted_records}
    severities_seen = {r["severity"] for r in corrupted_records}
    assert corruption_types_seen == {"gaussian_noise", "fog"}
    assert severities_seen == {1, 3}

    # Every corrupted record carries source_path back to one of the inputs.
    input_paths = {r["path"] for r in records}
    for r in corrupted_records:
        assert r["source_path"] in input_paths

    # Report exists.
    rd = report_dir(inst)
    assert (rd / "report.md").exists()


def test_imagecorruptions_apply_is_deterministic_across_runs(tmp_path: Path) -> None:
    """Two runs with the same recipe + records + seed materialize to the
    same cache key (the canonical-form contract on the new op kind).
    """
    cache_root_a = tmp_path / "cache_a"
    cache_root_b = tmp_path / "cache_b"
    recipe = _recipe()
    records = _records(12)
    hashes = _input_hashes(records)

    runner_a = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root_a),
        seed=7,
    )
    runner_b = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root_b),
        seed=7,
    )
    a = runner_a.run(
        tmp_dir_for(cache_root_a, "run-a"),
        raw_records=records,
        raw_input_hashes=hashes,
    )
    b = runner_b.run(
        tmp_dir_for(cache_root_b, "run-b"),
        raw_records=records,
        raw_input_hashes=hashes,
    )
    # Same recipe + same input hashes + same seed -> same cache key.
    assert a.manifest.recipe_hash == b.manifest.recipe_hash
    assert a.manifest.input_hash == b.manifest.input_hash
    assert a.manifest.record_counts == b.manifest.record_counts
