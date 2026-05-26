# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the sink stage hook (Story I.d).

`execute_sinks` filters declared sinks to those targeting the current
stage, walks the (filtered) split map, resolves each sink's
`path_template`, and dispatches to the writer. The tests here exercise
the hook in isolation from the full pipeline runner.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from datarefinery.pipeline.sinks.runner import (
    SinkCardinalityError,
    SinkResult,
    execute_sinks,
)
from datarefinery.recipe.models import SinkOp


def _img(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(4, 4, 3), dtype=np.uint8)


def _record(record_id: str, label: str, seed: int) -> Mapping[str, Any]:
    return {"record_id": record_id, "label": label, "image": _img(seed)}


def _split_map() -> dict[str, list[Mapping[str, Any]]]:
    return {
        "train": [_record("a", "cat", 1), _record("b", "dog", 2)],
        "val": [_record("c", "cat", 3)],
        "test": [_record("d", "dog", 4)],
    }


def _sink(**overrides: Any) -> SinkOp:
    base: dict[str, Any] = {
        "name": "pngs",
        "stage": "post_Filters",
        "field": "image",
        "format": "png_per_record",
        "path_template": "exports/{split}/{label}/{record_id}.png",
    }
    base.update(overrides)
    return SinkOp.model_validate(base)


def test_execute_sinks_writes_files_for_all_splits(tmp_path: Path) -> None:
    sinks = [_sink()]
    results = execute_sinks(
        sinks=sinks,
        stage="post_Filters",
        split_map=_split_map(),
        instance_dir=tmp_path,
    )
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, SinkResult)
    assert r.files_written == 4  # 2 train + 1 val + 1 test
    assert r.bytes_total > 0
    assert r.path_template_resolved_root == "exports"
    assert (tmp_path / "exports" / "train" / "cat" / "a.png").exists()
    assert (tmp_path / "exports" / "val" / "cat" / "c.png").exists()
    assert (tmp_path / "exports" / "test" / "dog" / "d.png").exists()


def test_execute_sinks_filters_by_splits(tmp_path: Path) -> None:
    sinks = [_sink(splits=["test"])]
    results = execute_sinks(
        sinks=sinks,
        stage="post_Filters",
        split_map=_split_map(),
        instance_dir=tmp_path,
    )
    assert results[0].files_written == 1
    assert (tmp_path / "exports" / "test" / "dog" / "d.png").exists()
    assert not (tmp_path / "exports" / "train").exists()


def test_execute_sinks_skips_when_stage_mismatch(tmp_path: Path) -> None:
    sinks = [_sink(stage="post_Generation")]
    results = execute_sinks(
        sinks=sinks,
        stage="post_Filters",
        split_map=_split_map(),
        instance_dir=tmp_path,
    )
    assert results == []
    assert list(tmp_path.iterdir()) == []


def test_execute_sinks_collision_detected(tmp_path: Path) -> None:
    # Two records mapping to the same output path -> cardinality error.
    sinks = [_sink(path_template="exports/{label}.png")]
    # Both 'cat'-labeled records collide.
    with pytest.raises(SinkCardinalityError, match="collision"):
        execute_sinks(
            sinks=sinks,
            stage="post_Filters",
            split_map=_split_map(),
            instance_dir=tmp_path,
        )


def test_execute_sinks_multiple_sinks_each_emit_result(tmp_path: Path) -> None:
    sinks = [
        _sink(name="all_pngs"),
        _sink(name="test_only", splits=["test"]),
    ]
    results = execute_sinks(
        sinks=sinks,
        stage="post_Filters",
        split_map=_split_map(),
        instance_dir=tmp_path,
    )
    by_name = {r.name: r for r in results}
    assert set(by_name) == {"all_pngs", "test_only"}
    assert by_name["all_pngs"].files_written == 4
    assert by_name["test_only"].files_written == 1
