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

import numpy as np

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
    *,
    skip_missing_field: bool = False,
) -> tuple[bool, str]:
    """``required_field`` evaluator.

    When ``skip_missing_field`` is True, records that lack the field
    entirely are ignored rather than counted as failures; records where
    the field is present but ``None`` still fail. Used by
    ``OutputExpectations`` against the label field when unlabeled
    partitions are present (records from unlabeled sources legitimately
    omit the label key).
    """
    if skip_missing_field:
        considered = [r for r in records if field in r]
        bad = [i for i, r in enumerate(considered) if r[field] is None]
        if bad:
            sample = bad[:3]
            more = "" if len(bad) <= 3 else f" (+{len(bad) - 3} more)"
            return False, (
                f"required field {field!r} is None in "
                f"{len(bad)} of {len(considered)} labeled records at indices "
                f"{sample}{more}"
            )
        skipped = len(records) - len(considered)
        suffix = f"; {skipped} unlabeled record(s) skipped" if skipped else ""
        return True, (
            f"required field {field!r} present in all {len(considered)} labeled records{suffix}"
        )
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
    bad: list[tuple[int, str]] = []
    for i, r in enumerate(records):
        v = r.get(field)
        if v is None:
            continue  # required-field check is a separate concern
        # ndarray branch: compare against the array's own dtype name (e.g.,
        # 'uint8', 'float32'). Tensor-shaped fields (image arrays, embeddings)
        # never match the scalar `isinstance` branch below.
        if isinstance(v, np.ndarray):
            if v.dtype.name != expected:
                bad.append((i, v.dtype.name))
            continue
        if reject_bool and isinstance(v, bool):
            bad.append((i, type(v).__name__))
            continue
        if not isinstance(v, accepted):
            bad.append((i, type(v).__name__))
    if bad:
        i, t = bad[0]
        more = "" if len(bad) == 1 else f" (+{len(bad) - 1} more)"
        return False, (f"field {field!r} expected dtype {expected!r}; got {t} at record {i}{more}")
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
        # ndarray branch: reduce over the array. The contract semantic
        # "every value of `field` is in [lo, hi]" extends naturally to
        # tensor fields as "every element of the tensor is in [lo, hi]";
        # min/max are sufficient witnesses.
        if isinstance(v, np.ndarray):
            v_min = float(v.min())
            v_max = float(v.max())
            if lo is not None and v_min < lo:
                bad.append((i, v_min))
                continue
            if hi is not None and v_max > hi:
                bad.append((i, v_max))
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
    *,
    skip_missing_label_field: str | None = None,
) -> AssertionResult:
    assertion = contract.assertion
    kind = assertion.get("kind")
    field = contract.field
    severity = contract.severity
    skip_missing = skip_missing_label_field is not None and field == skip_missing_label_field

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
            ok, msg = _eval_required_field(records, field, skip_missing_field=skip_missing)
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
    *,
    skip_missing_label_field: str | None = None,
) -> ContractResult:
    materialized = list(records)
    results = tuple(
        _evaluate_one(materialized, c, skip_missing_label_field=skip_missing_label_field)
        for c in contracts
    )
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
    *,
    skip_missing_label_field: str | None = None,
) -> ContractResult:
    """Evaluate ``OutputExpectations`` against the materialized dataset.

    The dataset is presented as a flat record iterable in v1; per-split
    expectations are not yet expressible (deferred to a post-v1 expectation
    extension).

    When ``skip_missing_label_field`` is set (the recipe's ``Labels.field``
    name when any source declares ``unlabeled: true``), expectations whose
    ``field`` equals that name treat records that lack the field as
    "skipped" rather than failures. Records where the field is present
    but ``None`` still fail. This lets a recipe that mixes labeled and
    unlabeled partitions declare ``required_field: <label>`` without
    being rejected for the unlabeled partition's missing labels.
    """
    return _evaluate_all(dataset, expectations, skip_missing_label_field=skip_missing_label_field)
