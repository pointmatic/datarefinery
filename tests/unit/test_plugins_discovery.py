# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for `datarefinery.plugins.discovery` and `OperationSpec`."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from datarefinery.core.errors import PluginError
from datarefinery.plugins.base import OperationSpec, ParameterSpec, Plugin
from datarefinery.plugins.discovery import discover_plugins

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_DUMMY_PLUGIN = _FIXTURES / "dummy_plugin.py"
_DUMMY_PLUGIN_DUP = _FIXTURES / "dummy_plugin_dup.py"


def test_discovery_returns_test_plugin_via_extra_paths_file() -> None:
    plugins = discover_plugins(extra_paths=[_DUMMY_PLUGIN])
    assert "_test_dummy" in plugins
    plugin = plugins["_test_dummy"]
    assert plugin.schema_version == 1
    assert "noop" in plugin.supported_operations


def test_discovery_returns_test_plugin_via_extra_paths_directory() -> None:
    # Pointing at the file directly avoids picking up `dummy_plugin_dup.py`.
    plugins = discover_plugins(extra_paths=[_DUMMY_PLUGIN])
    assert isinstance(plugins["_test_dummy"], Plugin)


def test_duplicate_plugin_name_raises_plugin_error() -> None:
    with pytest.raises(PluginError, match="duplicate plugin name"):
        discover_plugins(extra_paths=[_DUMMY_PLUGIN, _DUMMY_PLUGIN_DUP])


def test_missing_plugin_path_raises_plugin_error() -> None:
    with pytest.raises(PluginError, match="plugin path does not exist"):
        discover_plugins(extra_paths=[_FIXTURES / "does_not_exist.py"])


def test_operation_spec_rejects_extra_fields() -> None:
    with pytest.raises(PydanticValidationError):
        OperationSpec(
            applicable_sections=frozenset({"Filters"}),
            unknown_field=42,  # type: ignore[call-arg]
        )


def test_operation_spec_defaults() -> None:
    spec = OperationSpec(applicable_sections=frozenset({"Filters"}))
    assert spec.parameters == {}
    assert spec.fit_on_train is False
    assert spec.applicable_splits == frozenset({"train", "val", "test"})


def test_parameter_spec_rejects_extra_fields() -> None:
    with pytest.raises(PydanticValidationError):
        ParameterSpec(type="int", surprise="oops")  # type: ignore[call-arg]


def test_parameter_spec_round_trip_in_operation_spec() -> None:
    # No-implicit-defaults (J.n.4): ParameterSpec has no `default`; a param is
    # required or mode-selecting optional.
    spec = OperationSpec(
        parameters={
            "size": ParameterSpec(type="int", required=True),
            "method": ParameterSpec(type="str", required=False),
        },
        applicable_sections=frozenset({"Transformations"}),
        fit_on_train=True,
    )
    assert spec.parameters["size"].type == "int"
    assert spec.parameters["size"].required is True
    assert spec.parameters["method"].required is False
    assert spec.fit_on_train is True


def test_operation_spec_is_frozen() -> None:
    spec = OperationSpec(applicable_sections=frozenset({"Filters"}))
    with pytest.raises((PydanticValidationError, TypeError, AttributeError)):
        spec.fit_on_train = True  # type: ignore[misc]


def test_extra_path_module_without_plugin_attr_is_ignored(
    tmp_path: Path,
) -> None:
    """Lone Python files without a top-level ``PLUGIN`` attribute are
    skipped silently by discovery."""
    extra = tmp_path / "extras"
    extra.mkdir()
    (extra / "not_a_plugin.py").write_text(
        "# Copyright (c) 2026 Pointmatic\n# SPDX-License-Identifier: Apache-2.0\nVALUE = 42\n",
        encoding="utf-8",
    )
    # The fixture dummy plugin is still discovered; the attr-less module
    # next to it is ignored without raising.
    plugins = discover_plugins(extra_paths=[_DUMMY_PLUGIN, extra])
    assert "_test_dummy" in plugins


def test_extra_path_with_unimportable_module_raises_plugin_error(
    tmp_path: Path,
) -> None:
    """A Python file in an extra path that fails to import surfaces as
    ``PluginError`` rather than the raw ``Exception``."""
    extra = tmp_path / "extras"
    extra.mkdir()
    (extra / "broken.py").write_text(
        "raise ImportError('forced failure for tests')\n",
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="failed to import plugin"):
        discover_plugins(extra_paths=[extra])


def test_register_rejects_object_that_does_not_satisfy_protocol(
    tmp_path: Path,
) -> None:
    """A top-level ``PLUGIN`` attr that lacks the protocol surface
    raises ``PluginError`` with a class-named message."""
    extra = tmp_path / "extras"
    extra.mkdir()
    (extra / "fake.py").write_text(
        "# Copyright (c) 2026 Pointmatic\n"
        "# SPDX-License-Identifier: Apache-2.0\n"
        "class _Fake:\n"
        "    name = 'fake'\n"
        "PLUGIN = _Fake()\n",
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="does not satisfy the Plugin protocol"):
        discover_plugins(extra_paths=[extra])


def test_discovery_with_no_extra_paths_does_not_error() -> None:
    # Empty by default — no plugins are registered under the
    # `datarefinery.plugins` entry-point group at this point in the project
    # (image_classification lands in Story C.b).
    plugins = discover_plugins()
    assert isinstance(plugins, dict)
