# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-15 drift schema: ``drift.json`` placeholder for v1.

DataMachine consumes ``drift.json`` to track distributional drift between
materializations. The full machinery lands post-v1; for v1 we ship a
typed-JSON placeholder so consumers can code against the contract while
the implementation matures.

Per ``project-essentials.md`` post-production rules, the drift schema is
finalized and frozen at the production-release event (v1.0.0); until
then ``schema_version=0`` and the contents may evolve. After production
release ``schema_version`` bumps to 1.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DRIFT_SCHEMA_VERSION_PLACEHOLDER = 0


class SplitDriftRecord(BaseModel):
    """Per-split drift summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_count: int
    class_distribution: dict[str, int] | None = None


class FeatureDriftRecord(BaseModel):
    """Per-feature drift summary; mean/std for numeric, top_values for categorical."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dtype: str
    mean: float | None = None
    std: float | None = None
    top_values: dict[str, int] | None = None


class DriftSchema(BaseModel):
    """Top-level drift placeholder. Schema unstable until production release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = DRIFT_SCHEMA_VERSION_PLACEHOLDER
    plugin: str
    splits: dict[str, SplitDriftRecord] = Field(default_factory=dict)
    feature_summary: dict[str, FeatureDriftRecord] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def compute_drift_placeholder(
    splits: Mapping[str, list[Mapping[str, object]]],
    *,
    plugin_name: str,
    label_field: str | None,
) -> DriftSchema:
    """Build a v1 drift placeholder from materialized splits.

    For each split, records the count and (when ``label_field`` is
    supplied) the class distribution. Feature-level drift summaries are
    intentionally empty in v1 - the schema reserves the slot for
    DataMachine consumers; full per-feature analysis lands post-v1.
    """
    split_records: dict[str, SplitDriftRecord] = {}
    for split_name, recs in splits.items():
        class_dist: dict[str, int] | None
        if label_field is not None:
            counts: dict[str, int] = {}
            for r in recs:
                key = str(r.get(label_field))
                counts[key] = counts.get(key, 0) + 1
            class_dist = dict(sorted(counts.items()))
        else:
            class_dist = None
        split_records[split_name] = SplitDriftRecord(
            record_count=len(recs), class_distribution=class_dist
        )
    return DriftSchema(
        plugin=plugin_name,
        splits=dict(sorted(split_records.items())),
        feature_summary={},
        notes=[
            "v1 drift placeholder - feature-level analysis lands post-v1",
            "schema unstable until production release (v1.0.0)",
        ],
    )


def write_drift(path: Path, drift: DriftSchema) -> None:
    """Serialize ``drift`` to ``path`` as canonical JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(drift.model_dump_json())
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def read_drift(path: Path) -> DriftSchema:
    """Parse a previously-written ``drift.json``."""
    return DriftSchema.model_validate_json(path.read_text(encoding="utf-8"))
