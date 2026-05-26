# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story I.f.1 — announced-skip semantics for partial-run sinks.

When ``materialize --stage <stop>`` halts early, sinks targeting
stages later than ``<stop>`` are *announced-skipped* rather than
silently dropped: the partial manifest carries their declared
stages under ``manifest.sinks_skipped`` so a consumer inspecting the
temp dir can see what would have fired without ``--stage``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from datarefinery.cache.layout import manifest_path
from datarefinery.cache.layout import tmp_dir as tmp_dir_for
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe


def _img(value: int) -> np.ndarray:
    return np.full((4, 4, 3), value, dtype=np.uint8)


def _records(n: int = 12) -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": _img(20 + i * 5),
            "label": f"c{i % 2}",
            "path": f"/data/c{i % 2}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _recipe_with_three_sinks() -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {
                "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
                "seed": 11,
            },
            "Sinks": [
                {
                    "name": "filter_pngs",
                    "stage": "post_Filters",
                    "field": "image",
                    "format": "png_per_record",
                    "path_template": "filter/{record_id}.png",
                },
                {
                    "name": "gen_pngs",
                    "stage": "post_Generation",
                    "field": "image",
                    "format": "png_per_record",
                    "path_template": "gen/{record_id}.png",
                },
                {
                    "name": "viz_pngs",
                    "stage": "post_Visualizations",
                    "field": "image",
                    "format": "png_per_record",
                    "path_template": "viz/{record_id}.png",
                },
            ],
        }
    )


def test_partial_run_reports_fired_and_skipped_sinks(tmp_path: Path) -> None:
    """`--stage Filters/post_split`: post_Filters sink fires, the
    later two (post_Generation, post_Visualizations) appear in
    `manifest.sinks_skipped`."""
    cache_root = tmp_path / "cache"
    recipe = _recipe_with_three_sinks()
    records = _records(12)
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-partial")
    result = runner.run(
        temp,
        raw_records=records,
        raw_input_hashes=_input_hashes(records),
        stop_after="Filters/post_split",
    )

    assert result.is_partial is True
    m = read_manifest(manifest_path(result.instance_dir))
    assert m.is_partial is True
    assert m.completed_through == "Filters/post_split"

    # post_Filters sink fired before the stop point; it should be in `sinks`.
    assert "filter_pngs" in m.sinks, sorted(m.sinks.keys())
    assert m.sinks["filter_pngs"].stage == "post_Filters"
    assert m.sinks["filter_pngs"].files_written > 0

    # post_Generation + post_Visualizations sinks are announced-skipped.
    assert m.sinks_skipped == {
        "gen_pngs": "post_Generation",
        "viz_pngs": "post_Visualizations",
    }


def test_full_run_has_empty_sinks_skipped(tmp_path: Path) -> None:
    """A full materialize fires every sink; `sinks_skipped` is empty."""
    cache_root = tmp_path / "cache"
    # Use just the post_Filters sink (post_Generation needs a Generation
    # op present, and post_Visualizations needs a reporting visualization
    # for non-empty output — both irrelevant to this test's contract).
    recipe = Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {
                "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
                "seed": 11,
            },
            "Sinks": [
                {
                    "name": "filter_pngs",
                    "stage": "post_Filters",
                    "field": "image",
                    "format": "png_per_record",
                    "path_template": "filter/{record_id}.png",
                },
            ],
        }
    )
    records = _records(12)
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-full")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    assert result.is_partial is False
    m = read_manifest(manifest_path(result.instance_dir))
    assert "filter_pngs" in m.sinks
    assert m.sinks_skipped == {}


def test_partial_run_with_no_sinks_has_empty_sinks_skipped(tmp_path: Path) -> None:
    """A partial run on a recipe with no sinks has empty `sinks_skipped`."""
    cache_root = tmp_path / "cache"
    recipe = Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {
                "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
                "seed": 11,
            },
        }
    )
    records = _records(8)
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-nosinks")
    result = runner.run(
        temp,
        raw_records=records,
        raw_input_hashes=_input_hashes(records),
        stop_after="Splits",
    )
    m = read_manifest(manifest_path(result.instance_dir))
    assert m.is_partial is True
    assert m.sinks == {}
    assert m.sinks_skipped == {}
