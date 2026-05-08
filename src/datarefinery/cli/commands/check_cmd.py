# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-18 ``datarefinery check`` — environment soundness CLI verb.

Invokes :func:`DataRefinery.check` and renders the structured
:class:`CheckReport` as a stack of `rich` tables on stdout. Exits 0 on a
healthy environment (with warning rows for missing optional deps), exits
2 on a soundness failure such as plugin discovery erroring out.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from datarefinery.cli._exit_codes import EXIT_OK, EXIT_SYSTEM
from datarefinery.core.check import CheckReport
from datarefinery.core.datarefinery import DataRefinery


def check(ctx: typer.Context) -> None:
    """Report environment soundness."""
    config = ctx.obj["config"] if ctx.obj else None
    report = DataRefinery.check(config)

    console = Console(no_color=ctx.obj.get("no_color", False) if ctx.obj else False)
    _render(console, report)

    raise typer.Exit(code=EXIT_OK if report.passed else EXIT_SYSTEM)


def _render(console: Console, report: CheckReport) -> None:
    console.print(_environment_table(report))
    console.print(_plugins_table(report))
    console.print(_extras_table("Optional extras", report.optional_extras))
    console.print(_extras_table("Accelerators", report.accelerators))
    if report.failures:
        console.print(_failures_table(report))


def _environment_table(report: CheckReport) -> Table:
    table = Table(title="Environment", show_header=False, expand=False)
    table.add_column("key", style="bold cyan")
    table.add_column("value")
    table.add_row("DataRefinery version", report.datarefinery_version)
    table.add_row("Python version", report.python_version)
    table.add_row("Platform", report.platform)
    table.add_row("Plugin entry-point group", report.entry_point_group)
    extra = (
        ", ".join(str(p) for p in report.extra_plugin_paths)
        if report.extra_plugin_paths
        else "(none)"
    )
    table.add_row("Extra plugin paths", extra)
    return table


def _plugins_table(report: CheckReport) -> Table:
    table = Table(title="Plugins", expand=False)
    table.add_column("name", style="bold")
    table.add_column("schema")
    table.add_column("kind")
    table.add_column("module")
    if not report.plugins:
        table.add_row("(none discovered)", "-", "-", "-")
    else:
        for p in report.plugins:
            kind = "stub" if p.is_stub else "active"
            table.add_row(p.name, str(p.schema_version), kind, p.module)
    return table


def _extras_table(title: str, items: tuple) -> Table:  # type: ignore[type-arg]
    table = Table(title=title, expand=False)
    table.add_column("name", style="bold")
    table.add_column("status")
    table.add_column("detail")
    if not items:
        table.add_row("(none probed)", "-", "-")
    else:
        for dep in items:
            status = "[green]available[/green]" if dep.available else "[yellow]missing[/yellow]"
            table.add_row(dep.name, status, dep.detail)
    return table


def _failures_table(report: CheckReport) -> Table:
    table = Table(title="Failures", expand=False, border_style="red")
    table.add_column("message")
    for msg in report.failures:
        table.add_row(msg)
    return table
