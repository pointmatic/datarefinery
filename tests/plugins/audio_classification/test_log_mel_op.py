# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.s: `log_mel_spectrogram` Featurization op.

Converts a fixed-length window's `sample_array` into a log-mel spectrogram
`feature` of shape `(n_mels, n_frames)` via librosa. Deterministic (a pure
function of the samples + params), one output per input window, all existing
fields preserved. Requires the `[audio]` extra; skips without it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

pytest.importorskip("librosa")

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.stages.transformations import FittedValues
from datarefinery.plugins.audio_classification.operations.featurizations import (
    LogMelParams,
    LogMelSpectrogramOp,
)

_SR = 16000
_PARAMS: dict[str, Any] = {
    "n_fft": 512,
    "hop_length": 256,
    "n_mels": 64,
    "f_min": 0.0,
    "f_max": None,
    "power": 2.0,
}


def _window(*, record_id: str = "clips/cat/a.wav__w0000", n: int = 1600) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "source_record_id": "clips/cat/a.wav",
        "window_index": 0,
        "sample_array": np.linspace(0.0, 1.0, n, endpoint=False).astype(np.float32),
        "sample_rate": _SR,
        "path": "/data/clips/cat/a.wav",
        "label": "cat",
    }


def _apply(
    records: list[Mapping[str, Any]],
    params: dict[str, Any] | None = None,
    *,
    output_field: str = "feature",
) -> list[Mapping[str, Any]]:
    op = LogMelSpectrogramOp()
    return op.apply(
        list(records),
        params or _PARAMS,
        FittedValues(),
        inputs=["sample_array"],
        output_field=output_field,
        label_field="label",
    )


def _expected_frames(n: int, hop_length: int) -> int:
    # librosa default center=True pads, giving 1 + n // hop_length frames.
    return 1 + n // hop_length


def test_feature_shape_is_n_mels_by_n_frames() -> None:
    out = _apply([_window(n=1600)])
    feat = out[0]["feature"]
    assert feat.shape == (64, _expected_frames(1600, 256))


def test_feature_shape_tracks_n_mels_param() -> None:
    out = _apply([_window(n=1600)], {**_PARAMS, "n_mels": 32})
    assert out[0]["feature"].shape[0] == 32


def test_one_output_per_input_window() -> None:
    out = _apply([_window(record_id="a__w0000"), _window(record_id="b__w0000", n=2000)])
    assert len(out) == 2


def test_feature_is_deterministic_byte_identical() -> None:
    a = _apply([_window(n=1600)])
    b = _apply([_window(n=1600)])
    assert np.array_equal(a[0]["feature"], b[0]["feature"])
    assert a[0]["feature"].dtype == b[0]["feature"].dtype


def test_preserves_existing_fields_and_adds_feature() -> None:
    out = _apply([_window()])
    r = out[0]
    assert r["record_id"] == "clips/cat/a.wav__w0000"
    assert r["source_record_id"] == "clips/cat/a.wav"
    assert r["window_index"] == 0
    assert r["sample_rate"] == _SR
    assert r["label"] == "cat"
    assert "feature" in r
    # sample_array is left intact (the op adds, never removes).
    assert "sample_array" in r


def test_output_field_name_is_honored() -> None:
    out = _apply([_window()], output_field="log_mel")
    assert "log_mel" in out[0]
    assert "feature" not in out[0]


def test_f_max_none_resolves_to_nyquist() -> None:
    # f_max=None is the mode-selecting "use Nyquist" case; it must run and give a
    # full-height feature. A small explicit f_max produces the same n_mels rows.
    nyq = _apply([_window()], {**_PARAMS, "f_max": None})
    capped = _apply([_window()], {**_PARAMS, "f_max": 4000.0})
    assert nyq[0]["feature"].shape[0] == 64
    assert capped[0]["feature"].shape[0] == 64
    # The two are genuinely different spectrograms (Nyquist vs. 4 kHz ceiling).
    assert not np.array_equal(nyq[0]["feature"], capped[0]["feature"])


def test_hop_length_greater_than_n_fft_is_allowed() -> None:
    out = _apply([_window(n=2048)], {**_PARAMS, "n_fft": 256, "hop_length": 512})
    assert out[0]["feature"].shape[0] == 64
    assert out[0]["feature"].shape[1] == _expected_frames(2048, 512)


def test_missing_sample_array_is_a_materialize_error() -> None:
    bad: list[Mapping[str, Any]] = [{"record_id": "x", "sample_rate": _SR}]
    with pytest.raises(MaterializeError, match="sample_array"):
        _apply(bad)


def test_fit_is_a_noop() -> None:
    op = LogMelSpectrogramOp()
    assert op.fit_on_train is False
    fitted = op.fit(
        [_window()], _PARAMS, inputs=["sample_array"], output_field="feature", label_field="label"
    )
    assert fitted.scalars == {} and fitted.vectors == {}


def test_params_reject_nonpositive_values() -> None:
    for bad in ({"n_fft": 0}, {"n_mels": -1}, {"hop_length": 0}, {"power": 0}):
        with pytest.raises(ValidationError):
            LogMelParams.model_validate({**_PARAMS, **bad})


def test_params_reject_unknown_key() -> None:
    with pytest.raises(ValidationError):
        LogMelParams.model_validate({**_PARAMS, "bogus": 1})
