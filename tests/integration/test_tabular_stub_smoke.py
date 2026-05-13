# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Tabular stub smoke test (Story C.c).

A recipe declaring `plugin: tabular` validates clean against the stub's
declared schemas (FR-2 checks 1-18 all pass) but raises `PluginError` when
any operation is constructed via `operation_factory`. The pipeline runner
that wires this end-to-end lands in C.m; this smoke test exercises the
two ends of the contract directly.
"""

from __future__ import annotations

from typing import Any

import pytest

from datarefinery.core.errors import PluginError
from datarefinery.plugins.tabular import PLUGIN as TABULAR_PLUGIN
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import validate


def _tabular_recipe_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "tabular",
        "Input": {
            "sources": [
                {
                    "name": "train",
                    "type": "csv",
                    "path": "/data/customers.csv",
                }
            ]
        },
        "Output": {
            "record_schema": {
                "age": {"dtype": "float32"},
                "income": {"dtype": "float32"},
                "segment": {"dtype": "int32"},
            }
        },
        "Labels": {
            "field": "segment",
            "source": {"kind": "direct"},
        },
        "Splits": {
            "ratios": {"train": 0.7, "val": 0.15, "test": 0.15},
            "seed": 11,
        },
        "Filters": [
            {
                "name": "drop_missing",
                "predicate": {"op": "drop_nulls", "fields": ["age", "income"]},
                "stages": ["pre_split"],
            },
        ],
        "Transformations": [
            {
                "name": "scale",
                "op": "standardize",
                "params": {"fields": ["age", "income"]},
                "fit_source": "train",
                "splits": ["train", "val", "test"],
            },
        ],
    }


def test_tabular_recipe_validates_clean_against_stub_plugin() -> None:
    recipe = Recipe.model_validate(_tabular_recipe_dict())
    report = validate(recipe, TABULAR_PLUGIN)
    assert report.passed, [r for r in report.failures]
    assert len(report.results) == 20


def test_tabular_operation_factory_raises_plugin_error() -> None:
    with pytest.raises(PluginError, match="stub plugin; not implemented"):
        TABULAR_PLUGIN.operation_factory("Transformations", "standardize")


def test_tabular_plugin_is_stub_flag() -> None:
    assert TABULAR_PLUGIN.is_stub() is True
