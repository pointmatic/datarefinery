# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.g: lazy-mode ``path`` rewrite at dataset serialization.

When a pixel-altering Transformation runs and a qualifying image sink is
declared, the dataset writer rewrites each lazy record's ``path`` to the
sink's per-record output (instance-relative). Non-aggressive records in
splits with no plan entry keep their source ``path`` unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from datarefinery.pipeline.runner import _write_dataset
from datarefinery.recipe.models import SinkOp


def _records() -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": np.full((4, 4, 3), 10 + i, dtype=np.uint8),
            "label": f"c{i % 2}",
            "path": f"/data/source/img_{i:04d}.png",
        }
        for i in range(3)
    ]


_SINK = SinkOp(
    name="transformed",
    stage="post_Transformations",
    field="image",
    format="png_per_record",
    path_template="transformed/{split}/{record_id}.png",
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_path_rewritten_for_planned_split(tmp_path: Path) -> None:
    _write_dataset(tmp_path / "dataset", {"val": _records()}, rewrite_plan={"val": _SINK})
    rows = _read_jsonl(tmp_path / "dataset" / "val.jsonl")
    assert [r["path"] for r in rows] == [
        "transformed/val/rec_0000.png",
        "transformed/val/rec_0001.png",
        "transformed/val/rec_0002.png",
    ]


def test_path_unchanged_for_unplanned_split(tmp_path: Path) -> None:
    _write_dataset(tmp_path / "dataset", {"train": _records()}, rewrite_plan={"val": _SINK})
    rows = _read_jsonl(tmp_path / "dataset" / "train.jsonl")
    assert [r["path"] for r in rows] == [
        "/data/source/img_0000.png",
        "/data/source/img_0001.png",
        "/data/source/img_0002.png",
    ]


def test_path_unchanged_when_no_plan(tmp_path: Path) -> None:
    _write_dataset(tmp_path / "dataset", {"val": _records()})
    rows = _read_jsonl(tmp_path / "dataset" / "val.jsonl")
    assert rows[0]["path"] == "/data/source/img_0000.png"
