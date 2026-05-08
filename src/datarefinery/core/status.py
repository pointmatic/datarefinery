# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-19 instance-status report.

`DataRefinery.status()` resolves cache identity from the loaded recipe
plus the disk-backed input hashes and reports whether a materialized
instance exists. The CLI verb in
``datarefinery.cli.commands.status_cmd`` renders the report as a `rich`
table.

Cache states:

- ``hit``: ``instance_dir(cache_root, key)/manifest.json`` exists and
  parses cleanly.
- ``miss``: no instance for the recipe + inputs + seed triple. Not an
  error - exit code 0 from the CLI.
- ``corrupt``: instance directory present but ``manifest.json`` is
  missing or unreadable. The report names the path and suggests
  ``datarefinery clean`` (FR-19 edge case).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Literal

from datarefinery.cache.identity import CacheKey
from datarefinery.cache.layout import instance_dir, manifest_path
from datarefinery.pipeline.manifest import Manifest, read_manifest

CacheStatus = Literal["hit", "miss", "corrupt"]


@dataclasses.dataclass(frozen=True)
class StatusReport:
    """Structured outcome of `DataRefinery.status()`."""

    cache_status: CacheStatus
    cache_key: CacheKey
    instance_path: Path
    manifest: Manifest | None
    note: str | None = None


def resolve_status(
    cache_root: Path,
    key: CacheKey,
) -> StatusReport:
    """Inspect the on-disk state for a given cache key."""
    inst = instance_dir(cache_root, key)
    mp = manifest_path(inst)
    if not inst.exists():
        return StatusReport(
            cache_status="miss",
            cache_key=key,
            instance_path=inst,
            manifest=None,
        )
    if not mp.exists():
        return StatusReport(
            cache_status="corrupt",
            cache_key=key,
            instance_path=inst,
            manifest=None,
            note=(
                f"instance directory present at {inst} but "
                f"manifest.json is missing; consider `datarefinery clean`"
            ),
        )
    try:
        manifest = read_manifest(mp)
    except Exception as exc:
        return StatusReport(
            cache_status="corrupt",
            cache_key=key,
            instance_path=inst,
            manifest=None,
            note=(
                f"manifest.json at {mp} could not be parsed ({exc!r}); "
                f"consider `datarefinery clean`"
            ),
        )
    return StatusReport(
        cache_status="hit",
        cache_key=key,
        instance_path=inst,
        manifest=manifest,
    )


__all__ = ["CacheStatus", "StatusReport", "resolve_status"]
