# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Plugin contract tests for the tabular plugin stub (Story C.c).

The tabular plugin ships in v1 as a stub: schemas declared so recipes
validate clean, but `operation_factory(...)` raises
`PluginError("stub plugin; not implemented")` at materialize time.
"""

from __future__ import annotations

import pytest

from datarefinery.core.errors import PluginError
from datarefinery.plugins.base import OperationSpec, Plugin
from datarefinery.plugins.discovery import discover_plugins
from datarefinery.plugins.tabular import PLUGIN

EXPECTED_OPERATIONS = frozenset(
    {
        "filter_by_value",
        "drop_nulls",
        "random_sample",
        "duplicate_minority_class",
        "standardize",
        "min_max_scale",
        "one_hot_encode",
        "cast_dtype",
        "polynomial_features",
        "class_distribution_histogram",
        "field_summary_table",
    }
)


def test_plugin_satisfies_runtime_protocol() -> None:
    assert isinstance(PLUGIN, Plugin)


def test_plugin_metadata() -> None:
    assert PLUGIN.name == "tabular"
    assert PLUGIN.schema_version == 1
    assert PLUGIN.is_stub() is True


def test_supported_sections_cover_required_recipe_set() -> None:
    required = {"Input", "Output", "Labels", "Splits"}
    assert required.issubset(PLUGIN.supported_sections)


def test_every_expected_operation_is_declared() -> None:
    declared = set(PLUGIN.supported_operations.keys())
    assert EXPECTED_OPERATIONS == declared, (
        f"missing: {EXPECTED_OPERATIONS - declared}; "
        f"unexpected: {declared - EXPECTED_OPERATIONS}"
    )


@pytest.mark.parametrize("op_name", sorted(EXPECTED_OPERATIONS))
def test_every_operation_has_a_valid_operation_spec(op_name: str) -> None:
    spec = PLUGIN.supported_operations[op_name]
    assert isinstance(spec, OperationSpec)
    assert isinstance(spec.applicable_sections, frozenset)
    assert spec.applicable_sections
    assert spec.applicable_sections.issubset(PLUGIN.supported_sections)


def test_fit_on_train_ops_are_in_transformations_or_featurizations() -> None:
    fit_on_train_ops = {
        name
        for name, spec in PLUGIN.supported_operations.items()
        if spec.fit_on_train
    }
    assert fit_on_train_ops, "expected at least one fit-on-train op"
    for name in fit_on_train_ops:
        spec = PLUGIN.supported_operations[name]
        assert spec.applicable_sections & {
            "Transformations",
            "Featurizations",
        }, name


def test_operation_factory_raises_plugin_error() -> None:
    with pytest.raises(PluginError, match="stub plugin; not implemented"):
        PLUGIN.operation_factory("Transformations", "standardize")


def test_discover_plugins_returns_tabular() -> None:
    plugins = discover_plugins()
    assert "tabular" in plugins
    assert plugins["tabular"].is_stub() is True
