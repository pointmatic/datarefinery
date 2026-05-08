# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Typer CLI entry point for DataRefinery."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import click
import typer
from rich.console import Console
from rich.panel import Panel

from datarefinery import __version__
from datarefinery.cli._exit_codes import (
    EXIT_INTERRUPT,
    EXIT_OK,
    EXIT_SYSTEM,
    exit_code_for,
)
from datarefinery.cli.commands.check_cmd import check as check_cmd
from datarefinery.cli.commands.init_cmd import init as init_cmd
from datarefinery.cli.commands.inspect_cmd import inspect as inspect_cmd
from datarefinery.cli.commands.materialize_cmd import materialize as materialize_cmd
from datarefinery.cli.commands.report_cmd import report as report_cmd
from datarefinery.cli.commands.status_cmd import status as status_cmd
from datarefinery.cli.commands.validate_cmd import validate as validate_cmd
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import DataRefineryError
from datarefinery.logging import get_logger

app = typer.Typer(
    name="datarefinery",
    help="DataRefinery — recipe-driven data preparation and caching for ML.",
    no_args_is_help=False,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the package version and exit.",
        ),
    ] = False,
    cache_root: Annotated[
        Path | None,
        typer.Option(
            "--cache-root",
            help="Root directory for the cache (env: DATAREFINERY_CACHE_ROOT).",
        ),
    ] = None,
    log_level: Annotated[
        str | None,
        typer.Option(
            "--log-level",
            help="Log level (env: DATAREFINERY_LOG_LEVEL).",
        ),
    ] = None,
    log_target: Annotated[
        str | None,
        typer.Option(
            "--log-target",
            help="Log routing target; reserved no-op stub "
            "(env: DATAREFINERY_LOG_TARGET).",
        ),
    ] = None,
    plugin_path: Annotated[
        list[Path] | None,
        typer.Option(
            "--plugin-path",
            help="Extra plugin discovery path; repeatable "
            "(env: DATAREFINERY_PLUGIN_PATH, PATH-style).",
        ),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option(
            "--workers",
            help="Process pool worker count (env: DATAREFINERY_WORKERS).",
        ),
    ] = None,
    seed: Annotated[
        int | None,
        typer.Option(
            "--seed",
            help="Override the recipe-declared seed (changes cache identity).",
        ),
    ] = None,
    variant: Annotated[
        str | None,
        typer.Option("--variant", help="Recipe variant to apply before canonicalization."),
    ] = None,
    no_color: Annotated[
        bool,
        typer.Option("--no-color", help="Disable colored output."),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress non-essential output."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output."),
    ] = False,
) -> None:
    """DataRefinery — recipe-driven data preparation and caching for ML."""
    config = RuntimeConfig.resolve(
        cache_root=cache_root,
        log_level=log_level,
        log_target=log_target,
        plugin_path=plugin_path,
        workers=workers,
    )
    state = ctx.ensure_object(dict)
    state["config"] = config
    state["seed"] = seed
    state["variant"] = variant
    state["no_color"] = no_color
    state["quiet"] = quiet
    state["verbose"] = verbose

    get_logger("cli")
    return None


app.command("check", help="Report environment soundness (FR-18).")(check_cmd)
app.command("validate", help="Validate a recipe (FR-2).")(validate_cmd)
app.command("init", help="Scaffold a starter recipe from raw inputs (FR-17).")(init_cmd)
app.command(
    "materialize",
    help="Run the pipeline end-to-end against the recipe's inputs (FR-3).",
)(materialize_cmd)
app.command(
    "status",
    help="Summarize a materialized instance or resolve a recipe to one (FR-19).",
)(status_cmd)
app.command(
    "report",
    help="Re-render report.md, drift.json, and reporting visualizations (FR-15).",
)(report_cmd)
app.command(
    "inspect",
    help="Read-only views of a materialized instance (FR-20).",
)(inspect_cmd)


def _render_error(message: str, *, title: str) -> None:
    Console(stderr=True).print(
        Panel(message, title=title, border_style="red", expand=False)
    )


def main_entry() -> None:
    """Console-script entry point with DataRefinery's exit-code mapping."""
    try:
        app(standalone_mode=False)
    except click.exceptions.Exit as exc:
        sys.exit(exc.exit_code)
    except click.exceptions.UsageError as exc:
        exc.show()
        sys.exit(EXIT_SYSTEM)
    except click.exceptions.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except (click.exceptions.Abort, KeyboardInterrupt):
        _render_error("Interrupted.", title="Aborted")
        sys.exit(EXIT_INTERRUPT)
    except DataRefineryError as exc:
        _render_error(str(exc) or type(exc).__name__, title=type(exc).__name__)
        sys.exit(exit_code_for(exc))
    except Exception as exc:
        _render_error(f"{type(exc).__name__}: {exc}", title="Internal Error")
        sys.exit(EXIT_SYSTEM)
    sys.exit(EXIT_OK)
