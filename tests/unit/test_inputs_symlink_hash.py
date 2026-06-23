# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story K.g (FR-K-2): the input hasher must follow symlinked directories.

Gap 2 reproduction. `Path.rglob("*")` on Python 3.12 does not descend symlinked
directories (`recurse_symlinks` is 3.13+), so a symlinked-dir tree hashed to an
effectively empty file set — two different symlink views collided on one digest,
a silent stale-cache / wrong-data reproducibility bug, while the loader read the
real files. The fix is one shared symlink-following, cycle-protected enumeration
helper used by both the loader and the hasher.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from datarefinery.pipeline.inputs import (
    _hash_image_folder,
    _iter_files,
    enumerate_files,
)


def _img(root: Path, rel: str, fill: int) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((4, 4, 3), fill, dtype=np.uint8)).save(p)


def test_enumerate_files_follows_symlinked_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    _img(real / "brand_x", "1.png", 10)
    _img(real / "brand_x", "2.png", 20)
    view = tmp_path / "view"
    view.mkdir()
    (view / "brand_x").symlink_to(real / "brand_x", target_is_directory=True)

    found = {p.relative_to(view).as_posix() for p in enumerate_files(view)}
    assert found == {"brand_x/1.png", "brand_x/2.png"}, (
        "enumeration must descend symlinked directories (Gap 2)"
    )


def test_iter_files_not_empty_through_symlink(tmp_path: Path) -> None:
    # The exact Gap-2 symptom: _iter_files saw [] through a symlinked dir.
    real = tmp_path / "real"
    _img(real / "brand_x", "1.png", 10)
    view = tmp_path / "view"
    view.mkdir()
    (view / "brand_x").symlink_to(real / "brand_x", target_is_directory=True)

    assert _iter_files(view), "_iter_files must not be empty through a symlinked dir"


def test_two_symlink_views_with_different_targets_hash_differently(tmp_path: Path) -> None:
    real_a = tmp_path / "real_a"
    _img(real_a / "brand_x", "1.png", 10)
    _img(real_a / "brand_x", "2.png", 20)
    real_b = tmp_path / "real_b"
    _img(real_b / "brand_x", "1.png", 99)  # different bytes
    _img(real_b / "brand_x", "2.png", 88)

    view_a = tmp_path / "view_a"
    view_a.mkdir()
    (view_a / "brand_x").symlink_to(real_a / "brand_x", target_is_directory=True)
    view_b = tmp_path / "view_b"
    view_b.mkdir()
    (view_b / "brand_x").symlink_to(real_b / "brand_x", target_is_directory=True)

    assert _hash_image_folder(view_a) != _hash_image_folder(view_b), (
        "different symlink targets must produce different digests (no stale-cache collision)"
    )


def test_hash_reflects_symlinked_content_vs_empty(tmp_path: Path) -> None:
    # A symlinked-content view must NOT hash the same as an empty directory.
    real = tmp_path / "real"
    _img(real / "brand_x", "1.png", 10)
    view = tmp_path / "view"
    view.mkdir()
    (view / "brand_x").symlink_to(real / "brand_x", target_is_directory=True)

    empty = tmp_path / "empty"
    empty.mkdir()
    assert _hash_image_folder(view) != _hash_image_folder(empty)


def test_loader_vs_hasher_file_set_parity(tmp_path: Path) -> None:
    # The image_folder loader reads class subdirs (following the symlink); the
    # hasher's enumeration must see the same image files.
    real = tmp_path / "real"
    _img(real / "brand_x", "1.png", 10)
    _img(real / "brand_x", "2.png", 20)
    view = tmp_path / "view"
    view.mkdir()
    (view / "brand_x").symlink_to(real / "brand_x", target_is_directory=True)

    hasher_imgs = {
        p.relative_to(view).as_posix()
        for p in enumerate_files(view)
        if p.suffix.lower() in {".png", ".jpg", ".jpeg"}
    }
    # The loader globs class-dir images one level down (brand_x/*.png).
    loader_imgs = {p.relative_to(view).as_posix() for p in sorted((view / "brand_x").glob("*.png"))}
    assert hasher_imgs == loader_imgs


def test_cycle_protection_terminates(tmp_path: Path) -> None:
    # A symlink loop must not hang the walk.
    root = tmp_path / "root"
    _img(root, "a.png", 5)
    (root / "loop").symlink_to(root, target_is_directory=True)

    files = enumerate_files(root)
    rels = {p.relative_to(root).as_posix() for p in files}
    assert "a.png" in rels  # terminated and found the real file
