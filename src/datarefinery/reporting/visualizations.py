# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-13 exploration-mode visualization rendering (library API).

`exploration`-mode visualizations are rendered on demand via this
module - typically called by the ``inspect`` CLI verb (Story D.h) or
directly by users. Unlike reporting-mode (which persists into the
materialized instance), exploration renders return PNG bytes without
writing to disk.

The same operation handles power both modes; only the persistence
behavior differs. See ``datarefinery.pipeline.stages.visualizations``
for the reporting-mode runner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datarefinery.pipeline.stages.visualizations import (
    RenderedVisualization,
    VisualizationOpHandle,
)
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import VisualizationOp

Record = Mapping[str, Any]


def render_visualization(
    splits: Mapping[str, list[Record]],
    op: VisualizationOp,
    *,
    plugin: Plugin,
    label_field: str | None = None,
) -> RenderedVisualization:
    """Render one visualization on demand without persisting.

    Returns a :class:`RenderedVisualization` whose ``path`` is ``None``
    (exploration mode never writes to disk). Failures propagate as the
    plugin raised them; unlike reporting mode, exploration does not wrap
    in ``MaterializeError`` - the caller is exploring, not materializing.
    """
    handle: VisualizationOpHandle = plugin.operation_factory(
        "Visualizations", op.op
    )
    png = handle.render(splits, op.params, label_field=label_field)
    if not isinstance(png, (bytes, bytearray)):
        raise TypeError(
            f"Visualizations[{op.name!r}] returned {type(png).__name__}; "
            f"PNG bytes required"
        )
    return RenderedVisualization(
        name=op.name, op=op.op, png_bytes=bytes(png), path=None
    )
