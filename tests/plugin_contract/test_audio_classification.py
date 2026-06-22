# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Plugin-contract tests for the `audio_classification` scaffold (Story J.o).

`audio_classification` is the **second real plugin** (joining
`image_classification`) — `is_stub() → False` — but ships in J.o with an *empty*
operation set: the discovery / validator / contract-test machinery gets a
registered seam, and Stories J.p-J.t fill in the operations (decode, windowing,
`log_mel_spectrogram`, `audio_normalize`). Until then `operation_factory`
raises `PluginError` for any op kind.
"""

from __future__ import annotations

import pytest

from datarefinery.core.errors import PluginError
from datarefinery.plugins.audio_classification import PLUGIN
from datarefinery.plugins.base import Plugin
from datarefinery.plugins.discovery import discover_plugins


def test_plugin_satisfies_runtime_protocol() -> None:
    assert isinstance(PLUGIN, Plugin)


def test_plugin_metadata() -> None:
    assert PLUGIN.name == "audio_classification"
    assert PLUGIN.schema_version == 1
    # A *real* plugin (not a stub), unlike tabular/text — the seam is live even
    # though no operations are implemented yet.
    assert PLUGIN.is_stub() is False


def test_operations_grow_as_ops_land() -> None:
    # J.q adds the `window` Generation op; later stories add log_mel_spectrogram
    # (J.s) and audio_normalize (J.t).
    assert "window" in PLUGIN.supported_operations
    assert PLUGIN.supported_operations["window"].applicable_sections == frozenset({"Generation"})


def test_supported_sections_cover_required_recipe_set() -> None:
    required = {"Input", "Output", "Labels", "Splits"}
    assert required.issubset(PLUGIN.supported_sections)


def test_supported_sections_include_the_frozen_audio_stages() -> None:
    # Per the audio design memo § 4 (J.o): Generation (windowing),
    # Featurizations (log_mel_spectrogram), Transformations (audio_normalize).
    assert {"Generation", "Featurizations", "Transformations"}.issubset(PLUGIN.supported_sections)


def test_operation_factory_raises_until_ops_land() -> None:
    with pytest.raises(PluginError, match="audio_classification"):
        PLUGIN.operation_factory("Featurizations", "log_mel_spectrogram")


def test_recommended_params_and_extension_keys_are_empty() -> None:
    assert PLUGIN.recommended_params("Featurizations", "log_mel_spectrogram") == {}
    assert PLUGIN.extension_keys() == {}


def test_loader_stamped_fields_is_an_empty_set_in_the_scaffold() -> None:
    # The J.o stub returns no stamped fields; J.p-J.t populate it as
    # field-stamping ops (window/featurize) land.
    assert PLUGIN.loader_stamped_fields(recipe=None) == set()


def test_discover_plugins_returns_audio_classification() -> None:
    plugins = discover_plugins()
    assert "audio_classification" in plugins
    assert plugins["audio_classification"].is_stub() is False
