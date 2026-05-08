# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-21 ``datarefinery clean`` — cache management CLI verb.

Wraps :func:`datarefinery.cache.cleaner.clean` with typer options. The
library already supports every selector via :class:`CleanSelector`; the
verb's job is option parsing, ``--all`` confirmation, and rendering
the :class:`CleanReport` as a `rich` table.

Selector semantics (intersection across the ``--by-*`` filters, union
with ``--orphans``):

- ``--by-recipe HASH``: remove instances whose recipe-hash shard
  matches the first 16 chars of ``HASH``.
- ``--by-age DAYS``: remove instances older than ``DAYS`` (mtime).
- ``--orphans``: remove temp dirs in ``.tmp/`` older than 1 day.
- ``--all``: clear every direct child of ``<cache-root>/instances/``.
  Requires either an interactive TTY confirmation or ``--yes`` for
  non-TTY use.

The verb refuses if no selector is given, matching the FR-21 "no
silent broad delete" rule.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from datarefinery.cache.cleaner import CleanReport, CleanSelector, clean
from datarefinery.cli._exit_codes import EXIT_OK
from datarefinery.core.errors import CacheError


def clean_command(
    ctx: typer.Context,
    by_recipe: Annotated[
        str | None,
        typer.Option(
            "--by-recipe",
            help="Remove instances whose recipe-hash shard matches HASH "
            "(first 16 hex chars).",
        ),
    ] = None,
    by_age: Annotated[
        float | None,
        typer.Option(
            "--by-age",
            help="Remove instances older than this many days (mtime).",
        ),
    ] = None,
    orphans: Annotated[
        bool,
        typer.Option(
            "--orphans",
            help="Also remove temp directories in .tmp/ older than 1 day.",
        ),
    ] = False,
    all_: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Remove every cached instance. Requires confirmation or --yes.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Skip the interactive confirmation for --all (required in "
            "non-TTY contexts).",
        ),
    ] = False,
) -> None:
    """Manage cache contents (FR-21)."""
    state = ctx.obj or {}
    config = state.get("config")
    no_color = state.get("no_color", False)

    if config is None:
        raise CacheError("clean: runtime config not initialized")
    cache_root: Path = config.cache_root

    if not (by_recipe or by_age is not None or orphans or all_):
        raise CacheError(
            "clean: no selector given. Choose one of --by-recipe, "
            "--by-age, --orphans, or --all (with confirmation)."
        )

    if all_:
        _confirm_destructive(cache_root, yes=yes)

    selector = CleanSelector(
        by_recipe_hash=by_recipe,
        by_age_days=by_age,
        orphans=orphans,
        all=all_,
    )
    report = clean(cache_root, selector, force=all_)

    console = Console(no_color=no_color)
    _render(console, cache_root, report)
    raise typer.Exit(code=EXIT_OK)


def _confirm_destructive(cache_root: Path, *, yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        raise CacheError(
            "clean --all in a non-interactive context requires --yes "
            "(refusing to wipe the cache without explicit confirmation)."
        )
    confirmed = typer.confirm(
        f"This will remove every cached instance under {cache_root}. Continue?",
        default=False,
    )
    if not confirmed:
        raise typer.Exit(code=EXIT_OK)


def _render(console: Console, cache_root: Path, report: CleanReport) -> None:
    summary = Table(title="Clean", show_header=False, expand=False)
    summary.add_column("key", style="bold cyan")
    summary.add_column("value")
    summary.add_row("Cache root", str(cache_root))
    summary.add_row("Removed", str(len(report.removed)))
    summary.add_row("Skipped", str(len(report.skipped)))
    console.print(summary)

    if report.removed:
        rm = Table(title="Removed", expand=False)
        rm.add_column("path")
        for p in report.removed:
            rm.add_row(str(p))
        console.print(rm)

    if report.skipped:
        sk = Table(title="Skipped", expand=False, border_style="yellow")
        sk.add_column("path", style="bold")
        sk.add_column("reason")
        for path, reason in report.skipped:
            sk.add_row(str(path), reason)
        console.print(sk)
