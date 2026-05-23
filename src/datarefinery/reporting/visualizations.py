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
from datarefinery.recipe.models import Recipe, VisualizationOp

Record = Mapping[str, Any]


def render_visualization(
    splits: Mapping[str, list[Record]],
    op: VisualizationOp,
    *,
    plugin: Plugin,
    label_field: str | None = None,
    recipe: Recipe | None = None,
) -> RenderedVisualization:
    """Render one visualization on demand without persisting.

    Returns a :class:`RenderedVisualization` whose ``path`` is ``None``
    (exploration mode never writes to disk). Multi-output ops (mapping
    return) populate ``extras`` with every PNG keyed by sub-name; the
    first entry becomes the primary ``png_bytes``. Failures propagate as
    the plugin raised them; unlike reporting mode, exploration does not
    wrap in ``MaterializeError`` — the caller is exploring, not
    materializing.
    """
    handle: VisualizationOpHandle = plugin.operation_factory("Visualizations", op.op)
    raw = handle.render(splits, op.params, label_field=label_field, recipe=recipe)
    if isinstance(raw, (bytes, bytearray)):
        return RenderedVisualization(name=op.name, op=op.op, png_bytes=bytes(raw), path=None)
    if isinstance(raw, Mapping):
        if not raw:
            raise TypeError(
                f"Visualizations[{op.name!r}] returned an empty mapping; "
                f"at least one PNG entry required"
            )
        extras: dict[str, bytes] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"Visualizations[{op.name!r}] returned non-str key "
                    f"{type(key).__name__}; PNG-mapping keys must be str"
                )
            if not isinstance(value, (bytes, bytearray)):
                raise TypeError(
                    f"Visualizations[{op.name!r}] entry {key!r} is "
                    f"{type(value).__name__}; PNG bytes required"
                )
            extras[key] = bytes(value)
        primary = next(iter(extras.values()))
        return RenderedVisualization(
            name=op.name, op=op.op, png_bytes=primary, path=None, extras=extras
        )
    raise TypeError(
        f"Visualizations[{op.name!r}] returned {type(raw).__name__}; PNG bytes required"
    )
