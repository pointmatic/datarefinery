# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.p: audio input + decode end-to-end through the loader dispatch.

Exercises the full `pipeline.inputs.load_raw_records` path for the
`audio_classification` plugin: a tiny class-subdir fixture with clips recorded
at mixed source rates loads, decodes, and canonicalizes to the recipe-declared
`target_sample_rate`. Requires the `[audio]` extra (librosa); skips without it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("librosa")
pytest.importorskip("soundfile")

import soundfile as sf

from datarefinery.pipeline.inputs import load_raw_records
from datarefinery.plugins.audio_classification import PLUGIN as AUDIO_PLUGIN
from datarefinery.recipe.models import Recipe


def _write_wav(path: Path, *, sr: int, seconds: float = 0.1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0.0, seconds, int(sr * seconds), endpoint=False)
    sf.write(path, (0.5 * np.sin(2 * np.pi * 330.0 * t)).astype(np.float32), sr)


def _recipe(root: Path, *, target_sample_rate: int = 16000) -> Recipe:
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
                        "target_sample_rate": target_sample_rate,
                    }
                ]
            },
            "Output": {"record_schema": {"label": {"dtype": "str"}}},
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.6, "val": 0.2, "test": 0.2}},
        }
    )


def test_mixed_rate_audio_folder_loads_and_canonicalizes(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    # 3 clips across 2 classes, recorded at three different source rates.
    _write_wav(root / "cat" / "a.wav", sr=22050)
    _write_wav(root / "cat" / "b.wav", sr=8000)
    _write_wav(root / "dog" / "c.wav", sr=44100)

    records, hashes = load_raw_records(_recipe(root, target_sample_rate=16000), AUDIO_PLUGIN)

    # (count, sample_rate, shape) expectations.
    assert len(records) == 3
    assert {r["sample_rate"] for r in records} == {16000}
    for r in records:
        assert r["sample_array"].ndim == 1  # mono
        assert abs(len(r["sample_array"]) - 1600) <= 8  # ~0.1s @ 16 kHz
    assert {r["label"] for r in records} == {"cat", "dog"}
    assert len(hashes["clips"]) == 64


def test_input_hash_is_stable_across_loads(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    _write_wav(root / "cat" / "a.wav", sr=22050)
    _, h1 = load_raw_records(_recipe(root), AUDIO_PLUGIN)
    _, h2 = load_raw_records(_recipe(root), AUDIO_PLUGIN)
    assert h1 == h2  # content hash is order-stable / deterministic
