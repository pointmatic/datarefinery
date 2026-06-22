# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.t: `audio_normalize` fit-on-train Featurization op (R5).

Fit-on-train **per-mel-bin** normalization of `(n_mels, n_frames)` log-mel
features: a length-`n_mels` mean/std vector fit over examples and frames,
keeping the mel axis, persisted in the existing structured form, applied across
all declared splits. It is a *Featurization* (not a Transformation) so it runs after
`log_mel_spectrogram` produces the feature; the convention is `inputs: [mel]`,
`output_field: feature`. Mirrors `NormalizeOp`'s fit/apply/zero-variance
discipline but keeps mel (axis 0), not the last axis. No librosa dependency
(pure numpy), so no `[audio]` extra needed for these tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from datarefinery.plugins.audio_classification.operations.featurizations import (
    AudioNormalizeOp,
)

_N_MELS = 4
_N_FRAMES = 3


def _mel(seed: int) -> np.ndarray:
    rng = np.arange(_N_MELS * _N_FRAMES, dtype=np.float64) + seed
    return rng.reshape(_N_MELS, _N_FRAMES)


def _record(seed: int, *, label: str = "cat") -> dict[str, Any]:
    return {
        "record_id": f"clips/cat/a.wav__w{seed:04d}",
        "source_record_id": "clips/cat/a.wav",
        "window_index": seed,
        "mel": _mel(seed),
        "sample_rate": 16000,
        "label": label,
    }


def _fit(records: Sequence[Mapping[str, Any]], params: dict[str, Any] | None = None) -> Any:
    return AudioNormalizeOp().fit(
        list(records), params or {}, inputs=["mel"], output_field="feature", label_field="label"
    )


def _apply(
    records: Sequence[Mapping[str, Any]], fitted: Any, params: dict[str, Any] | None = None
) -> list[Mapping[str, Any]]:
    return AudioNormalizeOp().apply(
        list(records),
        params or {},
        fitted,
        inputs=["mel"],
        output_field="feature",
        label_field="label",
    )


def test_fit_is_per_mel_bin_over_examples_and_frames() -> None:
    records = [_record(0), _record(10), _record(100)]
    fitted = _fit(records)
    mean = np.asarray(fitted.vectors["mean"]["value"].to_pylist())
    std = np.asarray(fitted.vectors["std"]["value"].to_pylist())
    assert mean.shape == (_N_MELS,)
    assert std.shape == (_N_MELS,)
    # Reference: reduce over the example axis (0) and the frame axis (2),
    # keeping the mel axis (1) — the per-mel-bin statistic.
    stack = np.stack([r["mel"] for r in records])  # (N, n_mels, n_frames)
    np.testing.assert_allclose(mean, stack.mean(axis=(0, 2)))
    np.testing.assert_allclose(std, stack.std(axis=(0, 2)))


def test_fit_then_apply_yields_per_mel_zero_mean_unit_std() -> None:
    records = [_record(0), _record(7), _record(13), _record(21)]
    fitted = _fit(records)
    out = _apply(records, fitted)
    feats = np.stack([r["feature"] for r in out])  # (N, n_mels, n_frames)
    # Per-mel-bin (axis 1) mean ≈ 0 and std ≈ 1 across examples+frames.
    np.testing.assert_allclose(feats.mean(axis=(0, 2)), np.zeros(_N_MELS), atol=1e-9)
    np.testing.assert_allclose(feats.std(axis=(0, 2)), np.ones(_N_MELS), atol=1e-9)


def test_apply_preserves_other_fields_and_shape() -> None:
    out = _apply([_record(0)], _fit([_record(0), _record(5)]))
    r = out[0]
    assert r["feature"].shape == (_N_MELS, _N_FRAMES)
    # The raw input feature is preserved (distinct output field), and so is the
    # window metadata.
    assert "mel" in r
    assert r["source_record_id"] == "clips/cat/a.wav"
    assert r["window_index"] == 0
    assert r["label"] == "cat"


def test_zero_variance_bin_guard() -> None:
    # Mel bin 1 is constant across all examples+frames → std == 0 there.
    def const_bin1(seed: int) -> dict[str, Any]:
        f = _mel(seed)
        f[1, :] = 5.0  # bin 1 constant for every record
        return {**_record(seed), "mel": f}

    records = [const_bin1(0), const_bin1(9)]
    fitted = _fit(records)
    std = np.asarray(fitted.vectors["std"]["value"].to_pylist())
    # Persisted std carries the unmodified fit value (0) for the constant bin.
    assert std[1] == 0.0
    out = _apply(records, fitted)
    # Apply substitutes std==0 → 1.0 so the constant bin maps to 0, no nan/inf.
    for r in out:
        assert np.all(np.isfinite(r["feature"]))
        np.testing.assert_allclose(r["feature"][1, :], np.zeros(_N_FRAMES))


def test_fit_is_deterministic_byte_identical() -> None:
    records = [_record(0), _record(3), _record(8)]
    a = _fit(records)
    b = _fit(records)
    np.testing.assert_array_equal(
        np.asarray(a.vectors["mean"]["value"].to_pylist()),
        np.asarray(b.vectors["mean"]["value"].to_pylist()),
    )
    np.testing.assert_array_equal(
        np.asarray(a.vectors["std"]["value"].to_pylist()),
        np.asarray(b.vectors["std"]["value"].to_pylist()),
    )


def test_recipe_pinned_mean_std_is_honored() -> None:
    mean = [1.0, 2.0, 3.0, 4.0]
    std = [2.0, 2.0, 2.0, 2.0]
    fitted = _fit([_record(0)], {"mean": mean, "std": std})
    np.testing.assert_array_equal(np.asarray(fitted.vectors["mean"]["value"].to_pylist()), mean)
    np.testing.assert_array_equal(np.asarray(fitted.vectors["std"]["value"].to_pylist()), std)


def test_fit_on_train_flag_is_true() -> None:
    assert AudioNormalizeOp().fit_on_train is True
