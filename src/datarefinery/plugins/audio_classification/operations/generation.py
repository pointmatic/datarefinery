# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Audio-classification plugin: ``window`` Generation op (Story J.q, R3).

Turns one variable-length decoded clip into N fixed-length window records. A
window begins at every ``hop_samples`` offset within the clip; a full window is
emitted as-is, and any window that would extend past the clip end (the trailing
remainder) is either zero-padded (``remainder="pad_zero"``) or skipped
(``remainder="drop"``). Each child record carries ``source_record_id`` (the
parent clip id) and ``window_index`` so downstream aggregation (R7) can group
windows back to their clip; ``record_id`` is ``f"{parent}__w{index:04d}"``
(mirroring FR-11 aggressive variants' ``__v{i:03d}``, 4-digit width for typical
clip→window counts up to ~10k).

The op is **fully deterministic** (non-stochastic): the output is a pure
function of the input clip and the params — no RNG — so it is byte-identical
regardless of worker count (the determinism contract holds by construction). It
runs at the **Generation** stage with ``replace_input_records: true`` so each
parent clip is replaced by its windows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from datarefinery.core.errors import MaterializeError

Record = Mapping[str, Any]


class WindowParams(BaseModel):
    """Params for the ``window`` op.

    Exactly one of ``window_length_samples`` / ``window_length_seconds`` must be
    given (the seconds form is resolved against the record's ``sample_rate``).
    ``hop_samples`` and ``remainder`` are required — no implicit defaults (the
    interpreting code substitutes nothing; the scaffolder emits recommended
    values via ``Plugin.recommended_params``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_length_samples: int | None = Field(default=None, gt=0)
    window_length_seconds: float | None = Field(default=None, gt=0)
    hop_samples: int = Field(gt=0)
    remainder: Literal["pad_zero", "drop"]

    @model_validator(mode="after")
    def _exactly_one_window_length(self) -> WindowParams:
        provided = [self.window_length_samples is not None, self.window_length_seconds is not None]
        if sum(provided) != 1:
            raise ValueError(
                "window: provide exactly one of 'window_length_samples' / 'window_length_seconds'"
            )
        return self


def _window_length_samples(parsed: WindowParams, sample_rate: int) -> int:
    if parsed.window_length_samples is not None:
        return parsed.window_length_samples
    assert parsed.window_length_seconds is not None  # guaranteed by the validator
    if sample_rate <= 0:
        raise MaterializeError(
            "window: 'window_length_seconds' requires a positive 'sample_rate' on "
            "the record (was the clip decoded?)"
        )
    return round(parsed.window_length_seconds * sample_rate)


def window(
    records: list[Record],
    *,
    seed: int,
    inputs: list[str],
    output_schema: Mapping[str, Any],
    params: Mapping[str, Any],
    label_field: str | None,
    op_name: str,
) -> list[Record]:
    """Fan each clip out into fixed-length window records (see module docstring).

    Returns the NEW window records; with ``replace_input_records: true`` the
    Generation stage replaces each split's clips with these windows.
    """
    del seed, inputs, output_schema, label_field, op_name  # windowing is deterministic
    parsed = WindowParams.model_validate(dict(params))
    out: list[Record] = []
    for record in records:
        if "record_id" not in record:
            raise MaterializeError("window: input record missing 'record_id' field")
        if "sample_array" not in record:
            raise MaterializeError(
                f"window: input record {record['record_id']!r} missing 'sample_array' "
                f"(decode must run before windowing)"
            )
        samples = np.asarray(record["sample_array"], dtype=np.float32)
        wl = _window_length_samples(parsed, int(record.get("sample_rate", 0)))
        parent = record["record_id"]
        for window_index, start in enumerate(range(0, len(samples), parsed.hop_samples)):
            chunk = samples[start : start + wl]
            if len(chunk) < wl:
                # Trailing-remainder window (extends past the clip end).
                if parsed.remainder == "drop":
                    continue
                chunk = np.concatenate([chunk, np.zeros(wl - len(chunk), dtype=np.float32)])
            child = dict(record)
            child["record_id"] = f"{parent}__w{window_index:04d}"
            child["source_record_id"] = parent
            child["window_index"] = window_index
            child["sample_array"] = chunk
            out.append(child)
    return out
