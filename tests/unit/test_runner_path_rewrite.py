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


# ---------------------------------------------------------------------------
# feature_path rewrite (Story K.c — npy_per_record sinks)
# ---------------------------------------------------------------------------

_NPY_SINK = SinkOp(
    name="feats",
    stage="post_Featurizations",
    field="mel",
    format="npy_per_record",
    path_template="features/{split}/{record_id}.npy",
)


def _audio_records() -> list[Mapping[str, Any]]:
    # Audio window records: non-aggressive (source_record_id but no variant_index).
    return [
        {
            "record_id": f"clip_{i:04d}__w0000",
            "source_record_id": f"clip_{i:04d}",
            "window_index": 0,
            "mel": np.zeros((4, 3), dtype=np.float32),
            "label": "cat",
            "path": f"/data/clips/clip_{i:04d}.wav",
        }
        for i in range(2)
    ]


def test_feature_path_rewritten_for_planned_split(tmp_path: Path) -> None:
    _write_dataset(
        tmp_path / "dataset",
        {"train": _audio_records()},
        feature_rewrite_plan={"train": _NPY_SINK},
    )
    rows = _read_jsonl(tmp_path / "dataset" / "train.jsonl")
    assert [r["feature_path"] for r in rows] == [
        "features/train/clip_0000__w0000.npy",
        "features/train/clip_0001__w0000.npy",
    ]


def test_feature_path_absent_without_plan(tmp_path: Path) -> None:
    _write_dataset(tmp_path / "dataset", {"train": _audio_records()})
    rows = _read_jsonl(tmp_path / "dataset" / "train.jsonl")
    assert all("feature_path" not in r for r in rows)


def test_feature_path_nested_record_id_round_trips(tmp_path: Path) -> None:
    # record_id with '/' (ImageFolder-style source ids carried into windows)
    # must produce a nested, instance-relative POSIX feature_path verbatim.
    rec = {
        "record_id": "src/cat/clip_0001.wav__w0003",
        "source_record_id": "src/cat/clip_0001.wav",
        "window_index": 3,
        "mel": np.zeros((4, 3), dtype=np.float32),
        "label": "cat",
    }
    _write_dataset(
        tmp_path / "dataset",
        {"train": [rec]},
        feature_rewrite_plan={"train": _NPY_SINK},
    )
    rows = _read_jsonl(tmp_path / "dataset" / "train.jsonl")
    assert rows[0]["feature_path"] == "features/train/src/cat/clip_0001.wav__w0003.npy"
