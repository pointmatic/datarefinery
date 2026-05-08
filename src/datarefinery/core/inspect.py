# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-20 ``inspect`` library API.

`build_inspection_view()` enumerates the exploration-mode
visualizations declared in an instance's recipe, peeks at the persisted
fitted-statistics op ids, and (when a view name is supplied) renders
that view on demand via the plugin's exploration renderer. The CLI verb
in ``datarefinery.cli.commands.inspect_cmd`` wraps this and decides how
to surface the result on stdout vs. writing to a file.

The FR-20 partial-instance refusal is enforced here so library callers
get the same guard as CLI users: a partial (FAILED or
``--stage``-stopped) instance is not safe to inspect because the
fitted statistics + dataset on disk reflect an incomplete pipeline run.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from datarefinery.cache.layout import dataset_dir
from datarefinery.core.errors import MaterializeError
from datarefinery.core.instance import Instance
from datarefinery.pipeline.inputs import reload_dataset
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import VisualizationOp
from datarefinery.reporting.report import list_fitted_op_ids
from datarefinery.reporting.visualizations import render_visualization

#: Number of records peeked per split when ``view`` is not supplied.
DEFAULT_PEEK_PER_SPLIT = 3


@dataclasses.dataclass(frozen=True)
class RenderedView:
    """One rendered exploration visualization (in-memory PNG bytes)."""

    name: str
    op: str
    png_bytes: bytes


@dataclasses.dataclass(frozen=True)
class InspectionView:
    """Structured ``inspect`` outcome.

    - ``exploration_views``: every ``mode=="exploration"`` op name in
      the instance's recipe.
    - ``rendered``: present iff a specific view was requested.
    - ``fitted_op_ids``: op ids that have persisted fitted statistics.
    - ``record_counts``: per-split counts from the manifest.
    - ``sample_records``: first :data:`DEFAULT_PEEK_PER_SPLIT` rows of
      each split's persisted JSONL (serializable fields only).
    """

    instance_path: Path
    exploration_views: tuple[str, ...]
    rendered: RenderedView | None
    fitted_op_ids: tuple[str, ...]
    record_counts: dict[str, int]
    sample_records: dict[str, list[dict[str, object]]]


def build_inspection_view(
    instance: Instance,
    plugin: Plugin,
    *,
    view: str | None = None,
    peek_per_split: int = DEFAULT_PEEK_PER_SPLIT,
) -> InspectionView:
    """Assemble an :class:`InspectionView` for ``instance``.

    Refuses on a partial instance (FR-20 edge case) with a pointer to
    the manifest's ``failed_stage`` / ``completed_through`` field.
    """
    if instance.is_partial:
        kind, marker = _partial_classification(instance)
        raise MaterializeError(
            f"inspect: refusing to operate on partial instance at "
            f"{instance.path}. {kind}: {marker}. Re-materialize or "
            f"`datarefinery clean` before inspecting."
        )

    exploration_ops = tuple(
        op for op in instance.recipe.Visualizations if op.mode == "exploration"
    )
    exploration_names = tuple(op.name for op in exploration_ops)

    rendered: RenderedView | None = None
    if view is not None:
        op = _find_op(exploration_ops, view)
        splits = reload_dataset(instance.path, plugin)
        rv = render_visualization(
            splits,  # type: ignore[arg-type]  # invariant Mapping; runtime types match
            op,
            plugin=plugin,
            label_field=instance.recipe.Labels.field,
        )
        rendered = RenderedView(name=op.name, op=op.op, png_bytes=rv.png_bytes)

    sample_records = _peek_records(instance.path, peek_per_split)

    return InspectionView(
        instance_path=instance.path,
        exploration_views=exploration_names,
        rendered=rendered,
        fitted_op_ids=tuple(list_fitted_op_ids(_fitted_root(instance))),
        record_counts=dict(instance.manifest.record_counts),
        sample_records=sample_records,
    )


def _partial_classification(instance: Instance) -> tuple[str, str]:
    m = instance.manifest
    if m.failed_stage is not None:
        return "Failed stage", m.failed_stage
    if m.completed_through is not None:
        return "Completed through", m.completed_through
    return "Partial", "(reason not recorded)"


def _find_op(
    exploration_ops: tuple[VisualizationOp, ...], name: str
) -> VisualizationOp:
    for op in exploration_ops:
        if op.name == name:
            return op
    raise MaterializeError(
        f"inspect: no exploration visualization named {name!r}; "
        f"available: {[op.name for op in exploration_ops]}"
    )


def _fitted_root(instance: Instance) -> Path:
    return instance.fitted_statistics.root


def _peek_records(
    instance_path: Path, n: int
) -> dict[str, list[dict[str, object]]]:
    out: dict[str, list[dict[str, object]]] = {}
    root = dataset_dir(instance_path)
    if not root.is_dir():
        return out
    for split_path in sorted(root.glob("*.jsonl")):
        rows: list[dict[str, object]] = []
        with split_path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= n:
                    break
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        out[split_path.stem] = rows
    return out


__all__ = [
    "DEFAULT_PEEK_PER_SPLIT",
    "InspectionView",
    "RenderedView",
    "build_inspection_view",
]
