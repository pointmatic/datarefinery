# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-8 Filters stage: pre-split and post-split record filtering.

Each ``FilterOp`` declares a ``predicate`` dict whose ``op`` key names a
plugin operation in the ``Filters`` section. The remaining predicate keys
are operation parameters. The stage looks up the operation via
``plugin.operation_factory("Filters", op_name)`` and calls it with the
record list, parameters, and the recipe's label-field name as context.

Operation signature (Filters section):

    def op(records: list[Record], params: Mapping[str, Any], *,
           label_field: str | None) -> list[Record]

Pre-split filters apply to the raw record stream before splitting; the
default ``stages=["pre_split"]`` is honored (FR-8 #2). Post-split filters
apply to one or more named splits as declared by ``FilterOp.splits``.

Edge cases:

- A filter that empties a class entirely emits a warning (FR-8 edge
  case). This requires a non-None ``label_field``; without one, empty-
  class detection is skipped and no warning is produced.
- Sampling filters that omit a ``seed`` are caught by validator check 18
  (Story B.e.3); this stage does not re-validate.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from datarefinery.core.errors import MaterializeError
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import FilterOp

Record = Mapping[str, Any]
FilterCallable = Callable[..., list[Record]]


@dataclass(frozen=True)
class FilterResult:
    """Outcome of running one filter pass over a record list."""

    records: list[Record]
    warnings: tuple[str, ...]
    removed: int


def apply_pre_split_filters(
    records: Iterable[Record],
    filter_ops: list[FilterOp],
    *,
    plugin: Plugin,
    label_field: str | None = None,
) -> FilterResult:
    """Apply each ``pre_split``-stage filter to the raw record stream.

    Filters run in declared order; output of one feeds the next. Empty-
    class detection runs once at the end against the original
    distribution.
    """
    materialized = list(records)
    initial_count = len(materialized)
    initial_class_counts = _class_counts(materialized, label_field)

    for op in filter_ops:
        if "pre_split" not in op.stages:
            continue
        materialized = _invoke_one(op, materialized, plugin, label_field)

    final_class_counts = _class_counts(materialized, label_field)
    warnings = _empty_class_warnings(initial_class_counts, final_class_counts)
    return FilterResult(
        records=materialized,
        warnings=warnings,
        removed=initial_count - len(materialized),
    )


def apply_post_split_filters(
    splits: Mapping[str, list[Record]],
    filter_ops: list[FilterOp],
    *,
    plugin: Plugin,
    label_field: str | None = None,
) -> dict[str, FilterResult]:
    """Apply each ``post_split``-stage filter to the splits it targets.

    A filter contributes to a split's pass only if the split's name is
    listed in ``FilterOp.splits``. Splits not named by any post-split
    filter pass through unchanged.
    """
    out: dict[str, FilterResult] = {}
    for split_name, split_records in splits.items():
        records: list[Record] = list(split_records)
        initial_count = len(records)
        initial_class_counts = _class_counts(records, label_field)
        for op in filter_ops:
            if "post_split" not in op.stages:
                continue
            if split_name not in op.splits:
                continue
            records = _invoke_one(op, records, plugin, label_field)
        final_class_counts = _class_counts(records, label_field)
        warnings = _empty_class_warnings(
            initial_class_counts, final_class_counts, split=split_name
        )
        out[split_name] = FilterResult(
            records=records,
            warnings=warnings,
            removed=initial_count - len(records),
        )
    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _invoke_one(
    op: FilterOp,
    records: list[Record],
    plugin: Plugin,
    label_field: str | None,
) -> list[Record]:
    params = dict(op.predicate)
    op_name = params.pop("op", None)
    if not isinstance(op_name, str):
        raise MaterializeError(
            f"Filters[{op.name!r}].predicate missing 'op' string "
            f"(got {type(op_name).__name__})"
        )
    callable_: FilterCallable = plugin.operation_factory("Filters", op_name)
    return callable_(records, params, label_field=label_field)


def _class_counts(
    records: list[Record], label_field: str | None
) -> dict[Any, int]:
    if label_field is None:
        return {}
    counts: dict[Any, int] = {}
    for r in records:
        v = r.get(label_field)
        counts[v] = counts.get(v, 0) + 1
    return counts


def _empty_class_warnings(
    before: dict[Any, int],
    after: dict[Any, int],
    *,
    split: str | None = None,
) -> tuple[str, ...]:
    msgs: list[str] = []
    where = "" if split is None else f" in split {split!r}"
    for cls, n_before in before.items():
        if n_before > 0 and after.get(cls, 0) == 0:
            msgs.append(
                f"filter emptied class {cls!r}{where}: "
                f"{n_before} -> 0 records"
            )
    return tuple(msgs)
