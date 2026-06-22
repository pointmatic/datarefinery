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
from datarefinery.plugins.audio_classification.operations.generation import window
from datarefinery.plugins.base import Operation, OperationSpec, ParameterSpec

#: Generation-stage op handles dispatched by :meth:`operation_factory`.
_GENERATION_OPS: dict[str, Operation] = {
    "window": window,
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
    }


#: Recommended starting values the scaffolder emits into recipe text (J.n.4).
_RECOMMENDED_PARAMS: dict[str, dict[str, Any]] = {
    "window": {"window_length_seconds": 1.0, "hop_samples": 8000, "remainder": "drop"},
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
        raise PluginError(
            f"audio_classification has no operation for "
            f"(section={section!r}, op={op_name!r}); remaining audio ops land in "
            f"Stories J.s-J.t"
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
