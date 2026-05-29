# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-12 Featurizations stage + FR-22 derived-Labels machinery.

Each ``FeaturizationOp`` declares ``inputs``, ``output_field``, ``op``,
``params``, ``splits``, and optional ``fit_source``. Operations are
dispatched via ``plugin.operation_factory("Featurizations", op.op)``.

Operation handle (Featurizations section):

    class FeaturizationOpHandle:
        fit_on_train: bool

        def fit(records, params, *, inputs, output_field,
                label_field) -> FittedValues
        def apply(records, params, fitted, *, inputs, output_field,
                  label_field) -> list[Record]

The same machinery produces derived labels (FR-22 #3): when
``Labels.source.kind == "derived"``, the recipe author writes a
``FeaturizationOp`` whose ``output_field`` matches ``Labels.field``. No
special-casing in this stage - the featurization simply runs and
populates the label field.

FR-TRANS-1 (Story I.l): when a fit-on-train Featurization declares
``stats_from_instance`` in its params, the fit phase is skipped and
fitted statistics are imported from a sibling instance under
``cache_root`` via ``resolve_sibling_stats``, mirroring the
Transformations-stage behavior. ``cache_root`` is plumbed through from
the pipeline runner.

Edge case (FR-12): a featurization producing a name that collides with
an existing field raises ``MaterializeError`` before the apply phase
runs. Under the uniform-schema invariant (every record in a split
shares the same key set), the check inspects the first record of each
target split.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.stages.transformations import (
    FittedValues,
    _load_sibling_fitted,
)
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import FeaturizationOp, StatsFromInstanceSpec

Record = Mapping[str, Any]


class FeaturizationOpHandle(Protocol):
    """Plugin-supplied object exposing fit and apply phases."""

    fit_on_train: bool

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> FittedValues: ...

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> list[Record]: ...


@dataclass(frozen=True)
class FeaturizationsResult:
    """Outcome of running every featurization against the splits."""

    splits: Mapping[str, list[Record]]
    fitted_op_ids: tuple[str, ...]


def apply_featurizations(
    splits: Mapping[str, list[Record]],
    featurization_ops: list[FeaturizationOp],
    *,
    plugin: Plugin,
    fitted_stats: FittedStatistics,
    label_field: str | None = None,
    cache_root: Path | None = None,
) -> FeaturizationsResult:
    """Run every declared featurization, fitting and persisting as needed.

    When an op declares ``stats_from_instance`` in its params, the fit
    phase is skipped: fitted statistics are imported from a sibling
    instance under ``cache_root`` via
    :func:`datarefinery.cache.sibling_stats.resolve_sibling_stats`.
    """
    out: dict[str, list[Record]] = {name: list(recs) for name, recs in splits.items()}
    fitted_op_ids: list[str] = []

    for op in featurization_ops:
        spec = plugin.supported_operations.get(op.op)
        if spec is None:
            raise MaterializeError(
                f"Featurizations[{op.name!r}].op={op.op!r} not declared by plugin {plugin.name!r}"
            )
        handle: FeaturizationOpHandle = plugin.operation_factory("Featurizations", op.op)

        # Collision check before we touch any records: under the uniform-
        # schema invariant, any record having the field is a collision.
        for split_name in op.splits:
            if split_name not in out:
                raise MaterializeError(
                    f"Featurizations[{op.name!r}].splits references undeclared split {split_name!r}"
                )
            recs = out[split_name]
            if recs and op.output_field in recs[0]:
                raise MaterializeError(
                    f"Featurizations[{op.name!r}].output_field "
                    f"{op.output_field!r} collides with an existing field "
                    f"in split {split_name!r}"
                )

        fitted = FittedValues()
        sib_raw = op.params.get("stats_from_instance")
        if sib_raw is not None:
            if cache_root is None:
                raise MaterializeError(
                    f"Featurizations[{op.name!r}] declares 'stats_from_instance' "
                    f"but no cache_root was provided to apply_featurizations"
                )
            sib_spec = StatsFromInstanceSpec.model_validate(sib_raw)
            fitted = _load_sibling_fitted(
                op_name=op.name,
                cache_root=cache_root,
                spec=sib_spec,
            )
        elif spec.fit_on_train:
            if op.fit_source is None:
                raise MaterializeError(
                    f"Featurizations[{op.name!r}] is fit-on-train but no "
                    f"fit_source declared (validator check 6 normally "
                    f"catches this)"
                )
            if op.fit_source not in out:
                raise MaterializeError(
                    f"Featurizations[{op.name!r}].fit_source "
                    f"{op.fit_source!r} not in splits {sorted(out)!r}"
                )
            fitted = handle.fit(
                out[op.fit_source],
                op.params,
                inputs=list(op.inputs),
                output_field=op.output_field,
                label_field=label_field,
            )
            _persist(fitted_stats, op.name, fitted)
            fitted_op_ids.append(op.name)

        for split_name in op.splits:
            out[split_name] = handle.apply(
                out[split_name],
                op.params,
                fitted,
                inputs=list(op.inputs),
                output_field=op.output_field,
                label_field=label_field,
            )

    return FeaturizationsResult(splits=out, fitted_op_ids=tuple(fitted_op_ids))


def _persist(fitted_stats: FittedStatistics, op_id: str, fitted: FittedValues) -> None:
    for name, value in fitted.scalars.items():
        fitted_stats.put_scalar(op_id, name, value)
    for name, table in fitted.vectors.items():
        fitted_stats.put_vector(op_id, name, table)
