# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-6 FittedStatistics persistence tests (Story C.h)."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pytest

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.fitted_stats import FittedStatistics


def test_put_get_scalar_roundtrips(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    fs.put_scalar("op1", "mean", 12.5)
    assert fs.get_scalar("op1", "mean") == 12.5


def test_multiple_scalars_share_one_json_file(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    fs.put_scalar("op1", "a", 1)
    fs.put_scalar("op1", "b", 2.5)
    fs.put_scalar("op1", "c", "label")
    fs.put_scalar("op1", "d", True)
    payload = json.loads((tmp_path / "op1" / "scalars.json").read_text())
    assert payload == {"a": 1, "b": 2.5, "c": "label", "d": True}


def test_scalars_json_keys_are_sorted_for_canonical_layout(
    tmp_path: Path,
) -> None:
    fs = FittedStatistics(tmp_path)
    fs.put_scalar("op1", "z", 3)
    fs.put_scalar("op1", "a", 1)
    raw = (tmp_path / "op1" / "scalars.json").read_text()
    assert raw.index('"a"') < raw.index('"z"')


def test_overwriting_scalar_replaces_value(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    fs.put_scalar("op1", "x", 1)
    fs.put_scalar("op1", "x", 2)
    assert fs.get_scalar("op1", "x") == 2


def test_get_scalar_missing_op_raises(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    with pytest.raises(MaterializeError, match=r"no scalars\.json"):
        fs.get_scalar("op_missing", "x")


def test_get_scalar_missing_name_raises(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    fs.put_scalar("op1", "a", 1)
    with pytest.raises(MaterializeError, match="missing"):
        fs.get_scalar("op1", "b")


def test_put_scalar_rejects_non_jsonish_value(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    with pytest.raises(MaterializeError, match="float/int/str/bool"):
        fs.put_scalar("op1", "x", [1, 2, 3])  # type: ignore[arg-type]


def test_malformed_scalars_json_raises_on_read(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    fs.put_scalar("op1", "x", 1)
    (tmp_path / "op1" / "scalars.json").write_text("not json{")
    with pytest.raises(MaterializeError, match="malformed"):
        fs.get_scalar("op1", "x")


def test_scalars_json_must_be_an_object(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    fs.put_scalar("op1", "x", 1)
    (tmp_path / "op1" / "scalars.json").write_text("[1, 2, 3]")
    with pytest.raises(MaterializeError, match="not a JSON object"):
        fs.get_scalar("op1", "x")


def test_put_get_vector_roundtrips(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    table = pa.table({"value": [1.0, 2.0, 3.0]})
    fs.put_vector("op1", "mean", table)
    out = fs.get_vector("op1", "mean")
    assert out.column("value").to_pylist() == [1.0, 2.0, 3.0]


def test_put_vector_writes_one_parquet_per_name(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    fs.put_vector("op1", "mean", pa.table({"value": [1.0]}))
    fs.put_vector("op1", "std", pa.table({"value": [2.0]}))
    op_dir = tmp_path / "op1"
    assert (op_dir / "mean.parquet").exists()
    assert (op_dir / "std.parquet").exists()


def test_put_vector_rejects_non_table(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    with pytest.raises(MaterializeError, match=r"pyarrow\.Table required"):
        fs.put_vector("op1", "x", [1, 2, 3])  # type: ignore[arg-type]


def test_get_vector_missing_raises(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    with pytest.raises(MaterializeError, match=r"no x\.parquet"):
        fs.get_vector("op1", "x")


def test_layout_is_op_id_dir_per_op(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    fs.put_scalar("op_a", "x", 1)
    fs.put_scalar("op_b", "y", 2)
    assert (tmp_path / "op_a" / "scalars.json").exists()
    assert (tmp_path / "op_b" / "scalars.json").exists()


def test_root_property_returns_provided_path(tmp_path: Path) -> None:
    fs = FittedStatistics(tmp_path)
    assert fs.root == tmp_path


def test_independent_instances_share_layout(tmp_path: Path) -> None:
    """A second FittedStatistics rooted at the same directory reads what the
    first wrote - this is the post-promote read pattern."""
    writer = FittedStatistics(tmp_path)
    writer.put_scalar("op1", "x", 7.5)
    writer.put_vector("op1", "v", pa.table({"value": [9.0]}))

    reader = FittedStatistics(tmp_path)
    assert reader.get_scalar("op1", "x") == 7.5
    assert reader.get_vector("op1", "v").column("value").to_pylist() == [9.0]
