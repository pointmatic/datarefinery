# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-23 contracts/expectations evaluation tests (Story C.d).

Each assertion kind has a passing fixture and a failing fixture; severity
handling is exercised separately. The aggregator does not short-circuit -
all declared assertions are evaluated regardless of earlier failures.
"""

from __future__ import annotations

from typing import Any

import pytest

from datarefinery.core.errors import ContractError
from datarefinery.pipeline.contracts import (
    AssertionResult,
    ContractResult,
    evaluate_input_contracts,
    evaluate_output_expectations,
)
from datarefinery.recipe.models import Contract, Expectation


def _records(n: int = 3, **overrides: Any) -> list[dict[str, Any]]:
    base = [{"id": i, "value": float(i) / n, "label": f"c{i % 2}"} for i in range(n)]
    for k, v in overrides.items():
        for r in base:
            r[k] = v
    return base


# ---------------------------------------------------------------------------
# record_count
# ---------------------------------------------------------------------------


def test_record_count_within_bounds_passes() -> None:
    contract = Contract(assertion={"kind": "record_count", "min": 1, "max": 10})
    report = evaluate_input_contracts(_records(3), [contract])
    assert report.passed
    assert report.results[0].passed
    assert "within bounds" in report.results[0].message


def test_record_count_below_min_fails() -> None:
    contract = Contract(assertion={"kind": "record_count", "min": 5})
    report = evaluate_input_contracts(_records(3), [contract])
    assert not report.passed
    assert report.failures[0].kind == "record_count"
    assert "below min" in report.failures[0].message


def test_record_count_above_max_fails() -> None:
    contract = Contract(assertion={"kind": "record_count", "max": 2})
    report = evaluate_input_contracts(_records(5), [contract])
    assert not report.passed
    assert "above max" in report.failures[0].message


def test_record_count_missing_both_bounds_passes_vacuously() -> None:
    contract = Contract(assertion={"kind": "record_count"})
    report = evaluate_input_contracts(_records(3), [contract])
    assert report.passed


# ---------------------------------------------------------------------------
# required_field
# ---------------------------------------------------------------------------


def test_required_field_present_passes() -> None:
    contract = Contract(field="label", assertion={"kind": "required_field"})
    report = evaluate_input_contracts(_records(3), [contract])
    assert report.passed


def test_required_field_missing_fails() -> None:
    records = _records(3)
    del records[1]["label"]
    contract = Contract(field="label", assertion={"kind": "required_field"})
    report = evaluate_input_contracts(records, [contract])
    assert not report.passed
    assert "missing or None" in report.failures[0].message
    assert "label" in report.failures[0].message


def test_required_field_none_value_fails() -> None:
    records = _records(3)
    records[0]["label"] = None
    contract = Contract(field="label", assertion={"kind": "required_field"})
    report = evaluate_input_contracts(records, [contract])
    assert not report.passed


def test_required_field_assertion_without_field_fails() -> None:
    contract = Contract(assertion={"kind": "required_field"})
    report = evaluate_input_contracts(_records(1), [contract])
    assert not report.passed
    assert "needs a 'field'" in report.failures[0].message


# ---------------------------------------------------------------------------
# dtype
# ---------------------------------------------------------------------------


def test_dtype_match_passes() -> None:
    contract = Contract(
        field="value",
        assertion={"kind": "dtype", "expected": "float"},
    )
    report = evaluate_input_contracts(_records(3), [contract])
    assert report.passed


def test_dtype_mismatch_fails() -> None:
    records = _records(3)
    records[1]["value"] = "not a float"
    contract = Contract(
        field="value",
        assertion={"kind": "dtype", "expected": "float"},
    )
    report = evaluate_input_contracts(records, [contract])
    assert not report.passed
    assert "expected dtype 'float'" in report.failures[0].message


def test_dtype_numpy_alias_tolerates_python_int() -> None:
    contract = Contract(
        field="id",
        assertion={"kind": "dtype", "expected": "int32"},
    )
    report = evaluate_input_contracts(_records(3), [contract])
    assert report.passed


def test_dtype_int_rejects_bool() -> None:
    records = _records(3)
    records[0]["id"] = True  # bool subclasses int but should be rejected
    contract = Contract(
        field="id",
        assertion={"kind": "dtype", "expected": "int"},
    )
    report = evaluate_input_contracts(records, [contract])
    assert not report.passed


def test_dtype_unknown_tag_fails() -> None:
    contract = Contract(
        field="id",
        assertion={"kind": "dtype", "expected": "complex128"},
    )
    report = evaluate_input_contracts(_records(1), [contract])
    assert not report.passed
    assert "unknown" in report.failures[0].message


def test_dtype_assertion_without_field_fails() -> None:
    contract = Contract(assertion={"kind": "dtype", "expected": "int"})
    report = evaluate_input_contracts(_records(1), [contract])
    assert not report.passed


# ---------------------------------------------------------------------------
# range
# ---------------------------------------------------------------------------


def test_range_within_bounds_passes() -> None:
    contract = Contract(
        field="value",
        assertion={"kind": "range", "min": 0.0, "max": 1.0},
    )
    report = evaluate_input_contracts(_records(3), [contract])
    assert report.passed


def test_range_below_min_fails() -> None:
    records = _records(3)
    records[0]["value"] = -0.5
    contract = Contract(
        field="value",
        assertion={"kind": "range", "min": 0.0, "max": 1.0},
    )
    report = evaluate_input_contracts(records, [contract])
    assert not report.passed
    assert "outside" in report.failures[0].message


def test_range_above_max_fails() -> None:
    records = _records(3)
    records[2]["value"] = 5.0
    contract = Contract(
        field="value",
        assertion={"kind": "range", "min": 0.0, "max": 1.0},
    )
    report = evaluate_input_contracts(records, [contract])
    assert not report.passed


def test_range_one_sided_min_only() -> None:
    contract = Contract(
        field="value",
        assertion={"kind": "range", "min": 0.0},
    )
    report = evaluate_input_contracts(_records(3), [contract])
    assert report.passed


def test_range_assertion_with_neither_bound_fails() -> None:
    contract = Contract(field="value", assertion={"kind": "range"})
    report = evaluate_input_contracts(_records(1), [contract])
    assert not report.passed
    assert "at least one" in report.failures[0].message


# ---------------------------------------------------------------------------
# distributional placeholder
# ---------------------------------------------------------------------------


def test_distributional_placeholder_always_passes() -> None:
    contract = Contract(
        field="value",
        assertion={"kind": "distributional", "expected_mean": 0.5},
    )
    report = evaluate_input_contracts(_records(3), [contract])
    assert report.passed
    assert "placeholder" in report.results[0].message


# ---------------------------------------------------------------------------
# Severity handling
# ---------------------------------------------------------------------------


def test_warning_severity_failure_does_not_make_report_fail() -> None:
    contract = Contract(
        field="value",
        assertion={"kind": "range", "min": 100.0},
        severity="warning",
    )
    report = evaluate_input_contracts(_records(3), [contract])
    assert report.passed  # warnings do not flip `passed`
    assert len(report.warnings) == 1
    assert len(report.failures) == 0


def test_error_severity_failure_makes_report_fail() -> None:
    contract = Contract(
        field="value",
        assertion={"kind": "range", "min": 100.0},
        severity="error",
    )
    report = evaluate_input_contracts(_records(3), [contract])
    assert not report.passed
    assert len(report.failures) == 1
    assert len(report.warnings) == 0


def test_raise_for_status_raises_on_error_failure() -> None:
    contract = Contract(
        field="value",
        assertion={"kind": "range", "min": 100.0},
        severity="error",
    )
    report = evaluate_input_contracts(_records(3), [contract])
    with pytest.raises(ContractError, match="Contract failures"):
        report.raise_for_status()


def test_raise_for_status_silent_on_warning_only() -> None:
    contract = Contract(
        field="value",
        assertion={"kind": "range", "min": 100.0},
        severity="warning",
    )
    report = evaluate_input_contracts(_records(3), [contract])
    report.raise_for_status()  # must not raise


def test_raise_for_status_silent_when_all_pass() -> None:
    contract = Contract(
        assertion={"kind": "record_count", "min": 1, "max": 10},
    )
    report = evaluate_input_contracts(_records(3), [contract])
    report.raise_for_status()


# ---------------------------------------------------------------------------
# Aggregator behavior
# ---------------------------------------------------------------------------


def test_aggregator_does_not_short_circuit() -> None:
    contracts = [
        Contract(assertion={"kind": "record_count", "min": 999}),  # fail
        Contract(field="value", assertion={"kind": "required_field"}),  # pass
        Contract(
            field="value",
            assertion={"kind": "range", "min": 100.0},
        ),  # fail
    ]
    report = evaluate_input_contracts(_records(3), contracts)
    assert len(report.results) == 3
    assert sum(1 for r in report.results if r.passed) == 1
    assert len(report.failures) == 2


def test_unknown_assertion_kind_fails() -> None:
    contract = Contract(assertion={"kind": "made_up"})
    report = evaluate_input_contracts(_records(1), [contract])
    assert not report.passed
    assert "unknown assertion kind" in report.failures[0].message


def test_assertion_without_kind_fails() -> None:
    contract = Contract(assertion={"min": 0})
    report = evaluate_input_contracts(_records(1), [contract])
    assert not report.passed
    assert "missing string 'kind'" in report.failures[0].message


def test_evaluate_input_contracts_consumes_iterable_once() -> None:
    """Materializing the iterable internally lets multiple assertions traverse
    the same records without callers re-buffering."""

    def gen() -> Any:
        yield {"value": 0.5}
        yield {"value": 0.7}

    contracts = [
        Contract(assertion={"kind": "record_count", "min": 2}),
        Contract(
            field="value",
            assertion={"kind": "range", "min": 0.0, "max": 1.0},
        ),
    ]
    report = evaluate_input_contracts(gen(), contracts)
    assert report.passed
    assert len(report.results) == 2


def test_empty_contract_list_returns_empty_report() -> None:
    report = evaluate_input_contracts(_records(3), [])
    assert report.passed
    assert report.results == ()


# ---------------------------------------------------------------------------
# evaluate_output_expectations
# ---------------------------------------------------------------------------


def test_output_expectations_evaluates_same_assertion_kinds() -> None:
    expectations = [
        Expectation(assertion={"kind": "record_count", "min": 1}),
        Expectation(
            field="value",
            assertion={"kind": "range", "min": 0.0, "max": 1.0},
        ),
    ]
    report = evaluate_output_expectations(_records(3), expectations)
    assert report.passed
    assert len(report.results) == 2


def test_output_expectations_failure_raises_via_status() -> None:
    expectations = [
        Expectation(assertion={"kind": "record_count", "min": 999}),
    ]
    report = evaluate_output_expectations(_records(3), expectations)
    with pytest.raises(ContractError):
        report.raise_for_status()


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


def test_assertion_result_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    r = AssertionResult(kind="dtype", field="x", passed=True, severity="error", message="ok")
    with pytest.raises(FrozenInstanceError):
        r.passed = False  # type: ignore[misc]


def test_contract_result_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    cr = ContractResult(results=())
    with pytest.raises(FrozenInstanceError):
        cr.results = (None,)  # type: ignore[misc, assignment]


# ---------------------------------------------------------------------------
# G8 (dependency-gaps-v0.16.0.md): ndarray field handling
#
# The image_classification plugin produces records whose `image` field is a
# numpy ndarray. The `Output.record_schema` permits tensor-shaped fields
# (`shape: [H, W, C]`). The contracts evaluators should accept these fields
# in `dtype` and `range` assertions — today they don't, in two distinct ways.
# ---------------------------------------------------------------------------


def test_g8_dtype_on_uint8_ndarray_field_passes() -> None:
    """`dtype: uint8` on a tensor field should accept a uint8 ndarray.

    Today: fails for every record because `_eval_dtype` uses
    `isinstance(v, int)` where `accepted = _PY_DTYPE_TAGS["uint8"] = (int,)`;
    a numpy ndarray is not an int.
    """
    import numpy as np

    records: list[dict[str, Any]] = [
        {"id": i, "image": np.zeros((4, 4, 3), dtype=np.uint8)} for i in range(3)
    ]
    contract = Contract(
        field="image",
        assertion={"kind": "dtype", "expected": "uint8"},
    )
    report = evaluate_input_contracts(records, [contract])
    assert report.passed, (
        f"expected pass on uint8 ndarrays, got failure: {report.results[0].message}"
    )


def test_g8_dtype_on_float32_ndarray_field_passes() -> None:
    """`dtype: float32` on a tensor field should accept a float32 ndarray.

    Today: fails — `isinstance(arr, (float, int))` is False for ndarrays.
    """
    import numpy as np

    records: list[dict[str, Any]] = [
        {"id": i, "image": np.zeros((4, 4, 3), dtype=np.float32)} for i in range(3)
    ]
    contract = Contract(
        field="image",
        assertion={"kind": "dtype", "expected": "float32"},
    )
    report = evaluate_input_contracts(records, [contract])
    assert report.passed, report.results[0].message


def test_g8_dtype_on_wrong_ndarray_dtype_fails_with_clear_message() -> None:
    """`dtype: uint8` on a float64 ndarray field should fail with a clear
    message identifying the actual ndarray dtype, not Python's `ndarray`
    class name.
    """
    import numpy as np

    records: list[dict[str, Any]] = [
        {"id": i, "image": np.zeros((4, 4, 3), dtype=np.float64)} for i in range(3)
    ]
    contract = Contract(
        field="image",
        assertion={"kind": "dtype", "expected": "uint8"},
    )
    report = evaluate_input_contracts(records, [contract])
    assert not report.passed
    msg = report.failures[0].message
    assert "float64" in msg, f"expected message to identify ndarray dtype 'float64', got: {msg!r}"


def test_g8_range_on_tensor_field_does_not_raise() -> None:
    """`range` on a tensor field should not raise. Today: raises
    ``ValueError: The truth value of an array with more than one element
    is ambiguous`` from the ``v < lo`` comparison producing an
    element-wise boolean array.

    The evaluator should treat ndarrays as bulk numeric values: pass when
    all elements are within bounds, fail when any element is outside.
    """
    import numpy as np

    records: list[dict[str, Any]] = [
        {"id": i, "image": np.full((4, 4, 3), 0.5, dtype=np.float32)} for i in range(3)
    ]
    contract = Contract(
        field="image",
        assertion={"kind": "range", "min": 0.0, "max": 1.0},
    )
    # Today this raises ValueError inside the evaluator. After the fix the
    # report passes (all values are in [0, 1]).
    report = evaluate_input_contracts(records, [contract])
    assert report.passed, report.results[0].message


def test_g8_range_on_tensor_field_detects_out_of_bounds() -> None:
    """`range` on a tensor field should fail when any element is outside
    the declared bounds.
    """
    import numpy as np

    bad = np.full((4, 4, 3), 0.5, dtype=np.float32)
    bad[0, 0, 0] = 5.0
    records: list[dict[str, Any]] = [
        {"id": 0, "image": np.full((4, 4, 3), 0.5, dtype=np.float32)},
        {"id": 1, "image": bad},
    ]
    contract = Contract(
        field="image",
        assertion={"kind": "range", "min": 0.0, "max": 1.0},
    )
    report = evaluate_input_contracts(records, [contract])
    assert not report.passed
    msg = report.failures[0].message
    assert "5.0" in msg or "5" in msg, f"expected message to cite the bad value, got: {msg!r}"


# ---------------------------------------------------------------------------
# G6 + G16b (Story I.o): per-split / per-class / structural assertion kinds
# ---------------------------------------------------------------------------


def _split_map(
    train: int = 0, val: int = 0, test: int = 0, *, classes: int = 2
) -> dict[str, list[dict[str, Any]]]:
    def _mk(n: int, prefix: str) -> list[dict[str, Any]]:
        return [
            {"id": f"{prefix}_{i}", "label": f"c{i % classes}", "value": float(i)} for i in range(n)
        ]

    out: dict[str, list[dict[str, Any]]] = {}
    if train:
        out["train"] = _mk(train, "tr")
    if val:
        out["val"] = _mk(val, "va")
    if test:
        out["test"] = _mk(test, "te")
    return out


# --- signature widening / backward compatibility ---------------------------


def test_output_expectations_accepts_split_mapping() -> None:
    splits = _split_map(train=6, val=2, test=2)
    expectations = [Expectation(assertion={"kind": "record_count", "min": 1})]
    report = evaluate_output_expectations(splits, expectations)
    assert report.passed


def test_output_expectations_flat_iterable_still_supported() -> None:
    # Backward compatibility: a flat list routes as a single implicit split.
    expectations = [Expectation(assertion={"kind": "record_count", "min": 1})]
    report = evaluate_output_expectations(_records(3), expectations)
    assert report.passed


# --- split_record_counts ----------------------------------------------------


def test_split_record_counts_passes_when_counts_match() -> None:
    splits = _split_map(train=6, val=2, test=2)
    exp = Expectation(
        assertion={"kind": "split_record_counts", "counts": {"train": 6, "val": 2, "test": 2}}
    )
    report = evaluate_output_expectations(splits, [exp])
    assert report.passed, report.results[0].message


def test_split_record_counts_fails_with_precise_diff_message() -> None:
    splits = _split_map(train=6, val=3, test=2)
    exp = Expectation(
        assertion={"kind": "split_record_counts", "counts": {"train": 6, "val": 2, "test": 2}}
    )
    report = evaluate_output_expectations(splits, [exp])
    assert not report.passed
    msg = report.failures[0].message
    assert "val" in msg and "expected 2" in msg and "got 3" in msg, msg


def test_split_record_counts_fails_when_named_split_absent() -> None:
    splits = _split_map(train=6, val=2)
    exp = Expectation(
        assertion={"kind": "split_record_counts", "counts": {"train": 6, "val": 2, "test": 2}}
    )
    report = evaluate_output_expectations(splits, [exp])
    assert not report.passed
    assert "test" in report.failures[0].message


def test_split_record_counts_in_input_contracts_fails_without_split_context() -> None:
    contract = Contract(assertion={"kind": "split_record_counts", "counts": {"train": 3}})
    report = evaluate_input_contracts(_records(3), [contract])
    assert not report.passed
    assert "per-split" in report.failures[0].message


# --- per_class_count_per_split ----------------------------------------------


def test_per_class_count_per_split_passes_with_exact_counts() -> None:
    splits = _split_map(train=6, val=2, classes=2)  # 3 per class in train, 1 in val
    exp = Expectation(
        field="label",
        assertion={"kind": "per_class_count_per_split", "per_class": 3, "tolerance": 0},
    )
    report = evaluate_output_expectations({"train": splits["train"]}, [exp])
    assert report.passed, report.results[0].message


def test_per_class_count_per_split_tolerates_rounding_by_default() -> None:
    # train: c0 appears 4 times, c1 appears 3 times (7 records). per_class=3,
    # default tolerance 1 → both within [2, 4], passes.
    train = [{"id": i, "label": f"c{i % 2}"} for i in range(7)]
    exp = Expectation(
        field="label",
        assertion={"kind": "per_class_count_per_split", "per_class": 3},
    )
    report = evaluate_output_expectations({"train": train}, [exp])
    assert report.passed, report.results[0].message


def test_per_class_count_per_split_fails_outside_tolerance() -> None:
    # c0 appears 5 times, c1 once; per_class=3 tolerance=1 → c1 (1) is outside.
    train = [{"id": i, "label": "c0" if i < 5 else "c1"} for i in range(6)]
    exp = Expectation(
        field="label",
        assertion={"kind": "per_class_count_per_split", "per_class": 3, "tolerance": 1},
    )
    report = evaluate_output_expectations({"train": train}, [exp])
    assert not report.passed
    msg = report.failures[0].message
    assert "train" in msg and "c1" in msg


# --- count_by_field ---------------------------------------------------------


def test_count_by_field_passes_when_every_key_has_expected_count() -> None:
    records = [{"id": i, "label": f"c{i % 3}"} for i in range(9)]  # 3 each
    exp = Expectation(field="label", assertion={"kind": "count_by_field", "value_per_key": 3})
    report = evaluate_output_expectations({"train": records}, [exp])
    assert report.passed, report.results[0].message


def test_count_by_field_fails_naming_offending_key() -> None:
    records = [{"id": i, "label": "c0" if i < 4 else "c1"} for i in range(6)]  # c0=4, c1=2
    exp = Expectation(field="label", assertion={"kind": "count_by_field", "value_per_key": 3})
    report = evaluate_output_expectations({"train": records}, [exp])
    assert not report.passed
    msg = report.failures[0].message
    assert "c0" in msg or "c1" in msg


# --- count_by_fields --------------------------------------------------------


def test_count_by_fields_passes_per_combination() -> None:
    records = []
    for corruption in ("blur", "noise"):
        for sev in (1, 3):
            for i in range(2):
                records.append({"id": i, "corruption": corruption, "severity": sev})
    exp = Expectation(
        assertion={
            "kind": "count_by_fields",
            "fields": ["corruption", "severity"],
            "value_per_combination": 2,
        }
    )
    report = evaluate_output_expectations({"test": records}, [exp])
    assert report.passed, report.results[0].message


def test_count_by_fields_fails_on_wrong_combination_count() -> None:
    records = [
        {"corruption": "blur", "severity": 1},
        {"corruption": "blur", "severity": 1},
        {"corruption": "noise", "severity": 1},  # only 1
    ]
    exp = Expectation(
        assertion={
            "kind": "count_by_fields",
            "fields": ["corruption", "severity"],
            "value_per_combination": 2,
        }
    )
    report = evaluate_output_expectations({"test": records}, [exp])
    assert not report.passed


# --- shape_equals -----------------------------------------------------------


def test_shape_equals_passes_for_matching_ndarray_shape() -> None:
    import numpy as np

    records = [{"id": i, "image": np.zeros((4, 4, 3), dtype=np.uint8)} for i in range(3)]
    exp = Expectation(field="image", assertion={"kind": "shape_equals", "value": [4, 4, 3]})
    report = evaluate_output_expectations({"train": records}, [exp])
    assert report.passed, report.results[0].message


def test_shape_equals_fails_on_mismatched_shape() -> None:
    import numpy as np

    records = [
        {"id": 0, "image": np.zeros((4, 4, 3), dtype=np.uint8)},
        {"id": 1, "image": np.zeros((8, 8, 3), dtype=np.uint8)},
    ]
    exp = Expectation(field="image", assertion={"kind": "shape_equals", "value": [4, 4, 3]})
    report = evaluate_output_expectations({"train": records}, [exp])
    assert not report.passed
    assert "8" in report.failures[0].message


def test_shape_equals_fails_on_non_ndarray() -> None:
    records = [{"id": 0, "image": [1, 2, 3]}]
    exp = Expectation(field="image", assertion={"kind": "shape_equals", "value": [3]})
    report = evaluate_output_expectations({"train": records}, [exp])
    assert not report.passed


# --- value_in_set -----------------------------------------------------------


def test_value_in_set_passes_when_all_values_in_set() -> None:
    records = [{"id": i, "label": f"c{i % 2}"} for i in range(4)]
    exp = Expectation(field="label", assertion={"kind": "value_in_set", "value": ["c0", "c1"]})
    report = evaluate_output_expectations({"train": records}, [exp])
    assert report.passed, report.results[0].message


def test_value_in_set_fails_naming_offending_value() -> None:
    records = [{"id": 0, "label": "c0"}, {"id": 1, "label": "rogue"}]
    exp = Expectation(field="label", assertion={"kind": "value_in_set", "value": ["c0", "c1"]})
    report = evaluate_output_expectations({"train": records}, [exp])
    assert not report.passed
    assert "rogue" in report.failures[0].message


# --- per_class_count_equals -------------------------------------------------


def test_per_class_count_equals_passes_when_every_class_matches() -> None:
    records = [{"id": i, "label": f"c{i % 2}"} for i in range(6)]  # 3 each
    exp = Expectation(field="label", assertion={"kind": "per_class_count_equals", "value": 3})
    report = evaluate_output_expectations({"train": records}, [exp])
    assert report.passed, report.results[0].message


def test_per_class_count_equals_fails_with_precise_message() -> None:
    records = [{"id": i, "label": "c0" if i < 4 else "c1"} for i in range(6)]  # c0=4, c1=2
    exp = Expectation(field="label", assertion={"kind": "per_class_count_equals", "value": 3})
    report = evaluate_output_expectations({"train": records}, [exp])
    assert not report.passed
    msg = report.failures[0].message
    assert ("c0" in msg and "4" in msg) or ("c1" in msg and "2" in msg)


def test_all_seven_new_kinds_pass_together_on_a_canonical_fixture() -> None:
    """Integration-style: a single OutputExpectations block declaring all
    seven new kinds passes against a consistent split-keyed fixture.
    """
    import numpy as np

    def _mk(n: int, prefix: str) -> list[dict[str, Any]]:
        return [
            {
                "id": f"{prefix}_{i}",
                "label": f"c{i % 2}",
                "image": np.zeros((4, 4, 3), dtype=np.uint8),
                "corruption": "blur",
                "severity": 1,
            }
            for i in range(n)
        ]

    splits = {"train": _mk(4, "tr"), "val": _mk(2, "va")}
    expectations = [
        Expectation(assertion={"kind": "split_record_counts", "counts": {"train": 4, "val": 2}}),
        Expectation(
            field="label",
            severity="warning",
            assertion={"kind": "per_class_count_per_split", "per_class": 2, "tolerance": 1},
        ),
        Expectation(field="label", assertion={"kind": "count_by_field", "value_per_key": 3}),
        Expectation(
            assertion={
                "kind": "count_by_fields",
                "fields": ["corruption", "severity"],
                "value_per_combination": 6,
            }
        ),
        Expectation(field="image", assertion={"kind": "shape_equals", "value": [4, 4, 3]}),
        Expectation(field="label", assertion={"kind": "value_in_set", "value": ["c0", "c1"]}),
        Expectation(field="label", assertion={"kind": "per_class_count_equals", "value": 3}),
    ]
    report = evaluate_output_expectations(splits, expectations)
    assert report.passed, [r.message for r in report.results if not r.passed]
    assert len(report.results) == 7


def test_mutating_split_ratio_produces_precise_failure() -> None:
    splits = _split_map(train=5, val=2)  # train should be 6
    exp = Expectation(assertion={"kind": "split_record_counts", "counts": {"train": 6, "val": 2}})
    report = evaluate_output_expectations(splits, [exp])
    assert not report.passed
    assert "train" in report.failures[0].message and "got 5" in report.failures[0].message
