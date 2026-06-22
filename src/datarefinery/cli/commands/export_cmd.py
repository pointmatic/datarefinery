# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""``datarefinery export`` — re-run sinks against an existing instance (Story I.f).

See ``datarefinery.pipeline.sinks.export`` for the dispatch logic and
the v1 reconstructability table. This verb is a thin Typer surface
over :meth:`DataRefinery.export`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from datarefinery.cli._exit_codes import EXIT_OK
from datarefinery.core.datarefinery import DataRefinery


def export(
    ctx: typer.Context,
    recipe: Annotated[
        Path,
        typer.Argument(
            help="Path to the recipe YAML file whose Sinks should be re-run.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    sink: Annotated[
        list[str] | None,
        typer.Option(
            "--sink",
            help=(
                "Re-run only the named sink (repeatable). When omitted, every "
                "sink declared on the recipe is re-run."
            ),
        ),
    ] = None,
) -> None:
    """Re-run recipe-declared sinks against the bound materialized instance.

    Locates the bound instance by computing a sinks-stripped cache key
    so a user who adds a sink to an already-materialized recipe still
    resolves to the original instance. Refuses cleanly when no bound
    instance exists, or when a requested sink targets a stage that is
    not reconstructable from cached state in v1.
    """
    state = ctx.obj or {}
    config = state.get("config")
    overlays = state.get("overlays") or []
    seed = state.get("seed")
    no_color = state.get("no_color", False)

    dr = DataRefinery.from_recipe(recipe, config=config, overlays=overlays, seed=seed)

    result = dr.export(sink_names=sink if sink else None)

    console = Console(no_color=no_color)
    table = Table(title="Export", show_header=True, expand=False)
    table.add_column("sink", style="bold cyan")
    table.add_column("stage")
    table.add_column("format")
    table.add_column("files", justify="right")
    table.add_column("bytes", justify="right")
    for r in result.sinks_executed:
        table.add_row(r.name, r.stage, r.format, str(r.files_written), str(r.bytes_total))
    console.print(table)
    console.print(f"Instance: {result.instance_dir}")

    raise typer.Exit(code=EXIT_OK)
