# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Tests for cache layout helpers and `make_run_id`."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from datarefinery.cache.identity import CacheKey
from datarefinery.cache.layout import (
    dataset_dir,
    fitted_stats_dir,
    instance_dir,
    instances_root,
    make_run_id,
    manifest_path,
    report_dir,
    tmp_dir,
)


def test_instances_root() -> None:
    assert instances_root(Path("/cache")) == Path("/cache/instances")


def test_instance_dir_uses_short_hashes_and_seed() -> None:
    key = CacheKey(recipe_hash="a" * 64, input_hash="b" * 64, seed=42)
    path = instance_dir(Path("/cache"), key)
    assert path == Path("/cache/instances/aaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbb/42")


def test_instance_dir_truncates_to_16_chars() -> None:
    key = CacheKey(
        recipe_hash="0123456789abcdef" * 4,
        input_hash="fedcba9876543210" * 4,
        seed=0,
    )
    path = instance_dir(Path("/c"), key)
    assert path == Path("/c/instances/0123456789abcdef/fedcba9876543210/0")


def test_tmp_dir_lives_under_instances_dot_tmp() -> None:
    path = tmp_dir(Path("/cache"), "20260507T143022Z-deadbeef")
    assert path == Path("/cache/instances/.tmp/20260507T143022Z-deadbeef")


def test_manifest_path_is_inside_instance_dir() -> None:
    inst = Path("/cache/instances/abc/def/0")
    assert manifest_path(inst) == inst / "manifest.json"


def test_dataset_dir_path() -> None:
    inst = Path("/x")
    assert dataset_dir(inst) == inst / "dataset"


def test_fitted_stats_dir_path() -> None:
    inst = Path("/x")
    assert fitted_stats_dir(inst) == inst / "fitted_statistics"


def test_report_dir_path() -> None:
    inst = Path("/x")
    assert report_dir(inst) == inst / "report"


def test_make_run_id_format_is_compact_utc_plus_8hex() -> None:
    rid = make_run_id()
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", rid), rid


def test_make_run_id_unique_under_sequential_burst() -> None:
    ids = [make_run_id() for _ in range(2000)]
    assert len(set(ids)) == 2000


def test_make_run_id_unique_under_threaded_concurrency() -> None:
    collected: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        local = [make_run_id() for _ in range(100)]
        with lock:
            collected.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(collected) == 800
    assert len(set(collected)) == 800


def test_make_run_id_sorts_by_timestamp_prefix() -> None:
    """Sorting run-ids puts older timestamps first; the 8-hex suffix breaks ties."""
    ids = [make_run_id() for _ in range(50)]
    sorted_ids = sorted(ids)
    timestamps = [rid.split("-", 1)[0] for rid in sorted_ids]
    assert timestamps == sorted(timestamps)


def test_layout_helpers_compose_with_instance_dir() -> None:
    key = CacheKey(recipe_hash="a" * 64, input_hash="b" * 64, seed=0)
    inst = instance_dir(Path("/c"), key)
    assert manifest_path(inst).parent == inst
    assert dataset_dir(inst).parent == inst
    assert fitted_stats_dir(inst).parent == inst
    assert report_dir(inst).parent == inst
