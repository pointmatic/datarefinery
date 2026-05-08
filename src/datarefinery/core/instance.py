# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Loaded materialized-instance accessor.

`Instance` represents the on-disk artifacts of a successful (or failed)
pipeline run: the manifest, the canonicalized recipe used, the
fitted-statistics directory, and the report path. Instances are loaded
from a directory laid out by `cache.layout` and the pipeline runner.

Fitted statistics are exposed lazily: `Instance.fitted_statistics` is a
`FittedStatistics` view rooted at the instance's `fitted_statistics/`
subdirectory, with no file I/O performed at construction time. Callers
only pay for I/O when they `get_scalar` / `get_vector`.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

from datarefinery.cache.layout import (
    fitted_stats_dir,
    manifest_path,
    recipe_path,
    report_dir,
)
from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.manifest import Manifest, read_manifest
from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.models import Recipe
from datarefinery.reporting.report import REPORT_FILENAME, re_render_report


@dataclasses.dataclass(frozen=True)
class Instance:
    """One materialized DataRefinery instance loaded from disk."""

    path: Path
    manifest: Manifest
    recipe: Recipe
    fitted_statistics: FittedStatistics
    report_path: Path
    is_partial: bool

    @classmethod
    def load(cls, path: Path) -> Instance:
        """Load the instance rooted at `path`.

        Reads `manifest.json` and `recipe.json`, asserts the persisted
        recipe canonicalizes to the manifest's `recipe_hash`, and
        constructs a lazy `FittedStatistics` view. Does not read any
        fitted-statistics bytes; callers pay for that I/O on demand.
        """
        path = Path(path)
        m_path = manifest_path(path)
        if not m_path.exists():
            raise MaterializeError(
                f"Instance.load: no manifest.json at {m_path}; not a "
                f"materialized DataRefinery instance"
            )
        manifest = read_manifest(m_path)

        r_path = recipe_path(path)
        if not r_path.exists():
            raise MaterializeError(
                f"Instance.load: no recipe.json at {r_path}; instance "
                f"may predate the recipe-persistence convention"
            )
        recipe = Recipe.model_validate_json(r_path.read_text(encoding="utf-8"))

        actual_hash = hashlib.sha256(to_canonical_bytes(recipe)).hexdigest()
        if actual_hash != manifest.recipe_hash:
            raise MaterializeError(
                f"Instance.load: persisted recipe.json at {r_path} "
                f"canonicalizes to {actual_hash[:16]!r}... but the "
                f"manifest declares recipe_hash={manifest.recipe_hash[:16]!r}"
                f"...; instance directory is inconsistent"
            )

        return cls(
            path=path,
            manifest=manifest,
            recipe=recipe,
            fitted_statistics=FittedStatistics(fitted_stats_dir(path)),
            report_path=report_dir(path) / REPORT_FILENAME,
            is_partial=manifest.is_partial,
        )

    def render_report(self, *, plugin: object | None = None) -> None:
        """Re-render `report.md` (and optionally `drift.json` + reporting
        visualizations) from the persisted manifest + recipe.

        Does not rerun the pipeline. Pass ``plugin`` to also rewrite
        ``drift.json`` and the reporting-mode visualizations - those
        require an :class:`Plugin` instance to look up visualization op
        factories and to know how to re-inflate plugin-specific record
        fields. See FR-15.4.
        """
        re_render_report(self.path, self.recipe, plugin=plugin)
