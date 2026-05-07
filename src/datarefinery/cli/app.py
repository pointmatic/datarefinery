# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Typer CLI entry point for DataRefinery."""

from __future__ import annotations

from typing import Annotated

import typer

from datarefinery import __version__
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
    # Initialize the package logger on CLI startup. `--log-target` is a
    # reserved no-op stub; full routing lands in Story A.g.
    del log_target
    get_logger("cli")
    return None
