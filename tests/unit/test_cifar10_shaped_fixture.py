# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Self-tests for the CIFAR-10-shaped synthesizer (Story E.a).

The synthesizer is consumed across the integration suite; it has to be
deterministic and produce exactly the layout the scaffolder accepts.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from PIL import Image
from tests.fixtures.build_cifar10_shaped import (
    DEFAULT_IMAGE_SIZE,
    DEFAULT_NUM_CLASSES,
    DEFAULT_PER_CLASS,
    build_cifar10_shaped,
)


def _all_pngs(root: Path) -> list[Path]:
    return sorted(root.rglob("*.png"))


def test_default_layout_has_50_pngs_across_10_class_folders(
    tmp_path: Path,
) -> None:
    root = build_cifar10_shaped(tmp_path / "data")
    class_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    assert len(class_dirs) == DEFAULT_NUM_CLASSES
    assert all(d.name.startswith("class") for d in class_dirs)
    pngs = _all_pngs(root)
    assert len(pngs) == DEFAULT_NUM_CLASSES * DEFAULT_PER_CLASS == 50


def test_each_image_is_8x8_rgb(tmp_path: Path) -> None:
    root = build_cifar10_shaped(tmp_path / "data")
    for path in _all_pngs(root):
        with Image.open(path) as im:
            assert im.size == (DEFAULT_IMAGE_SIZE, DEFAULT_IMAGE_SIZE)
            assert im.mode == "RGB"


def test_synthesizer_is_deterministic(tmp_path: Path) -> None:
    """Same seed -> byte-identical PNG output across runs."""
    a = build_cifar10_shaped(tmp_path / "a", seed=42)
    b = build_cifar10_shaped(tmp_path / "b", seed=42)
    a_files = _all_pngs(a)
    b_files = _all_pngs(b)
    assert [p.relative_to(a) for p in a_files] == [
        p.relative_to(b) for p in b_files
    ]
    for ap, bp in zip(a_files, b_files, strict=True):
        assert hashlib.sha256(ap.read_bytes()).digest() == hashlib.sha256(
            bp.read_bytes()
        ).digest()


def test_different_seeds_produce_different_outputs(tmp_path: Path) -> None:
    a = build_cifar10_shaped(tmp_path / "a", seed=1)
    b = build_cifar10_shaped(tmp_path / "b", seed=2)
    a_first = _all_pngs(a)[0].read_bytes()
    b_first = _all_pngs(b)[0].read_bytes()
    assert a_first != b_first


def test_synthesizer_finishes_well_under_one_second(tmp_path: Path) -> None:
    """Story E.a: 'fixture builds in <1s'."""
    start = time.monotonic()
    build_cifar10_shaped(tmp_path / "data")
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"synthesizer took {elapsed:.3f}s; should be <1s"


def test_session_fixture_is_reusable(cifar10_shaped_dir: Path) -> None:
    """The conftest fixture is consumable by name and matches the layout."""
    assert cifar10_shaped_dir.is_dir()
    pngs = _all_pngs(cifar10_shaped_dir)
    assert len(pngs) == DEFAULT_NUM_CLASSES * DEFAULT_PER_CLASS
