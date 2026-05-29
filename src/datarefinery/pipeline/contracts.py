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

Per-split / per-class / structural kinds (G6 + G16b, Story I.o; valid in
``OutputExpectations`` only — they require the per-split structure):

- ``split_record_counts``        per-split record-count equality
                                 (``counts: {<split>: <int>, …}``)
- ``per_class_count_per_split``  per-split per-class count within a
                                 rounding tolerance (``field``,
                                 ``per_class``, optional ``tolerance``=1)
- ``count_by_field``             every distinct value of ``field`` has
                                 ``value_per_key`` records (flat)
- ``count_by_fields``            every distinct combination of ``fields``
                                 has ``value_per_combination`` records (flat)
- ``shape_equals``               every record's ``field`` is an ndarray
                                 whose shape equals ``value`` (flat)
- ``value_in_set``               every record's ``field`` value is in the
                                 ``value`` set (flat)
- ``per_class_count_equals``     every distinct value of ``field`` has
                                 exactly ``value`` records (single-split, flat)

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

from collections.abc import Iterable, Mapping, Sequence
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


def _eval_split_record_counts(
    splits: Mapping[str, list[Record]],
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    counts = assertion.get("counts")
    if not isinstance(counts, Mapping):
        return False, "split_record_counts assertion needs a 'counts' mapping"
    bad: list[str] = []
    for split_name, expected in counts.items():
        if split_name not in splits:
            bad.append(f"split {split_name!r} absent (expected {expected})")
            continue
        actual = len(splits[split_name])
        if actual != expected:
            bad.append(f"split {split_name!r} expected {expected}, got {actual}")
    if bad:
        return False, "; ".join(bad)
    return True, f"split record counts match {dict(counts)!r}"


def _eval_per_class_count_per_split(
    splits: Mapping[str, list[Record]],
    field: str,
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    per_class = assertion.get("per_class")
    if not isinstance(per_class, int):
        return False, "per_class_count_per_split assertion needs an integer 'per_class'"
    tolerance = assertion.get("tolerance", 1)
    if not isinstance(tolerance, int) or tolerance < 0:
        return False, "per_class_count_per_split 'tolerance' must be a non-negative int"
    bad: list[str] = []
    for split_name, recs in splits.items():
        counts: dict[Any, int] = {}
        for r in recs:
            counts[r.get(field)] = counts.get(r.get(field), 0) + 1
        for cls, n in sorted(counts.items(), key=lambda kv: str(kv[0])):
            if abs(n - per_class) > tolerance:
                bad.append(
                    f"split {split_name!r} class {cls!r} expected {per_class}±{tolerance}, got {n}"
                )
    if bad:
        return False, "; ".join(bad)
    return True, f"per-class counts within {per_class}±{tolerance} for every split"


def _eval_count_by_field(
    records: list[Record],
    field: str,
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    expected = assertion.get("value_per_key")
    if not isinstance(expected, int):
        return False, "count_by_field assertion needs an integer 'value_per_key'"
    counts: dict[Any, int] = {}
    for r in records:
        counts[r.get(field)] = counts.get(r.get(field), 0) + 1
    bad = [
        f"{key!r}={n}"
        for key, n in sorted(counts.items(), key=lambda kv: str(kv[0]))
        if n != expected
    ]
    if bad:
        return False, f"field {field!r} expected {expected} per key; got " + ", ".join(bad)
    return True, f"field {field!r} has {expected} records for every key"


def _eval_count_by_fields(
    records: list[Record],
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    fields = assertion.get("fields")
    if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
        return False, "count_by_fields assertion needs a 'fields' list of strings"
    expected = assertion.get("value_per_combination")
    if not isinstance(expected, int):
        return False, "count_by_fields assertion needs an integer 'value_per_combination'"
    counts: dict[tuple[Any, ...], int] = {}
    for r in records:
        key = tuple(r.get(f) for f in fields)
        counts[key] = counts.get(key, 0) + 1
    bad = [
        f"{combo!r}={n}"
        for combo, n in sorted(counts.items(), key=lambda kv: str(kv[0]))
        if n != expected
    ]
    if bad:
        return False, (
            f"fields {fields!r} expected {expected} per combination; got " + ", ".join(bad)
        )
    return True, f"fields {fields!r} have {expected} records for every combination"


def _eval_shape_equals(
    records: list[Record],
    field: str,
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    value = assertion.get("value")
    if not isinstance(value, list):
        return False, "shape_equals assertion needs a 'value' list of dimensions"
    expected_shape = tuple(value)
    bad: list[tuple[int, Any]] = []
    for i, r in enumerate(records):
        v = r.get(field)
        if not isinstance(v, np.ndarray):
            bad.append((i, type(v).__name__))
            continue
        if v.shape != expected_shape:
            bad.append((i, v.shape))
    if bad:
        i, got = bad[0]
        more = "" if len(bad) == 1 else f" (+{len(bad) - 1} more)"
        return False, (
            f"field {field!r} expected shape {list(expected_shape)}; got {got} at record {i}{more}"
        )
    return True, f"field {field!r} shape matches {list(expected_shape)} in all records"


def _eval_value_in_set(
    records: list[Record],
    field: str,
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    value = assertion.get("value")
    if not isinstance(value, list):
        return False, "value_in_set assertion needs a 'value' list of allowed values"
    allowed = set(value)
    bad: list[tuple[int, Any]] = []
    for i, r in enumerate(records):
        v = r.get(field)
        if v is None:
            continue
        if v not in allowed:
            bad.append((i, v))
    if bad:
        i, v = bad[0]
        more = "" if len(bad) == 1 else f" (+{len(bad) - 1} more)"
        return False, (f"field {field!r} value {v!r} at record {i} not in {value!r}{more}")
    return True, f"field {field!r} all values in {value!r}"


def _eval_per_class_count_equals(
    records: list[Record],
    field: str,
    assertion: Mapping[str, Any],
) -> tuple[bool, str]:
    expected = assertion.get("value")
    if not isinstance(expected, int):
        return False, "per_class_count_equals assertion needs an integer 'value'"
    counts: dict[Any, int] = {}
    for r in records:
        counts[r.get(field)] = counts.get(r.get(field), 0) + 1
    bad = [
        f"{cls!r}={n}"
        for cls, n in sorted(counts.items(), key=lambda kv: str(kv[0]))
        if n != expected
    ]
    if bad:
        return False, f"field {field!r} expected {expected} per class; got " + ", ".join(bad)
    return True, f"field {field!r} has exactly {expected} records per class"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_PER_SPLIT_KINDS = frozenset({"split_record_counts", "per_class_count_per_split"})


def _evaluate_one(
    records: list[Record],
    contract: Contract | Expectation,
    *,
    splits: Mapping[str, list[Record]] | None = None,
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

    if kind in _PER_SPLIT_KINDS and splits is None:
        return AssertionResult(
            kind,
            field,
            False,
            severity,
            f"{kind} requires per-split context (only valid in OutputExpectations)",
        )

    def _need_field() -> AssertionResult | None:
        if field is None:
            return AssertionResult(kind, None, False, severity, f"{kind} assertion needs a 'field'")
        return None

    try:
        if kind == "record_count":
            ok, msg = _eval_record_count(records, assertion)
        elif kind == "required_field":
            if (miss := _need_field()) is not None:
                return miss
            assert field is not None
            ok, msg = _eval_required_field(records, field, skip_missing_field=skip_missing)
        elif kind == "dtype":
            if (miss := _need_field()) is not None:
                return miss
            assert field is not None
            ok, msg = _eval_dtype(records, field, assertion)
        elif kind == "range":
            if (miss := _need_field()) is not None:
                return miss
            assert field is not None
            ok, msg = _eval_range(records, field, assertion)
        elif kind == "distributional":
            ok, msg = _eval_distributional(records, field, assertion)
        elif kind == "split_record_counts":
            assert splits is not None
            ok, msg = _eval_split_record_counts(splits, assertion)
        elif kind == "per_class_count_per_split":
            if (miss := _need_field()) is not None:
                return miss
            assert field is not None and splits is not None
            ok, msg = _eval_per_class_count_per_split(splits, field, assertion)
        elif kind == "count_by_field":
            if (miss := _need_field()) is not None:
                return miss
            assert field is not None
            ok, msg = _eval_count_by_field(records, field, assertion)
        elif kind == "count_by_fields":
            ok, msg = _eval_count_by_fields(records, assertion)
        elif kind == "shape_equals":
            if (miss := _need_field()) is not None:
                return miss
            assert field is not None
            ok, msg = _eval_shape_equals(records, field, assertion)
        elif kind == "value_in_set":
            if (miss := _need_field()) is not None:
                return miss
            assert field is not None
            ok, msg = _eval_value_in_set(records, field, assertion)
        elif kind == "per_class_count_equals":
            if (miss := _need_field()) is not None:
                return miss
            assert field is not None
            ok, msg = _eval_per_class_count_equals(records, field, assertion)
        else:
            ok, msg = False, f"unknown assertion kind {kind!r}"
    except (TypeError, ValueError) as exc:
        ok, msg = False, f"evaluator raised {type(exc).__name__}: {exc}"

    return AssertionResult(kind=kind, field=field, passed=ok, severity=severity, message=msg)


def evaluate_input_contracts(
    records: Iterable[Record],
    contracts: list[Contract],
) -> ContractResult:
    """Evaluate ``InputContracts`` against the raw input record stream.

    Materializes the iterable once internally so multiple assertions can
    traverse the same records without callers re-buffering. Input
    contracts run pre-splits, so per-split assertion kinds are rejected
    with a clear message.
    """
    materialized = list(records)
    results = tuple(_evaluate_one(materialized, c) for c in contracts)
    return ContractResult(results=results)


def evaluate_output_expectations(
    dataset: Mapping[str, Sequence[Record]] | Iterable[Record],
    expectations: list[Expectation],
    *,
    skip_missing_label_field: str | None = None,
) -> ContractResult:
    """Evaluate ``OutputExpectations`` against the materialized dataset.

    ``dataset`` is a ``Mapping[str, list[Record]]`` keyed by split name
    (the canonical form post-Splits). A flat iterable is also accepted
    and routed as a single implicit split for backward compatibility;
    per-split assertion kinds then see one unnamed split.

    Flat-record kinds (``record_count``, ``dtype``, ``range``,
    ``shape_equals``, ``value_in_set``, ``count_by_field``,
    ``count_by_fields``, ``per_class_count_equals``, …) evaluate against
    every record across all splits. Per-split kinds
    (``split_record_counts``, ``per_class_count_per_split``) evaluate
    against the split structure.

    When ``skip_missing_label_field`` is set (the recipe's ``Labels.field``
    name when any source declares ``unlabeled: true``), expectations whose
    ``field`` equals that name treat records that lack the field as
    "skipped" rather than failures. Records where the field is present
    but ``None`` still fail.
    """
    if isinstance(dataset, Mapping):
        splits: dict[str, list[Record]] = {k: list(v) for k, v in dataset.items()}
    else:
        splits = {"__all__": list(dataset)}
    all_records = [r for recs in splits.values() for r in recs]
    results = tuple(
        _evaluate_one(
            all_records,
            c,
            splits=splits,
            skip_missing_label_field=skip_missing_label_field,
        )
        for c in expectations
    )
    return ContractResult(results=results)
