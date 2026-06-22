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

    def recommended_params(self, section: str, op_name: str) -> dict[str, object]:
        del section, op_name
        return {}

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


def test_valid_recipe_passes_all_checks() -> None:
    recipe = _build(_base_dict())
    report = validate(recipe, _Plugin())
    assert report.passed, [r for r in report.failures]
    assert len(report.results) == 27
    assert {r.check_id for r in report.results} == set(range(1, 28))
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
            "op": "noop_filter",
            "params": {},
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
            "op": "noop_filter",
            "params": {},
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
            "op": "noop_filter",
            "params": {},
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
            "op": "noop_filter",
            "params": {"class_balance": {"field": "label"}},
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
            "op": "noop_filter",
            "params": {"class_balance": {"field": "label"}},
            "stages": ["pre_split"],
            "splits": [],
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 10)


# --- G10 (Story I.s): class_balance dict shape (MF-binding hint) ---


def test_check_10_passes_for_valid_dict_class_balance() -> None:
    ok = _base_dict()
    ok["Splits"]["class_balance"] = {
        "strategy": "oversample_minority_to_majority",
        "applies_to": ["train"],
    }
    recipe = _build(ok)
    assert recipe.Splits.class_balance == {
        "strategy": "oversample_minority_to_majority",
        "applies_to": ["train"],
    }
    assert not _failures_for(validate(recipe, _Plugin()), 10)


def test_check_10_fails_dict_missing_strategy() -> None:
    bad = _base_dict()
    bad["Splits"]["class_balance"] = {"applies_to": ["train"]}
    failures = _failures_for(validate(_build(bad), _Plugin()), 10)
    assert len(failures) == 1
    assert "strategy" in failures[0].message


def test_check_10_fails_dict_missing_applies_to() -> None:
    bad = _base_dict()
    bad["Splits"]["class_balance"] = {"strategy": "oversample_minority_to_majority"}
    failures = _failures_for(validate(_build(bad), _Plugin()), 10)
    assert len(failures) == 1
    assert "applies_to" in failures[0].message


def test_check_10_fails_dict_unknown_key() -> None:
    bad = _base_dict()
    bad["Splits"]["class_balance"] = {
        "strategy": "oversample_minority_to_majority",
        "applies_to": ["train"],
        "bogus": 1,
    }
    failures = _failures_for(validate(_build(bad), _Plugin()), 10)
    assert len(failures) == 1
    assert "bogus" in failures[0].message


def test_check_10_fails_dict_applies_to_undefined_split() -> None:
    bad = _base_dict()
    bad["Splits"]["class_balance"] = {
        "strategy": "oversample_minority_to_majority",
        "applies_to": ["nope"],
    }
    failures = _failures_for(validate(_build(bad), _Plugin()), 10)
    assert len(failures) == 1
    assert "nope" in failures[0].message


def test_check_11_passes_for_valid_visualization_mode() -> None:
    ok = _base_dict()
    ok["Visualizations"] = [
        {
            "name": "hist",
            "op": "histogram",
            "stage": "post_pipeline",
            "mode": "reporting",
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 11)


# --- G7 (Story I.v): check 11 extended — viz stage's pipeline section non-empty ---


def test_check_11_fails_when_viz_targets_empty_generation_section() -> None:
    bad = _base_dict()
    # _base_dict has no Generation ops; viz targeting post_Generation is bypassed.
    bad["Visualizations"] = [
        {"name": "v", "op": "histogram", "stage": "post_Generation", "mode": "reporting"}
    ]
    failures = _failures_for(validate(_build(bad), _Plugin()), 11)
    assert failures and "post_Generation" in failures[0].message


def test_check_11_passes_when_viz_targets_populated_transformations() -> None:
    # _base_dict declares a normalize Transformation → post_Transformations is meaningful.
    ok = _base_dict()
    ok["Visualizations"] = [
        {"name": "v", "op": "histogram", "stage": "post_Transformations", "mode": "reporting"}
    ]
    assert not _failures_for(validate(_build(ok), _Plugin()), 11)


def test_check_11_passes_for_post_pipeline_regardless_of_sections() -> None:
    ok = _base_dict()
    ok["Visualizations"] = [
        {"name": "v", "op": "histogram", "stage": "post_pipeline", "mode": "reporting"}
    ]
    assert not _failures_for(validate(_build(ok), _Plugin()), 11)


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
            "op": "noop_filter",
            "params": {"class_balance": {}},
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
            "op": "synth",
            "inputs": ["image"],
            "output_schema": {
                "ghost_field": {"dtype": "uint8", "shape": [32, 32, 3]},
            },
            "seed": 1,
            "splits": ["train"],
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
            "op": "synth",
            "inputs": ["image"],
            "output_schema": {
                # `image` declared as uint8 in Output; Generation says float32 -> mismatch
                "image": {"dtype": "float32", "shape": [32, 32, 3]},
            },
            "seed": 1,
            "splits": ["train"],
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
            "op": "synth",
            "inputs": ["image"],
            "output_schema": {
                "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                "label": {"dtype": "int32"},
            },
            "seed": 1,
            "splits": ["train"],
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


def test_check_15_fails_when_generation_splits_undefined_split() -> None:
    bad = _base_dict()
    bad["Generation"] = [
        {
            "name": "synth",
            "op": "synth",
            "inputs": ["image"],
            "output_schema": {"image": {"dtype": "uint8", "shape": [32, 32, 3]}},
            "seed": 1,
            "splits": ["unknown_split"],
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
            "op": "noop_filter",
            "params": {},
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


# --- G14 (Story I.r): kind / splits on the selector (schema-only) ---


def test_check_16_passes_for_per_class_with_label_source() -> None:
    ok = _base_dict()
    ok["SampleData"] = {"selector": {"n": 1, "kind": "per_class", "splits": ["train"]}}
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 16)


def test_check_16_fails_per_class_without_label_source() -> None:
    bad = _base_dict()
    # Every source unlabeled => no label source for per_class bucketing.
    bad["Input"] = {
        "sources": [
            {
                "name": "infer",
                "type": "image_flat",
                "path": "/data/infer",
                "unlabeled": True,
                "partition": "test",
            }
        ]
    }
    bad["SampleData"] = {"selector": {"n": 1, "kind": "per_class"}}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 16)
    assert len(failures) == 1
    assert "per_class" in failures[0].message
    assert "label" in failures[0].message


def test_check_16_fails_when_splits_entry_undefined() -> None:
    bad = _base_dict()
    bad["SampleData"] = {"selector": {"n": 1, "splits": ["nope"]}}
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 16)
    assert len(failures) == 1
    assert "nope" in failures[0].message


def test_check_16_passes_when_kind_uniform_default() -> None:
    ok = _base_dict()
    ok["SampleData"] = {"selector": {"n": 5}}
    recipe = _build(ok)
    assert recipe.SampleData is not None
    assert recipe.SampleData.selector.kind == "uniform"
    assert recipe.SampleData.selector.splits is None
    assert not _failures_for(validate(recipe, _Plugin()), 16)


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
        {"field": "ghost", "assertion": {"kind": "value_range"}, "severity": "warning"}
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
        {"name": "v", "op": "histogram", "stage": "post_pipeline", "mode": "reporting"}
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
            "op": "noop_filter",
            "params": {"class_balance": {}},
            "stages": ["pre_split"],
            "splits": [],
        }
    ]  # check 10
    bad["variants"] = {"v": {"FakeSection": {}}}  # check 12
    bad["Labels"]["field"] = "label_alt"  # check 13
    bad["Generation"] = [
        {
            "name": "synth",
            "op": "synth",
            "inputs": ["image"],
            "output_schema": {"image": {"dtype": "float32", "shape": [32, 32, 3]}},
            "seed": 1,
            "splits": ["train"],
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
    assert failures and "no source partition" in failures[0].message


# --- G1 (Story I.t): tag-driven applies_to ---


def _ic_tagged_pool_dict() -> dict[str, Any]:
    """Single source, no partitions; two sample_per_class filters tag pools."""
    payload = _ic_base_dict()
    payload["Filters"] = [
        {
            "name": "train_pool_filter",
            "op": "sample_per_class",
            "params": {"n_per_class": 2, "label": "train_pool"},
            "seed": 1,
            "stages": ["pre_split"],
        },
        {
            "name": "test_pool_filter",
            "op": "sample_per_class",
            "params": {
                "n_per_class": 1,
                "label": "test",
                "exclude_already_labeled": ["train_pool"],
            },
            "seed": 1,
            "stages": ["pre_split"],
        },
    ]
    payload["Splits"] = {
        "ratios": {"train": 0.8, "val": 0.2},
        "applies_to": "train_pool",
        "seed": 11,
    }
    return payload


def test_check_20_accepts_tag_driven_applies_to() -> None:
    report = validate(_build(_ic_tagged_pool_dict()), _ic_plugin())
    assert not _failures_for(report, 20)


def test_check_20_accepts_tag_from_fractional_filter() -> None:
    payload = _ic_base_dict()
    payload["Filters"] = [
        {
            "name": "pool",
            "op": "sample_per_class_fractional",
            "params": {
                "n_per_class_base": 4,
                "fractions": {"a": 0.5},
                "label": "keep_pool",
            },
            "seed": 1,
            "stages": ["pre_split"],
        }
    ]
    payload["Splits"] = {"ratios": {"train": 0.5, "val": 0.5}, "applies_to": "keep_pool", "seed": 1}
    report = validate(_build(payload), _ic_plugin())
    assert not _failures_for(report, 20)


def test_check_20_rejects_applies_to_matching_neither_partition_nor_tag() -> None:
    payload = _ic_tagged_pool_dict()
    payload["Splits"]["applies_to"] = "ghost_pool"
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 20)
    assert failures and "ghost_pool" in failures[0].message


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
            "op": "filter_by_label",
            "params": {"labels": ["cat"]},
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
            "op": "filter_by_label",
            "params": {"labels": ["cat"]},
            "stages": ["post_split"],
            "splits": ["sub_a"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 21)
    assert failures and "sub_a" in failures[0].message


# ---------------------------------------------------------------------------
# check_23: Featurization output_field must not collide with a loader-stamped
# field. G4 (dependency-gaps-v0.16.0.md). Shift-left of the runtime collision
# check in pipeline/stages/featurizations.py.
# ---------------------------------------------------------------------------


def test_check_23_passes_when_no_featurizations() -> None:
    payload = _ic_base_dict()
    assert not _failures_for(validate(_build(payload), _ic_plugin()), 23)


def test_check_23_passes_when_featurization_output_field_is_novel() -> None:
    """`image_size_stats` writes to a fresh field — no collision."""
    payload = _ic_base_dict()
    payload["Featurizations"] = [
        {
            "name": "sizes",
            "op": "image_size_stats",
            "inputs": ["image"],
            "output_field": "img_size",
            "splits": ["train", "val", "test"],
        }
    ]
    assert not _failures_for(validate(_build(payload), _ic_plugin()), 23)


def test_check_23_fails_on_output_field_label_when_loader_stamps_label() -> None:
    """G4 canonical case: image_flat + label_from + Labels.direct +
    Featurization(op=label_from_path, output_field=label) → collision.
    """
    payload = _ic_base_dict()
    payload["Input"]["sources"][0]["type"] = "image_flat"
    payload["Input"]["sources"][0]["label_from"] = {
        "path": "/data/labels.csv",
        "join": "by_id",
        "id_field": "filename",
        "label_field": "class",
    }
    payload["Featurizations"] = [
        {
            "name": "derive_label_from_path",
            "op": "label_from_path",
            "inputs": ["path"],
            "output_field": "label",
            "splits": ["train", "val", "test"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 23)
    assert failures
    assert "label" in failures[0].message


def test_check_23_fails_on_output_field_label_for_image_folder_direct_labels() -> None:
    """image_folder + Labels.direct also stamps `label` (from parent dir);
    a `label_from_path` Featurization writing to `label` collides.
    """
    payload = _ic_base_dict()
    # image_folder is the default in _ic_base_dict; Labels.kind=direct too
    payload["Featurizations"] = [
        {
            "name": "derive_label",
            "op": "label_from_path",
            "inputs": ["path"],
            "output_field": "label",
            "splits": ["train", "val", "test"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 23)
    assert failures
    assert "label" in failures[0].message


def test_check_23_fails_on_output_field_path() -> None:
    """`path` is always loader-stamped; any Featurization output_field='path' collides."""
    payload = _ic_base_dict()
    payload["Featurizations"] = [
        {
            "name": "derive_path",
            "op": "image_size_stats",
            "inputs": ["image"],
            "output_field": "path",
            "splits": ["train", "val", "test"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 23)
    assert failures
    assert "path" in failures[0].message


def test_check_23_fails_on_output_field_record_id() -> None:
    """`record_id` is always loader-stamped."""
    payload = _ic_base_dict()
    payload["Featurizations"] = [
        {
            "name": "derive_record_id",
            "op": "image_size_stats",
            "inputs": ["image"],
            "output_field": "record_id",
            "splits": ["train", "val", "test"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 23)
    assert failures
    assert "record_id" in failures[0].message


def test_check_23_fails_on_output_field_image() -> None:
    """`image` is always loader-stamped; reserve it from Featurization output."""
    payload = _ic_base_dict()
    payload["Featurizations"] = [
        {
            "name": "overwrite_image",
            "op": "image_size_stats",
            "inputs": ["image"],
            "output_field": "image",
            "splits": ["train", "val", "test"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 23)
    assert failures
    assert "image" in failures[0].message


def test_check_23_fails_on_output_field_partition_when_partition_declared() -> None:
    """`partition` is loader-stamped only when an InputSource declares one."""
    payload = _ic_base_dict()
    payload["Input"]["sources"] = [
        {
            "name": "train_src",
            "type": "image_folder",
            "path": "/data/train",
            "partition": "train",
        },
        {
            "name": "test_src",
            "type": "image_folder",
            "path": "/data/test",
            "partition": "test",
        },
    ]
    payload["Splits"] = {}  # partitions are the splits; no ratio re-split
    payload["Featurizations"] = [
        {
            "name": "derive_partition",
            "op": "image_size_stats",
            "inputs": ["image"],
            "output_field": "partition",
            "splits": ["train", "test"],
        }
    ]
    failures = _failures_for(validate(_build(payload), _ic_plugin()), 23)
    assert failures
    assert "partition" in failures[0].message


def test_check_23_passes_on_output_field_partition_when_no_partition_declared() -> None:
    """When no InputSource declares `partition`, the loader doesn't stamp
    a `partition` field, so a Featurization writing to `partition` is fine.
    (Unusual but not contradictory.)
    """
    payload = _ic_base_dict()
    payload["Featurizations"] = [
        {
            "name": "synth_partition",
            "op": "image_size_stats",
            "inputs": ["image"],
            "output_field": "partition",
            "splits": ["train", "val", "test"],
        }
    ]
    assert not _failures_for(validate(_build(payload), _ic_plugin()), 23)


def test_check_23_passes_on_output_field_label_when_labels_kind_is_derived() -> None:
    """When `Labels.source.kind == "derived"`, the loader does NOT stamp
    `label` — the recipe author is expected to derive it via a Featurization.
    So writing `output_field: label` is the intended pattern, not a collision.
    """
    payload = _ic_base_dict()
    payload["Labels"]["source"]["kind"] = "derived"
    payload["Featurizations"] = [
        {
            "name": "derive_label",
            "op": "label_from_path",
            "inputs": ["path"],
            "output_field": "label",
            "splits": ["train", "val", "test"],
        }
    ]
    assert not _failures_for(validate(_build(payload), _ic_plugin()), 23)


# ---------------------------------------------------------------------------
# check 25: Visualization group_by resolves to a known field (G17, Story I.p)
# ---------------------------------------------------------------------------


def test_check_25_passes_when_group_by_names_known_field() -> None:
    ok = _base_dict()
    ok["Visualizations"] = [
        {
            "name": "hist",
            "op": "histogram",
            "stage": "post_pipeline",
            "mode": "reporting",
            "params": {"group_by": "label"},
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 25)


def test_check_25_passes_when_group_by_absent() -> None:
    ok = _base_dict()
    ok["Visualizations"] = [
        {"name": "hist", "op": "histogram", "stage": "post_pipeline", "mode": "reporting"}
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 25)


def test_check_25_fails_when_group_by_unknown_field() -> None:
    bad = _base_dict()
    bad["Visualizations"] = [
        {
            "name": "hist",
            "op": "histogram",
            "stage": "post_pipeline",
            "mode": "reporting",
            "params": {"group_by": "nonexistent_field"},
        }
    ]
    report = validate(_build(bad), _Plugin())
    failures = _failures_for(report, 25)
    assert len(failures) == 1
    assert "nonexistent_field" in failures[0].message


def test_check_25_passes_when_group_by_is_generation_tag_field() -> None:
    ok = _base_dict()
    ok["Output"]["record_schema"]["image"] = {"dtype": "uint8", "shape": [32, 32, 3]}
    ok["Generation"] = [
        {
            "name": "corrupt",
            "op": "corrupt",
            "inputs": ["image"],
            "output_schema": {"image": {"dtype": "uint8", "shape": [32, 32, 3]}},
            "seed": 1,
            "params": {
                "corruption_types": ["fog"],
                "severities": [1],
                "tag_fields": ["corruption", "severity"],
            },
        }
    ]
    ok["Visualizations"] = [
        {
            "name": "hist",
            "op": "histogram",
            "stage": "post_pipeline",
            "mode": "reporting",
            "params": {"group_by": "corruption"},
        }
    ]
    report = validate(_build(ok), _Plugin())
    assert not _failures_for(report, 25)


# ---------------------------------------------------------------------------
# Check 26 — consumer-applied transformations boundary (Story J.g)
# ---------------------------------------------------------------------------

from datarefinery.plugins.image_classification import PLUGIN as _IMAGE_PLUGIN  # noqa: E402


def _image_recipe(
    *,
    transformations: list[dict[str, Any]] | None = None,
    augmentations: list[dict[str, Any]] | None = None,
    sinks: list[dict[str, Any]] | None = None,
) -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 2,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.6, "val": 0.2, "test": 0.2}, "seed": 11},
            "Transformations": transformations or [],
            "Augmentations": augmentations or [],
            "Sinks": sinks or [],
        }
    )


_RESIZE_ALL_SPLITS = {
    "name": "r",
    "op": "resize",
    "params": {"size": 8},
    "splits": ["train", "val", "test"],
}
_IMAGE_SINK_POST_TX = {
    "name": "transformed",
    "stage": "post_Transformations",
    "field": "image",
    "format": "png_per_record",
    "path_template": "transformed/{split}/{record_id}.png",
}


def test_check_26_refuses_pixel_altering_transform_without_sink() -> None:
    recipe = _image_recipe(transformations=[_RESIZE_ALL_SPLITS])
    report = validate(recipe, _IMAGE_PLUGIN)
    failures = _failures_for(report, 26)
    assert len(failures) == 1
    assert "resize" in failures[0].message
    assert "Sinks" in failures[0].message
    assert "val" in failures[0].message and "test" in failures[0].message


def test_check_26_passes_with_qualifying_image_sink() -> None:
    recipe = _image_recipe(transformations=[_RESIZE_ALL_SPLITS], sinks=[_IMAGE_SINK_POST_TX])
    report = validate(recipe, _IMAGE_PLUGIN)
    assert not _failures_for(report, 26)


def test_check_26_passes_for_normalize_only() -> None:
    recipe = _image_recipe(
        transformations=[
            {
                "name": "n",
                "op": "normalize",
                "fit_source": "train",
                "splits": ["train", "val", "test"],
            }
        ]
    )
    report = validate(recipe, _IMAGE_PLUGIN)
    assert not _failures_for(report, 26)


def test_check_26_refuses_on_partial_sink_coverage() -> None:
    sink = {**_IMAGE_SINK_POST_TX, "splits": ["train"]}
    recipe = _image_recipe(transformations=[_RESIZE_ALL_SPLITS], sinks=[sink])
    report = validate(recipe, _IMAGE_PLUGIN)
    failures = _failures_for(report, 26)
    assert len(failures) == 1
    assert "val" in failures[0].message and "test" in failures[0].message
    assert "train" not in failures[0].message.split("splits", 1)[-1]


def test_check_26_passes_when_resize_only_on_aggressive_train() -> None:
    recipe = _image_recipe(
        transformations=[{**_RESIZE_ALL_SPLITS, "splits": ["train"]}],
        augmentations=[
            {
                "name": "flip",
                "op": "horizontal_flip",
                "splits": ["train"],
                "materialization": "aggressive",
            }
        ],
    )
    report = validate(recipe, _IMAGE_PLUGIN)
    assert not _failures_for(report, 26)


# ---------------------------------------------------------------------------
# Check 27 — dtype-altering Transformation + aggressive Augmentation (Story J.i)
# ---------------------------------------------------------------------------


def _normalize(splits: list[str]) -> dict[str, Any]:
    return {"name": "norm", "op": "normalize", "fit_source": "train", "splits": splits}


def _aggressive_flip() -> dict[str, Any]:
    return {
        "name": "flip",
        "op": "horizontal_flip",
        "splits": ["train"],
        "materialization": "aggressive",
        "expansion": 2,
    }


def test_check_27_refuses_normalize_plus_aggressive_same_split() -> None:
    recipe = _image_recipe(
        transformations=[_normalize(["train", "val", "test"])],
        augmentations=[_aggressive_flip()],
    )
    report = validate(recipe, _IMAGE_PLUGIN)
    failures = _failures_for(report, 27)
    assert len(failures) == 1
    assert "normalize" in failures[0].message
    assert "horizontal_flip" in failures[0].message
    assert "train" in failures[0].message


def test_check_27_refuses_mean_subtract_plus_aggressive() -> None:
    recipe = _image_recipe(
        transformations=[
            {"name": "ms", "op": "mean_subtract", "fit_source": "train", "splits": ["train"]}
        ],
        augmentations=[_aggressive_flip()],
    )
    report = validate(recipe, _IMAGE_PLUGIN)
    failures = _failures_for(report, 27)
    assert len(failures) == 1
    assert "mean_subtract" in failures[0].message


def test_check_27_passes_for_resize_plus_aggressive() -> None:
    # resize is pixel-altering but uint8-preserving — it does NOT break the
    # aggressive realizer, so the combination is allowed. (A qualifying image
    # sink is added so check 26 also passes and the recipe is fully valid.)
    recipe = _image_recipe(
        transformations=[{"name": "r", "op": "resize", "params": {"size": 8}, "splits": ["train"]}],
        augmentations=[_aggressive_flip()],
        sinks=[_IMAGE_SINK_POST_TX],
    )
    report = validate(recipe, _IMAGE_PLUGIN)
    assert not _failures_for(report, 27)


def test_check_27_passes_for_normalize_plus_lazy_augmentation() -> None:
    recipe = _image_recipe(
        transformations=[_normalize(["train", "val", "test"])],
        augmentations=[{"name": "flip", "op": "horizontal_flip", "splits": ["train"]}],
    )
    report = validate(recipe, _IMAGE_PLUGIN)
    assert not _failures_for(report, 27)


def test_check_27_passes_for_normalize_only() -> None:
    recipe = _image_recipe(transformations=[_normalize(["train", "val", "test"])])
    report = validate(recipe, _IMAGE_PLUGIN)
    assert not _failures_for(report, 27)


def test_check_27_partial_split_overlap_still_refused() -> None:
    # normalize on train+val, aggressive only on train → train overlap → refuse.
    recipe = _image_recipe(
        transformations=[_normalize(["train", "val"])],
        augmentations=[_aggressive_flip()],
    )
    report = validate(recipe, _IMAGE_PLUGIN)
    failures = _failures_for(report, 27)
    assert len(failures) == 1
    assert "train" in failures[0].message
