# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-15 ``report.md`` renderer.

Builds the human-readable summary from a recipe + manifest + an
optional fitted-statistics directory. The renderer is pure: same inputs
-> identical markdown bytes (apart from intrinsically run-specific
manifest fields like ``created_at``/``elapsed_seconds`` which the caller
chooses to include).

FR-15.4 re-render: :func:`re_render_report` regenerates the report
files from a materialized instance directory without rerunning the
pipeline. It enforces the FR-15 edge case "re-rendering a report
against a stale fitted-statistics block -> hard error citing the
inconsistency" by comparing the manifest's ``recipe_hash`` against the
canonical hash of the recipe handed in.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from datarefinery.cache.layout import (
    fitted_stats_dir,
    manifest_path,
    report_dir,
)
from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.manifest import Manifest, read_manifest
from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.models import Recipe

REPORT_FILENAME = "report.md"
DRIFT_FILENAME = "drift.json"


def render_report_md(
    recipe: Recipe,
    manifest: Manifest,
    *,
    fitted_op_ids: Iterable[str] = (),
) -> str:
    """Build the ``report.md`` text for a materialized instance."""
    lines: list[str] = []
    lines.append(f"# DataRefinery report — {manifest.plugin}")
    lines.append("")
    lines.append("## Manifest summary")
    lines.append("")
    lines.append(f"- DataRefinery version: `{manifest.datarefinery_version}`")
    lines.append(f"- Plugin: `{manifest.plugin}` (v{manifest.plugin_version})")
    lines.append(f"- Recipe hash: `{manifest.recipe_hash}`")
    lines.append(f"- Input hash: `{manifest.input_hash}`")
    lines.append(f"- Seed: `{manifest.seed}`")
    if manifest.variant is not None:
        lines.append(f"- Variant: `{manifest.variant}`")
    lines.append(f"- Created at: `{manifest.created_at.isoformat()}`")
    lines.append(f"- Elapsed: `{manifest.elapsed_seconds:.3f}s`")
    if manifest.is_partial:
        lines.append(f"- **Partial**: failed at stage `{manifest.failed_stage}`")
    lines.append("")

    lines.append("## Inputs")
    lines.append("")
    for src in recipe.Input.sources:
        lines.append(f"- `{src.name}` (`{src.type}`) -> `{src.path}`")
    lines.append("")

    from datarefinery.recipe.validator import unlabeled_split_names

    unlabeled = unlabeled_split_names(recipe)
    lines.append("## Splits")
    lines.append("")
    for split, count in sorted(manifest.record_counts.items()):
        marker = " *(unlabeled)*" if split in unlabeled else ""
        lines.append(f"- `{split}`: {count} record(s){marker}")
    lines.append(f"- **Total**: {sum(manifest.record_counts.values())}")
    lines.append("")

    lines.append("## Operations applied")
    lines.append("")
    _section_header(lines, "Filters", recipe.Filters, lambda op: op.name)
    _section_header(lines, "Generation", recipe.Generation, lambda op: op.name)
    _section_header(
        lines,
        "Transformations",
        recipe.Transformations,
        lambda op: f"{op.name} (`{op.op}`)",
    )
    _section_header(
        lines,
        "Featurizations",
        recipe.Featurizations,
        lambda op: f"{op.name} -> `{op.output_field}`",
    )
    _section_header(
        lines,
        "Augmentations (policy-only)",
        recipe.Augmentations,
        lambda op: f"{op.name} (`{op.op}`)",
    )
    _section_header(
        lines,
        "Visualizations",
        recipe.Visualizations,
        lambda op: f"{op.name} (`{op.op}`, mode={op.mode})",
    )

    lines.append("## Fitted statistics")
    lines.append("")
    fitted_list = sorted(set(fitted_op_ids))
    if fitted_list:
        for op_id in fitted_list:
            lines.append(f"- `{op_id}`")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Warnings")
    lines.append("")
    if manifest.warnings:
        for w in manifest.warnings:
            lines.append(f"- **{w.stage}**: {w.message}")
    else:
        lines.append("- (none)")
    lines.append("")

    return "\n".join(lines)


def _section_header(
    lines: list[str],
    label: str,
    ops: list,  # type: ignore[type-arg]
    fmt: object,  # callable
) -> None:
    lines.append(f"### {label}")
    lines.append("")
    if not ops:
        lines.append("- (none)")
    else:
        for op in ops:
            lines.append(f"- {fmt(op)}")  # type: ignore[operator]
    lines.append("")


def write_report(path: Path, content: str) -> None:
    """Persist the report markdown to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def list_fitted_op_ids(fitted_root: Path) -> list[str]:
    """Return the sorted list of op_ids that have persisted statistics."""
    if not fitted_root.exists():
        return []
    return sorted(p.name for p in fitted_root.iterdir() if p.is_dir())


def re_render_report(
    instance_dir: Path,
    recipe: Recipe,
    *,
    plugin: object | None = None,
) -> None:
    """FR-15.4: regenerate ``report.md``, ``drift.json``, and reporting
    visualizations for an existing instance.

    Does NOT rerun the pipeline. Reads the persisted manifest, asserts
    its ``recipe_hash`` matches the canonical hash of the recipe we
    were handed (FR-15 edge case: stale fitted-stats vs. manifest is a
    hard error), then:

    1. Re-renders ``report.md`` from the manifest + fitted-stats
       directory.
    2. Reloads the persisted dataset (via
       :func:`pipeline.inputs.reload_dataset`) and rewrites
       ``drift.json`` from the per-split record lists.
    3. Re-renders every reporting-mode :class:`VisualizationOp` in the
       recipe and writes the PNG bytes under
       ``report/visualizations/``.

    Steps 2 and 3 require a ``plugin`` to be passed (so we can look up
    visualization op factories and reload plugin-specific record
    fields). When ``plugin`` is omitted only step 1 runs - useful for
    library callers that have already validated stat consistency and
    only want the markdown refreshed.
    """
    instance_dir = Path(instance_dir)
    manifest = read_manifest(manifest_path(instance_dir))

    expected_hash = hashlib.sha256(to_canonical_bytes(recipe)).hexdigest()
    if manifest.recipe_hash != expected_hash:
        raise MaterializeError(
            f"re_render_report: recipe hash mismatch with manifest. "
            f"Manifest says recipe_hash={manifest.recipe_hash[:16]!r}..., "
            f"recipe handed in canonicalizes to "
            f"{expected_hash[:16]!r}.... Re-rendering against a stale "
            f"fitted-statistics block is rejected per FR-15."
        )

    fitted_ids = list_fitted_op_ids(fitted_stats_dir(instance_dir))
    report_root = report_dir(instance_dir)
    content = render_report_md(recipe, manifest, fitted_op_ids=fitted_ids)
    write_report(report_root / REPORT_FILENAME, content)

    if plugin is None:
        return

    # Lazy-imported to avoid a hard dependency cycle: the plugin loader
    # imports the reporting module transitively.
    from datarefinery.pipeline.inputs import reload_dataset
    from datarefinery.pipeline.stages.visualizations import (
        apply_reporting_visualizations,
    )
    from datarefinery.plugins.base import Plugin
    from datarefinery.reporting.drift import (
        compute_drift_placeholder,
        write_drift,
    )

    if not isinstance(plugin, Plugin):
        raise MaterializeError(
            f"re_render_report: plugin argument must satisfy the Plugin "
            f"protocol; got {type(plugin).__name__}"
        )

    splits = reload_dataset(instance_dir, plugin)
    # Pydantic-validated `Mapping` parameters are invariant in mypy;
    # the runtime types are a strict subset, so cast through `Any`.
    splits_any: Any = splits
    from datarefinery.recipe.validator import unlabeled_split_names

    drift = compute_drift_placeholder(
        splits_any,
        plugin_name=plugin.name,
        label_field=recipe.Labels.field,
        unlabeled_splits=unlabeled_split_names(recipe),
    )
    write_drift(report_root / DRIFT_FILENAME, drift)

    apply_reporting_visualizations(
        splits_any,
        recipe.Visualizations,
        plugin=plugin,
        output_dir=report_root / "visualizations",
        label_field=recipe.Labels.field,
    )
