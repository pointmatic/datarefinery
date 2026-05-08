# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-15 report.md renderer tests (Story C.n)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from datarefinery.cache.layout import (
    fitted_stats_dir,
    manifest_path,
    report_dir,
)
from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.manifest import (
    Manifest,
    ManifestWarning,
    write_manifest,
)
from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.models import Recipe
from datarefinery.reporting.report import (
    list_fitted_op_ids,
    re_render_report,
    render_report_md,
)


def _recipe() -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [
                    {
                        "name": "train",
                        "type": "image_folder",
                        "path": "/data/train",
                    }
                ]
            },
            "Output": {
                "record_schema": {"image": {"dtype": "uint8"}, "label": {"dtype": "str"}}
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.6, "val": 0.2, "test": 0.2}, "seed": 11},
            "Transformations": [
                {
                    "name": "norm",
                    "op": "normalize",
                    "fit_source": "train",
                    "splits": ["train", "val", "test"],
                }
            ],
            "Visualizations": [
                {
                    "name": "hist",
                    "op": "class_distribution_histogram",
                    "stage": "post_pipeline",
                    "mode": "reporting",
                }
            ],
        }
    )


def _manifest(recipe: Recipe, *, warnings: list[ManifestWarning] | None = None) -> Manifest:
    rh = hashlib.sha256(to_canonical_bytes(recipe)).hexdigest()
    return Manifest(
        datarefinery_version="0.3.12",
        plugin="image_classification",
        plugin_version="1",
        recipe_hash=rh,
        input_hash="a" * 64,
        seed=7,
        variant=None,
        created_at=datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC),
        elapsed_seconds=1.23,
        record_counts={"train": 6, "val": 2, "test": 2},
        warnings=warnings or [],
    )


# ---------------------------------------------------------------------------
# render_report_md content
# ---------------------------------------------------------------------------


def test_report_includes_manifest_summary() -> None:
    recipe = _recipe()
    manifest = _manifest(recipe)
    md = render_report_md(recipe, manifest, fitted_op_ids=["norm"])
    assert "# DataRefinery report" in md
    assert "image_classification" in md
    assert manifest.recipe_hash in md
    assert manifest.input_hash in md
    assert "Seed: `7`" in md
    assert "1.230s" in md


def test_report_includes_inputs_and_splits() -> None:
    recipe = _recipe()
    manifest = _manifest(recipe)
    md = render_report_md(recipe, manifest)
    assert "## Inputs" in md
    assert "`train` (`image_folder`)" in md
    assert "## Splits" in md
    assert "`train`: 6 record(s)" in md
    assert "Total**: 10" in md


def test_report_lists_operations_per_section() -> None:
    recipe = _recipe()
    manifest = _manifest(recipe)
    md = render_report_md(recipe, manifest)
    assert "### Transformations" in md
    assert "norm (`normalize`)" in md
    assert "### Visualizations" in md
    assert "hist (`class_distribution_histogram`, mode=reporting)" in md
    # Empty sections render `(none)`.
    assert "### Filters" in md
    assert "(none)" in md


def test_report_lists_fitted_op_ids() -> None:
    recipe = _recipe()
    manifest = _manifest(recipe)
    md = render_report_md(recipe, manifest, fitted_op_ids=["norm", "tfidf"])
    assert "## Fitted statistics" in md
    assert "- `norm`" in md
    assert "- `tfidf`" in md


def test_report_lists_fitted_none_when_empty() -> None:
    md = render_report_md(_recipe(), _manifest(_recipe()))
    assert "## Fitted statistics" in md
    section = md.split("## Fitted statistics")[1].split("## Warnings")[0]
    assert "(none)" in section


def test_report_lists_warnings() -> None:
    recipe = _recipe()
    warnings = [
        ManifestWarning(stage="Splits", message="ratio remainder unassigned"),
    ]
    md = render_report_md(recipe, _manifest(recipe, warnings=warnings))
    assert "**Splits**: ratio remainder unassigned" in md


def test_report_partial_run_marker() -> None:
    recipe = _recipe()
    base = _manifest(recipe)
    partial = base.model_copy(
        update={"is_partial": True, "failed_stage": "Visualizations"}
    )
    md = render_report_md(recipe, partial)
    assert "**Partial**" in md
    assert "Visualizations" in md


def test_report_is_byte_stable_for_identical_inputs() -> None:
    recipe = _recipe()
    manifest = _manifest(recipe)
    a = render_report_md(recipe, manifest, fitted_op_ids=["norm"])
    b = render_report_md(recipe, manifest, fitted_op_ids=["norm"])
    assert a == b


# ---------------------------------------------------------------------------
# list_fitted_op_ids helper
# ---------------------------------------------------------------------------


def test_list_fitted_op_ids_empty_when_dir_missing(tmp_path: Path) -> None:
    assert list_fitted_op_ids(tmp_path / "missing") == []


def test_list_fitted_op_ids_returns_sorted_subdirs(tmp_path: Path) -> None:
    (tmp_path / "z").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "m").mkdir()
    (tmp_path / "not_a_dir.txt").write_text("hello")
    assert list_fitted_op_ids(tmp_path) == ["a", "m", "z"]


# ---------------------------------------------------------------------------
# re_render_report (FR-15.4) and stale-fitted-stats hard error
# ---------------------------------------------------------------------------


def test_re_render_writes_report_md(tmp_path: Path) -> None:
    recipe = _recipe()
    manifest = _manifest(recipe)
    instance = tmp_path / "instance"
    instance.mkdir()
    write_manifest(manifest_path(instance), manifest)
    fitted_stats_dir(instance).mkdir(parents=True)
    (fitted_stats_dir(instance) / "norm").mkdir()

    re_render_report(instance, recipe)

    out = report_dir(instance) / "report.md"
    assert out.exists()
    content = out.read_text()
    assert "DataRefinery report" in content
    assert "norm" in content


def test_re_render_recipe_hash_mismatch_raises(tmp_path: Path) -> None:
    recipe = _recipe()
    manifest = _manifest(recipe)
    instance = tmp_path / "instance"
    instance.mkdir()
    write_manifest(manifest_path(instance), manifest)

    # Tamper: hand in a different recipe.
    other = recipe.model_copy(update={"seed": 999})
    with pytest.raises(MaterializeError, match="recipe hash mismatch"):
        re_render_report(instance, other)


def test_re_render_overwrites_existing_report(tmp_path: Path) -> None:
    recipe = _recipe()
    manifest = _manifest(recipe)
    instance = tmp_path / "instance"
    instance.mkdir()
    write_manifest(manifest_path(instance), manifest)
    out = report_dir(instance) / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("stale content")

    re_render_report(instance, recipe)
    assert "stale content" not in out.read_text()
