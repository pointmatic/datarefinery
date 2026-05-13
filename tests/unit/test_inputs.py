# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the image_flat input loader (Story H.a).

Covers the three label_from modes (by_id headered, by_id with recipe-
declared header, by_row_order) and the relevant error paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from datarefinery.core.errors import MaterializeError, RecipeError
from datarefinery.pipeline.inputs import load_raw_records
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe


def _make_flat_images(root: Path, names: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        arr = np.full((4, 4, 3), i * 17 % 255, dtype=np.uint8)
        Image.fromarray(arr).save(root / name)


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")


def _base_recipe_dict(
    source_path: Path, label_from: dict[str, Any] | None = None
) -> dict[str, Any]:
    src: dict[str, Any] = {
        "name": "images",
        "type": "image_flat",
        "path": str(source_path),
    }
    if label_from is not None:
        src["label_from"] = label_from
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "Input": {"sources": [src]},
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                "label": {"dtype": "string"},
            }
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}, "seed": 0},
    }


# ---------------------------------------------------------------------------
# by_id + headered CSV (default mode)
# ---------------------------------------------------------------------------


def test_by_id_headered_happy_path(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png", "b.png", "c.png"])
    manifest = tmp_path / "labels.csv"
    _write_csv(
        manifest,
        [["filename", "class"], ["a", "cat"], ["b", "dog"], ["c", "cat"]],
    )
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_id",
                "id_field": "filename",
                "label_field": "class",
            },
        )
    )
    records, hashes = load_raw_records(recipe, IMAGE_PLUGIN)
    assert [r["label"] for r in records] == ["cat", "dog", "cat"]
    assert "images" in hashes


def test_by_id_missing_image_id_errors(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png", "b.png"])
    manifest = tmp_path / "labels.csv"
    _write_csv(manifest, [["filename", "class"], ["a", "cat"]])  # no 'b'
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_id",
                "id_field": "filename",
                "label_field": "class",
            },
        )
    )
    with pytest.raises(MaterializeError, match="no matching id 'b'"):
        load_raw_records(recipe, IMAGE_PLUGIN)


def test_by_id_extra_manifest_rows_are_silent(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png"])
    manifest = tmp_path / "labels.csv"
    _write_csv(manifest, [["filename", "class"], ["a", "cat"], ["ghost", "dog"]])
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_id",
                "id_field": "filename",
                "label_field": "class",
            },
        )
    )
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    assert [r["label"] for r in records] == ["cat"]


def test_by_id_duplicate_manifest_id_errors(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png"])
    manifest = tmp_path / "labels.csv"
    _write_csv(manifest, [["filename", "class"], ["a", "cat"], ["a", "dog"]])
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_id",
                "id_field": "filename",
                "label_field": "class",
            },
        )
    )
    with pytest.raises(MaterializeError, match="duplicate id 'a'"):
        load_raw_records(recipe, IMAGE_PLUGIN)


# ---------------------------------------------------------------------------
# by_id + recipe-declared header (file is headerless)
# ---------------------------------------------------------------------------


def test_by_id_with_recipe_header_happy_path(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["x.png", "y.png"])
    manifest = tmp_path / "labels.txt"
    _write_csv(manifest, [["x", "fish"], ["y", "bird"]])  # no header row
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_id",
                "header": ["fname", "kind"],
                "id_field": "fname",
                "label_field": "kind",
            },
        )
    )
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    assert [r["label"] for r in records] == ["fish", "bird"]


def test_recipe_header_column_count_mismatch_errors(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["x.png"])
    manifest = tmp_path / "labels.txt"
    _write_csv(manifest, [["x", "fish", "extra"]])  # 3 columns, header declares 2
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_id",
                "header": ["fname", "kind"],
                "id_field": "fname",
                "label_field": "kind",
            },
        )
    )
    with pytest.raises(MaterializeError, match="3 columns but declared header has 2"):
        load_raw_records(recipe, IMAGE_PLUGIN)


# ---------------------------------------------------------------------------
# by_row_order (CIFAR-style)
# ---------------------------------------------------------------------------


def test_by_row_order_happy_path(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png", "b.png", "c.png"])
    manifest = tmp_path / "labels.txt"
    _write_csv(manifest, [["cat"], ["dog"], ["fish"]])  # single column, no header
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_row_order",
                "header": ["class"],
                "label_field": "class",
            },
        )
    )
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    # Images sorted by name: a, b, c. Labels in same order.
    assert [r["label"] for r in records] == ["cat", "dog", "fish"]


def test_by_row_order_row_count_mismatch_errors(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png", "b.png"])
    manifest = tmp_path / "labels.txt"
    _write_csv(manifest, [["cat"], ["dog"], ["fish"]])  # 3 rows, 2 images
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_row_order",
                "header": ["class"],
                "label_field": "class",
            },
        )
    )
    with pytest.raises(MaterializeError, match="3 rows but source 'images' has 2 images"):
        load_raw_records(recipe, IMAGE_PLUGIN)


# ---------------------------------------------------------------------------
# Source-type vs label_from consistency (defense in depth at load time;
# also enforced by validator check 19).
# ---------------------------------------------------------------------------


def test_image_folder_with_label_from_rejected_at_load_time(tmp_path: Path) -> None:
    folder = tmp_path / "imgs"
    (folder / "cat").mkdir(parents=True)
    arr = np.zeros((4, 4, 3), dtype=np.uint8)
    Image.fromarray(arr).save(folder / "cat" / "a.png")
    manifest = tmp_path / "labels.csv"
    _write_csv(manifest, [["filename", "class"], ["a", "cat"]])
    payload = _base_recipe_dict(
        folder,
        label_from={
            "path": str(manifest),
            "join": "by_id",
            "id_field": "filename",
            "label_field": "class",
        },
    )
    payload["Input"]["sources"][0]["type"] = "image_folder"
    recipe = Recipe.model_validate(payload)
    with pytest.raises(RecipeError, match="image_folder' with label_from set"):
        load_raw_records(recipe, IMAGE_PLUGIN)


def test_image_flat_without_label_from_rejected_at_load_time(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png"])
    recipe = Recipe.model_validate(_base_recipe_dict(images, label_from=None))
    with pytest.raises(RecipeError, match="image_flat' but no label_from"):
        load_raw_records(recipe, IMAGE_PLUGIN)


def test_image_flat_recurses_into_subdirs_for_enumeration(tmp_path: Path) -> None:
    """`image_flat` walks subdirs too — record_id encodes the relative path."""
    images = tmp_path / "imgs"
    (images / "nested").mkdir(parents=True)
    arr = np.zeros((4, 4, 3), dtype=np.uint8)
    Image.fromarray(arr).save(images / "top.png")
    Image.fromarray(arr).save(images / "nested" / "deep.png")
    manifest = tmp_path / "labels.csv"
    _write_csv(manifest, [["filename", "class"], ["top", "a"], ["deep", "b"]])
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_id",
                "id_field": "filename",
                "label_field": "class",
            },
        )
    )
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    assert [r["record_id"] for r in records] == [
        "images/nested/deep.png",
        "images/top.png",
    ]


# ---------------------------------------------------------------------------
# InputSource.partition stamping (Story H.b)
# ---------------------------------------------------------------------------


def test_partition_unset_records_have_no_partition_field(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png", "b.png"])
    manifest = tmp_path / "labels.csv"
    _write_csv(manifest, [["filename", "class"], ["a", "cat"], ["b", "dog"]])
    recipe = Recipe.model_validate(
        _base_recipe_dict(
            images,
            label_from={
                "path": str(manifest),
                "join": "by_id",
                "id_field": "filename",
                "label_field": "class",
            },
        )
    )
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    assert all("partition" not in r for r in records)


def test_partition_set_stamps_field_on_each_record(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png", "b.png"])
    manifest = tmp_path / "labels.csv"
    _write_csv(manifest, [["filename", "class"], ["a", "cat"], ["b", "dog"]])
    payload = _base_recipe_dict(
        images,
        label_from={
            "path": str(manifest),
            "join": "by_id",
            "id_field": "filename",
            "label_field": "class",
        },
    )
    payload["Input"]["sources"][0]["partition"] = "train"
    recipe = Recipe.model_validate(payload)
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    assert [r["partition"] for r in records] == ["train", "train"]


def test_partition_per_source_flows_through(tmp_path: Path) -> None:
    """Two image_folder sources with distinct partition values."""
    train_root = tmp_path / "train"
    test_root = tmp_path / "test"
    (train_root / "cat").mkdir(parents=True)
    (test_root / "cat").mkdir(parents=True)
    arr = np.zeros((4, 4, 3), dtype=np.uint8)
    Image.fromarray(arr).save(train_root / "cat" / "a.png")
    Image.fromarray(arr).save(test_root / "cat" / "b.png")

    recipe = Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
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
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "string"},
                },
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {},
        }
    )
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    by_partition: dict[str, list[str]] = {}
    for r in records:
        by_partition.setdefault(r["partition"], []).append(r["record_id"])
    assert set(by_partition.keys()) == {"train", "test"}
    assert by_partition["train"] == ["train_data/cat/a.png"]
    assert by_partition["test"] == ["test_data/cat/b.png"]


# ---------------------------------------------------------------------------
# Unlabeled image_flat sources (Story H.d)
# ---------------------------------------------------------------------------


def test_image_flat_unlabeled_loads_records_without_label(tmp_path: Path) -> None:
    images = tmp_path / "imgs"
    _make_flat_images(images, ["a.png", "b.png"])
    recipe_dict = _base_recipe_dict(images)
    recipe_dict["Input"]["sources"][0]["partition"] = "test"
    recipe_dict["Input"]["sources"][0]["unlabeled"] = True
    # No Splits ratios — Form A
    recipe_dict["Splits"] = {}
    recipe = Recipe.model_validate(recipe_dict)
    records, hashes = load_raw_records(recipe, IMAGE_PLUGIN)
    assert len(records) == 2
    for r in records:
        assert "label" not in r
        assert r["partition"] == "test"
    assert "images" in hashes


def test_image_folder_with_unlabeled_rejected_at_load_time(tmp_path: Path) -> None:
    root = tmp_path / "data"
    cls_dir = root / "cat"
    _make_flat_images(cls_dir, ["a.png"])
    recipe = Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [
                    {
                        "name": "test",
                        "type": "image_folder",
                        "path": str(root),
                        "partition": "test",
                        # Bypassing check 21 to verify loader's defensive guard
                    }
                ]
            },
            "Output": {"record_schema": {"image": {"dtype": "uint8", "shape": [4, 4, 3]}}},
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {},
        }
    )
    # Manually mutate the loaded model bypassing frozen=True via dict round-trip
    # only when we *can*. Instead, build directly:
    src = recipe.Input.sources[0]
    new_src = src.model_copy(update={"unlabeled": True, "label_from": None})
    new_input = recipe.Input.model_copy(update={"sources": [new_src]})
    bad_recipe = recipe.model_copy(update={"Input": new_input})
    with pytest.raises(RecipeError, match="image_folder"):
        load_raw_records(bad_recipe, IMAGE_PLUGIN)
