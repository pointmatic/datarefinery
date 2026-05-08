# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-17 ``datarefinery init`` — deterministic recipe scaffolder CLI verb.

Thin wrapper around :func:`datarefinery.scaffolder.init.scaffold`. The
deterministic path is offline and never imports the optional `lmentry`
extra (per features.md FR-17 #2); ``--enhance`` opts in to the lazy
LLM-enhancement layer, which raises ``PluginError`` with the documented
install snippet if the extra is missing.

v1 supports `image_classification` only; tabular/text scaffolds are
declared in the dispatcher and refuse with a documented message.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from datarefinery.cli._exit_codes import EXIT_OK
from datarefinery.scaffolder.init import scaffold


def init(
    ctx: typer.Context,
    input_path: Annotated[
        Path,
        typer.Option(
            "--input",
            "-i",
            help="Root directory of raw inputs (ImageFolder layout for "
            "image_classification: <root>/<class>/<file>.{png,jpg,jpeg}).",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
        ),
    ],
    output_path: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Path to write the scaffolded recipe YAML.",
        ),
    ],
    plugin: Annotated[
        str,
        typer.Option(
            "--plugin",
            help="Plugin scaffolder to use; v1 supports image_classification only.",
        ),
    ] = "image_classification",
    enhance: Annotated[
        bool,
        typer.Option(
            "--enhance",
            help="Apply optional LLM enhancement layer (requires the "
            "[llm] extra: pip install 'datarefinery[llm]').",
        ),
    ] = False,
) -> None:
    """Scaffold a starter recipe from raw inputs (FR-17)."""
    scaffold(
        input_path=input_path,
        output_path=output_path,
        plugin=plugin,
        enhance=enhance,
    )

    console = Console(no_color=ctx.obj.get("no_color", False) if ctx.obj else False)
    console.print(
        f"[green]Scaffolded[/green] {plugin} recipe → {output_path}"
    )
    console.print(
        "Next: review the recipe, then run "
        f"[bold]datarefinery validate {output_path}[/bold]."
    )

    raise typer.Exit(code=EXIT_OK)
