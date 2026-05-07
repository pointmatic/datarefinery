# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Typer CLI entry point for DataRefinery."""

from __future__ import annotations

from typing import Annotated

import typer

from datarefinery import __version__

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
) -> None:
    """DataRefinery — recipe-driven data preparation and caching for ML."""
    return None
