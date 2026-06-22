# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.5: multi-overlay materialization end-to-end.

A recipe with several overlay definitions, materialized with an ordered
selection: the resolved recipe drives identity (so the selection determines
the instance deterministically) and the report echoes every applied overlay.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from datarefinery import DataRefinery
from datarefinery.cache.layout import report_dir
from datarefinery.core.config import RuntimeConfig


def _write_image_folder(root: Path, *, classes: int = 2, per_class: int = 6) -> None:
    rng = np.random.default_rng(0)
    for c in range(classes):
        cls_dir = root / f"c{c}"
        cls_dir.mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            arr = rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8)
            Image.fromarray(arr).save(cls_dir / f"img_{i:04d}.png")


_RECIPE = """\
schema_version: 3
plugin: image_classification
seed: 11
Input:
  sources:
    - name: imgs
      type: image_folder
      path: {source_root}
Output:
  record_schema:
    image: {{dtype: uint8, shape: [8, 8, 3]}}
    label: {{dtype: str}}
Labels:
  field: label
  source: {{kind: direct}}
Splits:
  ratios: {{train: 0.6, val: 0.2, test: 0.2}}
  seed: 11
overlays:
  small_seed:
    seed: 1
  big_seed:
    seed: 99
"""


def _scaffold(tmp_path: Path) -> tuple[Path, RuntimeConfig]:
    source_root = tmp_path / "imagefolder"
    _write_image_folder(source_root)
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(_RECIPE.format(source_root=source_root))
    return recipe_path, RuntimeConfig(cache_root=tmp_path / "cache")


def test_multi_overlay_materialization_is_deterministic(tmp_path: Path) -> None:
    recipe_path, config = _scaffold(tmp_path)
    # The later overlay wins on `seed`; the resolved recipe (seed=99) drives
    # identity, so the same ordered selection lands the same instance.
    a = DataRefinery.from_recipe(
        recipe_path, config=config, overlays=["small_seed", "big_seed"]
    ).materialize()
    b = DataRefinery.from_recipe(
        recipe_path, config=config, overlays=["small_seed", "big_seed"]
    ).materialize()
    assert a.path == b.path
    assert a.manifest.recipe_hash == b.manifest.recipe_hash


def test_overlay_order_changes_the_instance(tmp_path: Path) -> None:
    recipe_path, config = _scaffold(tmp_path)
    ab = DataRefinery.from_recipe(
        recipe_path, config=config, overlays=["small_seed", "big_seed"]
    ).materialize()
    ba = DataRefinery.from_recipe(
        recipe_path, config=config, overlays=["big_seed", "small_seed"]
    ).materialize()
    # Conflicting overlays applied in different order → different resolved
    # recipe → different instance.
    assert ab.path != ba.path


def test_manifest_and_report_echo_applied_overlays(tmp_path: Path) -> None:
    recipe_path, config = _scaffold(tmp_path)
    inst = DataRefinery.from_recipe(
        recipe_path, config=config, overlays=["small_seed", "big_seed"]
    ).materialize()
    assert inst.manifest.overlays == ["small_seed", "big_seed"]
    report_text = (report_dir(inst.path) / "report.md").read_text(encoding="utf-8")
    assert "small_seed" in report_text
    assert "big_seed" in report_text
