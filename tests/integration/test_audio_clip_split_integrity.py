# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.r (R6): clip-level labels + Splits-before-Generation integrity.

Splits runs at clip level (before the `window` Generation op fans each clip
into N window records), so every window of a clip inherits the clip's split and
its clip-level label. This is enforced structurally by the runner's stage order;
the end-to-end test verifies the observable consequence: with stratified splits,
no clip's `source_record_id` appears in two splits, and every window carries the
clip's label.

Requires the `[audio]` extra (librosa); skips without it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from datarefinery.pipeline.runner import STAGE_NAMES

pytest.importorskip("librosa")
pytest.importorskip("soundfile")

import soundfile as sf

from datarefinery.cache.layout import tmp_dir as tmp_dir_for
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.inputs import load_raw_records
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.audio_classification import PLUGIN as AUDIO_PLUGIN
from datarefinery.recipe.models import Recipe

_SR = 16000


def test_splits_runs_before_generation_in_stage_order() -> None:
    # The structural guard the R6 split-integrity guarantee rests on: clips are
    # assigned to splits before any record-fanning Generation op runs. If this
    # ever regresses, windowing could scatter a clip's windows across splits.
    assert STAGE_NAMES.index("Splits") < STAGE_NAMES.index("Generation")


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
            "Splits": {
                "ratios": {"train": 0.5, "val": 0.25, "test": 0.25},
                "stratify_by": "label",
                "seed": 7,
            },
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


def _read_split_jsonl(instance_dir: Path, split: str) -> list[dict[str, Any]]:
    path = instance_dir / "dataset" / f"{split}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_every_clips_windows_land_in_exactly_one_split(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    # 8 clips across 2 classes, each long enough for multiple windows.
    clip_ids = []
    for cls in ("cat", "dog"):
        for i in range(4):
            name = f"{cls}/{cls}_{i}.wav"
            _write_clip(root / name, seconds=0.4)  # 4 windows each
            clip_ids.append(f"clips/{cls}/{cls}_{i}.wav")

    recipe = _recipe(root)
    loaded, hashes = load_raw_records(recipe, AUDIO_PLUGIN)
    records: list[Mapping[str, Any]] = list(loaded)
    assert len(records) == 8  # eight clips before windowing

    cache_root = tmp_path / "cache"
    runner = PipelineRunner(
        recipe=recipe, plugin=AUDIO_PLUGIN, config=RuntimeConfig(cache_root=cache_root), seed=7
    )
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=hashes)

    # Collect the set of parent clip ids (source_record_id) observed in each split.
    clips_by_split: dict[str, set[str]] = {}
    all_window_count = 0
    for split in ("train", "val", "test"):
        rows = _read_split_jsonl(result.instance_dir, split)
        clips_by_split[split] = {r["source_record_id"] for r in rows}
        all_window_count += len(rows)
        # Every window carries the clip-level label (inherited verbatim).
        for r in rows:
            assert r["label"] in {"cat", "dog"}
            assert r["source_record_id"].rsplit("/", 2)[1] == r["label"]

    # No clip's windows straddle two splits: the per-split clip sets are disjoint.
    splits = list(clips_by_split.values())
    for i in range(len(splits)):
        for j in range(i + 1, len(splits)):
            assert splits[i].isdisjoint(splits[j]), (
                f"a clip appears in two splits: {splits[i] & splits[j]}"
            )

    # Every clip is accounted for, and the windows expanded the record count.
    assert set().union(*splits) == set(clip_ids)
    assert all_window_count == 8 * 4  # 32 windows total
