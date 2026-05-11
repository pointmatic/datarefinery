# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-5 atomic temp-then-promote and `FAILED` marker.

`atomic_promote(temp, final)` uses `os.replace` to swap a fully populated
temp directory into its final location atomically. A cross-device
mismatch is caught up-front so the EXDEV failure surfaces with a
"same-filesystem" message rather than deep inside the runner. On
failure, `mark_failed(temp, exc, stage)` writes a JSON `FAILED` marker
into the temp dir capturing the stage, exception type, message, and
traceback for diagnostic recovery.
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import UTC, datetime
from pathlib import Path

from datarefinery.core.errors import MaterializeError

FAILED_MARKER = "FAILED"


def _device_id(path: Path) -> int:
    """Return `st_dev` for `path`. Wrapped so tests can monkey-patch the cross-device guard."""
    return os.stat(path).st_dev


def atomic_promote(temp_dir: Path, final_dir: Path) -> None:
    """Atomically promote `temp_dir` to `final_dir` via `os.replace`.

    Raises `MaterializeError` if `temp_dir` does not exist, if temp and
    final live on different filesystems (`os.replace` would raise
    `EXDEV`), or if the underlying rename fails. `final_dir.parent` is
    created if missing; the parent directory chain ends one level above
    the eventual instance.
    """
    if not temp_dir.is_dir():
        raise MaterializeError(f"temp dir does not exist: {temp_dir}")

    final_parent = final_dir.parent
    final_parent.mkdir(parents=True, exist_ok=True)

    temp_dev = _device_id(temp_dir.parent)
    final_dev = _device_id(final_parent)
    if temp_dev != final_dev:
        raise MaterializeError(
            f"cannot atomically promote across filesystems: "
            f"temp_dir={temp_dir} (st_dev={temp_dev}), "
            f"final_dir={final_dir} (st_dev={final_dev}). "
            f"DataRefinery requires the cache root and the temp dir to "
            f"share a filesystem; configure --cache-root accordingly."
        )

    try:
        os.replace(temp_dir, final_dir)
    except OSError as exc:
        raise MaterializeError(
            f"atomic promote failed for {temp_dir} -> {final_dir}: {exc}"
        ) from exc


def mark_failed(temp_dir: Path, exc: BaseException, stage: str) -> None:
    """Write a `FAILED` JSON marker into `temp_dir` capturing the failure context.

    No-op when `temp_dir` does not exist (e.g., it was already promoted
    or deleted before the runner caught the failure). The marker is a
    diagnostic artifact; it never blocks failure propagation in the
    runner.
    """
    if not temp_dir.is_dir():
        return

    payload = {
        "stage": stage,
        "exc_type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "marked_at": (datetime.now(UTC).isoformat().replace("+00:00", "Z")),
    }

    marker = temp_dir / FAILED_MARKER
    marker.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
