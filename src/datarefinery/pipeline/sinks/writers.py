# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Sink format writers (Story I.d; `npy_per_record`: Story K.c).

:func:`write_png_per_record` expects a uint8 HxWxC (or HxW) numpy array
on the named record field and writes a single PNG via
``PIL.Image.fromarray``. :func:`write_npy_per_record` (Story K.c)
persists a float feature array (e.g. audio ``mel``) as a ``float32``
``.npy`` sidecar — the egress path for in-pipeline array features the
JSONL writer drops. The remaining formats (`parquet`, `tar`) are listed
in the spec § 3.4 and deferred to Future.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from datarefinery.core.errors import MaterializeError


def write_png_per_record(
    *,
    record: dict[str, Any],
    field: str,
    output_path: Path,
    sink_name: str,
    stage: str,
) -> int:
    """Write one PNG per record. Returns the number of bytes written.

    Required field shape: uint8 HxWxC (or HxW for grayscale). Anything
    else is a :class:`MaterializeError` with an actionable message
    naming the sink and the offending dtype/shape.
    """
    if field not in record:
        raise MaterializeError(
            f"sink {sink_name!r} at stage {stage!r}: record is missing required field {field!r}"
        )
    value = record[field]
    if not isinstance(value, np.ndarray):
        raise MaterializeError(
            f"sink {sink_name!r} at stage {stage!r}: format='png_per_record' "
            f"requires field {field!r} to be a numpy ndarray, got {type(value).__name__}"
        )
    if value.dtype != np.uint8:
        raise MaterializeError(
            f"sink {sink_name!r} at stage {stage!r}: format='png_per_record' "
            f"expects uint8 on field {field!r}; got {value.dtype} — move the "
            f"sink earlier than normalize or pick a different field."
        )
    if value.ndim not in (2, 3):
        raise MaterializeError(
            f"sink {sink_name!r} at stage {stage!r}: format='png_per_record' "
            f"expects field {field!r} to be HxW or HxWxC; got shape {value.shape!r}"
        )

    # Local import keeps the recipe-model + validator layers free of
    # PIL (which is a Pillow dependency, present in v1 but conceptually
    # a writer-side concern).
    from PIL import Image as _PIL_Image

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _PIL_Image.fromarray(value).save(output_path, format="PNG", optimize=False)
    return output_path.stat().st_size


def write_npy_per_record(
    *,
    record: dict[str, Any],
    field: str,
    output_path: Path,
    sink_name: str,
    stage: str,
) -> int:
    """Write one ``float32`` ``.npy`` per record. Returns bytes written.

    The named field must be a numpy ndarray (e.g. the audio ``mel``
    log-mel spectrogram, librosa-native ``(n_mels, n_frames)``). It is
    persisted as ``float32`` on disk (Story K.c contract Q3): a non-float32
    array is cast deterministically. The blessed audio consumption contract
    persists the *pre-normalize* ``mel`` so the consumer applies the
    ``audio_normalize`` stats at load — the field-targeting guardrail
    (validator check, Story K.d) enforces ``field == 'mel'`` when the sink
    rewrites ``feature_path``.

    Writing goes through a file handle (not ``np.save(path, ...)``) so the
    output lands at ``output_path`` verbatim — ``np.save`` would otherwise
    append a ``.npy`` suffix and orphan the rewritten ``feature_path``.
    """
    if field not in record:
        raise MaterializeError(
            f"sink {sink_name!r} at stage {stage!r}: record is missing required field {field!r}"
        )
    value = record[field]
    if not isinstance(value, np.ndarray):
        raise MaterializeError(
            f"sink {sink_name!r} at stage {stage!r}: format='npy_per_record' "
            f"requires field {field!r} to be a numpy ndarray, got {type(value).__name__}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.ascontiguousarray(value, dtype=np.float32)
    with output_path.open("wb") as fh:
        np.save(fh, arr, allow_pickle=False)
    return output_path.stat().st_size
