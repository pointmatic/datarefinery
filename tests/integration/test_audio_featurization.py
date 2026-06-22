# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.s: `log_mel_spectrogram` Featurization through the pipeline.

A decoded + windowed audio fixture is featurized: each window gains a
`feature` of shape `(n_mels, n_frames)`, the record count is unchanged across
the Featurization stage (one output per input window), and the feature is
byte-identical across runs (a pure function → worker-count invariant by
construction, mirroring the J.q windowing determinism rationale).

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
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.inputs import load_raw_records
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.pipeline.stages.featurizations import apply_featurizations
from datarefinery.plugins.audio_classification import PLUGIN as AUDIO_PLUGIN
from datarefinery.plugins.audio_classification.operations.generation import window
from datarefinery.recipe.models import FeaturizationOp, Recipe

_SR = 16000
_N_MELS = 64
_HOP = 256


def _write_clip(path: Path, *, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(_SR * seconds)
    sf.write(path, np.linspace(0.0, 1.0, n, endpoint=False).astype(np.float32), _SR)


_WINDOW_GEN: dict[str, Any] = {
    "name": "win",
    "op": "window",
    "inputs": ["sample_array"],
    "output_schema": "matches_input",
    "seed": 0,
    "splits": ["train", "val", "test"],
    "replace_input_records": True,
    "params": {"window_length_samples": 1600, "hop_samples": 1600, "remainder": "drop"},
}
_FEATURIZE: dict[str, Any] = {
    "name": "logmel",
    "op": "log_mel_spectrogram",
    "inputs": ["sample_array"],
    "output_field": "feature",
    "params": {"n_fft": 512, "hop_length": _HOP, "n_mels": _N_MELS, "f_min": 0.0, "power": 2.0},
    "splits": ["train", "val", "test"],
}


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
            "Generation": [_WINDOW_GEN],
            "Featurizations": [_FEATURIZE],
        }
    )


def test_featurization_does_not_change_record_count(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    _write_clip(root / "cat" / "a.wav", seconds=0.3)  # 3 windows
    _write_clip(root / "cat" / "b.wav", seconds=0.2)  # 2 windows
    _write_clip(root / "dog" / "c.wav", seconds=0.5)  # 5 windows

    recipe = _recipe(root)
    loaded, hashes = load_raw_records(recipe, AUDIO_PLUGIN)
    records: list[Mapping[str, Any]] = list(loaded)

    cache_root = tmp_path / "cache"
    runner = PipelineRunner(
        recipe=recipe, plugin=AUDIO_PLUGIN, config=RuntimeConfig(cache_root=cache_root), seed=7
    )
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=hashes)

    manifest = read_manifest(manifest_path(result.instance_dir))
    # 10 windows post-Generation; the Featurization stage is one-output-per-input,
    # so the final count is still 10 (the feature is added, not fanned out).
    assert sum(manifest.record_counts.values()) == 10


def _windowed(root: Path) -> list[Mapping[str, Any]]:
    recipe = _recipe(root)
    loaded, _ = load_raw_records(recipe, AUDIO_PLUGIN)
    return window(
        list(loaded),
        seed=0,
        inputs=["sample_array"],
        output_schema={},
        params=_WINDOW_GEN["params"],
        label_field="label",
        op_name="win",
    )


def test_feature_shape_and_determinism_through_the_stage(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    _write_clip(root / "cat" / "a.wav", seconds=0.3)
    _write_clip(root / "dog" / "c.wav", seconds=0.5)
    windows = _windowed(root)
    assert windows, "fixture should produce at least one window"

    op = FeaturizationOp.model_validate({**_FEATURIZE, "splits": ["train"]})

    def _featurize() -> Mapping[str, list[Mapping[str, Any]]]:
        return apply_featurizations(
            {"train": list(windows)},
            [op],
            plugin=AUDIO_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path / "stats"),
            label_field="label",
        ).splits

    first = _featurize()["train"]
    # One feature output per input window; shape is (n_mels, n_frames).
    assert len(first) == len(windows)
    for r in first:
        feat = r["feature"]
        assert feat.shape[0] == _N_MELS
        assert feat.shape == (_N_MELS, 1 + 1600 // _HOP)

    # Byte-identical across a re-run (pure function → worker-count invariant).
    second = _featurize()["train"]
    for a, b in zip(first, second, strict=True):
        assert np.array_equal(a["feature"], b["feature"])
