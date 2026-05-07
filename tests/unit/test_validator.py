# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-2 recipe validator tests - framework + checks 1-6 (Story B.e.1).

Per-check failure fixtures and the no-short-circuit aggregator. Checks
7-18 are added in B.e.2 / B.e.3.
"""

from __future__ import annotations

import copy
from typing import Any

from datarefinery.plugins.base import OperationSpec
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import (
    CheckResult,
    ValidationReport,
    validate,
)


class _Plugin:
    """Test plugin satisfying the `Plugin` runtime protocol."""

    def __init__(
        self,
        *,
        name: str = "test_plugin",
        supported_sections: frozenset[str] | None = None,
        supported_operations: dict[str, OperationSpec] | None = None,
    ) -> None:
        self.name = name
        self.schema_version = 1
        self.supported_sections = supported_sections or frozenset(
            {
                "Input",
                "Output",
                "Labels",
                "Splits",
                "SampleData",
                "InputContracts",
                "Filters",
                "Generation",
                "Transformations",
                "Augmentations",
                "Featurizations",
                "OutputExpectations",
                "Visualizations",
            }
        )
        self.supported_operations = supported_operations or _default_operations()

    def operation_factory(self, section: str, op_name: str) -> object:
        del section, op_name
        return lambda record: record

    def is_stub(self) -> bool:
        return False


def _default_operations() -> dict[str, OperationSpec]:
    return {
        "normalize": OperationSpec(
            applicable_sections=frozenset({"Transformations"}),
            fit_on_train=True,
        ),
        "resize": OperationSpec(
            applicable_sections=frozenset({"Transformations"}),
            fit_on_train=False,
        ),
        "horizontal_flip": OperationSpec(
            applicable_sections=frozenset({"Augmentations"}),
        ),
        "noop_filter": OperationSpec(
            applicable_sections=frozenset({"Filters"}),
        ),
        "embed": OperationSpec(
            applicable_sections=frozenset({"Featurizations"}),
        ),
    }


def _base_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "test_plugin",
        "Input": {
            "sources": [
                {"name": "train", "type": "image_folder", "path": "/data/train"}
            ]
        },
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
        "Transformations": [
            {
                "name": "n",
                "op": "normalize",
                "fit_source": "train",
                "splits": ["train", "val", "test"],
            },
        ],
        "Augmentations": [
            {
                "name": "f",
                "op": "horizontal_flip",
                "splits": ["train"],
                "seed": 1,
            },
        ],
    }


def _build(d: dict[str, Any]) -> Recipe:
    return Recipe.model_validate(d)


def _failures_for(report: ValidationReport, check_id: int) -> list[CheckResult]:
    return [r for r in report.failures if r.check_id == check_id]


# ---------------------------------------------------------------------------
# Framework / aggregator behavior
# ---------------------------------------------------------------------------


def test_valid_recipe_passes_all_six_checks() -> None:
    recipe = _build(_base_dict())
    report = validate(recipe, _Plugin())
    assert report.passed, [r for r in report.failures]
    assert len(report.results) == 6
    assert {r.check_id for r in report.results} == {1, 2, 3, 4, 5, 6}
    assert all(r.status == "pass" for r in report.results)


def test_validation_report_failures_property() -> None:
    bad = _base_dict()
    bad["schema_version"] = 99
    report = validate(_build(bad), _Plugin())
    assert not report.passed
    assert all(r.check_id == 1 for r in report.failures)


def test_validate_does_not_short_circuit() -> None:
    bad = _base_dict()
    bad["schema_version"] = 99  # check 1
    bad["Augmentations"] = [
        {"name": "f", "op": "horizontal_flip", "splits": ["val"], "seed": 1}
    ]  # check 5
    report = validate(_build(bad), _Plugin())
    failed_ids = {r.check_id for r in report.failures}
    assert {1, 5}.issubset(failed_ids), failed_ids


def test_check_exception_is_captured_as_failure(monkeypatch: Any) -> None:
    """A check that raises is reported as a fail, not propagated."""
    import datarefinery.recipe.validator as validator_mod

    def boom(recipe: Recipe, plugin: object) -> CheckResult:
        del recipe, plugin
        raise RuntimeError("kaboom")

    boom_entry = (1, "schema_version_recognized", boom)
    monkeypatch.setattr(
        validator_mod,
        "_CHECKS",
        (boom_entry, *validator_mod._CHECKS[1:]),
    )

    report = validate(_build(_base_dict()), _Plugin())
    failures = _failures_for(report, 1)
    assert len(failures) == 1
    assert "kaboom" in failures[0].message


# ---------------------------------------------------------------------------
# Per-check failure fixtures
# ---------------------------------------------------------------------------


def test_check_01_fails_on_unrecognized_schema_version() -> None:
    bad = _base_dict()
    bad["schema_version"] = 99
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 1)
    assert len(failures) == 1
    assert "99" in failures[0].message
    assert failures[0].location == "schema_version"


def test_check_02_fails_when_plugin_name_mismatches_recipe() -> None:
    plugin = _Plugin(name="different_plugin")
    report = validate(_build(_base_dict()), plugin)
    failures = _failures_for(report, 2)
    assert len(failures) == 1
    assert "test_plugin" in failures[0].message
    assert "different_plugin" in failures[0].message


def test_check_03_fails_when_section_unsupported_by_plugin() -> None:
    plugin = _Plugin(
        supported_sections=frozenset(
            {
                "Input",
                "Output",
                "Labels",
                "Splits",
                "Transformations",
                "Augmentations",
            }
        ),
    )
    bad = _base_dict()
    bad["Filters"] = [
        {
            "name": "f",
            "predicate": {},
            "stages": ["pre_split"],
            "splits": [],
        }
    ]
    report = validate(_build(bad), plugin)
    failures = _failures_for(report, 3)
    assert len(failures) == 1
    assert "Filters" in failures[0].message


def test_check_04_fails_on_transformation_with_empty_splits() -> None:
    bad = _base_dict()
    bad["Transformations"] = [
        {"name": "n", "op": "normalize", "fit_source": "train", "splits": []},
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 4)
    assert len(failures) == 1
    assert "Transformations" in failures[0].message


def test_check_04_fails_on_post_split_filter_with_empty_splits() -> None:
    bad = _base_dict()
    bad["Filters"] = [
        {
            "name": "f",
            "predicate": {},
            "stages": ["post_split"],
            "splits": [],
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 4)
    assert len(failures) == 1
    assert "Filters" in failures[0].message


def test_check_04_passes_for_pre_split_filter_with_empty_splits() -> None:
    ok = _base_dict()
    ok["Filters"] = [
        {
            "name": "f",
            "predicate": {},
            "stages": ["pre_split"],
            "splits": [],
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 4)


def test_check_05_fails_when_augmentation_targets_non_train_split() -> None:
    bad = _base_dict()
    bad["Augmentations"] = [
        {"name": "f", "op": "horizontal_flip", "splits": ["val"], "seed": 1}
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 5)
    assert len(failures) == 1
    assert "val" in failures[0].message


def test_check_06_fails_when_fit_on_train_op_uses_wrong_fit_source() -> None:
    bad = _base_dict()
    bad["Transformations"] = [
        {
            "name": "n",
            "op": "normalize",  # OperationSpec has fit_on_train=True
            "fit_source": "validation",
            "splits": ["train", "val", "test"],
        },
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 6)
    assert len(failures) == 1
    assert "validation" in failures[0].message
    assert "normalize" in failures[0].message


def test_check_06_skips_unknown_operations() -> None:
    """Unknown operations are surfaced by check 18 (B.e.3), not check 6."""
    bad = _base_dict()
    bad["Transformations"] = [
        {
            "name": "x",
            "op": "no_such_op",
            "fit_source": None,
            "splits": ["train"],
        },
    ]
    report = validate(_build(bad), _Plugin())
    assert not _failures_for(report, 6)


def test_check_06_passes_for_non_fit_on_train_op_without_fit_source() -> None:
    ok = _base_dict()
    ok["Transformations"] = [
        {
            "name": "r",
            "op": "resize",  # fit_on_train=False
            "fit_source": None,
            "splits": ["train", "val", "test"],
        },
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 6)


# ---------------------------------------------------------------------------
# Multi-violation cross-check
# ---------------------------------------------------------------------------


def test_multi_violation_recipe_reports_every_failure() -> None:
    bad = copy.deepcopy(_base_dict())
    bad["schema_version"] = 99  # check 1
    bad["plugin"] = "wrong_plugin_name"  # check 2 (plugin still named test_plugin)
    bad["Transformations"] = [
        {
            "name": "n",
            "op": "normalize",
            "fit_source": "validation",  # check 6
            "splits": [],  # check 4
        },
    ]
    bad["Augmentations"] = [
        {"name": "f", "op": "horizontal_flip", "splits": ["test"], "seed": 1}  # check 5
    ]
    report = validate(_build(bad), _Plugin())
    failed_ids = {r.check_id for r in report.failures}
    assert {1, 2, 4, 5, 6}.issubset(failed_ids)
