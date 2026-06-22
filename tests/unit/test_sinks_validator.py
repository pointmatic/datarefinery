# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Validator check_24_sinks tests (Story I.d).

Sink-name uniqueness, path-template parseability, path-escape
rejection, field-known-to-recipe, and splits-known-to-recipe.
"""

from __future__ import annotations

from typing import Any

from datarefinery.plugins.base import OperationSpec
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import CheckResult, ValidationReport, validate


class _Plugin:
    def __init__(self) -> None:
        self.name = "test_plugin"
        self.schema_version = 1
        self.supported_sections = frozenset(
            {
                "Input",
                "Output",
                "Labels",
                "Splits",
                "Sinks",
            }
        )
        self.supported_operations: dict[str, OperationSpec] = {}

    def recommended_params(self, section: str, op_name: str) -> dict[str, object]:
        del section, op_name
        return {}

    def operation_factory(self, section: str, op_name: str) -> object:
        del section, op_name
        return lambda r: r

    def is_stub(self) -> bool:
        return False

    def extension_keys(self) -> dict[str, set[str]]:
        return {}


def _base_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "test_plugin",
        "Input": {"sources": [{"name": "t", "type": "image_folder", "path": "/d"}]},
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                "label": {"dtype": "int32"},
            }
        },
        "Labels": {
            "field": "label",
            "source": {"kind": "derived", "derivation": "parent_directory_name"},
        },
        "Splits": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}, "seed": 7},
    }


def _sink_dict(**overrides: Any) -> dict[str, Any]:
    base = {
        "name": "pngs",
        "stage": "post_Filters",
        "field": "image",
        "format": "png_per_record",
        "path_template": "exports/{label}/{record_id}.png",
    }
    base.update(overrides)
    return base


def _failures(report: ValidationReport, check_id: int) -> list[CheckResult]:
    return [r for r in report.failures if r.check_id == check_id]


def test_check_24_passes_for_valid_sink() -> None:
    d = _base_dict()
    d["Sinks"] = [_sink_dict()]
    recipe = Recipe.model_validate(d)
    report = validate(recipe, _Plugin())
    assert not _failures(report, 24), report.failures


def test_check_24_fails_on_duplicate_sink_name() -> None:
    d = _base_dict()
    d["Sinks"] = [
        _sink_dict(name="pngs"),
        _sink_dict(name="pngs", stage="post_Generation"),
    ]
    recipe = Recipe.model_validate(d)
    report = validate(recipe, _Plugin())
    fails = _failures(report, 24)
    assert len(fails) == 1
    assert "duplicate" in fails[0].message.lower()


def test_check_24_fails_on_path_escape() -> None:
    d = _base_dict()
    d["Sinks"] = [_sink_dict(path_template="../escape/{record_id}.png")]
    recipe = Recipe.model_validate(d)
    report = validate(recipe, _Plugin())
    fails = _failures(report, 24)
    assert len(fails) == 1
    assert "escape" in fails[0].message.lower()


def test_check_24_fails_on_absolute_path_template() -> None:
    d = _base_dict()
    d["Sinks"] = [_sink_dict(path_template="/tmp/{record_id}.png")]
    recipe = Recipe.model_validate(d)
    report = validate(recipe, _Plugin())
    fails = _failures(report, 24)
    assert len(fails) == 1


def test_check_24_fails_on_unparseable_template() -> None:
    d = _base_dict()
    d["Sinks"] = [_sink_dict(path_template="exports/{record_id|wat}.png")]
    recipe = Recipe.model_validate(d)
    report = validate(recipe, _Plugin())
    fails = _failures(report, 24)
    assert len(fails) == 1
    assert "filter" in fails[0].message.lower() or "parse" in fails[0].message.lower()


def test_check_24_fails_on_unknown_field() -> None:
    d = _base_dict()
    d["Sinks"] = [_sink_dict(field="not_a_real_field")]
    recipe = Recipe.model_validate(d)
    report = validate(recipe, _Plugin())
    fails = _failures(report, 24)
    assert len(fails) == 1
    assert "field" in fails[0].message.lower()


def test_check_24_fails_on_unknown_split_in_sink() -> None:
    d = _base_dict()
    d["Sinks"] = [_sink_dict(splits=["nonexistent"])]
    recipe = Recipe.model_validate(d)
    report = validate(recipe, _Plugin())
    fails = _failures(report, 24)
    assert len(fails) == 1
    assert "split" in fails[0].message.lower()


def test_check_24_accepts_loader_stamped_fields() -> None:
    # `record_id` and `path` are loader-stamped, not in Output.record_schema.
    d = _base_dict()
    d["Sinks"] = [_sink_dict(field="path")]
    recipe = Recipe.model_validate(d)
    report = validate(recipe, _Plugin())
    assert not _failures(report, 24), report.failures
