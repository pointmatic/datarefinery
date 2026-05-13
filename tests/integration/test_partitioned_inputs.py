# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""End-to-end integration test for InputSource partitions (Story H.b).

Synthesises a Kaggle-style fixture with separate ``train/`` and
``test/`` ImageFolder subtrees and exercises both partition-honoring
forms via the typer CLI:

* Form A — Splits omitted entirely; source partitions are final.
* Form B — Splits.applies_to=train carves train/val; test stays heldout.

Assertions cover (a) the test partition's record set is byte-identical
across forms (heldout determinism), (b) every train record carries
partition=train, and (c) Form B produces three splits with the
sub-partition arithmetic correct.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image
from typer.testing import CliRunner

from datarefinery.cache.layout import dataset_dir
from datarefinery.cli.app import app

runner = CliRunner()


def _build_kaggle_fixture(base: Path, *, n_per_class: int = 5) -> tuple[Path, Path]:
    """Synthesise train/ and test/ ImageFolder subtrees at ``base``.

    Two classes (cat, dog); ``n_per_class`` images per class per subtree.
    Returns (train_root, test_root).
    """
    train_root = base / "train"
    test_root = base / "test"
    for root, kind in ((train_root, "train"), (test_root, "test")):
        for cls in ("cat", "dog"):
            d = root / cls
            d.mkdir(parents=True, exist_ok=True)
            for i in range(n_per_class):
                arr = np.full((8, 8, 3), (hash((kind, cls, i)) & 0xFF), dtype=np.uint8)
                Image.fromarray(arr).save(d / f"{cls}_{i:03d}.png")
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
                    "type": "image_folder",
                    "path": str(test_root),
                    "partition": "test",
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


def _read_split_record_ids(instance_dir: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for split_file in sorted(dataset_dir(instance_dir).glob("*.jsonl")):
        ids: list[str] = []
        with split_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                ids.append(json.loads(line)["record_id"])
        out[split_file.stem] = ids
    return out


def _materialise(tmp_path: Path, recipe_dict: dict[str, object]) -> Path:
    """Write recipe, run validate + materialize, return the instance dir."""
    cache_root = tmp_path / "cache"
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(recipe_dict))

    result = runner.invoke(app, ["--cache-root", str(cache_root), "validate", str(recipe_path)])
    assert result.exit_code == 0, result.stdout
    assert "20/20 checks passed" in result.stdout

    result = runner.invoke(app, ["--cache-root", str(cache_root), "materialize", str(recipe_path)])
    assert result.exit_code == 0, result.stdout

    instances = list((cache_root / "instances").glob("*/*/*"))
    instances = [p for p in instances if p.is_dir() and (p / "manifest.json").exists()]
    assert len(instances) == 1
    return instances[0]


def test_form_a_honors_source_partitions_verbatim(tmp_path: Path) -> None:
    train_root, test_root = _build_kaggle_fixture(tmp_path / "src")
    instance = _materialise(
        tmp_path,
        _recipe(train_root, test_root, splits={}),  # Form A
    )
    splits = _read_split_record_ids(instance)
    assert set(splits.keys()) == {"train", "test"}
    assert all(rid.startswith("train_data/") for rid in splits["train"])
    assert all(rid.startswith("test_data/") for rid in splits["test"])
    # No test record leaks into train.
    assert not (set(splits["train"]) & set(splits["test"]))


def test_form_b_sub_partitions_train_and_holds_test(tmp_path: Path) -> None:
    train_root, test_root = _build_kaggle_fixture(tmp_path / "src")
    instance = _materialise(
        tmp_path,
        _recipe(
            train_root,
            test_root,
            splits={
                "ratios": {"train": 0.8, "val": 0.2},
                "applies_to": "train",
                "seed": 7,
            },
        ),
    )
    splits = _read_split_record_ids(instance)
    assert set(splits.keys()) == {"train", "val", "test"}
    # test stays heldout verbatim
    assert all(rid.startswith("test_data/") for rid in splits["test"])
    # train+val are exactly the train-source records, partitioned
    sub_total = set(splits["train"]) | set(splits["val"])
    expected = {f"train_data/{cls}/{cls}_{i:03d}.png" for cls in ("cat", "dog") for i in range(5)}
    assert sub_total == expected
    assert not (set(splits["train"]) & set(splits["val"]))


def test_form_a_and_form_b_share_identical_test_set(tmp_path: Path) -> None:
    """The test partition's record set is independent of applies_to."""
    train_root, test_root = _build_kaggle_fixture(tmp_path / "src")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    form_a = _materialise(
        tmp_path / "a",
        _recipe(train_root, test_root, splits={}),
    )
    form_b = _materialise(
        tmp_path / "b",
        _recipe(
            train_root,
            test_root,
            splits={"ratios": {"train": 0.8, "val": 0.2}, "applies_to": "train", "seed": 7},
        ),
    )
    a_splits = _read_split_record_ids(form_a)
    b_splits = _read_split_record_ids(form_b)
    assert sorted(a_splits["test"]) == sorted(b_splits["test"])


def test_validate_rejects_partial_partition_declaration(tmp_path: Path) -> None:
    """Validator check 20 catches mixed partitioned/unpartitioned sources."""
    train_root, test_root = _build_kaggle_fixture(tmp_path / "src", n_per_class=2)
    recipe = _recipe(train_root, test_root, splits={})
    # Drop partition off one source — should fail validation.
    sources = recipe["Input"]["sources"]
    del sources[1]["partition"]
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(recipe))

    cache_root = tmp_path / "cache"
    result = runner.invoke(app, ["--cache-root", str(cache_root), "validate", str(recipe_path)])
    assert result.exit_code == 1
    # Rich-rendered table may wrap the message; assert via descriptor instead.
    assert "partitions_consistent" in result.stdout
    assert "1 check(s) failed" in result.stdout


def test_partition_distribution_per_split_is_homogeneous(tmp_path: Path) -> None:
    """Every record in a split should carry exactly that partition value."""
    train_root, test_root = _build_kaggle_fixture(tmp_path / "src")
    instance = _materialise(tmp_path, _recipe(train_root, test_root, splits={}))
    for split_file in sorted(dataset_dir(instance).glob("*.jsonl")):
        partition_counts: Counter[str] = Counter()
        with split_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                partition_counts[row["partition"]] += 1
        # Every record in a split has the matching partition value.
        assert list(partition_counts.keys()) == [split_file.stem]
