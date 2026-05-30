# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-4 canonical-bytes tests — the cache reproducibility contract.

Cosmetic-edit invariance (whitespace, comments, key order) and value-edit
sensitivity. The pinned-digest gate that signs off on cache
invalidations lives in its own file (`test_canonical_hash_pin.py`,
Story E.f) so the gate is easy to spot in `git diff` and harder to
edit accidentally.
"""

from __future__ import annotations

import json
from pathlib import Path

from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.loader import load

_BASELINE_YAML = """\
schema_version: 1
plugin: image_classification
seed: 42
Input:
  sources:
    - name: train
      type: image_folder
      path: /data/train
Output:
  record_schema:
    image:
      dtype: uint8
      shape: [32, 32, 3]
    label:
      dtype: int32
Labels:
  field: label
  source:
    kind: derived
    derivation: parent_directory_name
Splits:
  ratios:
    train: 0.8
    val: 0.1
    test: 0.1
  stratify_by: label
  seed: 7
"""

_REORDERED_YAML = """\
Splits:
  seed: 7
  stratify_by: label
  ratios:
    test: 0.1
    train: 0.8
    val: 0.1
Output:
  record_schema:
    label:
      dtype: int32
    image:
      shape: [32, 32, 3]
      dtype: uint8
Labels:
  source:
    derivation: parent_directory_name
    kind: derived
  field: label
Input:
  sources:
    - path: /data/train
      type: image_folder
      name: train
seed: 42
plugin: image_classification
schema_version: 1
"""

_WHITESPACE_YAML = """\


schema_version: 1

plugin:    image_classification
seed:   42

Input:
  sources:
    -   name: train
        type: image_folder
        path: /data/train

Output:
  record_schema:
    image:
      dtype: uint8
      shape: [32, 32, 3]
    label:
      dtype: int32
Labels:
  field: label
  source:
    kind: derived
    derivation: parent_directory_name


Splits:
  ratios:
    train: 0.8
    val: 0.1
    test: 0.1
  stratify_by: label
  seed: 7

"""

_COMMENTED_YAML = """\
# Top-of-file comment.
schema_version: 1  # current schema
plugin: image_classification  # registered via entry-point group
seed: 42
Input:  # raw image directories
  sources:
    - name: train
      type: image_folder
      path: /data/train
Output:
  record_schema:
    image:
      dtype: uint8
      shape: [32, 32, 3]
    label:
      dtype: int32
Labels:
  field: label
  source:
    # derived from the immediate parent directory name
    kind: derived
    derivation: parent_directory_name
Splits:
  ratios:
    train: 0.8
    val: 0.1
    test: 0.1
  stratify_by: label
  seed: 7
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / f"{name}.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def _canonical(tmp_path: Path, name: str, text: str) -> bytes:
    return to_canonical_bytes(load(_write(tmp_path, name, text)))


def test_whitespace_only_yaml_edits_are_canonical_invariant(tmp_path: Path) -> None:
    base = _canonical(tmp_path, "base", _BASELINE_YAML)
    ws = _canonical(tmp_path, "ws", _WHITESPACE_YAML)
    assert base == ws


def test_comment_only_yaml_edits_are_canonical_invariant(tmp_path: Path) -> None:
    base = _canonical(tmp_path, "base", _BASELINE_YAML)
    commented = _canonical(tmp_path, "c", _COMMENTED_YAML)
    assert base == commented


def test_key_reordered_yaml_is_canonical_invariant(tmp_path: Path) -> None:
    base = _canonical(tmp_path, "base", _BASELINE_YAML)
    reordered = _canonical(tmp_path, "r", _REORDERED_YAML)
    assert base == reordered


def test_value_change_produces_different_canonical_bytes(tmp_path: Path) -> None:
    base = _canonical(tmp_path, "base", _BASELINE_YAML)
    changed_seed = _BASELINE_YAML.replace("seed: 42", "seed: 43")
    different = _canonical(tmp_path, "vc", changed_seed)
    assert base != different


def test_added_section_produces_different_canonical_bytes(tmp_path: Path) -> None:
    base = _canonical(tmp_path, "base", _BASELINE_YAML)
    extra = _BASELINE_YAML + "Filters:\n  - name: dedup\n    op: dedup\n    params: {}\n"
    different = _canonical(tmp_path, "extra", extra)
    assert base != different


def test_canonical_bytes_are_valid_utf8_json(tmp_path: Path) -> None:
    canonical = _canonical(tmp_path, "base", _BASELINE_YAML)
    payload = json.loads(canonical.decode("utf-8"))
    # Authored as v1; loader migrates the recipe to the latest schema_version
    # before canonical-bytes computation (Story I.x.1).
    assert payload["schema_version"] == 2
    # Compact form: no whitespace separators.
    text = canonical.decode("utf-8")
    assert ", " not in text
    assert ": " not in text


def test_repeated_calls_are_byte_stable(tmp_path: Path) -> None:
    a = _canonical(tmp_path, "a", _BASELINE_YAML)
    b = _canonical(tmp_path, "b", _BASELINE_YAML)
    assert a == b
