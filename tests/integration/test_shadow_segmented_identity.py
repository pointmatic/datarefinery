# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.2: the dormant shadow path does not perturb cache identity.

`shadow_segmented_identity=True` makes the runner additionally compute + log
the segmented recipe hash, but the authoritative flat cache key — and thus
the resolved instance directory — must be byte-for-byte unchanged.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from datarefinery.cache.layout import tmp_dir as tmp_dir_for
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe


def _img(value: int) -> np.ndarray:
    return np.full((4, 4, 3), value, dtype=np.uint8)


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


def _hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
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


def _run(cache_root: Path, *, shadow: bool) -> tuple[str, Path]:
    config = RuntimeConfig(cache_root=cache_root, shadow_segmented_identity=shadow)
    runner = PipelineRunner(recipe=_recipe(), plugin=IMAGE_PLUGIN, config=config, seed=11)
    records = _records()
    result = runner.run(
        tmp_dir_for(cache_root, f"run-shadow-{shadow}"),
        raw_records=records,
        raw_input_hashes=_hashes(records),
    )
    return result.manifest.recipe_hash, result.instance_dir


def test_shadow_flag_leaves_authoritative_identity_unchanged(tmp_path: Path) -> None:
    off_hash, off_dir = _run(tmp_path / "off", shadow=False)
    on_hash, on_dir = _run(tmp_path / "on", shadow=True)

    # Same authoritative recipe_hash; same relative instance path under each root.
    assert on_hash == off_hash
    assert on_dir.relative_to(tmp_path / "on") == off_dir.relative_to(tmp_path / "off")
