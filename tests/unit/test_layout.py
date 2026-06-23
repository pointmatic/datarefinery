# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story K.h (FR-K-1): the `layout` path-template grammar + `path_tree` resolver.

`layout` is a path-segment *matcher* (semantically inverse to the sink
`path_template` substituter, K.f memo § 1): components `{label}` / `{split}` /
`{file}` + wildcards `*` (one ignored level) / `**` (any depth). `path_tree`
walks a source root (via the K.g symlink-following `enumerate_files`), matches
each file against the layout, and returns `[(path, record_id, label?, split?)]`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from datarefinery.core.errors import RecipeError
from datarefinery.recipe.layout import ResolvedFile, parse_layout, path_tree

_IMG_EXTS = frozenset({".png", ".jpg", ".jpeg"})


# --------------------------------------------------------------------------- #
# parse_layout — grammar validation (pure)
# --------------------------------------------------------------------------- #


def test_parse_accepts_label_file() -> None:
    parsed = parse_layout("{label}/{file}")
    assert parsed.components == ("{label}", "{file}")


def test_parse_accepts_wildcards_and_split() -> None:
    parse_layout("{split}/*/{label}/{file}")
    parse_layout("**/{label}/{file}")
    parse_layout("{file}")


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty
        "{label}",  # no terminal {file}
        "{file}/{label}",  # {file} not last
        "{file}/{file}",  # two {file}
        "{label}/{label}/{file}",  # two {label}
        "{split}/{split}/{file}",  # two {split}
        "**/**/{file}",  # two **
        "{bogus}/{file}",  # unknown token
        "{label}//{file}",  # empty segment
    ],
)
def test_parse_rejects_malformed(bad: str) -> None:
    with pytest.raises((ValueError, RecipeError)):
        parse_layout(bad)


# --------------------------------------------------------------------------- #
# path_tree — resolution against a real tree
# --------------------------------------------------------------------------- #


def _img(root: Path, rel: str, fill: int = 0) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((4, 4, 3), fill, dtype=np.uint8)).save(p)


def test_label_file_one_level(tmp_path: Path) -> None:
    _img(tmp_path, "cat/a.png")
    _img(tmp_path, "dog/b.png")
    out = path_tree(tmp_path, "{label}/{file}", extensions=_IMG_EXTS, source_name="s")
    assert out == [
        ResolvedFile(tmp_path / "cat/a.png", "s/cat/a.png", "cat", None),
        ResolvedFile(tmp_path / "dog/b.png", "s/dog/b.png", "dog", None),
    ]


def test_globstar_label_leaf_at_any_depth(tmp_path: Path) -> None:
    # category/class/file — label is the leaf dir at any depth.
    _img(tmp_path, "animals/cat/a.png")
    _img(tmp_path, "vehicles/car/b.png")
    out = path_tree(tmp_path, "**/{label}/{file}", extensions=_IMG_EXTS, source_name="s")
    assert [(r.label, r.record_id) for r in out] == [
        ("cat", "s/animals/cat/a.png"),
        ("car", "s/vehicles/car/b.png"),
    ]


def test_split_category_label_file(tmp_path: Path) -> None:
    _img(tmp_path, "train/big/cat/a.png")
    _img(tmp_path, "test/small/dog/b.png")
    out = path_tree(tmp_path, "{split}/*/{label}/{file}", extensions=_IMG_EXTS, source_name="s")
    # Deterministic rel_posix order: "test" < "train".
    assert [(r.split, r.label, r.record_id) for r in out] == [
        ("test", "dog", "s/test/small/dog/b.png"),
        ("train", "cat", "s/train/big/cat/a.png"),
    ]


def test_non_matching_extension_skipped(tmp_path: Path) -> None:
    _img(tmp_path, "cat/a.png")
    (tmp_path / "cat" / "notes.txt").write_text("ignore me")
    out = path_tree(tmp_path, "{label}/{file}", extensions=_IMG_EXTS, source_name="s")
    assert [r.record_id for r in out] == ["s/cat/a.png"]


def test_wrong_depth_file_skipped(tmp_path: Path) -> None:
    # A file at the wrong depth for the template is not matched.
    _img(tmp_path, "cat/a.png")  # depth 2 — matches {label}/{file}
    _img(tmp_path, "loose.png")  # depth 1 — does not match {label}/{file}
    out = path_tree(tmp_path, "{label}/{file}", extensions=_IMG_EXTS, source_name="s")
    assert [r.record_id for r in out] == ["s/cat/a.png"]


def test_deterministic_sorted_order(tmp_path: Path) -> None:
    for rel in ["dog/z.png", "cat/a.png", "cat/b.png"]:
        _img(tmp_path, rel)
    out = path_tree(tmp_path, "{label}/{file}", extensions=_IMG_EXTS, source_name="s")
    assert [r.record_id for r in out] == ["s/cat/a.png", "s/cat/b.png", "s/dog/z.png"]


def test_flat_file_layout(tmp_path: Path) -> None:
    _img(tmp_path, "a.png")
    _img(tmp_path, "b.png")
    out = path_tree(tmp_path, "{file}", extensions=_IMG_EXTS, source_name="s")
    assert [(r.record_id, r.label) for r in out] == [("s/a.png", None), ("s/b.png", None)]
