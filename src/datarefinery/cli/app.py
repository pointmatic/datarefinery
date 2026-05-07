# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Typer CLI entry point for DataRefinery."""

from __future__ import annotations

import sys
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
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the package version and exit.",
        ),
    ] = False,
    log_target: Annotated[
        str | None,
        typer.Option(
            "--log-target",
            help="Log routing target (reserved; currently a no-op stub).",
        ),
    ] = None,
) -> None:
    """DataRefinery — recipe-driven data preparation and caching for ML."""
    del log_target
    get_logger("cli")
    return None


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
