# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Audio-classification plugin: Featurization ops.

Two ops, both at the **Featurizations** stage, run in recipe-declared order:

- ``log_mel_spectrogram`` (Story J.s, R4) — converts each fixed-length window's
  ``sample_array`` into a **log-mel spectrogram** of shape ``(n_mels, n_frames)``
  (librosa-native orientation, mel bins on axis 0). No fit; one output per input
  window (no record-count change). librosa is lazily imported inside ``apply``
  (gated behind the ``[audio]`` extra). The recommended `output_field` is
  ``mel`` (the *raw* spectrogram); see the normalization note below.

- ``audio_normalize`` (Story J.t, R5) — **fit-on-train per-mel-bin**
  standardization of a derived spectral feature: a length-``n_mels`` mean/std
  vector fit over examples and frames keeping the mel axis, persisted to
  ``fitted_statistics/<op_id>/`` and applied across all declared splits.

**Why normalization is a Featurization, not a Transformation.** Fit-on-train
standardization of a *derived* feature is a cross-modality staple (audio
per-mel-bin now; tabular column scaling and text embedding normalization later).
DataRefinery's stage order runs ``Transformations`` *before* ``Featurizations``,
so a Transformation cannot see a feature a Featurization produces. The
Featurizations stage is the only stage that both runs *after* feature derivation
and supports fit-on-train + statistics persistence + ``stats_from_instance`` — so
feature scaling lives here, expressed as a fit-on-train Featurization that reads
a prior featurization's output. The convention is ``log_mel_spectrogram`` writes
``mel`` and ``audio_normalize`` reads ``mel`` → writes the final ``feature``
(distinct fields, so the stage's no-overwrite collision guard is satisfied and
the raw and scaled features both stay auditable). This is the deliberate split
from the image ``normalize`` op (which normalizes *raw* pixels at the
Transformations stage); see ``tech-spec.md`` § Fit-on-train feature scaling.

Both ops are deterministic (no RNG) → byte-identical across runs and worker
counts.

v1 ships log-mel only; MFCC and other spectral representations are Future (J.n).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from datarefinery.core.errors import MaterializeError, PluginError
from datarefinery.pipeline.stages.transformations import FittedValues
from datarefinery.plugins.normalize_stats import (
    fit_mean_std,
    unwrap_mean_std,
    wrap_mean_std,
    zscore,
)

Record = Mapping[str, Any]

#: Per-record axis the audio_normalize statistics are computed per: mel bins are
#: axis 0 of the ``(n_mels, n_frames)`` feature.
_MEL_AXIS = 0


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


def _audio_reduce_axes(ndim: int) -> tuple[int, ...]:
    """Reduce over every stacked axis except the mel axis.

    Per-record features are ``(n_mels, n_frames)``; stacking prepends the example
    axis → ``(N, n_mels, n_frames)``, so the mel axis is index 1 in the stack and
    every other axis (examples + frames) is reduced — yielding a length-``n_mels``
    per-mel-bin statistic.
    """
    mel_in_stack = _MEL_AXIS + 1
    return tuple(i for i in range(ndim) if i != mel_in_stack)


class AudioNormalizeOp:
    """Fit-on-train per-mel-bin standardization (see module docstring).

    A Featurization op (so it runs *after* ``log_mel_spectrogram`` in the same
    stage): it reads the spectral feature named by ``inputs[0]`` (convention:
    ``mel``), fits a length-``n_mels`` mean/std on the train split (or honors a
    recipe-pinned ``mean``/``std``), and writes the z-scored feature to
    ``output_field`` (convention: ``feature``). Shares the fit / parquet-wrap /
    ``std == 0 → 1.0`` zero-variance-guard machinery with the image
    ``NormalizeOp`` via :mod:`datarefinery.plugins.normalize_stats`; only the
    statistics axis differs (mel axis 0, not the last axis).
    """

    fit_on_train: bool = True

    def _input_field(self, inputs: list[str]) -> str:
        if not inputs:
            raise PluginError(
                "audio_normalize requires one input field naming the spectral "
                "feature to normalize (e.g. 'mel')"
            )
        return inputs[0]

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> FittedValues:
        del output_field, label_field
        # Recipe-pinned mean/std are honored as the fit output (mode-selecting:
        # absence ⇒ fit per-mel-bin from train), mirroring the image normalize op.
        mean_param = params.get("mean")
        std_param = params.get("std")
        if mean_param is not None and std_param is not None:
            mean = np.asarray(mean_param, dtype=np.float64)
            std = np.asarray(std_param, dtype=np.float64)
        else:
            mean, std = fit_mean_std(
                records, field=self._input_field(inputs), reduce_axes_for=_audio_reduce_axes
            )
        return wrap_mean_std(mean, std)

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
        del params, label_field
        field = self._input_field(inputs)
        mean, std = unwrap_mean_std(fitted)
        out: list[Record] = []
        for r in records:
            new = dict(r)
            new[output_field] = zscore(r[field], mean, std, axis=_MEL_AXIS)
            out.append(new)
        return out
