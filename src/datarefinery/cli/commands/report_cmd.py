# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-15 ``datarefinery report`` — report re-render CLI verb.

Loads a previously-materialized instance, re-renders ``report.md``,
``drift.json``, and every reporting-mode visualization in place, and
exits 0. Never reruns the pipeline.

The recipe persisted under ``<instance>/recipe.json`` (Story D.a) is
the source of truth: its canonical hash is checked against the
manifest's ``recipe_hash``, and a mismatch raises
:class:`MaterializeError` per the FR-15 stale-fitted-stats edge case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from datarefinery.cache.layout import report_dir
from datarefinery.cli._exit_codes import EXIT_OK
from datarefinery.core.errors import PluginError
from datarefinery.core.instance import Instance
from datarefinery.plugins.discovery import discover_plugins
from datarefinery.reporting.report import DRIFT_FILENAME, REPORT_FILENAME


def report(
    ctx: typer.Context,
    instance_path: Annotated[
        Path,
        typer.Argument(
            help="Materialized instance directory to re-render.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
) -> None:
    """Re-render an instance's report from persisted state (FR-15.4)."""
    state = ctx.obj or {}
    config = state.get("config")
    no_color = state.get("no_color", False)

    instance = Instance.load(instance_path)
    plugin = _discover_plugin(
        instance.recipe.plugin,
        extra_paths=tuple(config.plugin_path) if config is not None else (),
    )
    instance.render_report(plugin=plugin)

    console = Console(no_color=no_color)
    rd = report_dir(instance.path)
    console.print(
        f"[green]Re-rendered[/green] report for {instance.path}"
    )
    console.print(f"  - {rd / REPORT_FILENAME}")
    console.print(f"  - {rd / DRIFT_FILENAME}")
    console.print(f"  - {rd / 'visualizations'}/ (reporting-mode PNGs)")

    raise typer.Exit(code=EXIT_OK)


def _discover_plugin(name: str, extra_paths: tuple[Path, ...]) -> object:
    plugins = discover_plugins(extra_paths=extra_paths or None)
    if name not in plugins:
        raise PluginError(
            f"report: instance recipe references plugin {name!r} but "
            f"discovery only found {sorted(plugins)!r}"
        )
    return plugins[name]
