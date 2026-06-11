# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-J-1 SampleData runtime end-to-end (Story J.a).

P-postpipeline + M-sidecar: a recipe declaring ``SampleData:`` produces
a full materialized ``dataset/`` AND a sidecar ``sample/`` subset under
the same instance directory, plus a ``manifest.sample`` entry naming
the selector and per-split sampled record counts.

Determinism contract: same recipe + seed + inputs -> byte-identical
``sample/*.jsonl`` across runs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from datarefinery.cache.layout import (
    dataset_dir,
    manifest_path,
    sample_dir,
)
from datarefinery.cache.layout import (
    tmp_dir as tmp_dir_for,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe


def _img(value: int) -> np.ndarray:
    return np.full((4, 4, 3), value, dtype=np.uint8)


def _records(n: int = 60, classes: int = 3) -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": _img(20 + i),
            "label": f"c{i % classes}",
            "path": f"/data/c{i % classes}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _recipe_with_sample_data(selector: dict[str, Any]) -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [
                    {
                        "name": "train",
                        "type": "image_folder",
                        "path": "/data/train",
                    }
                ]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {
                "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
                "seed": 11,
            },
            "SampleData": {"selector": selector},
        }
    )


def _config(cache_root: Path) -> RuntimeConfig:
    return RuntimeConfig(cache_root=cache_root)


# ---------------------------------------------------------------------------
# End-to-end: dataset/ unchanged + sample/ produced
# ---------------------------------------------------------------------------


def test_sample_data_emits_sidecar_without_disturbing_dataset(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe_with_sample_data({"n": 3, "kind": "per_class", "splits": ["train"]})
    records = _records(60)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    # Full dataset present and unchanged in shape: 60 records split 60/20/20.
    ds = dataset_dir(result.instance_dir)
    train_lines = (ds / "train.jsonl").read_text().splitlines()
    val_lines = (ds / "val.jsonl").read_text().splitlines()
    test_lines = (ds / "test.jsonl").read_text().splitlines()
    assert len(train_lines) + len(val_lines) + len(test_lines) == 60

    # Sample sidecar present: train sampled to 3 per class * 3 classes = 9; no other splits.
    sd = sample_dir(result.instance_dir)
    assert (sd / "train.jsonl").exists()
    assert not (sd / "val.jsonl").exists()
    assert not (sd / "test.jsonl").exists()
    sample_train = (sd / "train.jsonl").read_text().splitlines()
    assert len(sample_train) == 9
    sampled_labels: dict[str, int] = {}
    for line in sample_train:
        rec = json.loads(line)
        sampled_labels[rec["label"]] = sampled_labels.get(rec["label"], 0) + 1
    assert sampled_labels == {"c0": 3, "c1": 3, "c2": 3}


def test_sample_data_manifest_entry_present_and_well_formed(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe_with_sample_data({"n": 4, "kind": "uniform"})
    records = _records(60)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    m = read_manifest(manifest_path(result.instance_dir))
    assert m.sample is not None
    assert m.sample.selector["kind"] == "uniform"
    assert m.sample.selector["n"] == 4
    assert m.sample.selector["splits"] is None
    # Default splits => sample every split.
    assert set(m.sample.record_counts.keys()) == {"train", "val", "test"}
    for count in m.sample.record_counts.values():
        assert count <= 4


def test_manifest_sample_is_none_when_recipe_omits_sample_data(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = Recipe.model_validate(
        {
            "schema_version": 1,
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
            "Splits": {"ratios": {"train": 1.0}, "seed": 11},
        }
    )
    records = _records(10)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    m = read_manifest(manifest_path(result.instance_dir))
    assert m.sample is None
    assert not sample_dir(result.instance_dir).exists()


def test_sample_jsonl_is_byte_identical_across_runs(tmp_path: Path) -> None:
    """Determinism: same recipe + seed + inputs -> identical sample bytes."""
    recipe = _recipe_with_sample_data({"n": 5, "kind": "uniform"})
    records = _records(60)

    def _bytes_for_run(label: str) -> bytes:
        cache_root = tmp_path / f"cache_{label}"
        runner = PipelineRunner(
            recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7
        )
        temp = tmp_dir_for(cache_root, f"run-{label}")
        result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
        return (sample_dir(result.instance_dir) / "train.jsonl").read_bytes()

    assert _bytes_for_run("a") == _bytes_for_run("b")
