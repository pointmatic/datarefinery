# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-3.7 manifest: per-instance summary written at promotion time.

The manifest is a frozen, pydantic-validated record of (recipe identity,
inputs identity, seed, applied overlays, build-time stats, per-split record
counts, accumulated warnings). It is the entry point downstream tools
use to interpret a materialized instance: full recipe and input hashes
live here (cache directory paths only carry the 16-char shard).

``Manifest.schema_version`` is a separate counter from the recipe
schema version - per the tech-spec, the manifest format can evolve
independently of the recipe schema. **v2 (Story J.n.5):** ``variant: str |
None`` was renamed/generalized to ``overlays: list[str]`` (the ordered list of
applied overlay names; empty when none selected).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_SCHEMA_VERSION = 2


class ManifestWarning(BaseModel):
    """One stage-tagged warning surfaced through the manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str
    message: str


class SinkManifestEntry(BaseModel):
    """Per-sink summary captured in ``manifest.sinks[<name>]`` (Story I.d).

    Downstream tools (ModelFoundry today; the cross-repo contract is
    pinned in ``docs/specs/modelfoundry/dependency-spec.md``) read
    this entry to discover which sinks ran and where their output
    lives.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str
    format: str
    files_written: int
    bytes_total: int
    path_template_resolved_root: str


class SampleManifestEntry(BaseModel):
    """Summary of the SampleData runtime emission (Story J.a, FR-J-1).

    Present only when the recipe declares a ``SampleData:`` section; the
    runtime persists a ``sample/`` sidecar alongside ``dataset/`` and
    records the selector echo + per-split record counts here so downstream
    consumers can discover the sidecar without parsing the recipe.

    ``selector`` echoes the resolved ``SampleSelector`` as a JSON-shaped
    dict (kind, n/fraction, splits, seed); ``record_counts`` maps each
    sampled split name to the count of records the sample emitted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    selector: dict[str, Any]
    record_counts: dict[str, int]


class Manifest(BaseModel):
    """Per-instance summary written to ``<instance>/manifest.json``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = MANIFEST_SCHEMA_VERSION
    datarefinery_version: str
    plugin: str
    plugin_version: str
    recipe_hash: str  # full SHA-256 hex
    input_hash: str  # full SHA-256 hex
    seed: int
    overlays: list[str] = Field(default_factory=list)
    created_at: datetime
    elapsed_seconds: float
    is_partial: bool = False
    failed_stage: str | None = None
    completed_through: str | None = None
    record_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[ManifestWarning] = Field(default_factory=list)
    # Forward-declared class-imbalance hint copied verbatim from
    # `Splits.class_balance` (bare string or `{strategy, applies_to}` dict).
    # DataRefinery does NOT resample or emit weights — consumer tools
    # (ModelFoundry) honor this at training time. Story I.s / G10; the
    # cross-repo contract is pinned in `modelfoundry/dependency-spec.md`.
    class_balance: str | dict[str, Any] | None = None
    sinks: dict[str, SinkManifestEntry] = Field(default_factory=dict)
    # Sinks declared on the recipe whose host stage was not reached
    # under a `--stage` partial run. Maps sink name -> declared stage.
    # Empty on full materializes. Story I.f.1.
    sinks_skipped: dict[str, str] = Field(default_factory=dict)
    # SampleData runtime emission summary (Story J.a, FR-J-1). Present only
    # when the recipe declares a ``SampleData:`` section; otherwise None.
    # Cross-repo contract: ``docs/specs/modelfoundry/vendor-dependency-spec.md``.
    sample: SampleManifestEntry | None = None
    # Canonical class set used by all labeled records (Story J.f, FR-J-2).
    # Distinct union of label values across every labeled split, sorted
    # ascending. ``None`` when no labeled records exist (FR-22 fully-unlabeled
    # case). Field lives in the manifest, not the recipe — does not perturb
    # canonical recipe bytes or cache identity. Cross-repo contract:
    # ``docs/specs/modelfoundry/vendor-dependency-spec.md`` § ``manifest.label_classes`` shape.
    label_classes: list[Any] | None = None


def write_manifest(path: Path, manifest: Manifest) -> None:
    """Serialize ``manifest`` to ``path`` with stable canonical JSON.

    Sorted keys + 2-space indent so the file is human-diffable and two
    runs on byte-identical inputs produce byte-identical manifest files
    (apart from ``created_at`` and ``elapsed_seconds``, which are
    intrinsically run-specific).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump_json(indent=2)
    path.write_text(payload, encoding="utf-8")


def read_manifest(path: Path) -> Manifest:
    """Parse a previously-written ``manifest.json`` from ``path``."""
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))
