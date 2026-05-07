# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-5 atomic temp-then-promote tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import datarefinery.cache.atomic as atomic_mod
from datarefinery.cache.atomic import (
    FAILED_MARKER,
    atomic_promote,
    mark_failed,
)
from datarefinery.core.errors import MaterializeError


def _populate(temp: Path) -> None:
    temp.mkdir(parents=True)
    (temp / "manifest.json").write_text("{}", encoding="utf-8")
    (temp / "dataset").mkdir()
    (temp / "dataset" / "shard_0").write_text("data", encoding="utf-8")


def test_atomic_promote_success_path(tmp_path: Path) -> None:
    temp = tmp_path / "instances" / ".tmp" / "20260507T0-abc"
    final = tmp_path / "instances" / "ab" / "cd" / "0"
    _populate(temp)

    atomic_promote(temp, final)

    assert not temp.exists(), "temp dir should be gone after promote"
    assert (final / "manifest.json").read_text() == "{}"
    assert (final / "dataset" / "shard_0").read_text() == "data"


def test_atomic_promote_creates_intermediate_final_parents(tmp_path: Path) -> None:
    temp = tmp_path / "instances" / ".tmp" / "run"
    final = tmp_path / "instances" / "deep" / "nested" / "path" / "0"
    _populate(temp)

    atomic_promote(temp, final)

    assert final.is_dir()


def test_atomic_promote_raises_when_temp_missing(tmp_path: Path) -> None:
    temp = tmp_path / "missing_temp"
    final = tmp_path / "final" / "instance"
    with pytest.raises(MaterializeError, match="temp dir does not exist"):
        atomic_promote(temp, final)


def test_atomic_promote_refuses_cross_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp = tmp_path / "tmp_root" / "run"
    final = tmp_path / "final_root" / "instance"
    _populate(temp)

    def fake_device_id(path: Path) -> int:
        # Treat the temp parent and final parent as different filesystems.
        return 1 if "tmp_root" in str(path) else 2

    monkeypatch.setattr(atomic_mod, "_device_id", fake_device_id)

    with pytest.raises(MaterializeError) as info:
        atomic_promote(temp, final)
    msg = str(info.value)
    assert "across filesystems" in msg
    assert "st_dev=1" in msg
    assert "st_dev=2" in msg
    # Temp dir untouched on cross-device refusal.
    assert temp.is_dir()
    assert (temp / "manifest.json").exists()


def test_atomic_promote_wraps_os_replace_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp = tmp_path / "tmp" / "run"
    final = tmp_path / "final" / "instance"
    _populate(temp)

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(atomic_mod.os, "replace", boom)

    with pytest.raises(MaterializeError, match="atomic promote failed"):
        atomic_promote(temp, final)


def test_mark_failed_writes_marker_with_required_fields(tmp_path: Path) -> None:
    temp = tmp_path / "tmp" / "run"
    temp.mkdir(parents=True)

    try:
        raise RuntimeError("kaboom")
    except RuntimeError as exc:
        mark_failed(temp, exc, stage="Transformations")

    marker = temp / FAILED_MARKER
    assert marker.is_file()
    payload = json.loads(marker.read_text())
    assert payload["stage"] == "Transformations"
    assert payload["exc_type"] == "RuntimeError"
    assert payload["message"] == "kaboom"
    assert "kaboom" in payload["traceback"]
    assert "RuntimeError" in payload["traceback"]
    assert payload["marked_at"].endswith("Z")


def test_mark_failed_is_noop_if_temp_does_not_exist(tmp_path: Path) -> None:
    """If temp_dir was already promoted/cleaned, mark_failed silently does nothing."""
    missing = tmp_path / "never_existed"

    try:
        raise RuntimeError("late")
    except RuntimeError as exc:
        mark_failed(missing, exc, stage="cleanup")  # must not raise

    assert not missing.exists()


def test_atomic_promote_failure_then_mark_failed_leaves_temp_with_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: forced promote failure -> mark_failed -> temp + FAILED present."""
    temp = tmp_path / "tmp" / "run"
    final = tmp_path / "final" / "instance"
    _populate(temp)

    def fake_device_id(path: Path) -> int:
        return 1 if "tmp" in str(path) else 2

    monkeypatch.setattr(atomic_mod, "_device_id", fake_device_id)

    captured_exc: MaterializeError | None = None
    try:
        atomic_promote(temp, final)
    except MaterializeError as exc:
        captured_exc = exc
        mark_failed(temp, exc, stage="atomic_promote")

    assert captured_exc is not None
    assert temp.is_dir()
    assert (temp / FAILED_MARKER).is_file()
    payload = json.loads((temp / FAILED_MARKER).read_text())
    assert payload["exc_type"] == "MaterializeError"
    assert payload["stage"] == "atomic_promote"
    # And the would-be final dir was never populated.
    assert not (final / "manifest.json").exists()
