# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story K.c: `npy_per_record` float-array sink + `feature_path` rewrite.

End-to-end through the audio pipeline (decode -> window -> log_mel(mel)):
a `Sinks` block persists the raw `mel` per record as a `float32` `.npy`
under `<instance>/features/<split>/<record_id>.npy`, and the dataset
writer rewrites an instance-root-relative `feature_path` into the JSONL.

Covers the Story K.c test checklist: byte-identical `.npy` across runs
(same recipe + inputs + seed); a changed featurization param shifts the
recipe identity (cache miss); `(n_mels, n_frames)` `float32` on disk;
nested `feature_path` round-trips; manifest reports the new format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from datarefinery.recipe.segments import recipe_identity_hash

_N_MELS = 8


def _recipe_dict(root: Path, *, n_mels: int = _N_MELS) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "plugin": "audio_classification",
        "seed": 0,
        "Input": {
            "sources": [
                {
                    "name": "clips",
                    "type": "audio_folder",
                    "path": str(root),
                    "target_sample_rate": 16000,
                }
            ]
        },
        "Output": {
            "record_schema": {"sample_array": {"dtype": "float32"}, "label": {"dtype": "str"}}
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {"ratios": {"train": 0.5, "val": 0.5}},
        "Generation": [
            {
                "name": "win",
                "op": "window",
                "inputs": ["sample_array"],
                "output_schema": "matches_input",
                "seed": 0,
                "splits": ["train", "val"],
                "replace_input_records": True,
                "params": {
                    "window_length_samples": 1600,
                    "hop_samples": 1600,
                    "remainder": "drop",
                },
            }
        ],
        "Featurizations": [
            {
                "name": "logmel",
                "op": "log_mel_spectrogram",
                "inputs": ["sample_array"],
                "output_field": "mel",
                "params": {
                    "n_fft": 512,
                    "hop_length": 256,
                    "n_mels": n_mels,
                    "f_min": 0.0,
                    "power": 2.0,
                },
                "splits": ["train", "val"],
            }
        ],
        "Sinks": [
            {
                "name": "feats",
                "stage": "post_Featurizations",
                "field": "mel",
                "format": "npy_per_record",
                "path_template": "features/{split}/{record_id}.npy",
            }
        ],
    }


def _build_clips(root: Path) -> None:
    import soundfile as sf

    for cls in ("cat", "dog"):
        for i in range(2):
            p = root / cls / f"{cls}{i}.wav"
            p.parent.mkdir(parents=True, exist_ok=True)
            sf.write(p, np.linspace(0.0, 1.0, 8000, endpoint=False).astype(np.float32), 16000)


def _materialize(recipe_dict: dict[str, Any], cache_root: Path, run_label: str) -> Path:
    from datarefinery.cache.layout import tmp_dir as tmp_dir_for
    from datarefinery.core.config import RuntimeConfig
    from datarefinery.pipeline.inputs import load_raw_records
    from datarefinery.pipeline.runner import PipelineRunner
    from datarefinery.plugins.audio_classification import PLUGIN as AUDIO_PLUGIN
    from datarefinery.recipe.models import Recipe

    recipe = Recipe.model_validate(recipe_dict)
    loaded, hashes = load_raw_records(recipe, AUDIO_PLUGIN)
    runner = PipelineRunner(
        recipe=recipe, plugin=AUDIO_PLUGIN, config=RuntimeConfig(cache_root=cache_root), seed=7
    )
    result = runner.run(
        tmp_dir_for(cache_root, run_label), raw_records=list(loaded), raw_input_hashes=hashes
    )
    return result.instance_dir


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_npy_sink_end_to_end(tmp_path: Path) -> None:
    pytest.importorskip("librosa")
    pytest.importorskip("soundfile")

    root = tmp_path / "clips"
    _build_clips(root)
    inst = _materialize(_recipe_dict(root), tmp_path / "cache", "run-1")

    # Every persisted record carries an instance-root-relative feature_path
    # that resolves to a float32 (n_mels, n_frames) array on disk.
    rows = _read_jsonl(inst / "dataset" / "train.jsonl")
    assert rows, "expected windowed train records"
    for r in rows:
        assert "feature_path" in r, "npy sink must rewrite feature_path into the JSONL"
        fpath = inst / r["feature_path"]
        assert fpath.exists(), (
            f"feature_path must resolve under the instance root: {r['feature_path']}"
        )
        arr = np.load(fpath)
        assert arr.dtype == np.float32
        assert arr.ndim == 2 and arr.shape[0] == _N_MELS


def test_npy_sink_feature_path_is_instance_relative_under_features(tmp_path: Path) -> None:
    pytest.importorskip("librosa")
    pytest.importorskip("soundfile")

    root = tmp_path / "clips"
    _build_clips(root)
    inst = _materialize(_recipe_dict(root), tmp_path / "cache", "run-1")
    rows = _read_jsonl(inst / "dataset" / "train.jsonl")
    for r in rows:
        # NOT dataset/-relative; lives in the sibling features/ bucket.
        assert r["feature_path"].startswith("features/train/")
        assert r["feature_path"].endswith(".npy")


def test_npy_sink_byte_identical_across_runs(tmp_path: Path) -> None:
    pytest.importorskip("librosa")
    pytest.importorskip("soundfile")

    root = tmp_path / "clips"
    _build_clips(root)
    inst_a = _materialize(_recipe_dict(root), tmp_path / "cache_a", "run-a")
    inst_b = _materialize(_recipe_dict(root), tmp_path / "cache_b", "run-b")

    rows_a = _read_jsonl(inst_a / "dataset" / "train.jsonl")
    rows_b = _read_jsonl(inst_b / "dataset" / "train.jsonl")
    feats_a = {r["feature_path"]: (inst_a / r["feature_path"]).read_bytes() for r in rows_a}
    feats_b = {r["feature_path"]: (inst_b / r["feature_path"]).read_bytes() for r in rows_b}
    assert feats_a.keys() == feats_b.keys()
    assert feats_a == feats_b, "same recipe + inputs + seed must yield byte-identical .npy"


def test_changed_featurization_param_changes_recipe_identity(tmp_path: Path) -> None:
    # A changed featurization param shifts the recipe identity hash, so the
    # materialization lands in a different instance dir (a cache miss) — the
    # feature bytes are part of the (recipe_hash, input_hash, seed) identity.
    from datarefinery.recipe.models import Recipe

    root = tmp_path / "clips"
    a = recipe_identity_hash(Recipe.model_validate(_recipe_dict(root, n_mels=8)))
    b = recipe_identity_hash(Recipe.model_validate(_recipe_dict(root, n_mels=16)))
    assert a != b


def test_npy_sink_manifest_reports_format(tmp_path: Path) -> None:
    pytest.importorskip("librosa")
    pytest.importorskip("soundfile")

    root = tmp_path / "clips"
    _build_clips(root)
    inst = _materialize(_recipe_dict(root), tmp_path / "cache", "run-1")
    manifest = json.loads((inst / "manifest.json").read_text())
    assert manifest["sinks"]["feats"]["format"] == "npy_per_record"
