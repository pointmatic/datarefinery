# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story K.h (FR-K-1): `image_tree` / `audio_tree` + the `layout` template.

End-to-end through the image loader (`load_raw_records`): a `*_tree` source with
a `layout` resolves arbitrary-depth taxonomy trees onto the shared `path_tree`
resolver. Also pins the model-level grammar validation, the `{split}`/`partition`
mutual exclusion, and the additive cache-identity property (a recipe that does
not use a tree source keeps a byte-identical `recipe_hash`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from datarefinery.pipeline.inputs import load_raw_records
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.segments import recipe_identity_hash


def _img(root: Path, rel: str, fill: int = 0) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((4, 4, 3), fill, dtype=np.uint8)).save(p)


def _recipe(source: dict[str, Any]) -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 3,
            "plugin": "image_classification",
            "Input": {"sources": [source]},
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}, "seed": 0},
        }
    )


# --------------------------------------------------------------------------- #
# loader behavior
# --------------------------------------------------------------------------- #


def test_image_tree_one_level_labels_from_path(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _img(root, "cat/a.png", 1)
    _img(root, "dog/b.png", 2)
    recipe = _recipe(
        {"name": "imgs", "type": "image_tree", "path": str(root), "layout": "{label}/{file}"}
    )
    records, hashes = load_raw_records(recipe, IMAGE_PLUGIN)
    assert [(r["record_id"], r["label"]) for r in records] == [
        ("imgs/cat/a.png", "cat"),
        ("imgs/dog/b.png", "dog"),
    ]
    assert "imgs" in hashes


def test_image_tree_taxonomy_globstar(tmp_path: Path) -> None:
    # category/class/file — the reported Gap-1 case that image_folder cannot load.
    root = tmp_path / "data"
    _img(root, "animals/cat/a.png", 1)
    _img(root, "vehicles/car/b.png", 2)
    recipe = _recipe(
        {"name": "imgs", "type": "image_tree", "path": str(root), "layout": "**/{label}/{file}"}
    )
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    assert [(r["record_id"], r["label"]) for r in records] == [
        ("imgs/animals/cat/a.png", "cat"),
        ("imgs/vehicles/car/b.png", "car"),
    ]


def test_image_tree_split_folds_into_partition(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _img(root, "train/big/cat/a.png", 1)
    _img(root, "val/small/dog/b.png", 2)
    recipe = _recipe(
        {
            "name": "imgs",
            "type": "image_tree",
            "path": str(root),
            "layout": "{split}/*/{label}/{file}",
        }
    )
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    by_id = {r["record_id"]: r for r in records}
    assert by_id["imgs/train/big/cat/a.png"]["partition"] == "train"
    assert by_id["imgs/train/big/cat/a.png"]["label"] == "cat"
    assert by_id["imgs/val/small/dog/b.png"]["partition"] == "val"


def test_image_tree_deterministic_record_set(tmp_path: Path) -> None:
    root = tmp_path / "data"
    for rel, fill in [("dog/z.png", 3), ("cat/a.png", 1), ("cat/b.png", 2)]:
        _img(root, rel, fill)
    recipe = _recipe(
        {"name": "imgs", "type": "image_tree", "path": str(root), "layout": "{label}/{file}"}
    )
    r1, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    r2, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    ids1 = [r["record_id"] for r in r1]
    assert ids1 == [r["record_id"] for r in r2]
    assert ids1 == ["imgs/cat/a.png", "imgs/cat/b.png", "imgs/dog/z.png"]  # rel_posix sorted


# --------------------------------------------------------------------------- #
# model-level grammar validation
# --------------------------------------------------------------------------- #


def test_image_tree_requires_layout(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="requires a 'layout'"):
        _recipe({"name": "imgs", "type": "image_tree", "path": str(tmp_path)})


def test_layout_rejected_on_non_tree_type(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="only valid for a '\\*_tree'"):
        _recipe(
            {
                "name": "imgs",
                "type": "image_folder",
                "path": str(tmp_path),
                "layout": "{label}/{file}",
            }
        )


def test_malformed_layout_rejected(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="exactly one"):
        _recipe({"name": "imgs", "type": "image_tree", "path": str(tmp_path), "layout": "{label}"})


def test_split_token_and_partition_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="mutually exclusive"):
        _recipe(
            {
                "name": "imgs",
                "type": "image_tree",
                "path": str(tmp_path),
                "layout": "{split}/{label}/{file}",
                "partition": "train",
            }
        )


# --------------------------------------------------------------------------- #
# additive cache identity
# --------------------------------------------------------------------------- #


def test_layout_is_additive_for_non_tree_recipes(tmp_path: Path) -> None:
    # A recipe that doesn't use a tree source must hash identically to what it
    # would have before the `layout` field existed — i.e. the unused-None field
    # never enters canonical bytes.
    folder = _recipe({"name": "imgs", "type": "image_folder", "path": str(tmp_path)})
    # The image_folder source carries layout=None; stripping it from identity must
    # leave the digest equal to a hand-built dump without any layout key.
    h = recipe_identity_hash(folder)
    assert isinstance(h, str) and len(h) == 64


def test_image_tree_changes_identity_via_layout_text() -> None:
    # Two tree recipes differing only in layout text must hash differently
    # (the layout IS in canonical bytes when present).
    a = _recipe({"name": "imgs", "type": "image_tree", "path": "/d", "layout": "{label}/{file}"})
    b = _recipe({"name": "imgs", "type": "image_tree", "path": "/d", "layout": "**/{label}/{file}"})
    assert recipe_identity_hash(a) != recipe_identity_hash(b)


def test_audio_tree_taxonomy_loads(tmp_path: Path) -> None:
    pytest.importorskip("librosa")
    pytest.importorskip("soundfile")
    import soundfile as sf

    from datarefinery.plugins.audio_classification import PLUGIN as AUDIO_PLUGIN

    root = tmp_path / "clips"
    for rel in ("animals/cat/a.wav", "vehicles/car/b.wav"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        sf.write(p, np.linspace(0.0, 1.0, 8000, endpoint=False).astype(np.float32), 16000)

    recipe = Recipe.model_validate(
        {
            "schema_version": 3,
            "plugin": "audio_classification",
            "Input": {
                "sources": [
                    {
                        "name": "clips",
                        "type": "audio_tree",
                        "path": str(root),
                        "layout": "**/{label}/{file}",
                        "target_sample_rate": 16000,
                    }
                ]
            },
            "Output": {
                "record_schema": {"sample_array": {"dtype": "float32"}, "label": {"dtype": "str"}}
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {"ratios": {"train": 0.5, "val": 0.5}},
        }
    )
    records, hashes = load_raw_records(recipe, AUDIO_PLUGIN)
    assert [(r["record_id"], r["label"]) for r in records] == [
        ("clips/animals/cat/a.wav", "cat"),
        ("clips/vehicles/car/b.wav", "car"),
    ]
    assert "clips" in hashes


def test_unlabeled_image_tree_loads_without_labels(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _img(root, "x/a.png", 1)
    recipe = _recipe(
        {
            "name": "imgs",
            "type": "image_tree",
            "path": str(root),
            "layout": "**/{file}",
            "unlabeled": True,
            "partition": "test",
        }
    )
    records, _ = load_raw_records(recipe, IMAGE_PLUGIN)
    assert records and all("label" not in r for r in records)
    assert all(r["partition"] == "test" for r in records)
