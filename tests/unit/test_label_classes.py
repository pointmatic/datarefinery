# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-J-2 / Story J.f: canonical class-set enumeration.

The runner emits ``Manifest.label_classes: list[Any] | None`` so every
downstream consumer binds against the producer's commitment for label
ordering instead of independently sort-by-convention-ing JSONL records.

Computation rules per
[`modelfoundry/vendor-dependency-spec.md`](../../docs/specs/modelfoundry/vendor-dependency-spec.md)
§ `manifest.label_classes` shape:

- Scan every labeled record across every split (skip unlabeled splits
  per FR-22).
- Distinct union of label values; sort ascending via Python ``sorted``.
- ``None`` when no labeled records exist.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datarefinery.pipeline.runner import _compute_label_classes


def _r(rid: str, label: Any = None) -> Mapping[str, Any]:
    """Record builder; omits ``label`` when ``label is None`` (unlabeled)."""
    rec: dict[str, Any] = {"record_id": rid}
    if label is not None:
        rec["label"] = label
    return rec


# ---------------------------------------------------------------------------
# Multi-class / multi-split coverage
# ---------------------------------------------------------------------------


def test_balanced_multi_class_emits_sorted_list() -> None:
    split_map = {
        "train": [_r("r0", "cat"), _r("r1", "dog"), _r("r2", "bird")],
        "val": [_r("r3", "cat"), _r("r4", "dog")],
        "test": [_r("r5", "bird"), _r("r6", "cat")],
    }
    result = _compute_label_classes(split_map, label_field="label", unlabeled_splits=set())
    assert result == ["bird", "cat", "dog"]


def test_sparse_class_present_only_in_test_split_appears_in_list() -> None:
    """A class that lives only in val/test must still surface in the
    canonical list — the producer commitment that makes label_classes
    safer than the consumer's "scan train.jsonl alone" workaround."""
    split_map = {
        "train": [_r("r0", "cat"), _r("r1", "dog")],
        "val": [_r("r2", "cat")],
        "test": [_r("r3", "bird")],  # 'bird' lives only here
    }
    result = _compute_label_classes(split_map, label_field="label", unlabeled_splits=set())
    assert result == ["bird", "cat", "dog"]


def test_single_class_emits_singleton_list() -> None:
    split_map = {"train": [_r("r0", "cat"), _r("r1", "cat")]}
    result = _compute_label_classes(split_map, label_field="label", unlabeled_splits=set())
    assert result == ["cat"]


# ---------------------------------------------------------------------------
# Dtype coverage — str and int
# ---------------------------------------------------------------------------


def test_int_label_dtype_preserves_int_in_list() -> None:
    split_map = {
        "train": [_r("r0", 0), _r("r1", 1), _r("r2", 0)],
        "val": [_r("r3", 2)],
    }
    result = _compute_label_classes(split_map, label_field="label", unlabeled_splits=set())
    assert result == [0, 1, 2]
    # Preserve the int dtype — consumers may rely on this for direct logit indexing.
    assert result is not None
    assert all(isinstance(v, int) for v in result)


def test_str_label_dtype_preserves_str_in_list() -> None:
    split_map = {"train": [_r("r0", "alpha"), _r("r1", "beta")]}
    result = _compute_label_classes(split_map, label_field="label", unlabeled_splits=set())
    assert result is not None
    assert all(isinstance(v, str) for v in result)


# ---------------------------------------------------------------------------
# FR-22 unlabeled handling
# ---------------------------------------------------------------------------


def test_fully_unlabeled_returns_none() -> None:
    split_map = {"train": [_r("r0"), _r("r1")]}  # no label key
    result = _compute_label_classes(split_map, label_field="label", unlabeled_splits=set())
    assert result is None


def test_records_missing_label_field_are_skipped() -> None:
    """Mixed labeled + missing-label records in the same split: the
    labeled records contribute, the missing-label records are dropped."""
    split_map = {
        "train": [_r("r0", "cat"), _r("r1"), _r("r2", "dog")],  # r1 has no label
    }
    result = _compute_label_classes(split_map, label_field="label", unlabeled_splits=set())
    assert result == ["cat", "dog"]


def test_unlabeled_splits_are_skipped_entirely() -> None:
    """A split declared unlabeled (FR-22) contributes nothing even if
    its records happen to carry a label field."""
    split_map = {
        "train": [_r("r0", "cat"), _r("r1", "dog")],
        "unlabeled_pool": [_r("r2", "stray_label_value")],
    }
    result = _compute_label_classes(
        split_map, label_field="label", unlabeled_splits={"unlabeled_pool"}
    )
    assert result == ["cat", "dog"]


def test_empty_split_map_returns_none() -> None:
    result = _compute_label_classes({}, label_field="label", unlabeled_splits=set())
    assert result is None


def test_all_splits_marked_unlabeled_returns_none() -> None:
    split_map = {
        "train": [_r("r0", "cat")],
        "val": [_r("r1", "dog")],
    }
    result = _compute_label_classes(
        split_map, label_field="label", unlabeled_splits={"train", "val"}
    )
    assert result is None


# ---------------------------------------------------------------------------
# Manifest round-trip — field survives write/read with label_classes set
# ---------------------------------------------------------------------------


def test_manifest_label_classes_field_round_trips(tmp_path: Any) -> None:
    from datetime import UTC, datetime

    from datarefinery.pipeline.manifest import (
        Manifest,
        read_manifest,
        write_manifest,
    )

    manifest = Manifest(
        datarefinery_version="0.20.0",
        plugin="image_classification",
        plugin_version="1",
        recipe_hash="0" * 64,
        input_hash="1" * 64,
        seed=42,
        created_at=datetime.now(UTC),
        elapsed_seconds=0.0,
        label_classes=["bird", "cat", "dog"],
    )
    target = tmp_path / "manifest.json"
    write_manifest(target, manifest)
    loaded = read_manifest(target)
    assert loaded.label_classes == ["bird", "cat", "dog"]


def test_manifest_label_classes_defaults_to_none(tmp_path: Any) -> None:
    """Recipes whose materialized output has no labeled records produce
    a manifest with ``label_classes=None`` (additive default — existing
    manifests stay valid through the additive bump)."""
    from datetime import UTC, datetime

    from datarefinery.pipeline.manifest import (
        Manifest,
        read_manifest,
        write_manifest,
    )

    manifest = Manifest(
        datarefinery_version="0.20.0",
        plugin="image_classification",
        plugin_version="1",
        recipe_hash="0" * 64,
        input_hash="1" * 64,
        seed=42,
        created_at=datetime.now(UTC),
        elapsed_seconds=0.0,
    )
    target = tmp_path / "manifest.json"
    write_manifest(target, manifest)
    loaded = read_manifest(target)
    assert loaded.label_classes is None
