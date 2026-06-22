# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.t: `audio_normalize` fit-on-train normalization through the pipeline.

`audio_normalize` is a fit-on-train Featurization that runs after
`log_mel_spectrogram` (convention: `mel` → `feature`). Three checks:

1. Full materialize (needs `[audio]`): decode → window → log_mel(mel) →
   audio_normalize(feature) fits on train, persists `fitted_statistics/<op>/`.
2. Fit-on-train parity (pure numpy): val records are normalized with the
   *train*-fitted per-mel-bin statistics, byte-identically across a re-run.
3. `stats_from_instance` read-through (pure numpy): a consumer recipe imports a
   sibling instance's audio-normalize statistics without re-fitting and without
   copying them into its own `fitted_statistics/` (FR-ARCH-1 loose coupling).
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from datarefinery.cache.identity import CacheKey
from datarefinery.cache.layout import fitted_stats_dir, instance_dir, manifest_path
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.manifest import Manifest, write_manifest
from datarefinery.pipeline.stages.featurizations import apply_featurizations
from datarefinery.plugins.audio_classification import PLUGIN as AUDIO_PLUGIN
from datarefinery.recipe.loader import load as load_recipe
from datarefinery.recipe.models import FeaturizationOp
from datarefinery.recipe.overlays import apply_overlays
from datarefinery.recipe.segments import recipe_identity_hash

_N_MELS = 4
_N_FRAMES = 3


def _mel(seed: int) -> np.ndarray:
    return (np.arange(_N_MELS * _N_FRAMES, dtype=np.float64) + seed).reshape(_N_MELS, _N_FRAMES)


def _record(seed: int) -> Mapping[str, Any]:
    return {"record_id": f"r{seed}", "source_record_id": "clip", "mel": _mel(seed), "label": "cat"}


def _norm_op(**overrides: Any) -> FeaturizationOp:
    base: dict[str, Any] = {
        "name": "norm",
        "inputs": ["mel"],
        "output_field": "feature",
        "op": "audio_normalize",
        "params": {},
        "fit_source": "train",
        "splits": ["train", "val"],
    }
    base.update(overrides)
    return FeaturizationOp.model_validate(base)


# --------------------------------------------------------------------------- #
# 1. Full materialize + fit-on-train persistence (needs librosa)
# --------------------------------------------------------------------------- #


def test_full_materialize_persists_per_mel_bin_stats(tmp_path: Path) -> None:
    pytest.importorskip("librosa")
    pytest.importorskip("soundfile")
    import soundfile as sf

    from datarefinery.cache.layout import tmp_dir as tmp_dir_for
    from datarefinery.core.config import RuntimeConfig
    from datarefinery.pipeline.inputs import load_raw_records
    from datarefinery.pipeline.runner import PipelineRunner
    from datarefinery.recipe.models import Recipe

    root = tmp_path / "clips"
    for cls in ("cat", "dog"):
        for i in range(2):
            p = root / cls / f"{cls}{i}.wav"
            p.parent.mkdir(parents=True, exist_ok=True)
            sf.write(p, np.linspace(0.0, 1.0, 8000, endpoint=False).astype(np.float32), 16000)

    n_mels = 32
    recipe = Recipe.model_validate(
        {
            "schema_version": 3,
            "plugin": "audio_classification",
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
            "Output": {"record_schema": {"label": {"dtype": "str"}}},
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
                },
                {
                    "name": "norm",
                    "op": "audio_normalize",
                    "inputs": ["mel"],
                    "output_field": "feature",
                    "fit_source": "train",
                    "splits": ["train", "val"],
                },
            ],
        }
    )
    loaded, hashes = load_raw_records(recipe, AUDIO_PLUGIN)
    cache_root = tmp_path / "cache"
    runner = PipelineRunner(
        recipe=recipe, plugin=AUDIO_PLUGIN, config=RuntimeConfig(cache_root=cache_root), seed=7
    )
    result = runner.run(
        tmp_dir_for(cache_root, "run-1"), raw_records=list(loaded), raw_input_hashes=hashes
    )

    op_dir = fitted_stats_dir(result.instance_dir) / "norm"
    mean = FittedStatistics(fitted_stats_dir(result.instance_dir)).get_vector("norm", "mean")
    std = FittedStatistics(fitted_stats_dir(result.instance_dir)).get_vector("norm", "std")
    assert (op_dir / "mean.parquet").exists() and (op_dir / "std.parquet").exists()
    # Per-mel-bin vectors: one value per mel bin.
    assert len(mean["value"]) == n_mels
    assert len(std["value"]) == n_mels


# --------------------------------------------------------------------------- #
# 2. Fit-on-train parity: val normalized with TRAIN statistics
# --------------------------------------------------------------------------- #


def test_val_is_normalized_with_train_fitted_stats(tmp_path: Path) -> None:
    train = [_record(0), _record(10), _record(100)]
    val = [_record(3), _record(50)]
    splits: dict[str, list[Mapping[str, Any]]] = {"train": list(train), "val": list(val)}

    def _run() -> Mapping[str, list[Mapping[str, Any]]]:
        return apply_featurizations(
            {k: list(v) for k, v in splits.items()},
            [_norm_op()],
            plugin=AUDIO_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path / "stats"),
            label_field="label",
        ).splits

    out = _run()
    # Reference: per-mel-bin mean/std fit on TRAIN only.
    train_stack = np.stack([r["mel"] for r in train])
    tmean = train_stack.mean(axis=(0, 2))
    tstd = np.where(train_stack.std(axis=(0, 2)) == 0, 1.0, train_stack.std(axis=(0, 2)))
    for r in out["val"]:
        expected = (r["mel"] - tmean[:, None]) / tstd[:, None]
        np.testing.assert_allclose(r["feature"], expected)
    # Byte-identical across a re-run (deterministic).
    rerun = _run()
    for a, b in zip(out["val"], rerun["val"], strict=True):
        np.testing.assert_array_equal(a["feature"], b["feature"])


# --------------------------------------------------------------------------- #
# 3. stats_from_instance read-through (loose coupling, FR-ARCH-1)
# --------------------------------------------------------------------------- #

_SIBLING_RECIPE_YAML = textwrap.dedent(
    """\
    schema_version: 3
    plugin: audio_classification
    seed: 0
    Input:
      sources:
        - name: clips
          type: audio_folder
          path: /data/clips
          target_sample_rate: 16000
    Output:
      record_schema:
        label: {dtype: str}
    Labels:
      field: label
      source: {kind: direct}
    Splits:
      ratios: {train: 0.5, val: 0.5}
    Featurizations:
      - name: norm
        op: audio_normalize
        inputs: [mel]
        output_field: feature
        fit_source: train
        splits: [train, val]
    """
)


def _build_sibling(
    cache_root: Path, recipe_path: Path, op_id: str
) -> tuple[np.ndarray, np.ndarray]:
    recipe_path.write_text(_SIBLING_RECIPE_YAML, encoding="utf-8")
    recipe_hash = recipe_identity_hash(apply_overlays(load_recipe(recipe_path), None))
    key = CacheKey(recipe_hash=recipe_hash, input_hash="a" * 64, seed=7)
    inst = instance_dir(cache_root, key)
    inst.mkdir(parents=True, exist_ok=True)
    write_manifest(
        manifest_path(inst),
        Manifest(
            datarefinery_version="0.0.0-test",
            plugin="audio_classification",
            plugin_version="1",
            recipe_hash=recipe_hash,
            input_hash="a" * 64,
            seed=7,
            created_at=datetime(2026, 6, 22, tzinfo=UTC),
            elapsed_seconds=0.0,
            record_counts={"train": 1},
        ),
    )
    import pyarrow as pa

    mean = np.array([1.0, 2.0, 3.0, 4.0])
    std = np.array([2.0, 4.0, 5.0, 10.0])
    fs = FittedStatistics(fitted_stats_dir(inst))
    fs.put_vector(op_id, "mean", pa.table({"value": mean.tolist()}))
    fs.put_vector(op_id, "std", pa.table({"value": std.tolist()}))
    return mean, std


def test_stats_from_instance_reads_through_without_refit_or_copy(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    sibling_path = tmp_path / "sibling_recipe.yaml"
    mean, std = _build_sibling(cache_root, sibling_path, op_id="norm")

    consumer = _norm_op(
        name="norm_consumer",
        params={"stats_from_instance": {"recipe": str(sibling_path), "op_id": "norm"}},
    )
    val = [_record(3), _record(50)]
    fs = FittedStatistics(tmp_path / "consumer_stats")
    result = apply_featurizations(
        {"train": [_record(0)], "val": list(val)},
        [consumer],
        plugin=AUDIO_PLUGIN,
        fitted_stats=fs,
        label_field="label",
        cache_root=cache_root,
    )
    # Applied with the SIBLING's stats (not re-fit locally).
    for r in result.splits["val"]:
        expected = (r["mel"] - mean[:, None]) / std[:, None]
        np.testing.assert_allclose(r["feature"], expected)
    # Read-through: no persistence into the consumer's fitted_statistics/.
    assert "norm_consumer" not in result.fitted_op_ids
    assert not (tmp_path / "consumer_stats" / "norm_consumer").exists()
