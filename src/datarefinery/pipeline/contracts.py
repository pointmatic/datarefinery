# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-23 pipeline contracts: InputContracts and OutputExpectations evaluation.

Assertion kinds supported in v1:

- ``record_count``     dataset-level record count bounds (``min``, ``max``)
- ``required_field``   every record contains the field (non-None)
- ``dtype``            every value of the field matches a Python type tag
- ``range``            every value of the field lies in ``[min, max]``
- ``distributional``   placeholder (always passes in v1; full machinery is
                       post-v1; see features.md FR-23 edge cases)

Evaluators return a :class:`ContractResult` listing one
:class:`AssertionResult` per declared contract. The runner calls
``result.raise_for_status()`` to abort materialization on any
``error``-severity failure; ``warning``-severity failures are recorded but
do not raise. The runner's call site decides whether to surface warnings
to the user.

The structural ``Output`` contract (record shape / field names / dtypes)
lives in the recipe's ``Output`` section per FR-23 #3 and is enforced by
plugin operations and validator check 14, not here. ``OutputExpectations``
are peers of ``Output`` and complement it with value-level assertions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from datarefinery.core.errors import ContractError
from datarefinery.recipe.models import Contract, Expectation, Severity

Record = Mapping[str, Any]


@dataclass(frozen=True)
class AssertionResult:
    """Outcome of evaluating one declared contract or expectation."""

    kind: str
    field: str | None
    passed: bool
    severity: Severity
    message: str


@dataclass(frozen=True)
class ContractResult:
    """Aggregated results of a contracts/expectations evaluation pass."""

    results: tuple[AssertionResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.passed or r.severity == "warning" for r in self.results)

    @property
    def failures(self) -> tuple[AssertionResult, ...]:
        return tuple(r for r in self.results if not r.passed and r.severity == "error")

    @property
    def warnings(self) -> tuple[AssertionResult, ...]:
        return tuple(r for r in self.results if not r.passed and r.severity == "warning")

    def raise_for_status(self) -> None:
        """Raise :class:`ContractError` if any error-severity failure exists."""
        if not self.failures:
            return
        lines = [f"  - [{r.kind}] field={r.field!r}: {r.message}" for r in self.failures]
        raise ContractError("Contract failures (error severity):\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# Per-kind evaluators
# ---------------------------------------------------------------------------


_PY_DTYPE_TAGS: dict[str, tuple[type, ...]] = {
    "int": (int,),
    "float": (float, int),  # int is a valid float in Python's tower
    "bool": (bool,),
    "str": (str,),
    "bytes": (bytes,),
    # Numpy-like aliases tolerated for recipes authored against Output schemas:
    "int8": (int,),
    "int16": (int,),
    "int32": (int,),
    "int64": (int,),
    "uint8": (int,),
    "uint16": (int,),
    "uint32": (int,),
    "uint64": (int,),
    "float16": (float, int),
    "float32": (float, int),
    "float64": (float, int),
}


def _eval_record_count(
    records: list[Record],
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    n = len(records)
    lo = assertion.get("min")
    hi = assertion.get("max")
    if lo is not None and n < lo:
        return False, f"record count {n} below min {lo}"
    if hi is not None and n > hi:
        return False, f"record count {n} above max {hi}"
    return True, f"record count {n} within bounds (min={lo}, max={hi})"


def _eval_required_field(
    records: list[Record],
    field: str,
) -> tuple[bool, str]:
    missing = [i for i, r in enumerate(records) if field not in r or r[field] is None]
    if missing:
        sample = missing[:3]
        more = "" if len(missing) <= 3 else f" (+{len(missing) - 3} more)"
        return False, (
            f"required field {field!r} missing or None in "
            f"{len(missing)} records at indices {sample}{more}"
        )
    return True, f"required field {field!r} present in all {len(records)} records"


def _eval_dtype(
    records: list[Record],
    field: str,
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    expected = assertion.get("expected")
    if not isinstance(expected, str):
        return False, (f"dtype assertion missing string 'expected' (got {type(expected).__name__})")
    accepted = _PY_DTYPE_TAGS.get(expected)
    if accepted is None:
        return False, f"dtype assertion expected tag {expected!r} unknown"
    # `bool` is a subclass of `int` in Python; for `int` checks we want to
    # reject bools since callers writing `dtype: int` mean numeric ints.
    reject_bool = expected.startswith(("int", "uint", "float"))
    bad: list[tuple[int, type]] = []
    for i, r in enumerate(records):
        v = r.get(field)
        if v is None:
            continue  # required-field check is a separate concern
        if reject_bool and isinstance(v, bool):
            bad.append((i, type(v)))
            continue
        if not isinstance(v, accepted):
            bad.append((i, type(v)))
    if bad:
        i, t = bad[0]
        more = "" if len(bad) == 1 else f" (+{len(bad) - 1} more)"
        return False, (
            f"field {field!r} expected dtype {expected!r}; got {t.__name__} at record {i}{more}"
        )
    return True, f"field {field!r} dtype matches {expected!r} in all records"


def _eval_range(
    records: list[Record],
    field: str,
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    lo = assertion.get("min")
    hi = assertion.get("max")
    if lo is None and hi is None:
        return False, "range assertion needs at least one of 'min'/'max'"
    bad: list[tuple[int, Any]] = []
    for i, r in enumerate(records):
        v = r.get(field)
        if v is None:
            continue
        if lo is not None and v < lo:
            bad.append((i, v))
            continue
        if hi is not None and v > hi:
            bad.append((i, v))
    if bad:
        i, v = bad[0]
        more = "" if len(bad) == 1 else f" (+{len(bad) - 1} more)"
        return False, (f"field {field!r} value {v!r} at record {i} outside [{lo}, {hi}]{more}")
    return True, f"field {field!r} all values within [{lo}, {hi}]"


def _eval_distributional(
    records: list[Record],
    field: str | None,
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    # v1 placeholder per features.md FR-23 edge cases. The distributional
    # machinery (KS-test, chi-squared, JSD, etc.) lands post-v1; for now,
    # this kind always passes with a documented "deferred" note so recipes
    # that declare it remain materializable.
    del records, field, assertion
    return True, "distributional check is a v1 placeholder; always passes"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _evaluate_one(
    records: list[Record],
    contract: Contract | Expectation,
) -> AssertionResult:
    assertion = contract.assertion
    kind = assertion.get("kind")
    field = contract.field
    severity = contract.severity

    if not isinstance(kind, str):
        return AssertionResult(
            kind=str(kind),
            field=field,
            passed=False,
            severity=severity,
            message=(f"assertion missing string 'kind' (got {type(kind).__name__})"),
        )

    try:
        if kind == "record_count":
            ok, msg = _eval_record_count(records, assertion)
        elif kind == "required_field":
            if field is None:
                return AssertionResult(
                    kind,
                    None,
                    False,
                    severity,
                    "required_field assertion needs a 'field'",
                )
            ok, msg = _eval_required_field(records, field)
        elif kind == "dtype":
            if field is None:
                return AssertionResult(
                    kind,
                    None,
                    False,
                    severity,
                    "dtype assertion needs a 'field'",
                )
            ok, msg = _eval_dtype(records, field, assertion)
        elif kind == "range":
            if field is None:
                return AssertionResult(
                    kind,
                    None,
                    False,
                    severity,
                    "range assertion needs a 'field'",
                )
            ok, msg = _eval_range(records, field, assertion)
        elif kind == "distributional":
            ok, msg = _eval_distributional(records, field, assertion)
        else:
            ok, msg = False, f"unknown assertion kind {kind!r}"
    except (TypeError, ValueError) as exc:
        ok, msg = False, f"evaluator raised {type(exc).__name__}: {exc}"

    return AssertionResult(kind=kind, field=field, passed=ok, severity=severity, message=msg)


def _evaluate_all(
    records: Iterable[Record],
    contracts: list[Contract] | list[Expectation],
) -> ContractResult:
    materialized = list(records)
    results = tuple(_evaluate_one(materialized, c) for c in contracts)
    return ContractResult(results=results)


def evaluate_input_contracts(
    records: Iterable[Record],
    contracts: list[Contract],
) -> ContractResult:
    """Evaluate ``InputContracts`` against the raw input record stream.

    Materializes the iterable once internally so multiple assertions can
    traverse the same records without callers re-buffering.
    """
    return _evaluate_all(records, contracts)


def evaluate_output_expectations(
    dataset: Iterable[Record],
    expectations: list[Expectation],
) -> ContractResult:
    """Evaluate ``OutputExpectations`` against the materialized dataset.

    The dataset is presented as a flat record iterable in v1; per-split
    expectations are not yet expressible (deferred to a post-v1 expectation
    extension).
    """
    return _evaluate_all(dataset, expectations)
