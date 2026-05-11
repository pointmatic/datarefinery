# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-21 cache cleaner tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from datarefinery.cache.cleaner import CleanSelector, clean
from datarefinery.core.errors import CacheError

# Identifiable 16-char shards for the fixture cache layout.
_RECIPE_A = "a" * 16
_RECIPE_B = "b" * 16
_INPUT_X = "x" * 16
_INPUT_Y = "y" * 16


def _set_mtime_days_ago(path: Path, days: float) -> None:
    mtime = time.time() - days * 86400
    os.utime(path, (mtime, mtime))


def _make_instance(cache_root: Path, recipe: str, input_: str, seed: int) -> Path:
    inst = cache_root / "instances" / recipe / input_ / str(seed)
    inst.mkdir(parents=True)
    (inst / "manifest.json").write_text("{}", encoding="utf-8")
    return inst


def _make_orphan(cache_root: Path, name: str) -> Path:
    orphan = cache_root / "instances" / ".tmp" / name
    orphan.mkdir(parents=True)
    (orphan / "manifest.json").write_text("{}", encoding="utf-8")
    return orphan


@pytest.fixture
def populated_cache(tmp_path: Path) -> Path:
    """Synthesized cache layout used by every selector test below.

    Layout:
      instances/
        <recipe_a>/<input_x>/0/
        <recipe_a>/<input_x>/1/
        <recipe_a>/<input_y>/0/
        <recipe_b>/<input_x>/0/
        .tmp/orphan_old/   (mtime: 3 days ago)
        .tmp/orphan_new/   (mtime: now)
    """
    _make_instance(tmp_path, _RECIPE_A, _INPUT_X, 0)
    _make_instance(tmp_path, _RECIPE_A, _INPUT_X, 1)
    _make_instance(tmp_path, _RECIPE_A, _INPUT_Y, 0)
    _make_instance(tmp_path, _RECIPE_B, _INPUT_X, 0)
    old = _make_orphan(tmp_path, "orphan_old")
    _make_orphan(tmp_path, "orphan_new")
    _set_mtime_days_ago(old, 3.0)
    return tmp_path


def test_clean_all_without_force_raises() -> None:
    with pytest.raises(CacheError, match="requires force"):
        clean(Path("/nonexistent"), CleanSelector(all=True))


def test_clean_all_with_force_clears_instances_root(populated_cache: Path) -> None:
    report = clean(populated_cache, CleanSelector(all=True), force=True)
    assert len(report.removed) >= 1
    assert list((populated_cache / "instances").iterdir()) == []


def test_clean_no_selector_is_noop(populated_cache: Path) -> None:
    """Library API: empty selector removes nothing (CLI enforces 'must have a selector')."""
    report = clean(populated_cache, CleanSelector())
    assert report.removed == ()
    assert (populated_cache / "instances" / _RECIPE_A / _INPUT_X / "0").is_dir()


def test_clean_by_recipe_hash_removes_only_that_recipe(populated_cache: Path) -> None:
    report = clean(populated_cache, CleanSelector(by_recipe_hash=_RECIPE_A))
    assert len(report.removed) == 3  # three instances under recipe_a
    assert (
        not (populated_cache / "instances" / _RECIPE_A).exists()
        or list((populated_cache / "instances" / _RECIPE_A).rglob("manifest.json")) == []
    )
    # recipe_b survives.
    assert (populated_cache / "instances" / _RECIPE_B / _INPUT_X / "0").is_dir()


def test_clean_by_recipe_hash_truncates_to_16_chars(populated_cache: Path) -> None:
    """Caller can pass a full hash; the matcher uses the first 16 chars."""
    full_hash = _RECIPE_A + "0" * 48
    report = clean(populated_cache, CleanSelector(by_recipe_hash=full_hash))
    assert len(report.removed) == 3


def test_clean_by_input_hash_intersects_across_recipes(populated_cache: Path) -> None:
    report = clean(populated_cache, CleanSelector(by_input_hash=_INPUT_X))
    # recipe_a/input_x/0, recipe_a/input_x/1, recipe_b/input_x/0
    assert len(report.removed) == 3
    # recipe_a/input_y/0 survives.
    assert (populated_cache / "instances" / _RECIPE_A / _INPUT_Y / "0").is_dir()


def test_clean_by_seed_removes_seed_dirs_only(populated_cache: Path) -> None:
    report = clean(populated_cache, CleanSelector(by_seed=1))
    # Only recipe_a/input_x/1.
    assert len(report.removed) == 1
    assert not (populated_cache / "instances" / _RECIPE_A / _INPUT_X / "1").exists()
    assert (populated_cache / "instances" / _RECIPE_A / _INPUT_X / "0").is_dir()


def test_clean_combines_filters_intersection_style(populated_cache: Path) -> None:
    report = clean(
        populated_cache,
        CleanSelector(by_recipe_hash=_RECIPE_A, by_input_hash=_INPUT_X, by_seed=0),
    )
    assert len(report.removed) == 1
    assert not (populated_cache / "instances" / _RECIPE_A / _INPUT_X / "0").exists()
    # Other instances under recipe_a survive.
    assert (populated_cache / "instances" / _RECIPE_A / _INPUT_X / "1").is_dir()
    assert (populated_cache / "instances" / _RECIPE_A / _INPUT_Y / "0").is_dir()


def test_clean_by_age_days_only_removes_old_instances(populated_cache: Path) -> None:
    aged = populated_cache / "instances" / _RECIPE_A / _INPUT_X / "0"
    _set_mtime_days_ago(aged, 30.0)
    report = clean(populated_cache, CleanSelector(by_age_days=7.0))
    assert len(report.removed) == 1
    assert report.removed[0] == aged


def test_clean_orphans_respects_age_threshold(populated_cache: Path) -> None:
    """orphan_age_days=1 -> only the 3-day-old orphan is removed."""
    report = clean(
        populated_cache,
        CleanSelector(orphans=True, orphan_age_days=1.0),
    )
    assert len(report.removed) == 1
    assert report.removed[0].name == "orphan_old"
    assert (populated_cache / "instances" / ".tmp" / "orphan_new").is_dir()


def test_clean_orphans_with_zero_threshold_removes_all_orphans(
    populated_cache: Path,
) -> None:
    report = clean(
        populated_cache,
        CleanSelector(orphans=True, orphan_age_days=0.0),
    )
    removed_names = sorted(p.name for p in report.removed)
    assert removed_names == ["orphan_new", "orphan_old"]


def test_clean_orphans_does_not_touch_instances(populated_cache: Path) -> None:
    clean(populated_cache, CleanSelector(orphans=True, orphan_age_days=0.0))
    # All four instance dirs still present.
    for recipe, input_, seed in [
        (_RECIPE_A, _INPUT_X, 0),
        (_RECIPE_A, _INPUT_X, 1),
        (_RECIPE_A, _INPUT_Y, 0),
        (_RECIPE_B, _INPUT_X, 0),
    ]:
        assert (populated_cache / "instances" / recipe / input_ / str(seed)).is_dir()


def test_clean_orphans_combined_with_filters(populated_cache: Path) -> None:
    """orphans + by_recipe_hash both fire."""
    report = clean(
        populated_cache,
        CleanSelector(by_recipe_hash=_RECIPE_B, orphans=True, orphan_age_days=1.0),
    )
    removed_names = sorted(p.name for p in report.removed)
    # recipe_b/input_x/0 (named "0") + orphan_old.
    assert "orphan_old" in removed_names
    assert "0" in removed_names


def test_clean_on_missing_cache_root_returns_empty_report(tmp_path: Path) -> None:
    report = clean(tmp_path / "no_cache_here", CleanSelector(by_recipe_hash=_RECIPE_A))
    assert report.removed == ()
    assert report.skipped == ()


def test_clean_skips_paths_that_fail_to_remove(
    populated_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import datarefinery.cache.cleaner as cleaner_mod

    def boom(path: Path) -> None:
        raise OSError("simulated rmtree failure")

    monkeypatch.setattr(cleaner_mod.shutil, "rmtree", boom)

    report = clean(populated_cache, CleanSelector(by_recipe_hash=_RECIPE_A))
    assert report.removed == ()
    assert len(report.skipped) == 3
    assert all("simulated rmtree failure" in reason for _, reason in report.skipped)
