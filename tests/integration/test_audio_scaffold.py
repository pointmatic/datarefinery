# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.o: the `audio_classification` scaffold materializes the empty seam.

A minimal recipe declaring `plugin: audio_classification` with **no operations**
validates cleanly and runs end-to-end through the pipeline to a promoted
instance — proving the new plugin is a first-class seam in discovery, the
validator, and the runner before any audio op exists.

**Scope note.** Audio input *sources* + decode are Story J.p; until then there
is no audio reader, so this seam test injects plain records directly into the
`PipelineRunner` (the same `raw_records=` path the other runner integration
tests use) rather than reading an audio source from disk. The point is the
zero-op pipeline seam, not audio I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from datarefinery.cache.layout import (
    dataset_dir,
    manifest_path,
)
from datarefinery.cache.layout import (
    tmp_dir as tmp_dir_for,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.audio_classification import PLUGIN as AUDIO_PLUGIN
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import validate


def _audio_recipe() -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 3,
            "plugin": "audio_classification",
            "Input": {
                "sources": [{"name": "clips", "type": "audio_folder", "path": "/data/clips"}]
            },
            "Output": {
                "record_schema": {
                    "label": {"dtype": "str"},
                    "value": {"dtype": "int32"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.6, "val": 0.2, "test": 0.2}},
        }
    )


def _records(n: int = 30, classes: int = 3) -> list[Mapping[str, Any]]:
    return [{"record_id": f"r{i:04d}", "label": f"c{i % classes}", "value": i} for i in range(n)]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    return {"clips": "a" * 64}


def test_minimal_audio_recipe_validates_cleanly() -> None:
    report = validate(_audio_recipe(), AUDIO_PLUGIN)
    assert report.passed, [r for r in report.failures]


def test_audio_scaffold_materializes_an_empty_op_instance(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _audio_recipe()
    records = _records(30)
    runner = PipelineRunner(
        recipe=recipe, plugin=AUDIO_PLUGIN, config=RuntimeConfig(cache_root=cache_root), seed=7
    )
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    # The full dataset is present and every record survives (no op drops any).
    ds = dataset_dir(result.instance_dir)
    total = sum(
        len((ds / f"{split}.jsonl").read_text().splitlines()) for split in ("train", "val", "test")
    )
    assert total == 30

    # A well-formed manifest was written for the audio-plugin run.
    manifest = read_manifest(manifest_path(result.instance_dir))
    assert manifest.recipe_hash
