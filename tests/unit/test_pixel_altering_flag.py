# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.g: the closed set of pixel-altering Transformation ops.

An op is *pixel-altering* if its ``apply`` changes the image array's
bytes in a consumer-visible way that is NOT recoverable from persisted
fitted statistics. ``resize`` qualifies (geometry change). ``normalize``
and ``mean_subtract`` do NOT — they are stat-based and consumer-applied
(the fitted mean/std are persisted; the consumer re-applies them at load
time). ``cast`` is a parameter-deterministic numeric op, also consumer-
applied; it is not pixel-altering by this criterion.
"""

from __future__ import annotations

from datarefinery.plugins.image_classification import PLUGIN


def test_resize_is_pixel_altering() -> None:
    assert PLUGIN.supported_operations["resize"].pixel_altering is True


def test_normalize_is_not_pixel_altering() -> None:
    assert PLUGIN.supported_operations["normalize"].pixel_altering is False


def test_mean_subtract_is_not_pixel_altering() -> None:
    assert PLUGIN.supported_operations["mean_subtract"].pixel_altering is False


def test_cast_is_not_pixel_altering() -> None:
    assert PLUGIN.supported_operations["cast"].pixel_altering is False


def test_pixel_altering_defaults_false() -> None:
    # Augmentation / Featurization / Visualization ops carry the default.
    assert PLUGIN.supported_operations["horizontal_flip"].pixel_altering is False
    assert PLUGIN.supported_operations["flatten"].pixel_altering is False
