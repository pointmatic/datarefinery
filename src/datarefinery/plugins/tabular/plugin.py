# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Tabular-data plugin stub.

v1 ships section list + operation outlines only - the plugin abstraction is
exercised, recipes targeting `plugin: tabular` validate clean, but
`operation_factory(...)` raises `PluginError("stub plugin; not implemented")`
at materialize time. Full operation implementations are post-v1.

The stub exists so the plugin abstraction does not bake in image
assumptions: the validator and discovery surfaces handle non-image plugins
from day one. `is_stub()` returns True so the runner (Story C.m) can
distinguish stub from real plugins for clearer error reporting.
"""

from __future__ import annotations

from typing import Any

from datarefinery.core.errors import PluginError
from datarefinery.plugins.base import Operation, OperationSpec, ParameterSpec

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
        "Featurizations",
        "OutputExpectations",
        "Visualizations",
        "Sinks",
    }
)


def _supported_operations() -> dict[str, OperationSpec]:
    return {
        # ----- Filters (FR-8) -----
        "filter_by_value": OperationSpec(
            parameters={
                "field": ParameterSpec(type="str", required=True),
                "op": ParameterSpec(type="str", required=True),
                "value": ParameterSpec(type="str", required=True),
            },
            applicable_sections=frozenset({"Filters"}),
        ),
        "drop_nulls": OperationSpec(
            parameters={
                "fields": ParameterSpec(type="list[str]", required=True),
            },
            applicable_sections=frozenset({"Filters"}),
        ),
        "random_sample": OperationSpec(
            parameters={
                "fraction": ParameterSpec(type="float", required=False),
                "n": ParameterSpec(type="int", required=False),
                "seed": ParameterSpec(type="int", required=True),
            },
            applicable_sections=frozenset({"Filters"}),
        ),
        # ----- Generation (FR-9) -----
        "duplicate_minority_class": OperationSpec(
            applicable_sections=frozenset({"Generation"}),
        ),
        # ----- Transformations (FR-10) -----
        "standardize": OperationSpec(
            parameters={
                "fields": ParameterSpec(type="list[str]", required=True),
            },
            fit_on_train=True,
            applicable_sections=frozenset({"Transformations"}),
        ),
        "min_max_scale": OperationSpec(
            parameters={
                "fields": ParameterSpec(type="list[str]", required=True),
                "feature_range": ParameterSpec(type="list[float]", required=False),
            },
            fit_on_train=True,
            applicable_sections=frozenset({"Transformations"}),
        ),
        "one_hot_encode": OperationSpec(
            parameters={
                "field": ParameterSpec(type="str", required=True),
            },
            fit_on_train=True,
            applicable_sections=frozenset({"Transformations"}),
        ),
        "cast_dtype": OperationSpec(
            parameters={
                "field": ParameterSpec(type="str", required=True),
                "dtype": ParameterSpec(type="str", required=True),
            },
            applicable_sections=frozenset({"Transformations"}),
        ),
        # ----- Featurizations (FR-12, FR-22) -----
        "polynomial_features": OperationSpec(
            parameters={
                "degree": ParameterSpec(type="int", required=True),
            },
            applicable_sections=frozenset({"Featurizations"}),
        ),
        # ----- Visualizations (FR-13) -----
        "class_distribution_histogram": OperationSpec(
            applicable_sections=frozenset({"Visualizations"}),
        ),
        "field_summary_table": OperationSpec(
            applicable_sections=frozenset({"Visualizations"}),
        ),
    }


class TabularPlugin:
    """Stub plugin: schemas declared, operations not implemented in v1."""

    name = "tabular"
    schema_version = 1
    supported_sections = SUPPORTED_SECTIONS

    def __init__(self) -> None:
        self.supported_operations = _supported_operations()

    def operation_factory(self, section: str, op_name: str) -> Operation:
        raise PluginError(
            f"stub plugin; not implemented "
            f"(plugin={self.name!r}, section={section!r}, op={op_name!r})"
        )

    def is_stub(self) -> bool:
        return True

    def recommended_params(self, section: str, op_name: str) -> dict[str, Any]:
        """Recommended starting values (Story J.n.4); stub plugin, so these
        document intent until the ops are implemented."""
        return dict(_RECOMMENDED_PARAMS.get(op_name, {}))


_RECOMMENDED_PARAMS: dict[str, dict[str, Any]] = {
    "filter_by_value": {"op": "eq"},
    "polynomial_features": {"degree": 2},
}


PLUGIN: Any = TabularPlugin()
