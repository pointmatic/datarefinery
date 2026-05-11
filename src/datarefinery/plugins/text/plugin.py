# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Text-data plugin stub.

v1 ships section list + operation outlines only - the plugin abstraction is
exercised, recipes targeting `plugin: text` validate clean, but
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
    }
)


def _supported_operations() -> dict[str, OperationSpec]:
    return {
        # ----- Filters (FR-8) -----
        "filter_by_label": OperationSpec(
            parameters={
                "labels": ParameterSpec(type="list[str]", required=True),
                "action": ParameterSpec(type="str", required=False, default="include"),
            },
            applicable_sections=frozenset({"Filters"}),
        ),
        "filter_by_length": OperationSpec(
            parameters={
                "min_tokens": ParameterSpec(type="int", required=False),
                "max_tokens": ParameterSpec(type="int", required=False),
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
            parameters={
                "label_field": ParameterSpec(type="str", required=True),
                "target_count": ParameterSpec(type="int", required=True),
                "seed": ParameterSpec(type="int", required=True),
            },
            applicable_sections=frozenset({"Generation"}),
        ),
        # ----- Transformations (FR-10) -----
        "lowercase": OperationSpec(
            parameters={
                "field": ParameterSpec(type="str", required=True),
            },
            applicable_sections=frozenset({"Transformations"}),
        ),
        "strip_punctuation": OperationSpec(
            parameters={
                "field": ParameterSpec(type="str", required=True),
            },
            applicable_sections=frozenset({"Transformations"}),
        ),
        "tokenize": OperationSpec(
            parameters={
                "field": ParameterSpec(type="str", required=True),
                "scheme": ParameterSpec(type="str", required=False, default="whitespace"),
            },
            applicable_sections=frozenset({"Transformations"}),
        ),
        "remove_stopwords": OperationSpec(
            parameters={
                "field": ParameterSpec(type="str", required=True),
                "language": ParameterSpec(type="str", required=False, default="en"),
            },
            applicable_sections=frozenset({"Transformations"}),
        ),
        # ----- Featurizations (FR-12, FR-22) -----
        "tfidf": OperationSpec(
            parameters={
                "field": ParameterSpec(type="str", required=True),
                "max_features": ParameterSpec(type="int", required=False),
            },
            fit_on_train=True,
            applicable_sections=frozenset({"Featurizations"}),
        ),
        "token_count": OperationSpec(
            parameters={
                "field": ParameterSpec(type="str", required=True),
            },
            applicable_sections=frozenset({"Featurizations"}),
        ),
        # ----- Visualizations (FR-13) -----
        "class_distribution_histogram": OperationSpec(
            applicable_sections=frozenset({"Visualizations"}),
        ),
        "token_length_histogram": OperationSpec(
            applicable_sections=frozenset({"Visualizations"}),
        ),
    }


class TextPlugin:
    """Stub plugin: schemas declared, operations not implemented in v1."""

    name = "text"
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


PLUGIN: Any = TextPlugin()
