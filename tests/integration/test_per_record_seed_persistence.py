# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story I.e end-to-end: per-record seed persists into cached JSONL,
and replaying the recorded seed reproduces the corruption bit-identically.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("cv2", reason="requires the [corruptions] extras")

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
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.image_classification._corruptions import corrupt
from datarefinery.recipe.models import Recipe


def _img(value: int) -> np.ndarray:
    return np.full((32, 32, 3), value, dtype=np.uint8)


def _records(n: int = 6) -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": _img(20 + i * 5),
            "label": f"c{i % 2}",
            "path": f"/data/c{i % 2}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _recipe() -> Recipe:
    # Single (corruption, severity) so the first (and only) corrupt()
    # call for each input record consumes RNG state from the seed —
    # cleanly replayable from the stamped seed without walking a multi-
    # combo sequence. The Story I.e contract is "seed is recorded";
    # multi-combo replays still work but require the consumer to walk
    # the deterministic order.
    return Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {
                "ratios": {"train": 0.5, "val": 0.25, "test": 0.25},
                "seed": 11,
            },
            "Generation": [
                {
                    "name": "imagecorruptions_apply",
                    "inputs": ["image"],
                    "output_schema": {
                        "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                        "label": {"dtype": "str"},
                    },
                    "seed": 42,
                    "applies_at": ["train"],
                    "params": {
                        "corruption_types": ["gaussian_noise"],
                        "severities": [3],
                        "preserve_original": False,
                        "tag_fields": ["corruption", "severity", "source_path"],
                    },
                }
            ],
            "Sinks": [
                # Capture uint8 corrupted bytes at post_Generation so the
                # bit-identical recompute test has an authoritative
                # in-cache reference.
                {
                    "name": "corrupted_pngs",
                    "stage": "post_Generation",
                    "splits": ["train"],
                    "field": "image",
                    "format": "png_per_record",
                    "path_template": "exports/{record_id}.png",
                }
            ],
        }
    )


def test_cached_records_carry_op_name_seed_field(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(6)
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    inst = result.instance_dir

    manifest = read_manifest(manifest_path(inst))
    assert manifest.cache_hit is False if hasattr(manifest, "cache_hit") else True

    train_lines = (dataset_dir(inst) / "train.jsonl").read_text().splitlines()
    corrupted = [json.loads(line) for line in train_lines if "corruption" in json.loads(line)]
    assert corrupted, "expected at least one corrupted record in train split"
    for r in corrupted:
        assert "imagecorruptions_apply_seed" in r, sorted(r.keys())
        assert isinstance(r["imagecorruptions_apply_seed"], int)
        # 64-bit unsigned int range.
        assert 0 <= r["imagecorruptions_apply_seed"] < 2**64


def test_replaying_stamped_seed_reproduces_corruption_bit_identically(tmp_path: Path) -> None:
    """Read the recorded `imagecorruptions_apply_seed` from a cached record, replay
    `corrupt(...)` with a fresh RNG seeded from it, and assert the
    result matches the post-Generation sink output byte-for-byte."""
    from PIL import Image

    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(6)
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    inst = result.instance_dir

    train_lines = (dataset_dir(inst) / "train.jsonl").read_text().splitlines()
    parsed = [json.loads(line) for line in train_lines]
    by_id = {r["record_id"]: r for r in parsed}

    # The post_Generation sink wrote uint8 bytes per corrupted record.
    sink_root = inst / "exports"
    pngs = list(sink_root.glob("*.png"))
    assert pngs, "expected post_Generation sink output"

    # Build a lookup of input record image bytes for the replay.
    input_by_id = {r["record_id"]: r["image"] for r in records}

    checked = 0
    for png_path in pngs:
        rid = png_path.stem
        cached_record = by_id[rid]
        if cached_record.get("corruption") != "gaussian_noise":
            continue
        source_rid = rid.split("_gaussian_noise_")[0]
        source_image = input_by_id[source_rid]
        seed = cached_record["imagecorruptions_apply_seed"]

        reproduced = corrupt(
            source_image,
            corruption_name="gaussian_noise",
            severity=3,
            rng=np.random.default_rng(seed),
        )
        expected = np.array(Image.open(png_path))
        np.testing.assert_array_equal(
            reproduced,
            expected,
            err_msg=(
                f"replayed corruption for record_id={rid!r} did not match "
                f"the sink-captured PNG bytes — per-record seed persistence "
                f"contract broken (Story I.e)"
            ),
        )
        checked += 1
    assert checked > 0, "expected to replay at least one corrupted record"
