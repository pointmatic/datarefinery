# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.q: `window` Generation op.

Turns one decoded clip into N fixed-length window records. Fully deterministic
(non-stochastic): same input + params → byte-identical windows and stable
`record_id`s. Window records carry `source_record_id` (the parent clip id) and
`window_index` so downstream aggregation (R7) can group them; the trailing
remainder is either zero-padded or dropped per the author-declared policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from datarefinery.core.errors import MaterializeError
from datarefinery.plugins.audio_classification.operations.generation import (
    WindowParams,
    window,
)

_OUTPUT_SCHEMA: dict[str, Any] = {}


def _clip(record_id: str = "clips/cat/a.wav", n: int = 1000, sr: int = 16000) -> Mapping[str, Any]:
    return {
        "record_id": record_id,
        "sample_array": np.arange(n, dtype=np.float32),
        "sample_rate": sr,
        "path": f"/data/{record_id}",
        "label": "cat",
    }


def _run(records: list[Mapping[str, Any]], params: dict[str, Any]) -> list[Mapping[str, Any]]:
    return window(
        records,
        seed=0,
        inputs=["sample_array"],
        output_schema=_OUTPUT_SCHEMA,
        params=params,
        label_field="label",
        op_name="win",
    )


def test_drop_remainder_emits_only_full_windows() -> None:
    # 1000 samples, window 400, hop 300: full-window starts at 0, 300, 600
    # (600+400=1000 ✓); next start 900 → 900+400>1000 → dropped.
    out = _run(
        [_clip(n=1000)], {"window_length_samples": 400, "hop_samples": 300, "remainder": "drop"}
    )
    assert len(out) == 3
    assert all(len(r["sample_array"]) == 400 for r in out)


def test_pad_zero_remainder_emits_padded_trailing_window() -> None:
    # Same geometry, but pad_zero also emits the start at 900 (one real sample
    # window [900:1000] zero-padded to 400).
    out = _run(
        [_clip(n=1000)], {"window_length_samples": 400, "hop_samples": 300, "remainder": "pad_zero"}
    )
    assert len(out) == 4
    assert all(len(r["sample_array"]) == 400 for r in out)
    # The trailing window is padded: its tail is zeros beyond the 100 real samples.
    last = out[-1]["sample_array"]
    assert np.array_equal(last[100:], np.zeros(300, dtype=np.float32))
    assert np.array_equal(last[:100], np.arange(900, 1000, dtype=np.float32))


def test_window_records_carry_source_record_id_and_index() -> None:
    out = _run(
        [_clip(record_id="clips/cat/a.wav", n=1000)],
        {"window_length_samples": 500, "hop_samples": 500, "remainder": "drop"},
    )
    assert len(out) == 2
    assert [r["record_id"] for r in out] == ["clips/cat/a.wav__w0000", "clips/cat/a.wav__w0001"]
    assert all(r["source_record_id"] == "clips/cat/a.wav" for r in out)
    assert [r["window_index"] for r in out] == [0, 1]


def test_window_inherits_sample_rate_path_and_label() -> None:
    out = _run(
        [_clip(n=600)], {"window_length_samples": 300, "hop_samples": 300, "remainder": "drop"}
    )
    for r in out:
        assert r["sample_rate"] == 16000
        assert r["path"] == "/data/clips/cat/a.wav"
        assert r["label"] == "cat"


def test_window_length_seconds_resolves_against_sample_rate() -> None:
    # 0.5s @ 16 kHz = 8000 samples; a 16000-sample clip yields 2 windows (hop=8000).
    out = _run(
        [_clip(n=16000, sr=16000)],
        {"window_length_seconds": 0.5, "hop_samples": 8000, "remainder": "drop"},
    )
    assert len(out) == 2
    assert all(len(r["sample_array"]) == 8000 for r in out)


def test_decode_is_deterministic_byte_identical() -> None:
    params = {"window_length_samples": 400, "hop_samples": 250, "remainder": "pad_zero"}
    a = _run([_clip(n=1000)], params)
    b = _run([_clip(n=1000)], params)
    assert [r["record_id"] for r in a] == [r["record_id"] for r in b]
    for ra, rb in zip(a, b, strict=True):
        assert np.array_equal(ra["sample_array"], rb["sample_array"])


def test_multiple_clips_window_independently() -> None:
    out = _run(
        [_clip(record_id="a", n=600), _clip(record_id="b", n=300)],
        {"window_length_samples": 300, "hop_samples": 300, "remainder": "drop"},
    )
    by_parent: dict[str, int] = {}
    for r in out:
        by_parent[r["source_record_id"]] = by_parent.get(r["source_record_id"], 0) + 1
    assert by_parent == {"a": 2, "b": 1}


def test_clip_shorter_than_window_drops_or_pads() -> None:
    short = [_clip(n=100)]
    dropped = _run(short, {"window_length_samples": 400, "hop_samples": 400, "remainder": "drop"})
    assert dropped == []
    padded = _run(
        short, {"window_length_samples": 400, "hop_samples": 400, "remainder": "pad_zero"}
    )
    assert len(padded) == 1
    assert len(padded[0]["sample_array"]) == 400


def test_missing_sample_array_is_a_materialize_error() -> None:
    bad: list[Mapping[str, Any]] = [{"record_id": "x", "sample_rate": 16000}]
    with pytest.raises(MaterializeError, match="sample_array"):
        _run(bad, {"window_length_samples": 100, "hop_samples": 100, "remainder": "drop"})


def test_params_require_exactly_one_window_length() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        WindowParams.model_validate({"hop_samples": 100, "remainder": "drop"})
    with pytest.raises(ValidationError, match="exactly one"):
        WindowParams.model_validate(
            {
                "window_length_samples": 100,
                "window_length_seconds": 0.5,
                "hop_samples": 100,
                "remainder": "drop",
            }
        )


def test_params_reject_nonpositive_hop_and_length() -> None:
    with pytest.raises(ValidationError):
        WindowParams.model_validate(
            {"window_length_samples": 0, "hop_samples": 100, "remainder": "drop"}
        )
    with pytest.raises(ValidationError):
        WindowParams.model_validate(
            {"window_length_samples": 100, "hop_samples": 0, "remainder": "drop"}
        )
