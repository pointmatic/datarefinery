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
    base = [
        {"id": i, "value": float(i) / n, "label": f"c{i % 2}"}
        for i in range(n)
    ]
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

    r = AssertionResult(
        kind="dtype", field="x", passed=True, severity="error", message="ok"
    )
    with pytest.raises(FrozenInstanceError):
        r.passed = False  # type: ignore[misc]


def test_contract_result_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    cr = ContractResult(results=())
    with pytest.raises(FrozenInstanceError):
        cr.results = (None,)  # type: ignore[misc, assignment]
