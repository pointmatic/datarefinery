# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.i: dtype-altering Transformation + aggressive Augmentation guard.

A recipe combining `normalize` (float64 output) with an aggressive
augmentation crashes mid-pipeline because the realizer's
`PIL.Image.fromarray` requires uint8. This test documents the raw crash
AND confirms validator check 27 refuses the recipe before any run starts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from datarefinery.cache.layout import tmp_dir as tmp_dir_for
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import validate


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


def _normalize_plus_aggressive_recipe() -> Recipe:
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
            "Transformations": [
                {
                    "name": "norm",
                    "op": "normalize",
                    "fit_source": "train",
                    "splits": ["train", "val", "test"],
                }
            ],
            "Augmentations": [
                {
                    "name": "flip",
                    "op": "horizontal_flip",
                    "splits": ["train"],
                    "materialization": "aggressive",
                    "expansion": 2,
                }
            ],
        }
    )


def test_normalize_plus_aggressive_crashes_unguarded(tmp_path: Path) -> None:
    """The raw failure mode this story closes: without a validate-time
    guard, the realizer crashes mid-pipeline on float64 input."""
    recipe = _normalize_plus_aggressive_recipe()
    records = _records()
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=tmp_path / "cache"),
        seed=11,
    )
    with pytest.raises(Exception):  # noqa: B017 - documents the unguarded crash
        runner.run(
            tmp_dir_for(tmp_path / "cache", "run-1"),
            raw_records=records,
            raw_input_hashes=_input_hashes(records),
        )


def test_validate_refuses_before_run() -> None:
    """Check 27 catches the same recipe at validate time, so a caller that
    validates first never reaches the crash."""
    report = validate(_normalize_plus_aggressive_recipe(), IMAGE_PLUGIN)
    failures = [r for r in report.failures if r.check_id == 27]
    assert len(failures) == 1
    assert "normalize" in failures[0].message
    assert "horizontal_flip" in failures[0].message
