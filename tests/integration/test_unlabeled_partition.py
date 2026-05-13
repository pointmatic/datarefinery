# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""End-to-end integration tests for unlabeled partitions (Story H.d).

Synthesises a Kaggle-style fixture: a labeled ``train/`` ImageFolder
subtree plus an unlabeled flat ``test/`` directory. Exercises validate,
materialize, the drift placeholder's unlabeled-split handling, and the
report's unlabeled marker.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image
from typer.testing import CliRunner

from datarefinery.cache.layout import dataset_dir, report_dir
from datarefinery.cli.app import app
from datarefinery.reporting.drift import read_drift

runner = CliRunner()


def _build_fixture(base: Path, *, n_per_class: int = 4, n_unlabeled: int = 5) -> tuple[Path, Path]:
    """Synthesise labeled train/ + unlabeled test/ at ``base``."""
    train_root = base / "train"
    for cls in ("cat", "dog"):
        d = train_root / cls
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n_per_class):
            arr = np.full((8, 8, 3), (hash(("train", cls, i)) & 0xFF), dtype=np.uint8)
            Image.fromarray(arr).save(d / f"{cls}_{i:03d}.png")
    test_root = base / "test"
    test_root.mkdir(parents=True, exist_ok=True)
    for i in range(n_unlabeled):
        arr = np.full((8, 8, 3), (hash(("test", i)) & 0xFF), dtype=np.uint8)
        Image.fromarray(arr).save(test_root / f"img_{i:03d}.png")
    return train_root, test_root


def _recipe(train_root: Path, test_root: Path, splits: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 0,
        "Input": {
            "sources": [
                {
                    "name": "train_data",
                    "type": "image_folder",
                    "path": str(train_root),
                    "partition": "train",
                },
                {
                    "name": "test_data",
                    "type": "image_flat",
                    "path": str(test_root),
                    "partition": "test",
                    "unlabeled": True,
                },
            ]
        },
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [8, 8, 3]},
                "label": {"dtype": "string"},
            }
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": splits,
    }


def _materialise(tmp_path: Path, recipe_dict: dict[str, object]) -> Path:
    cache_root = tmp_path / "cache"
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(recipe_dict))

    result = runner.invoke(app, ["--cache-root", str(cache_root), "validate", str(recipe_path)])
    assert result.exit_code == 0, result.stdout
    assert "21/21 checks passed" in result.stdout

    result = runner.invoke(app, ["--cache-root", str(cache_root), "materialize", str(recipe_path)])
    assert result.exit_code == 0, result.stdout

    instances = list((cache_root / "instances").glob("*/*/*"))
    instances = [p for p in instances if p.is_dir() and (p / "manifest.json").exists()]
    assert len(instances) == 1
    return instances[0]


def _read_split_records(instance_dir: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for split_file in sorted(dataset_dir(instance_dir).glob("*.jsonl")):
        records: list[dict[str, Any]] = []
        with split_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        out[split_file.stem] = records
    return out


def test_unlabeled_partition_materialises_without_labels(tmp_path: Path) -> None:
    train_root, test_root = _build_fixture(tmp_path / "src")
    instance = _materialise(
        tmp_path,
        _recipe(
            train_root,
            test_root,
            splits={
                "ratios": {"train": 0.75, "val": 0.25},
                "applies_to": "train",
                "stratify_by": "label",
                "seed": 7,
            },
        ),
    )
    splits = _read_split_records(instance)
    assert set(splits.keys()) == {"train", "val", "test"}
    # Every test record lacks the label field.
    for r in splits["test"]:
        assert "label" not in r
    # Every train+val record has a label.
    for r in splits["train"] + splits["val"]:
        assert "label" in r and r["label"] in {"cat", "dog"}


def test_drift_json_marks_unlabeled_splits(tmp_path: Path) -> None:
    train_root, test_root = _build_fixture(tmp_path / "src")
    instance = _materialise(
        tmp_path,
        _recipe(
            train_root,
            test_root,
            splits={
                "ratios": {"train": 0.75, "val": 0.25},
                "applies_to": "train",
                "stratify_by": "label",
                "seed": 7,
            },
        ),
    )
    drift = read_drift(report_dir(instance) / "drift.json")
    test_record = drift.splits["test"]
    assert test_record.class_distribution is None
    assert test_record.note == "skipped: unlabeled"
    # Labeled splits still get a class distribution.
    train_record = drift.splits["train"]
    assert train_record.class_distribution is not None
    assert set(train_record.class_distribution.keys()) <= {"cat", "dog"}


def test_report_md_marks_unlabeled_splits(tmp_path: Path) -> None:
    train_root, test_root = _build_fixture(tmp_path / "src")
    instance = _materialise(
        tmp_path,
        _recipe(
            train_root,
            test_root,
            splits={
                "ratios": {"train": 0.75, "val": 0.25},
                "applies_to": "train",
                "seed": 7,
            },
        ),
    )
    report_text = (report_dir(instance) / "report.md").read_text(encoding="utf-8")
    # Test split is flagged; labeled splits are not.
    assert "`test`:" in report_text
    test_line = next(line for line in report_text.splitlines() if line.startswith("- `test`:"))
    assert "*(unlabeled)*" in test_line
    train_line = next(line for line in report_text.splitlines() if line.startswith("- `train`:"))
    assert "*(unlabeled)*" not in train_line


def test_validate_rejects_unlabeled_image_folder(tmp_path: Path) -> None:
    """Check 21 — image_folder + unlabeled is rejected."""
    train_root, test_root = _build_fixture(tmp_path / "src")
    recipe = _recipe(
        train_root,
        test_root,
        splits={
            "ratios": {"train": 0.8, "val": 0.2},
            "applies_to": "train",
            "seed": 7,
        },
    )
    # Flip test_data type back to image_folder while keeping unlabeled=true.
    recipe["Input"]["sources"][1]["type"] = "image_folder"
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(recipe))
    cache_root = tmp_path / "cache"
    result = runner.invoke(app, ["--cache-root", str(cache_root), "validate", str(recipe_path)])
    assert result.exit_code == 1
    assert "unlabeled_consistency" in result.stdout


def test_validate_rejects_stratify_on_unlabeled_partition(tmp_path: Path) -> None:
    """Check 21 — stratify_by + applies_to=<unlabeled> is rejected."""
    train_root, test_root = _build_fixture(tmp_path / "src")
    recipe = _recipe(
        train_root,
        test_root,
        splits={
            "ratios": {"sub_a": 0.5, "sub_b": 0.5},
            "applies_to": "test",  # carve up the unlabeled partition
            "stratify_by": "label",
            "seed": 7,
        },
    )
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(recipe))
    cache_root = tmp_path / "cache"
    result = runner.invoke(app, ["--cache-root", str(cache_root), "validate", str(recipe_path)])
    assert result.exit_code == 1
    assert "unlabeled_consistency" in result.stdout
