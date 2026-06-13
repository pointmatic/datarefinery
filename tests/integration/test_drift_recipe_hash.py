# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.j: drift.json.recipe_hash aligns with manifest.recipe_hash.

A fresh instance's `report/drift.json` carries `recipe_hash` equal to
`manifest.recipe_hash` (full 64-hex), so consumers detect a stale
fitted-statistics block from `drift.json` alone — the contract the MF
vendor-dependency-spec advertises.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from datarefinery.cache.layout import manifest_path, report_dir
from datarefinery.cache.layout import tmp_dir as tmp_dir_for
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe
from datarefinery.reporting.drift import read_drift
from datarefinery.reporting.report import DRIFT_FILENAME


def _records(n: int = 12) -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": np.full((4, 4, 3), 10 + i, dtype=np.uint8),
            "label": f"c{i % 2}",
            "path": f"/data/source/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _recipe() -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 2,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.6, "val": 0.2, "test": 0.2}, "seed": 11},
        }
    )


def test_drift_recipe_hash_matches_manifest(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records()
    runner = PipelineRunner(
        recipe=recipe, plugin=IMAGE_PLUGIN, config=RuntimeConfig(cache_root=cache_root), seed=11
    )
    result = runner.run(
        tmp_dir_for(cache_root, "run-1"),
        raw_records=records,
        raw_input_hashes=_input_hashes(records),
    )
    inst = result.instance_dir

    manifest = read_manifest(manifest_path(inst))
    drift = read_drift(report_dir(inst) / DRIFT_FILENAME)

    assert drift.recipe_hash == manifest.recipe_hash
    # Full 64-hex digest, not the truncated 16-char cache-path shard.
    assert len(drift.recipe_hash or "") == 64
