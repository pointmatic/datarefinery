# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Audio-classification plugin: `log_mel_spectrogram` Featurization op (Story J.s, R4).

Converts each fixed-length window record's `sample_array` into a **log-mel
spectrogram** `feature` of shape `(n_mels, n_frames)` (librosa-native
orientation, mel bins on axis 0; frozen by the audio design memo Finding B).
One feature output per input window — no record-count change at the
Featurization stage. All existing fields are preserved; the op only *adds* the
feature under the recipe's declared `output_field`.

The op is **fully deterministic** (no RNG): the output is a pure function of the
window samples and the params, so it is byte-identical across runs and worker
counts (the determinism contract holds by construction).

librosa is imported **lazily** inside `apply` (mirroring the decode path in
`inputs.py` and the writer-side `from PIL import Image` pattern) so this module
stays importable for plugin discovery / contract tests without the `[audio]`
extra; invoking the op without librosa raises an actionable `PluginError`.

v1 ships log-mel only; MFCC and other spectral representations are Future (J.n).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from datarefinery.core.errors import MaterializeError, PluginError
from datarefinery.pipeline.stages.transformations import FittedValues

Record = Mapping[str, Any]


class LogMelParams(BaseModel):
    """Params for the `log_mel_spectrogram` op.

    All values are required (no-implicit-defaults rule, J.n.4) except `f_max`,
    which is **mode-selecting**: `None` means "use the Nyquist frequency
    (`sample_rate / 2`)", so its absence is itself meaningful (mirroring
    `normalize.mean: None ⇒ fit-from-train`). The scaffolder emits recommended
    values for the required params via `Plugin.recommended_params`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_fft: int = Field(gt=0)
    hop_length: int = Field(gt=0)
    n_mels: int = Field(gt=0)
    f_min: float = Field(ge=0)
    f_max: float | None = Field(default=None, gt=0)
    power: float = Field(gt=0)


class LogMelSpectrogramOp:
    """Featurization op handle (see module docstring). Stateless, no fit."""

    fit_on_train: bool = False

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> FittedValues:
        del records, params, inputs, output_field, label_field
        return FittedValues()

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> list[Record]:
        del fitted, label_field
        parsed = LogMelParams.model_validate(dict(params))
        if not inputs:
            raise PluginError(
                "log_mel_spectrogram requires one input field naming the sample "
                "array (e.g. 'sample_array')"
            )
        sample_field = inputs[0]
        librosa = _import_librosa()
        out: list[Record] = []
        for record in records:
            samples = record.get(sample_field)
            if samples is None:
                raise MaterializeError(
                    f"log_mel_spectrogram: record {record.get('record_id')!r} missing "
                    f"input field {sample_field!r} (the decoded/windowed sample array)"
                )
            sample_rate = int(record.get("sample_rate", 0))
            if sample_rate <= 0:
                raise MaterializeError(
                    f"log_mel_spectrogram: record {record.get('record_id')!r} has a "
                    f"non-positive 'sample_rate' (was the clip decoded?)"
                )
            y = np.asarray(samples, dtype=np.float32)
            mel = librosa.feature.melspectrogram(
                y=y,
                sr=sample_rate,
                n_fft=parsed.n_fft,
                hop_length=parsed.hop_length,
                n_mels=parsed.n_mels,
                fmin=parsed.f_min,
                fmax=parsed.f_max,
                power=parsed.power,
            )
            log_mel = librosa.power_to_db(mel).astype(np.float32)
            new = dict(record)
            new[output_field] = log_mel
            out.append(new)
        return out


def _import_librosa() -> Any:
    try:
        import librosa
    except ImportError as exc:  # pragma: no cover - exercised only without [audio]
        raise PluginError(
            "audio_classification log_mel_spectrogram requires the 'audio' extra; "
            "install it with: pip install 'ml-datarefinery[audio]'"
        ) from exc
    return librosa
