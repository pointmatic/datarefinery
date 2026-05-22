# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Canonical corruption-name list for FR-GEN-1.

Lives separately from `_corruptions.py` (which imports `cv2` and
`scikit-image` at module load) so recipe-time validation in
`generation_imagecorruptions.py` can check corruption names without
requiring the `[corruptions]` extras to be installed.

The order matches upstream `imagecorruptions.corruptions._CORRUPTION_TUPLE`
exactly: 15 common (indices 0..14) + 4 validation (indices 15..18).
``tests/plugins/image_classification/test_corruptions_vendored.py``
includes a guard that asserts `_corruptions.get_corruption_names("all")`
agrees with this tuple when the extras are installed.
"""

from __future__ import annotations

CORRUPTION_NAMES_COMMON: tuple[str, ...] = (
    "gaussian_noise",
    "shot_noise",
    "impulse_noise",
    "defocus_blur",
    "glass_blur",
    "motion_blur",
    "zoom_blur",
    "snow",
    "frost",
    "fog",
    "brightness",
    "contrast",
    "elastic_transform",
    "pixelate",
    "jpeg_compression",
)

CORRUPTION_NAMES_VALIDATION: tuple[str, ...] = (
    "speckle_noise",
    "gaussian_blur",
    "spatter",
    "saturate",
)

CORRUPTION_NAMES_ALL: tuple[str, ...] = (
    *CORRUPTION_NAMES_COMMON,
    *CORRUPTION_NAMES_VALIDATION,
)
