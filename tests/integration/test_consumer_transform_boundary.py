# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.g: consumer-applied transformations boundary (end-to-end).

A lazy-mode recipe with a pixel-altering Transformation (``resize``) plus
a qualifying image sink materializes an instance where each record's
``path`` points at the sink's per-record PNG. A consumer reading the
JSONL ``path``, decoding the PNG, gets pixels byte-identical to the
in-memory transformed array — never the diverged pre-resize source.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from datarefinery.cache.identity import compute_cache_key
from datarefinery.cache.layout import dataset_dir, instance_dir
from datarefinery.cache.layout import tmp_dir as tmp_dir_for
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe


def _gradient(i: int) -> np.ndarray:
    # Non-uniform so resize genuinely changes the pixels (a uniform
    # image would survive resize unchanged and hide the divergence).
    base = (np.arange(48).reshape(4, 4, 3) + i) % 256
    return base.astype(np.uint8)


def _records(n: int = 15) -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": _gradient(i),
            "label": f"c{i % 3}",
            "path": f"/data/source/c{i % 3}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _expected_resize(arr: np.ndarray, size: int) -> np.ndarray:
    return np.asarray(Image.fromarray(arr).resize((size, size), resample=Image.Resampling.BILINEAR))


def _recipe() -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 2,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [8, 8, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.6, "val": 0.2, "test": 0.2}, "seed": 11},
            "Transformations": [
                {
                    "name": "r",
                    "op": "resize",
                    "params": {"size": 8, "method": "bilinear"},
                    "splits": ["train", "val", "test"],
                }
            ],
            "Sinks": [
                {
                    "name": "transformed",
                    "stage": "post_Transformations",
                    "field": "image",
                    "format": "png_per_record",
                    "path_template": "transformed/{split}/{record_id}.png",
                }
            ],
        }
    )


def test_path_resolves_to_transformed_pixels(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records()
    config = RuntimeConfig(cache_root=cache_root)
    cache_key = compute_cache_key(recipe, _input_hashes(records), recipe.seed)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=config, seed=recipe.seed)
    result = runner.run(
        tmp_dir_for(cache_root, "run-1"),
        raw_records=records,
        raw_input_hashes=_input_hashes(records),
    )
    inst = result.instance_dir
    assert inst == instance_dir(cache_root, cache_key)

    # Expected transformed pixels, keyed by record_id.
    expected = {r["record_id"]: _expected_resize(r["image"], 8) for r in records}

    rows_seen = 0
    for split in ("train", "val", "test"):
        jsonl = dataset_dir(inst) / f"{split}.jsonl"
        for line in jsonl.read_text().splitlines():
            row = json.loads(line)
            rows_seen += 1
            # path is rewritten to the sink output, not the source.
            assert row["path"] == f"transformed/{split}/{row['record_id']}.png"
            assert not row["path"].startswith("/data/source")
            # The numpy image field is dropped from JSONL as before.
            assert "image" not in row
            # Consumer resolves path relative to the instance dir, decodes,
            # and gets byte-identical transformed pixels.
            decoded = np.asarray(Image.open(inst / row["path"]))
            np.testing.assert_array_equal(decoded, expected[row["record_id"]])
    assert rows_seen == len(records)


def test_path_rewrite_is_deterministic_across_runs(tmp_path: Path) -> None:
    recipe = _recipe()
    records = _records()
    hashes = _input_hashes(records)

    def _materialize(root: Path) -> bytes:
        config = RuntimeConfig(cache_root=root)
        runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=config, seed=recipe.seed)
        res = runner.run(tmp_dir_for(root, "run-1"), raw_records=records, raw_input_hashes=hashes)
        return (dataset_dir(res.instance_dir) / "val.jsonl").read_bytes()

    assert _materialize(tmp_path / "a") == _materialize(tmp_path / "b")
