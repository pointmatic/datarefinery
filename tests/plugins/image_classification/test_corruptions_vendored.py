# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.m.1 tests for the vendored `_corruptions` module.

Verifies the four spike-driven patches (`np.float_` -> `np.float64`;
`multichannel=` -> `channel_axis=`; explicit-`rng` `impulse_noise`;
`importlib.resources`-based frost loading) all work, and that all 19
corruption names are deterministic at severity 3 for a fixed input.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from datarefinery.plugins.image_classification import _corruptions

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


def test_get_corruption_names_all_19() -> None:
    all_names = _corruptions.get_corruption_names("all")
    assert len(all_names) == 19


def test_get_corruption_names_common_15() -> None:
    assert len(_corruptions.get_corruption_names("common")) == 15


def test_get_corruption_names_validation_4() -> None:
    assert len(_corruptions.get_corruption_names("validation")) == 4


def test_common_plus_validation_equals_all_no_overlap() -> None:
    common = set(_corruptions.get_corruption_names("common"))
    validation = set(_corruptions.get_corruption_names("validation"))
    all_names = set(_corruptions.get_corruption_names("all"))
    assert common.isdisjoint(validation)
    assert common | validation == all_names


def test_get_corruption_names_unknown_subset_raises() -> None:
    with pytest.raises(ValueError, match="subset must be one of"):
        _corruptions.get_corruption_names("nonexistent")


def test_static_names_module_matches_backend() -> None:
    """The dependency-free `_corruption_names` module must stay in sync
    with the backend's `get_corruption_names('all')`. Drift between the
    two would cause recipe-time validation to accept names the backend
    cannot apply, or reject names the backend supports.
    """
    from datarefinery.plugins.image_classification._corruption_names import (
        CORRUPTION_NAMES_ALL,
        CORRUPTION_NAMES_COMMON,
        CORRUPTION_NAMES_VALIDATION,
    )

    assert list(CORRUPTION_NAMES_COMMON) == _corruptions.get_corruption_names("common")
    assert list(CORRUPTION_NAMES_VALIDATION) == _corruptions.get_corruption_names("validation")
    assert list(CORRUPTION_NAMES_ALL) == _corruptions.get_corruption_names("all")


# ---------------------------------------------------------------------------
# Determinism — all 19 corruptions at severity 3
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_image() -> np.ndarray:
    """A 64x64 RGB uint8 image derived from a fixed seed.

    Module-scoped so the input bytes are stable across the determinism
    sweep but not shared with tests that mutate the image in place.
    """
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)


@pytest.mark.parametrize("name", _corruptions.get_corruption_names("all"))
def test_each_corruption_is_deterministic_at_severity_3(
    name: str, fixture_image: np.ndarray
) -> None:
    rng_a = np.random.default_rng(0)
    rng_b = np.random.default_rng(0)
    out_a = _corruptions.corrupt(fixture_image.copy(), corruption_name=name, severity=3, rng=rng_a)
    out_b = _corruptions.corrupt(fixture_image.copy(), corruption_name=name, severity=3, rng=rng_b)
    assert out_a.shape == fixture_image.shape
    assert out_a.dtype == np.uint8
    h_a = hashlib.sha256(out_a.tobytes()).hexdigest()
    h_b = hashlib.sha256(out_b.tobytes()).hexdigest()
    assert h_a == h_b, f"{name}: re-run produced different bytes"


# ---------------------------------------------------------------------------
# Patch-specific regressions (named explicitly so failures point at the
# right upstream issue)
# ---------------------------------------------------------------------------


def test_fog_does_not_raise_numpy2_attributeerror(fixture_image: np.ndarray) -> None:
    """Upstream `fog` crashed on `np.float_` (removed in NumPy 2.0)."""
    out = _corruptions.corrupt(
        fixture_image.copy(),
        corruption_name="fog",
        severity=3,
        rng=np.random.default_rng(0),
    )
    assert out.shape == fixture_image.shape


def test_gaussian_blur_uses_channel_axis(fixture_image: np.ndarray) -> None:
    """Upstream `gaussian_blur` crashed on `gaussian(multichannel=True)`."""
    out = _corruptions.corrupt(
        fixture_image.copy(),
        corruption_name="gaussian_blur",
        severity=3,
        rng=np.random.default_rng(0),
    )
    assert out.shape == fixture_image.shape


def test_glass_blur_uses_channel_axis(fixture_image: np.ndarray) -> None:
    """Upstream `glass_blur` crashed on `gaussian(multichannel=True)`."""
    out = _corruptions.corrupt(
        fixture_image.copy(),
        corruption_name="glass_blur",
        severity=3,
        rng=np.random.default_rng(0),
    )
    assert out.shape == fixture_image.shape


def test_impulse_noise_is_deterministic_with_explicit_rng(
    fixture_image: np.ndarray,
) -> None:
    """Upstream `impulse_noise` called `skimage.util.random_noise` without
    threading an `rng`, making the output non-deterministic on
    scikit-image 0.21+.
    """
    rng_a = np.random.default_rng(7)
    rng_b = np.random.default_rng(7)
    out_a = _corruptions.corrupt(
        fixture_image.copy(),
        corruption_name="impulse_noise",
        severity=3,
        rng=rng_a,
    )
    out_b = _corruptions.corrupt(
        fixture_image.copy(),
        corruption_name="impulse_noise",
        severity=3,
        rng=rng_b,
    )
    assert (
        hashlib.sha256(out_a.tobytes()).hexdigest() == hashlib.sha256(out_b.tobytes()).hexdigest()
    )


def test_frost_loads_a_texture_via_importlib_resources(fixture_image: np.ndarray) -> None:
    """Upstream `frost` resolved texture paths via `pkg_resources`
    (removed from `setuptools>=81`). The vendored copy uses
    `importlib.resources`; this test smoke-checks the data path.
    """
    out = _corruptions.corrupt(
        fixture_image.copy(),
        corruption_name="frost",
        severity=3,
        rng=np.random.default_rng(0),
    )
    assert out.shape == fixture_image.shape


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_corrupt_rejects_non_ndarray() -> None:
    with pytest.raises(TypeError, match=r"numpy\.ndarray"):
        _corruptions.corrupt(
            "not an array",  # type: ignore[arg-type]
            corruption_name="gaussian_noise",
            severity=3,
            rng=np.random.default_rng(0),
        )


def test_corrupt_rejects_non_uint8(fixture_image: np.ndarray) -> None:
    with pytest.raises(TypeError, match="uint8"):
        _corruptions.corrupt(
            fixture_image.astype(np.float32),
            corruption_name="gaussian_noise",
            severity=3,
            rng=np.random.default_rng(0),
        )


def test_corrupt_rejects_small_image() -> None:
    small = np.zeros((16, 16, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="at least 32"):
        _corruptions.corrupt(
            small, corruption_name="gaussian_noise", severity=3, rng=np.random.default_rng(0)
        )


def test_corrupt_rejects_unknown_corruption_name(fixture_image: np.ndarray) -> None:
    with pytest.raises(ValueError, match="unknown corruption_name"):
        _corruptions.corrupt(
            fixture_image.copy(),
            corruption_name="not_real",
            severity=3,
            rng=np.random.default_rng(0),
        )


def test_corrupt_rejects_severity_out_of_range(fixture_image: np.ndarray) -> None:
    with pytest.raises(ValueError, match=r"\[1, 5\]"):
        _corruptions.corrupt(
            fixture_image.copy(),
            corruption_name="gaussian_noise",
            severity=6,
            rng=np.random.default_rng(0),
        )
