# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
#
# spike — do not import from src/
#
# Story A.c: end-to-end stack spike. Wires the critical path together:
#   recipe dict -> canonical bytes -> SHA-256 -> temp dir -> manifest.json ->
#   atomic os.replace promote -> ./data/instances/<recipe16>/<input16>/<seed>/
#
# Throwaway. Production modules will replace every step. The point is to
# learn the rough edges before recipe/, cache/, pipeline/ exist.

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_ROOT = REPO_ROOT / "data" / "instances"
TMP_ROOT = CACHE_ROOT / ".tmp"


def canonical_bytes(recipe: dict[str, object]) -> bytes:
    return json.dumps(
        recipe,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def make_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(4)}"


def main() -> int:
    recipe: dict[str, object] = {
        "schema_version": 1,
        "plugin": "image_classification",
        "Input": {"sources": [{"name": "train", "kind": "image_folder"}]},
        "Output": {"shape": [32, 32, 3], "dtype": "uint8"},
        "Splits": {"train": 0.8, "val": 0.1, "test": 0.1},
        "seed": 0,
    }
    seed = 0
    fake_input_payload = b"fake-image-bytes-v1"

    recipe_hash_full = sha256_hex(canonical_bytes(recipe))
    input_hash_full = sha256_hex(fake_input_payload)
    recipe16 = recipe_hash_full[:16]
    input16 = input_hash_full[:16]

    final_dir = CACHE_ROOT / recipe16 / input16 / str(seed)

    if final_dir.is_dir() and (final_dir / "manifest.json").is_file():
        print(f"cache=hit path={final_dir.relative_to(REPO_ROOT)}")
        return 0

    run_id = make_run_id()
    temp_dir = TMP_ROOT / run_id
    temp_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "schema_version": 1,
        "recipe_hash": recipe_hash_full,
        "input_hash": input_hash_full,
        "seed": seed,
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
    }
    (temp_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    final_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.replace(temp_dir, final_dir)
    except OSError as exc:
        # Cross-device or already-promoted; clean up and re-raise.
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"promote failed: {exc}", file=sys.stderr)
        return 1

    print(f"cache=miss path={final_dir.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# Discoveries / notes for Phase B implementation stories
# ---------------------------------------------------------------------------
#
# 1. os.replace cross-device trap
#    os.replace() raises OSError(EXDEV) if temp and final live on different
#    filesystems. Implication for cache.atomic (B.h): both
#    `<cache-root>/.tmp/` and `<cache-root>/<recipe16>/<input16>/<seed>/`
#    MUST share a parent on the same filesystem. The atomic_promote() helper
#    should validate `os.stat(temp.parent).st_dev == os.stat(final.parent).st_dev`
#    up front and raise MaterializeError with a clear "same-filesystem" hint
#    rather than letting EXDEV surface deep in a stage.
#
# 2. final_dir.parent.mkdir(parents=True) before os.replace
#    os.replace() does NOT create intermediate parents. The two-level shard
#    (<recipe16>/<input16>/) means we always have to mkdir the parent first.
#    Easy to forget; lock it into the helper.
#
# 3. Truncated hash directories vs full hash in manifest
#    Path components use [:16] of each hex digest (per project-essentials.md
#    "Cache identity is the reproducibility contract — invalidations are
#    ceremonious"). The full digest lives in manifest.json. The spike already
#    follows this so the convention is exercised before code lands.
#
# 4. Idempotency check before any work
#    Cache-hit detection has to happen BEFORE creating the temp dir. Otherwise
#    every re-run leaves orphan temp directories under .tmp/. The runner in
#    C.m should mirror this ordering: check final_dir/manifest.json, only
#    then create temp_dir.
#
# 5. pathlib vs os
#    pathlib.Path is ergonomic for everything except os.replace() — it accepts
#    Path objects but the operation itself is on os. Mixing the two is fine;
#    the only landmine is .relative_to() on a path that has already been
#    promoted (the temp_dir Path is no longer valid post-replace, even though
#    Python doesn't tell you that).
#
# 6. run_id format
#    `<utc_iso_compact>-<8hex>` (YYYYMMDDTHHMMSSZ-XXXXXXXX) sorts
#    lexicographically by creation time and is collision-resistant within a
#    second. Adopt verbatim in cache.layout.make_run_id (B.g).
#
# 7. UTC, not local time
#    datetime.now(UTC) (PEP 691) — never datetime.utcnow() (deprecated, also
#    naive). Worth a unit test that asserts manifest timestamps end in 'Z' or
#    '+00:00'.
