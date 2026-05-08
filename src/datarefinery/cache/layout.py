# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Cache directory layout helpers under `<cache-root>/instances/...`.

Layout (per tech-spec):

    <cache-root>/
    └── instances/
        ├── .tmp/<run-id>/                  # in-flight runs; promoted via os.replace
        └── <recipe-hash16>/<input-hash16>/<seed>/
            ├── manifest.json
            ├── dataset/
            ├── fitted_statistics/
            └── report/
                ├── report.md
                ├── drift.json
                └── visualizations/

The 16-char shards come from `CacheKey.short` (recipe) and the first 16
chars of `input_hash`; the full hashes are recorded in `manifest.json`.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path

from datarefinery.cache.identity import CacheKey

INSTANCES_DIR = "instances"
TMP_DIR_NAME = ".tmp"
MANIFEST_FILE = "manifest.json"
RECIPE_FILE = "recipe.json"
DATASET_SUBDIR = "dataset"
FITTED_STATS_SUBDIR = "fitted_statistics"
REPORT_SUBDIR = "report"


def instances_root(cache_root: Path) -> Path:
    """Root for all materialized instances and temp dirs."""
    return cache_root / INSTANCES_DIR


def instance_dir(cache_root: Path, key: CacheKey) -> Path:
    """Final path for a materialized instance under the cache root."""
    return (
        instances_root(cache_root)
        / key.recipe_hash[:16]
        / key.input_hash[:16]
        / str(key.seed)
    )


def tmp_dir(cache_root: Path, run_id: str) -> Path:
    """Temp directory for an in-flight run, atomically promoted via os.replace."""
    return instances_root(cache_root) / TMP_DIR_NAME / run_id


def manifest_path(instance: Path) -> Path:
    return instance / MANIFEST_FILE


def recipe_path(instance: Path) -> Path:
    return instance / RECIPE_FILE


def dataset_dir(instance: Path) -> Path:
    return instance / DATASET_SUBDIR


def fitted_stats_dir(instance: Path) -> Path:
    return instance / FITTED_STATS_SUBDIR


def report_dir(instance: Path) -> Path:
    return instance / REPORT_SUBDIR


def make_run_id() -> str:
    """Return `<utc_iso_compact>-<8hex>`, e.g. `20260507T143022Z-deadbeef`.

    Lexicographically sortable down to the second; the 8-hex random
    suffix makes outputs unique under burst/concurrent calls within the
    same second.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(4)}"
