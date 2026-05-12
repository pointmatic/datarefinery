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
