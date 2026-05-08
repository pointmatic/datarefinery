# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-15 drift schema tests (Story C.n)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from datarefinery.reporting.drift import (
    DRIFT_SCHEMA_VERSION_PLACEHOLDER,
    DriftSchema,
    FeatureDriftRecord,
    SplitDriftRecord,
    compute_drift_placeholder,
    read_drift,
    write_drift,
)


def _splits_with_labels() -> dict[str, list[dict[str, object]]]:
    return {
        "train": [
            {"label": "cat"},
            {"label": "dog"},
            {"label": "cat"},
        ],
        "val": [{"label": "cat"}],
    }


def test_drift_schema_default_version_is_zero_placeholder() -> None:
    drift = DriftSchema(plugin="image_classification")
    assert drift.schema_version == DRIFT_SCHEMA_VERSION_PLACEHOLDER == 0


def test_drift_schema_extra_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DriftSchema(plugin="x", made_up=True)  # type: ignore[call-arg]


def test_drift_schema_is_frozen() -> None:
    drift = DriftSchema(plugin="x")
    with pytest.raises(ValidationError):
        drift.plugin = "y"  # type: ignore[misc]


def test_split_drift_record_extra_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        SplitDriftRecord(record_count=1, foo="bar")  # type: ignore[call-arg]


def test_feature_drift_record_extra_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        FeatureDriftRecord(dtype="float32", bogus=1)  # type: ignore[call-arg]


def test_compute_drift_placeholder_records_per_split_counts() -> None:
    drift = compute_drift_placeholder(
        _splits_with_labels(),
        plugin_name="image_classification",
        label_field="label",
    )
    assert drift.plugin == "image_classification"
    assert drift.splits["train"].record_count == 3
    assert drift.splits["val"].record_count == 1


def test_compute_drift_placeholder_class_distribution_with_label_field() -> None:
    drift = compute_drift_placeholder(
        _splits_with_labels(),
        plugin_name="image_classification",
        label_field="label",
    )
    assert drift.splits["train"].class_distribution == {"cat": 2, "dog": 1}
    assert drift.splits["val"].class_distribution == {"cat": 1}


def test_compute_drift_placeholder_skips_class_distribution_without_label() -> (
    None
):
    drift = compute_drift_placeholder(
        _splits_with_labels(),
        plugin_name="text",
        label_field=None,
    )
    assert drift.splits["train"].class_distribution is None


def test_compute_drift_placeholder_split_keys_are_sorted() -> None:
    splits = {"z": [], "a": [], "m": []}
    drift = compute_drift_placeholder(
        splits, plugin_name="image_classification", label_field=None
    )
    assert list(drift.splits.keys()) == ["a", "m", "z"]


def test_compute_drift_placeholder_includes_unstable_notes() -> None:
    drift = compute_drift_placeholder(
        _splits_with_labels(),
        plugin_name="x",
        label_field="label",
    )
    assert any("v1" in n for n in drift.notes)
    assert any("unstable" in n for n in drift.notes)


def test_compute_drift_placeholder_feature_summary_is_empty_in_v1() -> None:
    drift = compute_drift_placeholder(
        _splits_with_labels(),
        plugin_name="x",
        label_field="label",
    )
    assert drift.feature_summary == {}


def test_write_and_read_drift_roundtrip(tmp_path: Path) -> None:
    drift = compute_drift_placeholder(
        _splits_with_labels(),
        plugin_name="image_classification",
        label_field="label",
    )
    path = tmp_path / "drift.json"
    write_drift(path, drift)
    loaded = read_drift(path)
    assert loaded == drift


def test_drift_json_is_canonical_sorted(tmp_path: Path) -> None:
    drift = compute_drift_placeholder(
        _splits_with_labels(),
        plugin_name="x",
        label_field="label",
    )
    path = tmp_path / "drift.json"
    write_drift(path, drift)
    raw = path.read_text()
    parsed = json.loads(raw)
    # Top-level keys present.
    assert set(parsed) == {
        "schema_version", "plugin", "splits", "feature_summary", "notes",
    }
    # Sorted-keys: a < f < n < p < s for the top level.
    keys = list(parsed.keys())
    assert keys == sorted(keys)
