# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-2 ``datarefinery validate`` — recipe-validation CLI verb.

Loads the recipe (applying any requested variant overlay), runs every
registered FR-2 check, and renders the 18-entry :class:`ValidationReport`
as a `rich` table (id, status, location, message). Exits 0 if every
check passes (warnings allowed), exits 1 if any check failed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from datarefinery.cli._exit_codes import EXIT_OK, EXIT_USER
from datarefinery.core.datarefinery import DataRefinery
from datarefinery.recipe.validator import CheckResult, ValidationReport

_STATUS_STYLES = {
    "pass": "[green]pass[/green]",
    "warn": "[yellow]warn[/yellow]",
    "fail": "[red]fail[/red]",
}


def validate(
    ctx: typer.Context,
    recipe: Annotated[
        Path,
        typer.Argument(
            help="Path to the recipe YAML file to validate.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
) -> None:
    """Run schema + enumerated checks (FR-2) on a recipe."""
    state = ctx.obj or {}
    config = state.get("config")
    variant = state.get("variant")

    dr = DataRefinery.from_recipe(recipe, config=config, variant=variant)
    report = dr.validate()

    console = Console(no_color=state.get("no_color", False))
    _render(console, recipe, report)

    raise typer.Exit(code=EXIT_OK if report.passed else EXIT_USER)


def _render(
    console: Console, recipe_path: Path, report: ValidationReport
) -> None:
    console.print(_results_table(recipe_path, report.results))
    console.print(_summary_line(report))


def _results_table(
    recipe_path: Path, results: tuple[CheckResult, ...]
) -> Table:
    table = Table(
        title=f"FR-2 validation — {recipe_path}",
        expand=False,
    )
    table.add_column("id", justify="right", style="bold")
    table.add_column("status")
    table.add_column("descriptor")
    table.add_column("location")
    table.add_column("message")
    for r in results:
        table.add_row(
            str(r.check_id),
            _STATUS_STYLES.get(r.status, r.status),
            r.descriptor,
            r.location or "-",
            r.message,
        )
    return table


def _summary_line(report: ValidationReport) -> str:
    failures = len(report.failures)
    warnings = len(report.warnings)
    total = len(report.results)
    if report.passed and warnings == 0:
        return f"[green]{total}/{total} checks passed.[/green]"
    if report.passed:
        return (
            f"[yellow]{total - warnings}/{total} checks passed; "
            f"{warnings} warning(s).[/yellow]"
        )
    return (
        f"[red]{failures} check(s) failed[/red] "
        f"({warnings} warning(s); {total} total)."
    )
