# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.p: audio input sources + decode.

`audio_folder` (class-subdir labels) and `audio_flat` (+`label_from`) mirror the
image source kinds; the decode step (librosa, loader-side) canonicalizes every
clip to its source's declared `target_sample_rate` and emits
`{record_id, sample_array, sample_rate, path[, label]}`. These tests require the
`[audio]` extra (librosa + soundfile); they skip cleanly without it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("librosa")
pytest.importorskip("soundfile")

import soundfile as sf

from datarefinery.core.errors import RecipeError
from datarefinery.plugins.audio_classification.inputs import (
    load_audio_records,
)
from datarefinery.recipe.models import AudioSource, InputSource


def _write_wav(path: Path, *, sr: int, seconds: float = 0.1, freq: float = 440.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0.0, seconds, int(sr * seconds), endpoint=False)
    sf.write(path, np.sin(2 * np.pi * freq * t).astype(np.float32), sr)


def _audio_folder(root: Path, *, classes: dict[str, int]) -> None:
    """Build a class-subdir audio_folder. `classes` maps class name → source sr."""
    for cls, sr in classes.items():
        _write_wav(root / cls / f"{cls}_0.wav", sr=sr)


def _source(root: Path, *, target_sample_rate: int = 16000, **kw: Any) -> AudioSource:
    return AudioSource.model_validate(
        {
            "name": "clips",
            "type": "audio_folder",
            "path": str(root),
            "target_sample_rate": target_sample_rate,
            **kw,
        }
    )


def test_audio_folder_decodes_with_clip_level_labels(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    _audio_folder(root, classes={"cat": 22050, "dog": 22050})
    records, hashes = load_audio_records([_source(root)], attach_label=True)

    assert len(records) == 2
    assert {r["label"] for r in records} == {"cat", "dog"}
    for r in records:
        assert isinstance(r["sample_array"], np.ndarray)
        assert r["sample_rate"] == 16000  # canonicalized to target
        assert r["record_id"].startswith("clips/")
        assert r["path"].endswith(".wav")
    assert "clips" in hashes and len(hashes["clips"]) == 64


def test_decode_resamples_to_target_rate_deterministically(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    _audio_folder(root, classes={"cat": 22050})
    a, _ = load_audio_records([_source(root, target_sample_rate=16000)], attach_label=True)
    b, _ = load_audio_records([_source(root, target_sample_rate=16000)], attach_label=True)
    # Same bytes + same target → byte-identical decoded array (determinism contract).
    assert np.array_equal(a[0]["sample_array"], b[0]["sample_array"])
    # A 0.1s clip resampled to 16 kHz is ~1600 samples (resampler edge effects
    # may shift by a few); assert it is in the canonicalized neighborhood.
    assert abs(len(a[0]["sample_array"]) - 1600) <= 8


def test_different_source_rates_canonicalize_to_one_target(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    # Two clips recorded at different source rates...
    _write_wav(root / "cat" / "a.wav", sr=22050)
    _write_wav(root / "cat" / "b.wav", sr=8000)
    records, _ = load_audio_records([_source(root, target_sample_rate=16000)], attach_label=True)
    assert len(records) == 2
    # ...both land at the single recipe-declared target rate.
    assert {r["sample_rate"] for r in records} == {16000}


def test_unlabeled_audio_folder_attaches_no_label(tmp_path: Path) -> None:
    root = tmp_path / "infer"
    _write_wav(root / "clip_0.wav", sr=16000)
    src = AudioSource.model_validate(
        {
            "name": "infer",
            "type": "audio_flat",
            "path": str(root),
            "target_sample_rate": 16000,
            "unlabeled": True,
            "partition": "holdout",
        }
    )
    records, _ = load_audio_records([src], attach_label=False)
    assert len(records) == 1
    assert "label" not in records[0]
    assert records[0]["partition"] == "holdout"


def test_non_audio_source_without_target_sample_rate_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    _write_wav(root / "cat" / "a.wav", sr=16000)
    # A plain InputSource (no target_sample_rate) reaching the audio loader is a
    # recipe error — the canonical sample rate is required for audio.
    plain = InputSource.model_validate({"name": "clips", "type": "audio_folder", "path": str(root)})
    with pytest.raises(RecipeError, match="target_sample_rate"):
        load_audio_records([plain], attach_label=True)


def test_audio_flat_by_id_label_from_manifest(tmp_path: Path) -> None:
    root = tmp_path / "flat"
    _write_wav(root / "c0.wav", sr=16000)
    _write_wav(root / "c1.wav", sr=22050)
    manifest = tmp_path / "labels.csv"
    manifest.write_text("clip_id,label\nc0,cat\nc1,dog\n", encoding="utf-8")
    src = AudioSource.model_validate(
        {
            "name": "clips",
            "type": "audio_flat",
            "path": str(root),
            "target_sample_rate": 16000,
            "label_from": {
                "path": str(manifest),
                "join": "by_id",
                "id_field": "clip_id",
                "label_field": "label",
            },
        }
    )
    records, hashes = load_audio_records([src], attach_label=True)
    by_id = {r["record_id"].split("/")[-1]: r["label"] for r in records}
    assert by_id == {"c0.wav": "cat", "c1.wav": "dog"}
    # The manifest bytes participate in the source content hash.
    assert len(hashes["clips"]) == 64


def test_audio_flat_by_row_order_label_from_manifest(tmp_path: Path) -> None:
    root = tmp_path / "flat"
    _write_wav(root / "a.wav", sr=16000)
    _write_wav(root / "b.wav", sr=16000)
    manifest = tmp_path / "labels.csv"
    # Headerless, recipe-supplied column names; row order aligns with sorted files.
    manifest.write_text("cat\ndog\n", encoding="utf-8")
    src = AudioSource.model_validate(
        {
            "name": "clips",
            "type": "audio_flat",
            "path": str(root),
            "target_sample_rate": 16000,
            "label_from": {
                "path": str(manifest),
                "join": "by_row_order",
                "header": ["label"],
                "label_field": "label",
            },
        }
    )
    records, _ = load_audio_records([src], attach_label=True)
    ordered = [r["label"] for r in sorted(records, key=lambda r: r["record_id"])]
    assert ordered == ["cat", "dog"]


def test_hash_audio_sources_matches_load_hashes(tmp_path: Path) -> None:
    from datarefinery.plugins.audio_classification.inputs import hash_audio_sources

    root = tmp_path / "clips"
    _audio_folder(root, classes={"cat": 16000})
    src = _source(root)
    _, load_hashes = load_audio_records([src], attach_label=True)
    # The decode-free hash equals the hash returned by the full load.
    assert hash_audio_sources([src]) == load_hashes
