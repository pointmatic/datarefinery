# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-10 Transformations stage with FR-6 fit-on-train persistence.

Each ``TransformationOp`` declares ``op`` (the operation kind),
``params``, optional ``fit_source`` (the split to fit statistics on), and
``splits`` (the splits to apply to). Operations are dispatched via
``plugin.operation_factory("Transformations", op.op)``.

Operation handle (Transformations section):

    class TransformationOpHandle:
        def fit(records, params, *, label_field) -> FittedValues
        def apply(records, params, fitted, *, label_field) -> list[Record]

For non-fitting ops, ``fit`` returns an empty ``FittedValues`` and the
stage skips persistence; whether an op is fit-on-train is determined by
the plugin's ``OperationSpec.fit_on_train``.

Determinism contract: transformations are deterministic given inputs and
fitted statistics (FR-10 #3). The fit phase runs once, on the train
split; the apply phase reads the same persisted statistics for every
declared split.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import pyarrow as pa

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import TransformationOp

Record = Mapping[str, Any]


@dataclass(frozen=True)
class FittedValues:
    """Statistics produced by a transformation's fit phase."""

    scalars: Mapping[str, float | int | str | bool] = field(default_factory=dict)
    vectors: Mapping[str, pa.Table] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.scalars and not self.vectors


class TransformationOpHandle(Protocol):
    """Plugin-supplied object exposing fit and apply phases."""

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
    ) -> FittedValues: ...

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        label_field: str | None,
    ) -> list[Record]: ...


@dataclass(frozen=True)
class TransformationsResult:
    """Outcome of running every transformation against the splits."""

    splits: Mapping[str, list[Record]]
    fitted_op_ids: tuple[str, ...]


def apply_transformations(
    splits: Mapping[str, list[Record]],
    transformation_ops: list[TransformationOp],
    *,
    plugin: Plugin,
    fitted_stats: FittedStatistics,
    label_field: str | None = None,
) -> TransformationsResult:
    """Run every declared transformation, fitting and persisting as needed.

    For each op, fit on ``fit_source`` (if any) before applying to the
    declared splits. The same fitted values are used across every split
    in ``op.splits`` to honor FR-10 #2.
    """
    out: dict[str, list[Record]] = {name: list(recs) for name, recs in splits.items()}
    fitted_op_ids: list[str] = []

    for op in transformation_ops:
        spec = plugin.supported_operations.get(op.op)
        if spec is None:
            raise MaterializeError(
                f"Transformations[{op.name!r}].op={op.op!r} not declared by plugin {plugin.name!r}"
            )
        handle: TransformationOpHandle = plugin.operation_factory("Transformations", op.op)

        fitted = FittedValues()
        if spec.fit_on_train:
            if op.fit_source is None:
                raise MaterializeError(
                    f"Transformations[{op.name!r}] is fit-on-train but no "
                    f"fit_source declared (validator check 6 normally "
                    f"catches this)"
                )
            if op.fit_source not in out:
                raise MaterializeError(
                    f"Transformations[{op.name!r}].fit_source "
                    f"{op.fit_source!r} not in splits {sorted(out)!r}"
                )
            fitted = handle.fit(out[op.fit_source], op.params, label_field=label_field)
            _persist(fitted_stats, op.name, fitted)
            fitted_op_ids.append(op.name)

        for split_name in op.splits:
            if split_name not in out:
                raise MaterializeError(
                    f"Transformations[{op.name!r}].splits references "
                    f"undeclared split {split_name!r}"
                )
            out[split_name] = handle.apply(
                out[split_name],
                op.params,
                fitted,
                label_field=label_field,
            )

    return TransformationsResult(splits=out, fitted_op_ids=tuple(fitted_op_ids))


def _persist(fitted_stats: FittedStatistics, op_id: str, fitted: FittedValues) -> None:
    for name, value in fitted.scalars.items():
        fitted_stats.put_scalar(op_id, name, value)
    for name, table in fitted.vectors.items():
        fitted_stats.put_vector(op_id, name, table)
