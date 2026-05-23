# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-13 Visualizations stage: reporting-mode rendering at materialize time.

The pipeline runner calls :func:`apply_reporting_visualizations` to
render every ``VisualizationOp`` whose ``mode == "reporting"`` and write
the resulting PNG bytes under ``<instance>/report/visualizations/``.
``exploration``-mode ops are skipped here; they are rendered on demand by
``datarefinery.reporting.visualizations.render_visualization``.

Operation handle (Visualizations section):

    class VisualizationOpHandle:
        def render(splits: Mapping[str, list[Record]],
                   params: Mapping[str, Any],
                   *, label_field: str | None) -> bytes | Mapping[str, bytes]

A ``bytes`` return persists as ``<op.name>.png``. A ``Mapping[str, bytes]``
return persists each entry as ``<op.name>_<key>.png`` — used by FR-VIZ-1
``pixel_distribution`` (one PNG per split) and other per-key viz ops.
Failures during reporting-mode rendering are wrapped in
:class:`MaterializeError` per FR-13 ("reporting visualization that
fails -> hard error during materialization").
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from datarefinery.core.errors import MaterializeError
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import VisualizationOp

Record = Mapping[str, Any]


class VisualizationOpHandle(Protocol):
    """Plugin-supplied visualization renderer."""

    def render(
        self,
        splits: Mapping[str, list[Record]],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
    ) -> bytes | Mapping[str, bytes]: ...


@dataclass(frozen=True)
class RenderedVisualization:
    """One rendered visualization (in-memory + on-disk path, if persisted).

    ``png_bytes`` is the primary PNG (for multi-output ops, the first
    entry in stable key order). ``extras`` carries the full mapping for
    multi-output ops keyed by sub-name (e.g. split); empty for single-
    output ops. ``path`` is the on-disk location of the primary PNG, or
    ``None`` for exploration-mode renders. ``extra_paths`` mirrors
    ``extras`` with the per-key on-disk locations and is empty for both
    single-output ops and any exploration-mode render.
    """

    name: str
    op: str
    png_bytes: bytes
    path: Path | None
    extras: Mapping[str, bytes] = field(default_factory=dict)
    extra_paths: Mapping[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class VisualizationsResult:
    """Aggregated outcome of the reporting-mode visualization stage."""

    rendered: tuple[RenderedVisualization, ...]
    output_dir: Path

    @property
    def written_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for r in self.rendered:
            if r.extra_paths:
                paths.extend(r.extra_paths.values())
            elif r.path is not None:
                paths.append(r.path)
        return tuple(paths)


def apply_reporting_visualizations(
    splits: Mapping[str, list[Record]],
    viz_ops: list[VisualizationOp],
    *,
    plugin: Plugin,
    output_dir: Path,
    label_field: str | None = None,
) -> VisualizationsResult:
    """Render and persist every reporting-mode visualization.

    The output directory is created if needed. ``exploration``-mode ops
    are skipped. Names are unique within a recipe (validator check 4
    family enforces uniqueness elsewhere); the stage uses ``op.name`` as
    the file stem, so a name collision would overwrite within a single
    materialization - validators upstream prevent that case.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[RenderedVisualization] = []

    for op in viz_ops:
        if op.mode != "reporting":
            continue
        try:
            handle: VisualizationOpHandle = plugin.operation_factory("Visualizations", op.op)
            result_obj = handle.render(splits, op.params, label_field=label_field)
        except Exception as exc:
            raise MaterializeError(
                f"Visualizations[{op.name!r}] (op={op.op!r}, "
                f"mode='reporting') failed: {type(exc).__name__}: {exc}"
            ) from exc
        primary_png, extras = _normalize_render_output(result_obj, op_name=op.name)
        extra_paths: dict[str, Path] = {}
        if extras:
            for key, payload in extras.items():
                target = output_dir / f"{op.name}_{key}.png"
                target.write_bytes(payload)
                extra_paths[key] = target
            primary_path = extra_paths[next(iter(extras))]
        else:
            primary_path = output_dir / f"{op.name}.png"
            primary_path.write_bytes(primary_png)
        rendered.append(
            RenderedVisualization(
                name=op.name,
                op=op.op,
                png_bytes=primary_png,
                path=primary_path,
                extras=extras,
                extra_paths=extra_paths,
            )
        )

    return VisualizationsResult(rendered=tuple(rendered), output_dir=output_dir)


def _normalize_render_output(
    raw: Any,
    *,
    op_name: str,
) -> tuple[bytes, Mapping[str, bytes]]:
    """Coerce a handle's return into ``(primary_png, extras)``.

    Single-output (``bytes``) handles return ``(payload, {})``.
    Multi-output (``Mapping[str, bytes]``) handles return the first
    entry as the primary plus the full mapping (insertion order
    preserved) under ``extras``. Empty mappings and bad return types
    raise :class:`MaterializeError`.
    """
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw), {}
    if isinstance(raw, Mapping):
        if not raw:
            raise MaterializeError(
                f"Visualizations[{op_name!r}] returned an empty mapping; "
                f"at least one PNG entry required"
            )
        normalized: dict[str, bytes] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                raise MaterializeError(
                    f"Visualizations[{op_name!r}] returned non-str key "
                    f"{type(key).__name__}; PNG-mapping keys must be str"
                )
            if not isinstance(value, (bytes, bytearray)):
                raise MaterializeError(
                    f"Visualizations[{op_name!r}] entry {key!r} is "
                    f"{type(value).__name__}; PNG bytes required"
                )
            normalized[key] = bytes(value)
        primary = next(iter(normalized.values()))
        return primary, normalized
    raise MaterializeError(
        f"Visualizations[{op_name!r}] returned {type(raw).__name__}; PNG bytes required"
    )
