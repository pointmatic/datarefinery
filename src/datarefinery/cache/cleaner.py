# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-21 cache cleaner: library API only.

The CLI verb wraps this in Phase D. The library here exposes
`CleanSelector` plus `clean(cache_root, selector, *, force=False)`. The
selector is intersection-style across the `by_*` filters; `orphans` adds
old temp dirs to the target set; `all=True` requires `force=True` and
clears every direct child of `<cache-root>/instances/`.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from datarefinery.cache.layout import (
    TMP_DIR_NAME,
    instances_root,
)
from datarefinery.core.errors import CacheError


@dataclass(frozen=True, slots=True)
class CleanSelector:
    """Declarative selector for `clean(...)`."""

    by_recipe_hash: str | None = None
    by_input_hash: str | None = None
    by_seed: int | None = None
    by_age_days: float | None = None
    orphans: bool = False
    orphan_age_days: float = 1.0
    all: bool = False


@dataclass(frozen=True, slots=True)
class CleanReport:
    removed: tuple[Path, ...]
    skipped: tuple[tuple[Path, str], ...]


def clean(
    cache_root: Path,
    selector: CleanSelector,
    *,
    force: bool = False,
) -> CleanReport:
    """Remove cache entries matching `selector`.

    `selector.all=True` requires `force=True` and removes every direct
    child of `<cache-root>/instances/` (including the `.tmp/` orphans
    dir). The `by_*` filters compose intersection-style: each one
    narrows the candidate set further. `orphans=True` independently
    targets temp dirs older than `orphan_age_days`.
    """
    if selector.all:
        if not force:
            raise CacheError("clean(all=True) requires force=True")
        return _clean_everything(cache_root)

    instances = instances_root(cache_root)
    if not instances.is_dir():
        return CleanReport(removed=(), skipped=())

    targets: list[Path] = []

    if selector.orphans:
        targets.extend(_orphan_temp_dirs(cache_root, selector.orphan_age_days))

    instance_filters_active = (
        selector.by_recipe_hash is not None
        or selector.by_input_hash is not None
        or selector.by_seed is not None
        or selector.by_age_days is not None
    )
    if instance_filters_active:
        candidates = list(_iter_instance_dirs(instances))
        if selector.by_recipe_hash is not None:
            prefix = selector.by_recipe_hash[:16]
            candidates = [p for p in candidates if p.parent.parent.name == prefix]
        if selector.by_input_hash is not None:
            prefix = selector.by_input_hash[:16]
            candidates = [p for p in candidates if p.parent.name == prefix]
        if selector.by_seed is not None:
            candidates = [
                p for p in candidates if p.name == str(selector.by_seed)
            ]
        if selector.by_age_days is not None:
            cutoff = time.time() - selector.by_age_days * 86400
            candidates = [p for p in candidates if p.stat().st_mtime < cutoff]
        targets.extend(candidates)

    return _remove_paths(targets)


def _iter_instance_dirs(instances: Path) -> Iterable[Path]:
    """Yield every `<recipe>/<input>/<seed>/` directory, skipping `.tmp/`."""
    for recipe_shard in instances.iterdir():
        if recipe_shard.name.startswith(".") or not recipe_shard.is_dir():
            continue
        for input_shard in recipe_shard.iterdir():
            if not input_shard.is_dir():
                continue
            for seed_dir in input_shard.iterdir():
                if seed_dir.is_dir():
                    yield seed_dir


def _orphan_temp_dirs(cache_root: Path, age_days: float) -> Iterable[Path]:
    tmp_root = instances_root(cache_root) / TMP_DIR_NAME
    if not tmp_root.is_dir():
        return
    cutoff = time.time() - age_days * 86400
    for entry in tmp_root.iterdir():
        if entry.is_dir() and entry.stat().st_mtime < cutoff:
            yield entry


def _clean_everything(cache_root: Path) -> CleanReport:
    instances = instances_root(cache_root)
    if not instances.is_dir():
        return CleanReport(removed=(), skipped=())
    return _remove_paths(list(instances.iterdir()))


def _remove_paths(paths: list[Path]) -> CleanReport:
    removed: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for path in paths:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(path)
        except OSError as exc:
            skipped.append((path, str(exc)))
    return CleanReport(removed=tuple(removed), skipped=tuple(skipped))
