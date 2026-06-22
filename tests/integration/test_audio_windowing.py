# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.q: windowing through the full pipeline.

A 3-clip fixture with varied lengths decodes, splits at clip level, then the
`window` Generation op (replace_input_records) fans each clip into fixed-length
windows — and `manifest.record_counts` reflects the post-windowing expansion.
Requires the `[audio]` extra (librosa); skips without it.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("librosa")
pytest.importorskip("soundfile")

import soundfile as sf

from datarefinery.cache.layout import manifest_path
from datarefinery.cache.layout import tmp_dir as tmp_dir_for
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.inputs import load_raw_records
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.audio_classification import PLUGIN as AUDIO_PLUGIN
from datarefinery.recipe.models import Recipe

_SR = 16000


def _write_clip(path: Path, *, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(_SR * seconds)
    sf.write(path, np.linspace(0.0, 1.0, n, endpoint=False).astype(np.float32), _SR)


def _recipe(root: Path) -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 3,
            "plugin": "audio_classification",
            "Input": {
                "sources": [
                    {
                        "name": "clips",
                        "type": "audio_folder",
                        "path": str(root),
                        "target_sample_rate": _SR,
                    }
                ]
            },
            "Output": {"record_schema": {"label": {"dtype": "str"}}},
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.34, "val": 0.33, "test": 0.33}},
            "Generation": [
                {
                    "name": "win",
                    "op": "window",
                    "inputs": ["sample_array"],
                    "output_schema": "matches_input",
                    "seed": 0,
                    "splits": ["train", "val", "test"],
                    "replace_input_records": True,
                    "params": {
                        "window_length_samples": 1600,  # 0.1s @ 16 kHz
                        "hop_samples": 1600,  # non-overlapping
                        "remainder": "drop",
                    },
                }
            ],
        }
    )


def test_windowing_expands_manifest_record_counts(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    # 3 clips, varied lengths → 3 + 2 + 5 = 10 non-overlapping 0.1s windows total.
    _write_clip(root / "cat" / "a.wav", seconds=0.3)  # 3 windows
    _write_clip(root / "cat" / "b.wav", seconds=0.2)  # 2 windows
    _write_clip(root / "dog" / "c.wav", seconds=0.5)  # 5 windows

    recipe = _recipe(root)
    loaded, hashes = load_raw_records(recipe, AUDIO_PLUGIN)
    records: list[Mapping[str, Any]] = list(loaded)
    assert len(records) == 3  # three clips before windowing

    cache_root = tmp_path / "cache"
    runner = PipelineRunner(
        recipe=recipe, plugin=AUDIO_PLUGIN, config=RuntimeConfig(cache_root=cache_root), seed=7
    )
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=hashes)

    manifest = read_manifest(manifest_path(result.instance_dir))
    # Post-windowing total reflects the expansion (10 windows across all splits),
    # not the 3 input clips.
    assert sum(manifest.record_counts.values()) == 10
