# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-2 recipe validator tests - checks 1-18 (Stories B.e.1, B.e.2, B.e.3).

Per-check failure fixtures and the no-short-circuit aggregator.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
from PIL import Image

from datarefinery.plugins.base import OperationSpec, ParameterSpec
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
            parameters={"size": ParameterSpec(type="int", required=False)},
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
        "histogram": OperationSpec(
            applicable_sections=frozenset({"Visualizations"}),
        ),
        # Used by check 18 failure fixtures: requires `mean` and `std`.
        "normalize_strict": OperationSpec(
            parameters={
                "mean": ParameterSpec(type="float", required=True),
                "std": ParameterSpec(type="float", required=True),
            },
            applicable_sections=frozenset({"Transformations"}),
            fit_on_train=True,
        ),
    }


def _base_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "test_plugin",
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]},
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


def test_valid_recipe_passes_all_twenty_two_checks() -> None:
    recipe = _build(_base_dict())
    report = validate(recipe, _Plugin())
    assert report.passed, [r for r in report.failures]
    assert len(report.results) == 22
    assert {r.check_id for r in report.results} == set(range(1, 23))
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
    bad["Augmentations"] = [{"name": "f", "op": "horizontal_flip", "splits": ["val"], "seed": 1}]
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


# ---------------------------------------------------------------------------
# Per-check failure fixtures: checks 7-13 (Story B.e.2)
# ---------------------------------------------------------------------------


def test_check_07_fails_when_featurization_input_undeclared() -> None:
    bad = _base_dict()
    bad["Featurizations"] = [
        {
            "name": "embed",
            "inputs": ["nonexistent_field"],
            "output_field": "embedding",
            "op": "embed",
            "splits": ["train"],
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 7)
    assert len(failures) == 1
    assert "nonexistent_field" in failures[0].message


def test_check_07_passes_when_featurization_input_is_in_record_schema() -> None:
    ok = _base_dict()
    ok["Featurizations"] = [
        {
            "name": "embed",
            "inputs": ["image"],
            "output_field": "embedding",
            "op": "embed",
            "splits": ["train"],
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 7)


def test_check_07_chained_featurization_uses_upstream_output() -> None:
    ok = _base_dict()
    ok["Featurizations"] = [
        {
            "name": "embed",
            "inputs": ["image"],
            "output_field": "embedding",
            "op": "embed",
            "splits": ["train"],
        },
        {
            "name": "embed_norm",
            "inputs": ["embedding"],
            "output_field": "embedding_norm",
            "op": "embed",
            "splits": ["train"],
        },
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 7)


def test_check_08_fails_when_neither_ratios_nor_key_assignment() -> None:
    bad = _base_dict()
    bad["Splits"] = {}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 8)
    assert len(failures) == 1
    assert "must declare" in failures[0].message


def test_check_08_fails_when_both_ratios_and_key_assignment() -> None:
    bad = _base_dict()
    bad["Splits"] = {
        "ratios": {"train": 0.8, "val": 0.2},
        "key_assignment": {"field": "split_id", "mapping": {"a": "train"}},
    }
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 8)
    assert len(failures) == 1
    assert "got both" in failures[0].message


def test_check_08_fails_when_ratios_sum_exceeds_one() -> None:
    bad = _base_dict()
    bad["Splits"] = {"ratios": {"train": 0.8, "val": 0.5}}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 8)
    assert len(failures) == 1
    assert "1.3" in failures[0].message or "sum to" in failures[0].message


def test_check_08_fails_on_negative_ratio() -> None:
    bad = _base_dict()
    bad["Splits"] = {"ratios": {"train": 1.0, "val": -0.1}}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 8)
    assert len(failures) == 1
    assert "non-negative" in failures[0].message


def test_check_08_passes_when_ratios_sum_below_one() -> None:
    """Sum < 1.0 is allowed (unsplit remainder)."""
    ok = _base_dict()
    ok["Splits"] = {"ratios": {"train": 0.5, "val": 0.2}}
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 8)


def test_check_08_fails_on_empty_key_assignment_mapping() -> None:
    bad = _base_dict()
    bad["Splits"] = {"key_assignment": {"field": "split_id", "mapping": {}}}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 8)
    assert len(failures) == 1


def test_check_09_fails_when_stratify_by_field_undeclared() -> None:
    bad = _base_dict()
    bad["Splits"] = {
        "ratios": {"train": 0.8, "val": 0.1, "test": 0.1},
        "stratify_by": "ghost_field",
    }
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 9)
    assert len(failures) == 1
    assert "ghost_field" in failures[0].message


def test_check_09_passes_when_stratify_by_is_in_record_schema() -> None:
    ok = _base_dict()
    ok["Splits"] = {
        "ratios": {"train": 0.8, "val": 0.1, "test": 0.1},
        "stratify_by": "label",
    }
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 9)


def test_check_09_passes_when_stratify_by_is_a_featurization_output() -> None:
    ok = _base_dict()
    ok["Splits"] = {
        "ratios": {"train": 0.8, "val": 0.1, "test": 0.1},
        "stratify_by": "embedding",
    }
    ok["Featurizations"] = [
        {
            "name": "embed",
            "inputs": ["image"],
            "output_field": "embedding",
            "op": "embed",
            "splits": ["train"],
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 9)


def test_check_10_fails_when_class_balance_in_both_splits_and_filter() -> None:
    bad = _base_dict()
    bad["Splits"]["class_balance"] = "upsample"
    bad["Filters"] = [
        {
            "name": "balance_filter",
            "predicate": {"class_balance": {"field": "label"}},
            "stages": ["pre_split"],
            "splits": [],
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 10)
    assert len(failures) == 1
    assert "class-imbalance" in failures[0].message.lower()


def test_check_10_passes_when_only_splits_handles_imbalance() -> None:
    ok = _base_dict()
    ok["Splits"]["class_balance"] = "upsample"
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 10)


def test_check_10_passes_when_only_filter_handles_imbalance() -> None:
    ok = _base_dict()
    ok["Filters"] = [
        {
            "name": "balance_filter",
            "predicate": {"class_balance": {"field": "label"}},
            "stages": ["pre_split"],
            "splits": [],
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 10)


def test_check_11_passes_for_valid_visualization_mode() -> None:
    ok = _base_dict()
    ok["Visualizations"] = [
        {
            "name": "hist",
            "op": "histogram",
            "stage": "post_split",
            "mode": "reporting",
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 11)


def test_check_12_fails_when_variant_targets_unknown_section() -> None:
    bad = _base_dict()
    bad["variants"] = {
        "weird": {"FakeSection": {"x": 1}},
    }
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 12)
    assert len(failures) == 1
    assert "FakeSection" in failures[0].message


def test_check_12_passes_for_known_section_overrides() -> None:
    ok = _base_dict()
    ok["variants"] = {
        "no_aug": {"Augmentations": []},
        "extra_seed": {"seed": 99},
    }
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 12)


def test_check_13_fails_when_labels_field_missing_from_record_schema() -> None:
    bad = _base_dict()
    bad["Labels"] = {
        "field": "label_alt",
        "source": {"kind": "direct"},
    }
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 13)
    assert len(failures) == 1
    assert "label_alt" in failures[0].message


def test_check_13_passes_when_labels_field_in_record_schema() -> None:
    report = validate(_build(_base_dict()), _Plugin())
    assert not _failures_for(report, 13)


# ---------------------------------------------------------------------------
# Multi-violation cross-check spanning 1-13
# ---------------------------------------------------------------------------


def test_multi_violation_recipe_spans_checks_1_through_13() -> None:
    bad = copy.deepcopy(_base_dict())
    bad["schema_version"] = 99  # check 1
    bad["Splits"]["ratios"] = {"train": 1.5}  # check 8
    bad["Splits"]["stratify_by"] = "ghost"  # check 9
    bad["Splits"]["class_balance"] = "upsample"
    bad["Filters"] = [
        {
            "name": "bal",
            "predicate": {"class_balance": {}},
            "stages": ["pre_split"],
            "splits": [],
        }
    ]  # check 10
    bad["variants"] = {"v": {"FakeSection": {}}}  # check 12
    bad["Labels"]["field"] = "label_alt"  # check 13
    report = validate(_build(bad), _Plugin())
    failed_ids = {r.check_id for r in report.failures}
    assert {1, 8, 9, 10, 12, 13}.issubset(failed_ids), failed_ids


# ---------------------------------------------------------------------------
# Per-check failure fixtures: checks 14-18 (Story B.e.3)
# ---------------------------------------------------------------------------


def test_check_14_fails_when_generation_field_not_in_record_schema() -> None:
    bad = _base_dict()
    bad["Generation"] = [
        {
            "name": "synth",
            "inputs": ["image"],
            "output_schema": {
                "ghost_field": {"dtype": "uint8", "shape": [32, 32, 3]},
            },
            "seed": 1,
            "applies_at": ["train"],
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 14)
    assert len(failures) == 1
    assert "ghost_field" in failures[0].message


def test_check_14_fails_on_dtype_mismatch() -> None:
    bad = _base_dict()
    bad["Generation"] = [
        {
            "name": "synth",
            "inputs": ["image"],
            "output_schema": {
                # `image` declared as uint8 in Output; Generation says float32 -> mismatch
                "image": {"dtype": "float32", "shape": [32, 32, 3]},
            },
            "seed": 1,
            "applies_at": ["train"],
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 14)
    assert len(failures) == 1
    assert "dtype" in failures[0].message


def test_check_14_passes_when_generation_matches_record_schema() -> None:
    ok = _base_dict()
    ok["Generation"] = [
        {
            "name": "synth",
            "inputs": ["image"],
            "output_schema": {
                "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                "label": {"dtype": "int32"},
            },
            "seed": 1,
            "applies_at": ["train"],
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 14)


def test_check_15_fails_when_transformation_references_undefined_split() -> None:
    bad = _base_dict()
    bad["Transformations"] = [
        {
            "name": "n",
            "op": "normalize",
            "fit_source": "train",
            "splits": ["train", "ghost"],
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 15)
    assert len(failures) == 1
    assert "ghost" in failures[0].message


def test_check_15_fails_when_generation_applies_at_undefined_split() -> None:
    bad = _base_dict()
    bad["Generation"] = [
        {
            "name": "synth",
            "inputs": ["image"],
            "output_schema": {"image": {"dtype": "uint8", "shape": [32, 32, 3]}},
            "seed": 1,
            "applies_at": ["unknown_split"],
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 15)
    assert len(failures) == 1
    assert "unknown_split" in failures[0].message


def test_check_15_fails_for_filter_referencing_undefined_split() -> None:
    bad = _base_dict()
    bad["Filters"] = [
        {
            "name": "f",
            "predicate": {},
            "stages": ["post_split"],
            "splits": ["nope"],
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 15)
    assert len(failures) == 1


def test_check_15_passes_when_all_split_refs_defined() -> None:
    report = validate(_build(_base_dict()), _Plugin())
    assert not _failures_for(report, 15)


def test_check_16_fails_when_neither_n_nor_fraction() -> None:
    bad = _base_dict()
    bad["SampleData"] = {"selector": {}}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 16)
    assert len(failures) == 1
    assert "must declare" in failures[0].message


def test_check_16_fails_when_both_n_and_fraction() -> None:
    bad = _base_dict()
    bad["SampleData"] = {"selector": {"n": 100, "fraction": 0.1}}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 16)
    assert len(failures) == 1
    assert "got both" in failures[0].message


def test_check_16_fails_when_fraction_not_strict() -> None:
    bad = _base_dict()
    bad["SampleData"] = {"selector": {"fraction": 1.0}}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 16)
    assert len(failures) == 1
    assert "(0, 1)" in failures[0].message


def test_check_16_fails_when_n_below_one() -> None:
    bad = _base_dict()
    bad["SampleData"] = {"selector": {"n": 0}}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 16)
    assert len(failures) == 1
    assert ">= 1" in failures[0].message


def test_check_16_passes_when_sample_data_absent() -> None:
    report = validate(_build(_base_dict()), _Plugin())
    assert not _failures_for(report, 16)


def test_check_16_passes_for_valid_fraction() -> None:
    ok = _base_dict()
    ok["SampleData"] = {"selector": {"fraction": 0.1, "seed": 1}}
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 16)


def test_check_17_fails_when_input_contract_field_undeclared() -> None:
    bad = _base_dict()
    bad["InputContracts"] = [
        {"field": "ghost_field", "assertion": {"kind": "required"}, "severity": "error"}
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 17)
    assert len(failures) == 1
    assert "ghost_field" in failures[0].message


def test_check_17_fails_when_output_expectation_field_undeclared() -> None:
    bad = _base_dict()
    bad["OutputExpectations"] = [
        {"field": "ghost", "assertion": {"kind": "range"}, "severity": "warning"}
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 17)
    assert len(failures) == 1


def test_check_17_passes_for_dataset_level_assertion_without_field() -> None:
    ok = _base_dict()
    ok["OutputExpectations"] = [
        {
            "field": None,
            "assertion": {"kind": "record_count_min", "value": 10},
            "severity": "error",
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 17)


def test_check_18_fails_on_unknown_op_name() -> None:
    bad = _base_dict()
    bad["Transformations"] = [
        {"name": "x", "op": "ghost_op", "fit_source": "train", "splits": ["train"]}
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 18)
    assert len(failures) == 1
    assert "ghost_op" in failures[0].message


def test_check_18_fails_on_missing_required_param() -> None:
    bad = _base_dict()
    bad["Transformations"] = [
        {
            "name": "n",
            "op": "normalize_strict",  # requires mean and std
            "fit_source": "train",
            "splits": ["train", "val", "test"],
            "params": {"mean": 0.5},  # missing std
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 18)
    assert len(failures) == 1
    assert "std" in failures[0].message
    assert "missing required" in failures[0].message


def test_check_18_fails_on_unexpected_param() -> None:
    bad = _base_dict()
    bad["Transformations"] = [
        {
            "name": "r",
            "op": "resize",
            "fit_source": None,
            "splits": ["train"],
            "params": {"size": 32, "extra_param": True},
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 18)
    assert len(failures) == 1
    assert "extra_param" in failures[0].message


def test_check_18_passes_on_well_formed_params() -> None:
    ok = _base_dict()
    ok["Transformations"] = [
        {
            "name": "n",
            "op": "normalize_strict",
            "fit_source": "train",
            "splits": ["train", "val", "test"],
            "params": {"mean": 0.5, "std": 0.2},
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 18)


# ---------------------------------------------------------------------------
# Multi-violation cross-check spanning every check 1-18
# ---------------------------------------------------------------------------


def test_multi_violation_recipe_spans_every_check_1_through_18() -> None:
    bad = copy.deepcopy(_base_dict())
    bad["schema_version"] = 99  # check 1
    bad["plugin"] = "wrong_plugin"  # check 2
    # Use a plugin that doesn't list "Visualizations" -> check 3
    plugin = _Plugin(
        supported_sections=frozenset(
            {
                "Input",
                "Output",
                "Labels",
                "Splits",
                "InputContracts",
                "Filters",
                "Generation",
                "Transformations",
                "Augmentations",
                "Featurizations",
                "OutputExpectations",
                "SampleData",
            }
        ),
    )
    bad["Visualizations"] = [
        {"name": "v", "op": "histogram", "stage": "post_split", "mode": "reporting"}
    ]
    bad["Transformations"] = [
        {
            "name": "n",
            "op": "normalize_strict",  # requires mean+std (check 18)
            "fit_source": "validation",  # check 6
            "splits": [],  # check 4
        }
    ]
    bad["Augmentations"] = [
        {"name": "f", "op": "horizontal_flip", "splits": ["test"], "seed": 1}  # check 5
    ]
    bad["Featurizations"] = [
        {
            "name": "embed",
            "inputs": ["nonexistent"],  # check 7
            "output_field": "emb",
            "op": "embed",
            "splits": ["ghost_split"],  # check 15
        }
    ]
    bad["Splits"]["ratios"] = {"train": 1.5}  # check 8
    bad["Splits"]["stratify_by"] = "missing"  # check 9
    bad["Splits"]["class_balance"] = "upsample"
    bad["Filters"] = [
        {
            "name": "bal",
            "predicate": {"class_balance": {}},
            "stages": ["pre_split"],
            "splits": [],
        }
    ]  # check 10
    bad["variants"] = {"v": {"FakeSection": {}}}  # check 12
    bad["Labels"]["field"] = "label_alt"  # check 13
    bad["Generation"] = [
        {
            "name": "synth",
            "inputs": ["image"],
            "output_schema": {"image": {"dtype": "float32", "shape": [32, 32, 3]}},
            "seed": 1,
            "applies_at": ["train"],
        }
    ]  # check 14
    bad["SampleData"] = {"selector": {}}  # check 16
    bad["InputContracts"] = [
        {"field": "no_such", "assertion": {"kind": "required"}, "severity": "error"}
    ]  # check 17

    report = validate(_build(bad), plugin)
    failed_ids = {r.check_id for r in report.failures}
    expected = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18}
    assert expected.issubset(failed_ids), (
        f"missing failures for {sorted(expected - failed_ids)}; got {sorted(failed_ids)}"
    )


# ---------------------------------------------------------------------------
# Check 19 (Story H.a) — label_from_spec_resolves
#
# Uses a real image_classification plugin name so the check engages
# (check 19 short-circuits as `pass` for other plugins).
# ---------------------------------------------------------------------------


def _ic_base_dict() -> dict[str, Any]:
    """Minimal image_classification recipe dict for check 19 fixtures."""
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]},
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                "label": {"dtype": "string"},
            },
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}, "seed": 0},
    }


def _ic_plugin() -> _Plugin:
    return _Plugin(name="image_classification")


def test_check_19_passes_when_image_folder_has_no_label_from() -> None:
    recipe = _build(_ic_base_dict())
    report = validate(recipe, _ic_plugin())
    assert not _failures_for(report, 19)


def test_check_19_fails_when_image_folder_has_label_from(tmp_path: Any) -> None:
    payload = _ic_base_dict()
    manifest = tmp_path / "labels.csv"
    manifest.write_text("filename,class\nfoo,bar\n", encoding="utf-8")
    payload["Input"]["sources"][0]["label_from"] = {
        "path": str(manifest),
        "join": "by_id",
        "id_field": "filename",
        "label_field": "class",
    }
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 19)
    assert failures and "image_folder" in failures[0].message


def test_check_19_fails_when_image_flat_has_no_label_from() -> None:
    payload = _ic_base_dict()
    payload["Input"]["sources"][0]["type"] = "image_flat"
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 19)
    assert failures and "no label_from" in failures[0].message


def test_check_19_fails_when_manifest_file_missing(tmp_path: Any) -> None:
    payload = _ic_base_dict()
    payload["Input"]["sources"][0]["type"] = "image_flat"
    payload["Input"]["sources"][0]["path"] = str(tmp_path)
    payload["Input"]["sources"][0]["label_from"] = {
        "path": str(tmp_path / "nope.csv"),
        "join": "by_id",
        "id_field": "filename",
        "label_field": "class",
    }
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 19)
    assert failures and "file not found" in failures[0].message


def test_check_19_fails_on_duplicate_ids_in_manifest(tmp_path: Any) -> None:
    manifest = tmp_path / "labels.csv"
    manifest.write_text("filename,class\na,cat\na,dog\n", encoding="utf-8")
    payload = _ic_base_dict()
    payload["Input"]["sources"][0]["type"] = "image_flat"
    payload["Input"]["sources"][0]["path"] = str(tmp_path)
    payload["Input"]["sources"][0]["label_from"] = {
        "path": str(manifest),
        "join": "by_id",
        "id_field": "filename",
        "label_field": "class",
    }
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 19)
    assert failures and "duplicate ids" in failures[0].message


def test_check_19_fails_on_unknown_label_field(tmp_path: Any) -> None:
    manifest = tmp_path / "labels.csv"
    manifest.write_text("filename,class\na,cat\n", encoding="utf-8")
    payload = _ic_base_dict()
    payload["Input"]["sources"][0]["type"] = "image_flat"
    payload["Input"]["sources"][0]["path"] = str(tmp_path)
    payload["Input"]["sources"][0]["label_from"] = {
        "path": str(manifest),
        "join": "by_id",
        "id_field": "filename",
        "label_field": "missing",
    }
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 19)
    assert failures and "label_field" in failures[0].message


def test_check_19_passes_for_valid_image_flat_recipe(tmp_path: Any) -> None:
    images = tmp_path / "imgs"
    images.mkdir()
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(images / "a.png")
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(images / "b.png")
    manifest = tmp_path / "labels.csv"
    manifest.write_text("filename,class\na,cat\nb,dog\n", encoding="utf-8")
    payload = _ic_base_dict()
    payload["Input"]["sources"][0]["type"] = "image_flat"
    payload["Input"]["sources"][0]["path"] = str(images)
    payload["Input"]["sources"][0]["label_from"] = {
        "path": str(manifest),
        "join": "by_id",
        "id_field": "filename",
        "label_field": "class",
    }
    report = validate(_build(payload), _ic_plugin())
    assert not _failures_for(report, 19)


def test_check_19_fails_on_row_count_mismatch_for_by_row_order(tmp_path: Any) -> None:
    images = tmp_path / "imgs"
    images.mkdir()
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(images / "a.png")
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(images / "b.png")
    manifest = tmp_path / "labels.csv"
    manifest.write_text("cat\ndog\nfish\n", encoding="utf-8")
    payload = _ic_base_dict()
    payload["Input"]["sources"][0]["type"] = "image_flat"
    payload["Input"]["sources"][0]["path"] = str(images)
    payload["Input"]["sources"][0]["label_from"] = {
        "path": str(manifest),
        "join": "by_row_order",
        "header": ["class"],
        "label_field": "class",
    }
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 19)
    assert failures and "by_row_order" in failures[0].message


# ---------------------------------------------------------------------------
# Check 20 (Story H.b) — partitions_consistent
#
# Uses the image_classification plugin since check 20 short-circuits as
# `pass` for plugins whose loader doesn't stamp `partition`.
# ---------------------------------------------------------------------------


def _ic_two_source_dict() -> dict[str, Any]:
    """Two image_folder sources, both declaring distinct partitions."""
    base = _ic_base_dict()
    base["Input"]["sources"] = [
        {
            "name": "train_data",
            "type": "image_folder",
            "path": "/data/train",
            "partition": "train",
        },
        {
            "name": "test_data",
            "type": "image_folder",
            "path": "/data/test",
            "partition": "test",
        },
    ]
    base["Splits"] = {}  # Form A: honor source partitions verbatim
    return base


def test_check_20_passes_when_no_partitions_declared() -> None:
    report = validate(_build(_ic_base_dict()), _ic_plugin())
    assert not _failures_for(report, 20)


def test_check_20_passes_for_form_a() -> None:
    report = validate(_build(_ic_two_source_dict()), _ic_plugin())
    assert not _failures_for(report, 20)


def test_check_20_passes_for_form_b() -> None:
    payload = _ic_two_source_dict()
    payload["Splits"] = {
        "ratios": {"train": 0.8, "val": 0.2},
        "applies_to": "train",
        "seed": 11,
    }
    report = validate(_build(payload), _ic_plugin())
    assert not _failures_for(report, 20)


def test_check_20_fails_on_partial_partition_declaration() -> None:
    payload = _ic_two_source_dict()
    del payload["Input"]["sources"][1]["partition"]  # mixed mode
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 20)
    assert failures and "declare on all or none" in failures[0].message


def test_check_20_fails_when_output_schema_declares_partition_field() -> None:
    payload = _ic_base_dict()
    payload["Output"]["record_schema"]["partition"] = {"dtype": "string"}
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 20)
    assert failures and "reserved" in failures[0].message


def test_check_20_fails_when_applies_to_references_unknown_partition() -> None:
    payload = _ic_two_source_dict()
    payload["Splits"] = {
        "ratios": {"train": 1.0},
        "applies_to": "ghost",
    }
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 20)
    assert failures and "ghost" in failures[0].message


def test_check_20_fails_when_applies_to_set_without_partitions() -> None:
    payload = _ic_base_dict()
    payload["Splits"]["applies_to"] = "train"
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 20)
    assert failures and "no source declares 'partition'" in failures[0].message


def test_check_20_fails_on_sibling_collision_in_applies_to_ratios() -> None:
    payload = _ic_two_source_dict()
    payload["Splits"] = {
        "ratios": {"train": 0.5, "test": 0.5},  # 'test' collides with sibling
        "applies_to": "train",
    }
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 20)
    assert failures and "collide" in failures[0].message


def test_check_20_fails_when_ratios_set_without_applies_to_under_partitions() -> None:
    payload = _ic_two_source_dict()
    payload["Splits"] = {"ratios": {"train": 0.5, "val": 0.5}}  # contradicts partitions
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 20)
    assert failures and "applies_to" in failures[0].message


def test_check_20_skips_for_non_partition_plugin() -> None:
    """Plugin not in _PARTITION_PLUGINS short-circuits as pass."""
    payload = _ic_base_dict()
    payload["plugin"] = "test_plugin"  # not an image_classification plugin name
    payload["Input"]["sources"][0]["partition"] = "train"  # would normally trigger checks
    # Use the default _Plugin which has name='test_plugin'.
    report = validate(_build(payload), _Plugin())
    assert not _failures_for(report, 20)


# ---------------------------------------------------------------------------
# Check 21 — `unlabeled_consistency` (Story H.d)
# ---------------------------------------------------------------------------


def _ic_unlabeled_dict() -> dict[str, Any]:
    """Labeled train + unlabeled test sources (image_flat for unlabeled)."""
    base = _ic_base_dict()
    base["Input"]["sources"] = [
        {
            "name": "train_data",
            "type": "image_folder",
            "path": "/data/train",
            "partition": "train",
        },
        {
            "name": "test_data",
            "type": "image_flat",
            "path": "/data/test",
            "partition": "test",
            "unlabeled": True,
        },
    ]
    base["Splits"] = {"ratios": {"train": 0.85, "val": 0.15}, "applies_to": "train"}
    return base


def test_check_21_passes_on_valid_unlabeled_recipe() -> None:
    report = validate(_build(_ic_unlabeled_dict()), _ic_plugin())
    assert not _failures_for(report, 21)


def test_check_21_fails_on_image_folder_with_unlabeled() -> None:
    payload = _ic_unlabeled_dict()
    payload["Input"]["sources"][1]["type"] = "image_folder"
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 21)
    assert failures and "image_flat" in failures[0].message


def test_check_21_fails_on_stratify_by_with_unlabeled_applies_to() -> None:
    payload = _ic_unlabeled_dict()
    payload["Splits"] = {
        "ratios": {"sub_a": 0.5, "sub_b": 0.5},
        "applies_to": "test",
        "stratify_by": "label",
    }
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 21)
    assert failures and "stratify_by" in failures[0].message


def test_check_21_fails_on_filter_by_label_targeting_unlabeled_split() -> None:
    payload = _ic_unlabeled_dict()
    payload["Filters"] = [
        {
            "name": "drop_other",
            "predicate": {"op": "filter_by_label", "labels": ["cat"]},
            "stages": ["post_split"],
            "splits": ["test"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 21)
    assert failures and "filter_by_label" in failures[0].message


def test_check_21_fails_on_label_from_path_featurization_on_unlabeled_split() -> None:
    payload = _ic_unlabeled_dict()
    payload["Featurizations"] = [
        {
            "name": "derive_label",
            "op": "label_from_path",
            "inputs": ["path"],
            "output_field": "label",
            "splits": ["test"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 21)
    assert failures and "label_from_path" in failures[0].message


def test_check_21_passes_on_label_independent_featurization_on_unlabeled_split() -> None:
    """image_size_stats does not read label; targeting unlabeled splits is fine."""
    payload = _ic_unlabeled_dict()
    payload["Featurizations"] = [
        {
            "name": "sizes",
            "op": "image_size_stats",
            "inputs": ["image"],
            "output_field": "size",
            "splits": ["test"],
        }
    ]
    assert not _failures_for(validate(_build(payload), _ic_plugin()), 21)


def test_check_21_skips_for_non_partition_plugin() -> None:
    payload = _ic_base_dict()
    payload["plugin"] = "test_plugin"
    report = validate(_build(payload), _Plugin())
    assert not _failures_for(report, 21)


def test_check_21_propagates_unlabeled_to_sub_splits() -> None:
    """When applies_to targets an unlabeled partition, sub-split names inherit
    unlabeled-ness for filter/featurization checks."""
    payload = _ic_unlabeled_dict()
    payload["Splits"] = {
        "ratios": {"sub_a": 0.5, "sub_b": 0.5},
        "applies_to": "test",
    }
    # filter_by_label on sub_a — derived from the unlabeled 'test' partition.
    payload["Filters"] = [
        {
            "name": "f",
            "predicate": {"op": "filter_by_label", "labels": ["cat"]},
            "stages": ["post_split"],
            "splits": ["sub_a"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 21)
    assert failures and "sub_a" in failures[0].message
