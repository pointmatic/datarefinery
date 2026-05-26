# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Sink execution hook (Story I.d).

:func:`execute_sinks` is invoked by the pipeline runner after each
named stage emits its records. It iterates the recipe's `Sinks` list,
filters to those targeting the current stage, resolves each sink's
`path_template` per record, and dispatches to the format-specific
writer. Output lives under the instance temp dir, so atomic
temp-then-promote (FR-5) covers sink output for free.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.sinks.template import parse_template, render_template
from datarefinery.pipeline.sinks.writers import write_png_per_record
from datarefinery.recipe.models import SinkOp


@dataclass(frozen=True)
class SinkResult:
    """Per-sink summary captured into the manifest's ``sinks`` map.

    The ``path_template_resolved_root`` is the longest fixed prefix of
    the template (the segment up to the first placeholder), which gives
    consumers a stable "where do this sink's files live" pointer
    without forcing them to enumerate the directory tree.
    """

    name: str
    stage: str
    format: str
    files_written: int
    bytes_total: int
    path_template_resolved_root: str


@dataclass
class _SinkAccumulator:
    files_written: int = 0
    bytes_total: int = 0
    written_paths: set[Path] = field(default_factory=set)


class SinkCardinalityError(MaterializeError):
    """Raised when a sink writes a different number of files than expected.

    The expected count is the number of records the sink visited
    (after the `splits` filter). A mismatch indicates either a
    collision in the resolved per-record paths (two records hashing to
    the same output filename) or a writer that silently dropped output.
    """


def _resolved_root(template: str) -> str:
    """Longest fixed prefix of ``template`` before the first placeholder.

    Used as the manifest's ``path_template_resolved_root`` so
    downstream consumers can locate a sink's output tree without
    walking the recipe.
    """
    parts = parse_template(template)
    if parts and isinstance(parts[0], str):
        prefix = parts[0]
    else:
        prefix = ""
    # Trim to the directory containing the placeholder so the root
    # stays a directory path, not a filename-prefix fragment.
    prefix = prefix.rstrip("/")
    if "/" in prefix:
        return prefix.rsplit("/", 1)[0] if not template.startswith(prefix + "/") else prefix
    return prefix


def execute_sinks(
    *,
    sinks: list[SinkOp],
    stage: str,
    split_map: Mapping[str, list[Mapping[str, Any]]],
    instance_dir: Path,
) -> list[SinkResult]:
    """Run every sink targeting ``stage`` against ``split_map``.

    ``instance_dir`` is the (temp) instance directory; all sink output
    lands under it. Returns one :class:`SinkResult` per sink that ran
    at this stage (empty list when no sinks match).
    """
    results: list[SinkResult] = []
    for sink in sinks:
        if sink.stage != stage:
            continue
        results.append(_run_one_sink(sink, split_map, instance_dir))
    return results


def _run_one_sink(
    sink: SinkOp,
    split_map: Mapping[str, list[Mapping[str, Any]]],
    instance_dir: Path,
) -> SinkResult:
    acc = _SinkAccumulator()
    expected = 0
    target_splits = list(split_map.keys()) if sink.splits is None else list(sink.splits)
    for split_name in target_splits:
        records = split_map.get(split_name, [])
        for record in records:
            expected += 1
            rel = render_template(sink.path_template, record=record, split=split_name)
            output_path = instance_dir / rel
            if output_path in acc.written_paths:
                raise SinkCardinalityError(
                    f"sink {sink.name!r}: path_template collision — "
                    f"{rel!r} was already written for an earlier record."
                )
            if sink.format == "png_per_record":
                bytes_written = write_png_per_record(
                    record=dict(record),
                    field=sink.field,
                    output_path=output_path,
                    sink_name=sink.name,
                    stage=sink.stage,
                )
            else:  # pragma: no cover — pydantic Literal blocks other values
                raise MaterializeError(f"sink {sink.name!r}: unsupported format {sink.format!r}")
            acc.files_written += 1
            acc.bytes_total += bytes_written
            acc.written_paths.add(output_path)
    if acc.files_written != expected:
        raise SinkCardinalityError(
            f"sink {sink.name!r}: wrote {acc.files_written} files but "
            f"expected {expected} (records visited)."
        )
    return SinkResult(
        name=sink.name,
        stage=sink.stage,
        format=sink.format,
        files_written=acc.files_written,
        bytes_total=acc.bytes_total,
        path_template_resolved_root=_resolved_root(sink.path_template),
    )
