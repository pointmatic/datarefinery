# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.h: ImageFolder + aggressive Augmentations end-to-end.

The ImageFolder loader stamps `record_id` as `<source>/<class>/<file>`
(with forward slashes); aggressive realization appends `__v<NNN>`. The
sidecar-PNG writer must create the nested parent directories those
slashes imply, or `PIL.Image.save` fails with `FileNotFoundError`.

This exercises the **disk-loader** path (`load_raw_records`) end-to-end —
the existing aggressive tests use the library API with flat
manually-constructed record_ids and so never hit the nested-dir case.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from datarefinery.cache.layout import dataset_dir
from datarefinery.cache.layout import tmp_dir as tmp_dir_for
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.inputs import load_raw_records
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe


def _write_image_folder(root: Path, *, classes: int = 2, per_class: int = 6) -> None:
    rng = np.random.default_rng(0)
    for c in range(classes):
        cls_dir = root / f"c{c}"
        cls_dir.mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            arr = rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8)
            Image.fromarray(arr).save(cls_dir / f"img_{i:04d}.png")


def _recipe(source_root: Path) -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 2,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "imgs", "type": "image_folder", "path": str(source_root)}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [8, 8, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.6, "val": 0.2, "test": 0.2}, "seed": 11},
            "Augmentations": [
                {
                    "name": "flip",
                    "op": "horizontal_flip",
                    "params": {"p": 0.5},
                    "splits": ["train"],
                    "seed": 1,
                    "materialization": "aggressive",
                    "expansion": 3,
                }
            ],
        }
    )


def test_imagefolder_aggressive_materializes_with_nested_sidecars(tmp_path: Path) -> None:
    source_root = tmp_path / "imagefolder"
    _write_image_folder(source_root)
    recipe = _recipe(source_root)
    loaded, hashes = load_raw_records(recipe, IMAGE_PLUGIN)
    records: list[Mapping[str, Any]] = list(loaded)

    # Loader stamps slashes into record_id — this is the precondition that
    # makes the nested-dir crash reachable.
    assert any("/" in r["record_id"] for r in records)

    cache_root = tmp_path / "cache"
    runner = PipelineRunner(
        recipe=recipe, plugin=IMAGE_PLUGIN, config=RuntimeConfig(cache_root=cache_root), seed=11
    )
    result = runner.run(
        tmp_dir_for(cache_root, "run-1"), raw_records=records, raw_input_hashes=hashes
    )

    ds = dataset_dir(result.instance_dir)
    lines = [json.loads(line) for line in (ds / "train.jsonl").read_text().splitlines() if line]
    assert lines, "expected aggressive train variants"
    for line in lines:
        rid = line["record_id"]
        assert "image" not in line
        # record_id carries the loader slashes plus the variant suffix.
        assert "/" in rid and "__v" in rid
        # image_path mirrors record_id verbatim under the split images dir.
        assert line["image_path"] == f"train/images/{rid}.png"
        sidecar = ds / line["image_path"]
        assert sidecar.is_file()
        # Decodes to a valid uint8 image.
        decoded = np.asarray(Image.open(sidecar))
        assert decoded.dtype == np.uint8 and decoded.shape == (8, 8, 3)
