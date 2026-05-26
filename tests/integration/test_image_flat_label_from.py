# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""End-to-end integration test for image_flat + label_from (Story H.a).

Synthesises a flat directory of images plus a parallel `labels.csv`,
hand-authors a recipe (the v1 scaffolder is ImageFolder-only by design;
flat-layout scaffolder support is deferred), validates it, materialises
it through the typer CLI, and asserts the materialised instance carries
labels from the manifest. The assertion is on the per-split label
distribution rather than byte-equality with the ImageFolder golden path
because the two source types produce different ``record_id`` formats —
record-bytes can't match byte-for-byte across the two layouts.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from typer.testing import CliRunner

from datarefinery.cache.layout import dataset_dir
from datarefinery.cli.app import app

runner = CliRunner()


def _seeded_image(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, size=(8, 8, 3), dtype=np.uint8).astype(np.uint8)


def _build_flat_fixture(base: Path, *, n_images: int = 30, n_classes: int = 3) -> tuple[Path, Path]:
    """Synthesise images/ + labels.csv at `base`. Returns (images_dir, manifest_path)."""
    images_dir = base / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    manifest = base / "labels.csv"
    rows: list[str] = ["filename,class"]
    for i in range(n_images):
        name = f"img_{i:03d}.png"
        cls = f"class{i % n_classes:02d}"
        Image.fromarray(_seeded_image(i)).save(images_dir / name)
        rows.append(f"img_{i:03d},{cls}")
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return images_dir, manifest


def _recipe(images_dir: Path, manifest: Path, cache_root: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 0,
        "Input": {
            "sources": [
                {
                    "name": "images",
                    "type": "image_flat",
                    "path": str(images_dir),
                    "label_from": {
                        "path": str(manifest),
                        "join": "by_id",
                        "id_field": "filename",
                        "label_field": "class",
                    },
                }
            ],
        },
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [8, 8, 3]},
                "label": {"dtype": "string"},
            }
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {
            "ratios": {"train": 0.7, "val": 0.15, "test": 0.15},
            "stratify_by": "label",
            "seed": 7,
        },
    }


def test_image_flat_label_from_validate_and_materialize(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    images_dir, manifest = _build_flat_fixture(tmp_path)
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(_recipe(images_dir, manifest, cache_root)))

    # validate — check 19 (and all others) green
    result = runner.invoke(
        app,
        ["--cache-root", str(cache_root), "validate", str(recipe_path)],
    )
    assert result.exit_code == 0, result.stdout
    assert "24/24 checks passed" in result.stdout

    # materialize
    result = runner.invoke(
        app,
        ["--cache-root", str(cache_root), "materialize", str(recipe_path)],
    )
    assert result.exit_code == 0, result.stdout

    # Per-split label distributions: every record carries a label drawn
    # from the manifest's class column.
    import json

    counts_per_split: dict[str, Counter[str]] = {}
    # Find the materialised instance.
    instances = list((cache_root / "instances").glob("*/*/*"))
    instances = [p for p in instances if p.is_dir() and (p / "manifest.json").exists()]
    assert len(instances) == 1, instances
    inst = instances[0]
    dataset = dataset_dir(inst)
    for split_file in sorted(dataset.glob("*.jsonl")):
        c: Counter[str] = Counter()
        with split_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                c[row["label"]] += 1
        counts_per_split[split_file.stem] = c

    # All three classes appear across splits, totaling 30 records.
    total = sum(sum(c.values()) for c in counts_per_split.values())
    assert total == 30
    all_labels: set[str] = set()
    for c in counts_per_split.values():
        all_labels.update(c.keys())
    assert all_labels == {"class00", "class01", "class02"}


def test_image_flat_validate_rejects_image_folder_with_label_from(tmp_path: Path) -> None:
    """Cross-check: validator catches the type/label-from inconsistency."""
    images_dir, manifest = _build_flat_fixture(tmp_path, n_images=3, n_classes=1)
    recipe = _recipe(images_dir, manifest, tmp_path / "cache")
    # Switch type to image_folder while keeping label_from set — should fail check 19.
    recipe["Input"]["sources"][0]["type"] = "image_folder"  # type: ignore[index]
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(recipe))

    result = runner.invoke(
        app,
        ["--cache-root", str(tmp_path / "cache"), "validate", str(recipe_path)],
    )
    assert result.exit_code == 1
    assert "image_folder" in result.stdout
