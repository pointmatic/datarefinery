# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""CIFAR-10-shaped synthetic dataset builder for tests.

DataRefinery test suites need an image-classification fixture that
exercises the full critical path: 10 classes, multiple images per
class, an ImageFolder layout the scaffolder accepts, deterministic
content. The actual CIFAR-10 dataset is far too large to vendor (and
licensing is messier than synthesizing); this builder generates a tiny
look-alike at test time using a seeded NumPy RNG so every machine
produces byte-identical images.

DO NOT check in the real CIFAR-10 binary archives here. The point of
this synthesizer is that the test suite stays self-contained and fast
- vendoring the real dataset would balloon the repo and add a
licensing surface to manage. If a test genuinely needs the real
dataset (visual sanity checks, post-v1 benchmarks), download it
locally via a one-shot script and gitignore the result.

Layout produced::

    <root>/
      class00/
        class00_000.png
        class00_001.png
        ...
      class01/
        ...

Default size: 10 classes x 5 images each = 50 PNGs. Each PNG is 8x8
RGB uniform-noise generated from ``numpy.random.default_rng(seed)``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

DEFAULT_NUM_CLASSES = 10
DEFAULT_PER_CLASS = 5
DEFAULT_IMAGE_SIZE = 8
DEFAULT_SEED = 2026


def build_cifar10_shaped(
    root: Path,
    *,
    num_classes: int = DEFAULT_NUM_CLASSES,
    per_class: int = DEFAULT_PER_CLASS,
    image_size: int = DEFAULT_IMAGE_SIZE,
    seed: int = DEFAULT_SEED,
) -> Path:
    """Synthesize a CIFAR-10-shaped image-classification dataset at ``root``.

    Returns ``root`` so the result composes with `tmp_path` patterns:
    ``data = build_cifar10_shaped(tmp_path / "data")``.

    The seed is a single RNG seed; per-image arrays are drawn in
    deterministic order (sorted classes, image index ascending) so
    outputs are byte-stable across runs.
    """
    root = Path(root)
    rng = np.random.default_rng(seed)
    classes = tuple(f"class{i:02d}" for i in range(num_classes))
    for cls in classes:
        cls_dir = root / cls
        cls_dir.mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            arr = rng.integers(0, 255, (image_size, image_size, 3), dtype=np.uint8)
            Image.fromarray(arr).save(cls_dir / f"{cls}_{i:03d}.png")
    return root
