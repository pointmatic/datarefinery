# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-3 ``datarefinery materialize`` — pipeline-execution CLI verb.

Loads the recipe, validates it (the loader does this for free via
``DataRefinery.from_recipe``), inflates the input sources from disk,
runs every pipeline stage, atomically promotes the result into the
cache layout, and prints a summary. Cache hits short-circuit before
any temp-dir work.

`--stage NAME` opts in to a partial run: stages run up to and including
the named stage, the result is left unpromoted in the temp directory
with ``manifest.is_partial=True``, and the path is printed for
inspection. Valid stage names match the runner's :data:`STAGE_NAMES`
tuple.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from datarefinery.cli._exit_codes import EXIT_OK
from datarefinery.core.datarefinery import DataRefinery
from datarefinery.core.errors import MaterializeError
from datarefinery.core.instance import Instance
from datarefinery.pipeline.runner import STAGE_NAMES


def materialize(
    ctx: typer.Context,
    recipe: Annotated[
        Path,
        typer.Argument(
            help="Path to the recipe YAML file to materialize.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    stop_after: Annotated[
        str | None,
        typer.Option(
            "--stage",
            help=(
                "Run up to and including this stage, then stop without "
                "promoting. Manifest is marked partial. Valid: " + ", ".join(STAGE_NAMES)
            ),
        ),
    ] = None,
) -> None:
    """Run the pipeline end-to-end (FR-3)."""
    state = ctx.obj or {}
    config = state.get("config")
    overlays = state.get("overlays") or []
    seed = state.get("seed")
    no_color = state.get("no_color", False)

    if stop_after is not None and stop_after not in STAGE_NAMES:
        raise MaterializeError(
            f"--stage={stop_after!r} not recognized. Valid stages: {list(STAGE_NAMES)}"
        )

    dr = DataRefinery.from_recipe(recipe, config=config, overlays=overlays, seed=seed)

    console = Console(no_color=no_color)
    instance = _run_with_progress(dr, console=console, stop_after=stop_after)
    cache_hit = dr.last_run is not None and dr.last_run.cache_hit
    _print_summary(console, instance, cache_hit=cache_hit, stop_after=stop_after)

    raise typer.Exit(code=EXIT_OK)


def _run_with_progress(
    dr: DataRefinery,
    *,
    console: Console,
    stop_after: str | None,
) -> Instance:
    """Drive a `rich` progress bar from the runner's per-stage callback.

    A determinate task is sized to the number of stages we expect to
    visit; each callback fires advance(1). Cache hits skip the
    progress block entirely (no work is done).
    """
    expected_stages = list(STAGE_NAMES)
    if stop_after is not None:
        expected_stages = expected_stages[: expected_stages.index(stop_after) + 1]
    total = len(expected_stages)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("starting…", total=total)

        def _on_stage(name: str) -> None:
            progress.update(task_id, description=name, advance=1)

        return dr.materialize(stop_after=stop_after, progress_callback=_on_stage)


def _print_summary(
    console: Console,
    instance: Instance,
    *,
    cache_hit: bool,
    stop_after: str | None,
) -> None:
    manifest = instance.manifest
    table = Table(title="Materialize summary", show_header=False, expand=False)
    table.add_column("key", style="bold cyan")
    table.add_column("value")
    if instance.is_partial:
        cache_status = f"partial (--stage {stop_after})"
    elif cache_hit:
        cache_status = "[green]hit[/green]"
    else:
        cache_status = "[yellow]miss[/yellow]"
    table.add_row("Cache", cache_status)
    table.add_row("Instance", str(instance.path))
    table.add_row("Plugin", f"{manifest.plugin} (v{manifest.plugin_version})")
    table.add_row("Recipe hash", manifest.recipe_hash)
    table.add_row("Input hash", manifest.input_hash)
    table.add_row("Seed", str(manifest.seed))
    if manifest.overlays:
        table.add_row("Overlays", ", ".join(manifest.overlays))
    table.add_row("Elapsed", f"{manifest.elapsed_seconds:.3f}s")
    if manifest.completed_through is not None:
        table.add_row("Completed through", manifest.completed_through)
    console.print(table)

    counts_table = Table(title="Records per split", expand=False)
    counts_table.add_column("split", style="bold")
    counts_table.add_column("count", justify="right")
    if not manifest.record_counts:
        counts_table.add_row("(none)", "-")
    else:
        for split, count in sorted(manifest.record_counts.items()):
            counts_table.add_row(split, str(count))
    console.print(counts_table)

    if manifest.warnings:
        warn_table = Table(title="Warnings", expand=False, border_style="yellow")
        warn_table.add_column("stage", style="bold")
        warn_table.add_column("message")
        for w in manifest.warnings:
            warn_table.add_row(w.stage, w.message)
        console.print(warn_table)
