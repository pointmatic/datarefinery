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
from datarefinery.plugins.base import Operation, OperationSpec

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


class AudioClassificationPlugin:
    """Real plugin, empty operation set (J.o scaffold)."""

    name = "audio_classification"
    schema_version = 1
    supported_sections = SUPPORTED_SECTIONS

    def __init__(self) -> None:
        #: Populated by J.p-J.t (`window`, `log_mel_spectrogram`, `audio_normalize`).
        self.supported_operations: dict[str, OperationSpec] = {}

    def operation_factory(self, section: str, op_name: str) -> Operation:
        raise PluginError(
            f"audio_classification has no operation yet "
            f"(section={section!r}, op={op_name!r}); audio ops land in Stories J.p-J.t"
        )

    def is_stub(self) -> bool:
        # A real plugin (the seam is live), unlike the tabular/text stubs —
        # even though no operations are implemented yet.
        return False

    def recommended_params(self, section: str, op_name: str) -> dict[str, Any]:
        """No recommended values yet (Story J.n.4); populated as ops land."""
        return {}

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
