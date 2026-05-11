# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-19 ``datarefinery status`` — instance summary CLI verb.

Accepts either an instance directory or a recipe YAML file and renders
the manifest as a `rich` table.

- **Instance path** (a directory): the manifest is read directly via
  :meth:`Instance.load`. ``cache=hit``.
- **Recipe path** (a file): :meth:`DataRefinery.status` resolves the
  cache key from disk-backed input hashes and inspects the cache. May
  report ``cache=miss`` (exit 0, no error) or ``cache=corrupt`` if the
  instance directory is present but ``manifest.json`` is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from datarefinery.cli._exit_codes import EXIT_OK
from datarefinery.core.datarefinery import DataRefinery
from datarefinery.core.errors import MaterializeError
from datarefinery.core.instance import Instance
from datarefinery.core.status import StatusReport
from datarefinery.pipeline.manifest import Manifest


def status(
    ctx: typer.Context,
    target: Annotated[
        Path,
        typer.Argument(
            help="Either a recipe YAML file or a materialized instance directory.",
            exists=True,
            readable=True,
        ),
    ],
) -> None:
    """Summarize a materialized instance (FR-19)."""
    state = ctx.obj or {}
    config = state.get("config")
    variant = state.get("variant")
    seed = state.get("seed")
    no_color = state.get("no_color", False)

    console = Console(no_color=no_color)

    if target.is_dir():
        _render_instance_path(console, target)
    elif target.is_file():
        _render_recipe_path(console, target, config=config, variant=variant, seed=seed)
    else:
        raise MaterializeError(f"status: {target!s} is neither a directory nor a regular file")

    raise typer.Exit(code=EXIT_OK)


def _render_instance_path(console: Console, instance_path: Path) -> None:
    instance = Instance.load(instance_path)
    console.print(
        _summary_table(
            cache_label=("partial" if instance.is_partial else "hit"),
            instance_path=instance.path,
            manifest=instance.manifest,
        )
    )
    console.print(_record_counts_table(instance.manifest))
    if instance.manifest.warnings:
        console.print(_warnings_table(instance.manifest))


def _render_recipe_path(
    console: Console,
    recipe_path: Path,
    *,
    config: object,
    variant: str | None,
    seed: int | None,
) -> None:
    dr = DataRefinery.from_recipe(
        recipe_path,
        config=config,  # type: ignore[arg-type]
        variant=variant,
        seed=seed,
    )
    report: StatusReport = dr.status()

    if report.cache_status == "hit":
        assert report.manifest is not None
        console.print(
            _summary_table(
                cache_label="hit",
                instance_path=report.instance_path,
                manifest=report.manifest,
            )
        )
        console.print(_record_counts_table(report.manifest))
        if report.manifest.warnings:
            console.print(_warnings_table(report.manifest))
        return

    table = Table(title="Status", show_header=False, expand=False)
    table.add_column("key", style="bold cyan")
    table.add_column("value")
    label = "[yellow]miss[/yellow]" if report.cache_status == "miss" else "[red]corrupt[/red]"
    table.add_row("Cache", label)
    table.add_row("Instance (expected)", str(report.instance_path))
    table.add_row("Recipe hash", report.cache_key.recipe_hash)
    table.add_row("Input hash", report.cache_key.input_hash)
    table.add_row("Seed", str(report.cache_key.seed))
    if report.note is not None:
        table.add_row("Note", report.note)
    console.print(table)


def _summary_table(*, cache_label: str, instance_path: Path, manifest: Manifest) -> Table:
    table = Table(title="Status", show_header=False, expand=False)
    table.add_column("key", style="bold cyan")
    table.add_column("value")
    color = {
        "hit": f"[green]{cache_label}[/green]",
        "partial": f"[yellow]{cache_label}[/yellow]",
    }.get(cache_label, cache_label)
    table.add_row("Cache", color)
    table.add_row("Instance", str(instance_path))
    table.add_row("Plugin", f"{manifest.plugin} (v{manifest.plugin_version})")
    table.add_row("Schema version", str(manifest.schema_version))
    table.add_row("Recipe hash", manifest.recipe_hash)
    table.add_row("Input hash", manifest.input_hash)
    table.add_row("Seed", str(manifest.seed))
    if manifest.variant is not None:
        table.add_row("Variant", manifest.variant)
    table.add_row("Created at", manifest.created_at.isoformat())
    table.add_row("Elapsed", f"{manifest.elapsed_seconds:.3f}s")
    if manifest.is_partial:
        table.add_row("Partial", "yes")
        if manifest.completed_through is not None:
            table.add_row("Completed through", manifest.completed_through)
        if manifest.failed_stage is not None:
            table.add_row("Failed stage", manifest.failed_stage)
    return table


def _record_counts_table(manifest: Manifest) -> Table:
    table = Table(title="Records per split", expand=False)
    table.add_column("split", style="bold")
    table.add_column("count", justify="right")
    if not manifest.record_counts:
        table.add_row("(none)", "-")
    else:
        for split, count in sorted(manifest.record_counts.items()):
            table.add_row(split, str(count))
    return table


def _warnings_table(manifest: Manifest) -> Table:
    table = Table(title="Warnings", expand=False, border_style="yellow")
    table.add_column("stage", style="bold")
    table.add_column("message")
    for w in manifest.warnings:
        table.add_row(w.stage, w.message)
    return table
