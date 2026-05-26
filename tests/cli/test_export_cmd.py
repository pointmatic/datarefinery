# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Smoke tests for ``datarefinery export`` (Story I.f)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image
from typer.testing import CliRunner

pytest.importorskip("cv2", reason="requires the [corruptions] extras")

from datarefinery.cli.app import app

runner = CliRunner()


def _build_image_folder(
    root: Path, *, classes: tuple[str, ...] = ("a", "b"), per_class: int = 4
) -> Path:
    rng = np.random.default_rng(0)
    for cls in classes:
        cls_dir = root / cls
        cls_dir.mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            arr = rng.integers(0, 255, (32, 32, 3), dtype=np.uint8)
            Image.fromarray(arr).save(cls_dir / f"{cls}_{i:03d}.png")
    return root


def _recipe_dict(image_root: Path, *, with_sink: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 7,
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": str(image_root)}]},
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                "label": {"dtype": "str"},
                "path": {"dtype": "str"},
            }
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {
            "ratios": {"train": 0.5, "val": 0.25, "test": 0.25},
            "seed": 11,
        },
        "Generation": [
            {
                "name": "imagecorruptions_apply",
                "inputs": ["image"],
                "output_schema": {
                    "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                    "label": {"dtype": "str"},
                    "path": {"dtype": "str"},
                },
                "seed": 42,
                "applies_at": ["train"],
                "params": {
                    "corruption_types": ["gaussian_noise"],
                    "severities": [3],
                    "preserve_original": False,
                    "tag_fields": ["corruption", "severity", "source_path"],
                },
            }
        ],
    }
    if with_sink:
        body["Sinks"] = [
            {
                "name": "corrupted",
                "stage": "post_Generation",
                "splits": ["train"],
                "field": "image",
                "format": "png_per_record",
                "path_template": "exports/{record_id}.png",
            }
        ]
    return body


def test_export_cli_writes_sink_into_existing_instance(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    cache = tmp_path / "cache"

    # Materialize without sinks first.
    recipe_no_sinks = tmp_path / "recipe.yaml"
    recipe_no_sinks.write_text(yaml.safe_dump(_recipe_dict(images, with_sink=False)))
    res = runner.invoke(app, ["--cache-root", str(cache), "materialize", str(recipe_no_sinks)])
    assert res.exit_code == 0, res.stdout

    # Add a sink and run export against the same cache.
    recipe_with_sinks = tmp_path / "recipe_with_sinks.yaml"
    recipe_with_sinks.write_text(yaml.safe_dump(_recipe_dict(images, with_sink=True)))
    res = runner.invoke(app, ["--cache-root", str(cache), "export", str(recipe_with_sinks)])
    assert res.exit_code == 0, res.stdout
    assert "corrupted" in res.stdout
    assert "post_Generation" in res.stdout

    # Locate the instance (only one under the cache) and confirm sink output.
    # The `image_classification` loader uses
    # `f"{source_name}/{cls}/{path.name}"` as record_id, so each PNG
    # lands at `exports/<source>/<cls>/<filename>_<corruption>_s<sev>_<hash>.png`
    # — search recursively.
    instances_dir = cache / "instances"
    exports_roots = [p for p in instances_dir.rglob("exports") if p.is_dir()]
    pngs: list[Path] = []
    for root in exports_roots:
        pngs.extend(root.rglob("*.png"))
    assert pngs, "no sink output produced under the existing instance"


def test_export_cli_refuses_when_no_bound_instance(tmp_path: Path) -> None:
    images = _build_image_folder(tmp_path / "data")
    cache = tmp_path / "empty_cache"
    recipe_with_sinks = tmp_path / "recipe.yaml"
    recipe_with_sinks.write_text(yaml.safe_dump(_recipe_dict(images, with_sink=True)))

    res = runner.invoke(app, ["--cache-root", str(cache), "export", str(recipe_with_sinks)])
    assert res.exit_code != 0, res.stdout
    # `main_entry`'s top-level handler renders the panel; CliRunner
    # surfaces the raised `MaterializeError` via `result.exception`.
    assert res.exception is not None
    assert "no bound instance" in str(res.exception).lower()
