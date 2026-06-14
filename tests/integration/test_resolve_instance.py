# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.l: datarefinery.resolve_instance(...) end-to-end.

The blessed instance-locator: a top-level facade over
DataRefinery.from_recipe(...).status() so a consumer never reimplements
the cache-key math. Covers miss/hit, delegation equivalence, and
seed/variant flow-through.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from datarefinery import DataRefinery, materialize, resolve_instance
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.status import StatusReport


def _write_image_folder(root: Path, *, classes: int = 2, per_class: int = 6) -> None:
    rng = np.random.default_rng(0)
    for c in range(classes):
        cls_dir = root / f"c{c}"
        cls_dir.mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            arr = rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8)
            Image.fromarray(arr).save(cls_dir / f"img_{i:04d}.png")


_RECIPE_TEMPLATE = """\
schema_version: 2
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
variants:
  alt:
    seed: 42
"""


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    source_root = tmp_path / "imagefolder"
    _write_image_folder(source_root)
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(_RECIPE_TEMPLATE.format(source_root=source_root))
    return recipe_path, tmp_path / "cache"


def test_resolve_instance_miss_returns_status_report(tmp_path: Path) -> None:
    recipe_path, cache_root = _scaffold(tmp_path)
    report = resolve_instance(recipe_path, cache_root=cache_root)
    assert isinstance(report, StatusReport)
    assert report.cache_status == "miss"
    assert report.manifest is None
    # instance_path is the deterministic location even on a miss.
    assert isinstance(report.instance_path, Path)


def test_resolve_instance_miss_path_is_deterministic(tmp_path: Path) -> None:
    recipe_path, cache_root = _scaffold(tmp_path)
    report = resolve_instance(recipe_path, cache_root=cache_root)
    assert report.cache_status == "miss"
    # cache_key is fully populated (full 64-hex digests) without materializing.
    assert len(report.cache_key.recipe_hash) == 64
    assert len(report.cache_key.input_hash) == 64
    assert report.cache_key.seed == 11
    # The resolved path lives under the requested cache_root.
    assert str(report.instance_path).startswith(str(cache_root))


def test_resolve_instance_hit_after_materialize(tmp_path: Path) -> None:
    recipe_path, cache_root = _scaffold(tmp_path)
    config = RuntimeConfig(cache_root=cache_root)
    inst = materialize(recipe_path, config=config)

    report = resolve_instance(recipe_path, cache_root=cache_root)
    assert report.cache_status == "hit"
    assert report.instance_path == inst.path
    assert report.manifest is not None
    assert report.manifest.recipe_hash == report.cache_key.recipe_hash


def test_resolve_instance_delegates_to_status(tmp_path: Path) -> None:
    recipe_path, cache_root = _scaffold(tmp_path)
    config = RuntimeConfig(cache_root=cache_root)
    via_facade = resolve_instance(recipe_path, cache_root=cache_root)
    via_handle = DataRefinery.from_recipe(recipe_path, config=config).status()
    assert via_facade == via_handle


def test_resolve_instance_seed_flows_through(tmp_path: Path) -> None:
    recipe_path, cache_root = _scaffold(tmp_path)
    default = resolve_instance(recipe_path, cache_root=cache_root)
    overridden = resolve_instance(recipe_path, cache_root=cache_root, seed=999)
    assert overridden.cache_key.seed == 999
    assert overridden.cache_key != default.cache_key
    assert overridden.instance_path != default.instance_path


def test_resolve_instance_variant_flows_through(tmp_path: Path) -> None:
    recipe_path, cache_root = _scaffold(tmp_path)
    base = resolve_instance(recipe_path, cache_root=cache_root)
    alt = resolve_instance(recipe_path, cache_root=cache_root, variant="alt")
    # The variant overlay perturbs the recipe → different cache identity.
    assert alt.cache_key != base.cache_key


def test_resolve_instance_accepts_str_paths(tmp_path: Path) -> None:
    recipe_path, cache_root = _scaffold(tmp_path)
    report = resolve_instance(str(recipe_path), cache_root=str(cache_root))
    assert isinstance(report, StatusReport)
