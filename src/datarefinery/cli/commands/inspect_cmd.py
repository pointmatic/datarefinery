# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-20 ``datarefinery inspect`` — read-only views CLI verb.

Two modes:

- **List + peek** (no ``--view``): prints the exploration-mode
  visualizations declared in the instance's recipe, the persisted
  fitted-statistics op ids, per-split record counts, and a small
  sample of records from each split's JSONL.
- **Render** (``--view NAME``): renders the named exploration
  visualization on demand and either streams the PNG bytes to
  ``--out PATH`` or, if no out path is supplied, prints a one-line
  byte-count summary.

A partial (FAILED or ``--stage``-stopped) instance is refused with the
documented pointer per the FR-20 edge case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from datarefinery.cli._exit_codes import EXIT_OK
from datarefinery.core.datarefinery import DataRefinery
from datarefinery.core.errors import MaterializeError
from datarefinery.core.inspect import InspectionView


def inspect(
    ctx: typer.Context,
    target: Annotated[
        Path,
        typer.Argument(
            help="Recipe YAML file or materialized instance directory.",
            exists=True,
            readable=True,
        ),
    ],
    view: Annotated[
        str | None,
        typer.Option(
            "--view",
            help="Render the named exploration visualization on demand.",
        ),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="Write the rendered visualization to this path "
            "(only valid with --view).",
        ),
    ] = None,
) -> None:
    """Read-only views over a materialized instance (FR-20)."""
    state = ctx.obj or {}
    config = state.get("config")
    variant = state.get("variant")
    seed = state.get("seed")
    no_color = state.get("no_color", False)

    if out is not None and view is None:
        raise MaterializeError(
            "inspect: --out requires --view (it has no meaning in list mode)"
        )

    inspection = _resolve_inspection(
        target, config=config, variant=variant, seed=seed, view=view
    )

    console = Console(no_color=no_color)
    if inspection.rendered is not None and out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(inspection.rendered.png_bytes)
        console.print(
            f"[green]Rendered[/green] view {inspection.rendered.name!r} "
            f"({len(inspection.rendered.png_bytes)} bytes) → {out}"
        )
    elif inspection.rendered is not None:
        console.print(
            f"[green]Rendered[/green] view {inspection.rendered.name!r} "
            f"({len(inspection.rendered.png_bytes)} bytes); "
            f"pass --out to write."
        )
    else:
        _render_listing(console, inspection)

    raise typer.Exit(code=EXIT_OK)


def _resolve_inspection(
    target: Path,
    *,
    config: object,
    variant: str | None,
    seed: int | None,
    view: str | None,
) -> InspectionView:
    """Build an :class:`InspectionView` from either a recipe or instance path."""
    if target.is_dir():
        # Instance-path mode. We still need a DataRefinery to reach the
        # plugin; use the persisted recipe to construct one without a
        # YAML file on disk.
        from datarefinery.core.instance import Instance

        instance = Instance.load(target)
        # Reconstruct a DataRefinery bound to the instance's recipe so
        # plugin lookup and validation reuse the same machinery as
        # recipe-path mode. We sidestep the YAML loader by writing the
        # recipe.json contents to a temp file? No — simpler: discover
        # the plugin directly and build the view.
        from datarefinery.core.inspect import build_inspection_view
        from datarefinery.plugins.discovery import discover_plugins

        extra = (
            tuple(config.plugin_path)  # type: ignore[attr-defined]
            if config is not None
            else ()
        )
        plugins = discover_plugins(extra_paths=extra or None)
        plugin_name = instance.recipe.plugin
        if plugin_name not in plugins:
            raise MaterializeError(
                f"inspect: instance recipe references plugin "
                f"{plugin_name!r} but discovery only found "
                f"{sorted(plugins)!r}"
            )
        return build_inspection_view(instance, plugins[plugin_name], view=view)

    dr = DataRefinery.from_recipe(
        target,
        config=config,  # type: ignore[arg-type]
        variant=variant,
        seed=seed,
    )
    return dr.inspect(view=view)


def _render_listing(console: Console, inspection: InspectionView) -> None:
    overview = Table(title="Inspect", show_header=False, expand=False)
    overview.add_column("key", style="bold cyan")
    overview.add_column("value")
    overview.add_row("Instance", str(inspection.instance_path))
    overview.add_row(
        "Exploration views",
        ", ".join(inspection.exploration_views) or "(none)",
    )
    overview.add_row(
        "Fitted statistics",
        ", ".join(inspection.fitted_op_ids) or "(none)",
    )
    console.print(overview)

    counts_table = Table(title="Records per split", expand=False)
    counts_table.add_column("split", style="bold")
    counts_table.add_column("count", justify="right")
    if not inspection.record_counts:
        counts_table.add_row("(none)", "-")
    else:
        for split, count in sorted(inspection.record_counts.items()):
            counts_table.add_row(split, str(count))
    console.print(counts_table)

    if inspection.sample_records:
        peek_table = Table(title="Sample records", expand=False)
        peek_table.add_column("split", style="bold")
        peek_table.add_column("row", overflow="fold")
        for split in sorted(inspection.sample_records):
            for row in inspection.sample_records[split]:
                peek_table.add_row(split, json.dumps(row, sort_keys=True))
        console.print(peek_table)
