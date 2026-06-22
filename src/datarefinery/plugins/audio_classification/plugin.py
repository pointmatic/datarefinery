# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Audio-classification plugin scaffold (Story J.o).

The **second real plugin** (joining `image_classification`) — `is_stub()` is
`False` — but it ships in J.o with an *empty* operation set. Its purpose is to
give the existing discovery / validator / contract-test machinery a registered
seam to build against; Stories J.p-J.t fill in the operations frozen in the
[audio design memo](../../../../docs/specs/phase-j-subphase-1-audio-design-memo.md):
decode + audio input sources (J.p), `window` Generation (J.q),
`log_mel_spectrogram` Featurization (J.s), and `audio_normalize` Transformation
(J.t). Until an op lands, `operation_factory(...)` raises `PluginError`.

`supported_sections` is the full standard recipe section set (per the design
memo § 4: at minimum Input / Filters / Splits / Generation / Transformations /
Featurizations / OutputExpectations / Visualizations; inheriting the rest costs
nothing and keeps the validator's section check uniform with
`image_classification`).
"""

from __future__ import annotations

from typing import Any

from datarefinery.core.errors import PluginError
from datarefinery.plugins.audio_classification.operations.featurizations import (
    AudioNormalizeOp,
    LogMelSpectrogramOp,
)
from datarefinery.plugins.audio_classification.operations.generation import window
from datarefinery.plugins.base import Operation, OperationSpec, ParameterSpec

#: Generation-stage op handles dispatched by :meth:`operation_factory`.
_GENERATION_OPS: dict[str, Operation] = {
    "window": window,
}

#: Featurization-stage op handles (objects with fit/apply) dispatched by
#: :meth:`operation_factory`. ``audio_normalize`` is a *fit-on-train*
#: Featurization (not a Transformation): fit-on-train scaling of a derived
#: feature must run after the feature exists, and Featurizations is the only
#: stage that runs after derivation and supports fit-on-train + stats
#: persistence (Story J.t; see the module docstring + tech-spec.md).
_FEATURIZATION_OPS: dict[str, Any] = {
    "log_mel_spectrogram": LogMelSpectrogramOp(),
    "audio_normalize": AudioNormalizeOp(),
}

#: The full standard recipe section set. Mirrors `image_classification` —
#: `Output`/`Labels`/`Splits` are mandatory recipe sections, so they MUST be
#: present or validator check 3 would reject every audio recipe.
SUPPORTED_SECTIONS = frozenset(
    {
        "Input",
        "Output",
        "Labels",
        "SampleData",
        "InputContracts",
        "Filters",
        "Generation",
        "Splits",
        "Transformations",
        "Augmentations",
        "Featurizations",
        "OutputExpectations",
        "Visualizations",
        "Sinks",
    }
)


def _supported_operations() -> dict[str, OperationSpec]:
    return {
        # ----- Generation (R3, Story J.q) -----
        "window": OperationSpec(
            parameters={
                # Exactly one of the two length forms (mode-selecting optionals);
                # hop_samples + remainder are required (no-implicit-defaults).
                "window_length_samples": ParameterSpec(type="int", required=False),
                "window_length_seconds": ParameterSpec(type="float", required=False),
                "hop_samples": ParameterSpec(type="int", required=True),
                "remainder": ParameterSpec(type="str", required=True),
            },
            fit_on_train=False,
            applicable_sections=frozenset({"Generation"}),
        ),
        # ----- Featurization (R4, Story J.s) -----
        "log_mel_spectrogram": OperationSpec(
            parameters={
                # All required (no-implicit-defaults) except f_max, which is
                # mode-selecting: absent ⇒ Nyquist (sample_rate / 2).
                "n_fft": ParameterSpec(type="int", required=True),
                "hop_length": ParameterSpec(type="int", required=True),
                "n_mels": ParameterSpec(type="int", required=True),
                "f_min": ParameterSpec(type="float", required=True),
                "f_max": ParameterSpec(type="float", required=False),
                "power": ParameterSpec(type="float", required=True),
            },
            fit_on_train=False,
            applicable_sections=frozenset({"Featurizations"}),
        ),
        # ----- Feature normalization (R5, Story J.t) — fit-on-train -----
        "audio_normalize": OperationSpec(
            parameters={
                # Both mode-selecting: absent ⇒ fit per-mel-bin from train.
                "mean": ParameterSpec(type="float", required=False),
                "std": ParameterSpec(type="float", required=False),
            },
            fit_on_train=True,
            applicable_sections=frozenset({"Featurizations"}),
        ),
    }


#: Recommended starting values the scaffolder emits into recipe text (J.n.4).
#: Mode-selecting optionals are omitted (e.g. `window_length_samples`,
#: `log_mel_spectrogram.f_max`) so the scaffolder doesn't pin a mode the author
#: should choose — absence is itself meaningful (f_max absent ⇒ Nyquist).
_RECOMMENDED_PARAMS: dict[str, dict[str, Any]] = {
    "window": {"window_length_seconds": 1.0, "hop_samples": 8000, "remainder": "drop"},
    "log_mel_spectrogram": {
        "n_fft": 2048,
        "hop_length": 512,
        "n_mels": 128,
        "f_min": 0.0,
        "power": 2.0,
    },
}


class AudioClassificationPlugin:
    """Real plugin (`is_stub() → False`); operations land across J.q-J.t."""

    name = "audio_classification"
    schema_version = 1
    supported_sections = SUPPORTED_SECTIONS

    def __init__(self) -> None:
        self.supported_operations: dict[str, OperationSpec] = _supported_operations()

    def operation_factory(self, section: str, op_name: str) -> Operation:
        if section == "Generation" and op_name in _GENERATION_OPS:
            return _GENERATION_OPS[op_name]
        if section == "Featurizations" and op_name in _FEATURIZATION_OPS:
            return _FEATURIZATION_OPS[op_name]
        raise PluginError(
            f"audio_classification has no operation for (section={section!r}, op={op_name!r})"
        )

    def is_stub(self) -> bool:
        # A real plugin (the seam is live), unlike the tabular/text stubs.
        return False

    def recommended_params(self, section: str, op_name: str) -> dict[str, Any]:
        """Recommended starting values the scaffolder emits (Story J.n.4)."""
        return dict(_RECOMMENDED_PARAMS.get(op_name, {}))

    def extension_keys(self) -> dict[str, set[str]]:
        """No extensions consumed (Story J.n.6)."""
        return {}

    def loader_stamped_fields(self, recipe: Any) -> set[str]:
        """Fields this plugin's loader stamps onto records (validator check 23).

        Story J.o ships the **stub**: the scaffold stamps no fields, so it
        returns an empty set. Stories J.p-J.t populate it as field-stamping ops
        (windowing → `source_record_id` / `window_index`, featurization →
        `feature`) land. (Per the Future "plugin-pluggable validator reserved-set
        hook" entry — only the audio scaffold's stub is in J.o scope; wiring the
        hook into validator check 23 across all plugins is a separate effort.)
        """
        del recipe
        return set()


PLUGIN: Any = AudioClassificationPlugin()
