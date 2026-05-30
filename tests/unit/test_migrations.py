# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Recipe loader v1 -> v2 migration framework (Story I.x.1, G15).

The migration framework is shared infrastructure that I.x.1 (Filters),
I.x.2 (Generation), and I.x.3 (assertion naming) all register against
``migrations[(1, 2)]``. This file pins the v1->v2 surface for the
Filters reshape only; I.x.2 and I.x.3 add their own cases here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from datarefinery.core.errors import RecipeError
from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.loader import SUPPORTED_SCHEMA_VERSIONS, load, migrations
from datarefinery.recipe.migrations import (
    filters_reshape_v1_to_v2,
    generation_reshape_v1_to_v2,
)

# ---------------------------------------------------------------------------
# filters_reshape_v1_to_v2
# ---------------------------------------------------------------------------


def test_filters_reshape_lifts_op_and_renames_rest_to_params() -> None:
    """A v1 filter ``{predicate: {op, ...rest}}`` reshapes to v2
    ``{op, params: {...rest}}``."""
    v1 = {
        "Filters": [
            {
                "name": "keep_c0",
                "predicate": {
                    "op": "filter_by_label",
                    "labels": ["c0"],
                    "action": "include",
                },
            }
        ]
    }
    v2 = filters_reshape_v1_to_v2(v1)
    assert v2["Filters"] == [
        {
            "name": "keep_c0",
            "op": "filter_by_label",
            "params": {"labels": ["c0"], "action": "include"},
        }
    ]


def test_filters_reshape_lifts_seed_out_of_predicate() -> None:
    """``seed`` inside a v1 predicate lifts to the top-level
    ``FilterOp.seed`` field, matching v2 GenerationOp/AugmentationOp pattern."""
    v1 = {
        "Filters": [
            {
                "name": "sample",
                "predicate": {
                    "op": "random_sample",
                    "fraction": 0.5,
                    "seed": 42,
                },
            }
        ]
    }
    v2 = filters_reshape_v1_to_v2(v1)
    assert v2["Filters"] == [
        {
            "name": "sample",
            "op": "random_sample",
            "params": {"fraction": 0.5},
            "seed": 42,
        }
    ]


def test_filters_reshape_lifts_master_seed_form() -> None:
    """A v1 predicate seed of ``{from: master}`` lifts to the top-level seed."""
    v1 = {
        "Filters": [
            {
                "name": "sample",
                "predicate": {
                    "op": "random_sample",
                    "fraction": 0.5,
                    "seed": {"from": "master"},
                },
            }
        ]
    }
    v2 = filters_reshape_v1_to_v2(v1)
    assert v2["Filters"][0]["seed"] == {"from": "master"}
    assert "seed" not in v2["Filters"][0]["params"]


def test_filters_reshape_preserves_top_level_fields() -> None:
    """Non-predicate fields on a v1 ``FilterOp`` pass through unchanged."""
    v1 = {
        "Filters": [
            {
                "name": "f",
                "predicate": {"op": "filter_by_label", "labels": ["c0"]},
                "stages": ["pre_split", "post_split"],
                "splits": ["train", "val"],
            }
        ]
    }
    v2 = filters_reshape_v1_to_v2(v1)
    f = v2["Filters"][0]
    assert f["stages"] == ["pre_split", "post_split"]
    assert f["splits"] == ["train", "val"]


def test_filters_reshape_with_no_filters_is_noop() -> None:
    """Recipes without a Filters block (or with an empty list) pass through."""
    v1: dict[str, object] = {"plugin": "image_classification"}
    assert filters_reshape_v1_to_v2(v1) == v1
    v1b: dict[str, object] = {"Filters": []}
    assert filters_reshape_v1_to_v2(v1b) == v1b


def test_filters_reshape_rejects_predicate_missing_op() -> None:
    """A v1 predicate without an ``op`` key cannot be reshaped; the
    runtime already required ``predicate.op`` to be a string."""
    v1 = {"Filters": [{"name": "bad", "predicate": {"labels": ["c0"]}}]}
    with pytest.raises(RecipeError, match="predicate missing 'op'"):
        filters_reshape_v1_to_v2(v1)


def test_filters_reshape_rejects_v2_filter_with_predicate_key() -> None:
    """A filter already in v2 shape (has ``op`` at top level) but carrying a
    stray ``predicate`` key indicates an authoring mistake; refuse it
    rather than silently dropping data."""
    v1 = {
        "Filters": [
            {
                "name": "f",
                "op": "filter_by_label",
                "params": {},
                "predicate": {"labels": ["c0"]},
            }
        ]
    }
    with pytest.raises(RecipeError, match="both 'op' and 'predicate'"):
        filters_reshape_v1_to_v2(v1)


def test_filters_reshape_is_idempotent_on_v2_input() -> None:
    """Re-running the migration on already-v2 input is a no-op (so the
    composed migration chain stays robust under partial application)."""
    v2 = {"Filters": [{"name": "f", "op": "filter_by_label", "params": {"labels": ["c0"]}}]}
    assert filters_reshape_v1_to_v2(v2) == v2


# ---------------------------------------------------------------------------
# Loader migration registry + schema-version gate
# ---------------------------------------------------------------------------


def test_schema_version_2_is_supported() -> None:
    assert 2 in SUPPORTED_SCHEMA_VERSIONS
    # v1 still accepted (the gate doesn't refuse old recipes; the migration
    # path is the documented upgrade).
    assert 1 in SUPPORTED_SCHEMA_VERSIONS


def test_migrations_registry_has_v1_to_v2_entry() -> None:
    assert (1, 2) in migrations


# ---------------------------------------------------------------------------
# End-to-end loader: v1 recipe migrates to v2 canonical bytes byte-identical
# to a directly-authored v2 recipe.
# ---------------------------------------------------------------------------


_V1_RECIPE = """\
schema_version: 1
plugin: image_classification
seed: 7
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
Filters:
  - name: keep_c0
    predicate:
      op: filter_by_label
      labels: [c0]
      action: include
  - name: sample_half
    predicate:
      op: random_sample
      fraction: 0.5
      seed: 13
Splits:
  ratios:
    train: 0.8
    val: 0.1
    test: 0.1
  seed: 7
"""


_V2_RECIPE = """\
schema_version: 2
plugin: image_classification
seed: 7
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
Filters:
  - name: keep_c0
    op: filter_by_label
    params:
      labels: [c0]
      action: include
  - name: sample_half
    op: random_sample
    params:
      fraction: 0.5
    seed: 13
Splits:
  ratios:
    train: 0.8
    val: 0.1
    test: 0.1
  seed: 7
"""


def test_v1_recipe_round_trips_to_v2_canonical_bytes(tmp_path: Path) -> None:
    v1_path = tmp_path / "v1.yaml"
    v1_path.write_text(_V1_RECIPE, encoding="utf-8")
    v2_path = tmp_path / "v2.yaml"
    v2_path.write_text(_V2_RECIPE, encoding="utf-8")
    v1_bytes = to_canonical_bytes(load(v1_path))
    v2_bytes = to_canonical_bytes(load(v2_path))
    assert v1_bytes == v2_bytes
    # And the digest is stable across repeated calls.
    assert hashlib.sha256(v1_bytes).hexdigest() == hashlib.sha256(v2_bytes).hexdigest()


def test_loader_rejects_unknown_schema_version(tmp_path: Path) -> None:
    p = tmp_path / "future.yaml"
    p.write_text(_V1_RECIPE.replace("schema_version: 1", "schema_version: 99"), encoding="utf-8")
    with pytest.raises(RecipeError, match="unsupported schema_version=99"):
        load(p)


# ---------------------------------------------------------------------------
# generation_reshape_v1_to_v2 (Story I.x.2 / G12)
# ---------------------------------------------------------------------------


def test_generation_reshape_lifts_op_from_name_when_no_explicit_op() -> None:
    """Canonical v1 shape: the op-name lived in ``GenerationOp.name`` (the
    runtime did ``plugin.operation_factory("Generation", op.name)``). The
    migration copies ``name`` to a new top-level ``op`` field so v2's
    explicit ``op:`` matches what v1's runtime looked up."""
    v1 = {
        "Generation": [
            {
                "name": "duplicate_minority_class",
                "inputs": ["image", "label"],
                "output_schema": {
                    "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                    "label": {"dtype": "str"},
                },
                "seed": 42,
                "applies_at": ["train"],
                "params": {"factor": 3},
            }
        ]
    }
    v2 = generation_reshape_v1_to_v2(v1)
    gen = v2["Generation"][0]
    assert gen["op"] == "duplicate_minority_class"
    assert gen["name"] == "duplicate_minority_class"


def test_generation_reshape_lifts_op_from_params_workaround_pattern() -> None:
    """v1 workaround pattern: authors who wanted a separate op-name from
    the recipe identifier stashed ``op:`` inside ``params``. Lift it to
    top-level and remove it from ``params`` so the v2 shape stays clean."""
    v1 = {
        "Generation": [
            {
                "name": "apply_corruptions",
                "inputs": ["image"],
                "output_schema": {"image": {"dtype": "uint8", "shape": [32, 32, 3]}},
                "seed": 0,
                "applies_at": ["train"],
                "params": {"op": "imagecorruptions_apply", "severities": [1, 3]},
            }
        ]
    }
    v2 = generation_reshape_v1_to_v2(v1)
    gen = v2["Generation"][0]
    assert gen["op"] == "imagecorruptions_apply"
    assert "op" not in gen["params"]
    assert gen["params"] == {"severities": [1, 3]}


def test_generation_reshape_renames_applies_at_to_splits() -> None:
    v1 = {
        "Generation": [
            {
                "name": "g",
                "inputs": ["image"],
                "output_schema": {"image": {"dtype": "uint8", "shape": [8, 8, 3]}},
                "seed": 0,
                "applies_at": ["train", "val"],
            }
        ]
    }
    v2 = generation_reshape_v1_to_v2(v1)
    gen = v2["Generation"][0]
    assert gen["splits"] == ["train", "val"]
    assert "applies_at" not in gen


def test_generation_reshape_lifts_output_schema_matches_input_workaround() -> None:
    """v1 workaround pattern: ``output_schema_matches_input: true``
    documented in the gap doc as how authors expressed the shorthand
    before the model supported it. Lift to v2's ``output_schema: "matches_input"``."""
    v1 = {
        "Generation": [
            {
                "name": "g",
                "inputs": ["image"],
                "output_schema": {"image": {"dtype": "uint8", "shape": [8, 8, 3]}},
                "output_schema_matches_input": True,
                "seed": 0,
                "applies_at": ["train"],
            }
        ]
    }
    v2 = generation_reshape_v1_to_v2(v1)
    gen = v2["Generation"][0]
    assert gen["output_schema"] == "matches_input"
    assert "output_schema_matches_input" not in gen


def test_generation_reshape_preserves_explicit_output_schema() -> None:
    """Explicit dicts pass through (cannot inflate to ``matches_input``
    without runtime context — the gap doc spells this out)."""
    schema = {"image": {"dtype": "uint8", "shape": [8, 8, 3]}}
    v1 = {
        "Generation": [
            {
                "name": "g",
                "inputs": ["image"],
                "output_schema": schema,
                "seed": 0,
                "applies_at": ["train"],
            }
        ]
    }
    v2 = generation_reshape_v1_to_v2(v1)
    assert v2["Generation"][0]["output_schema"] == schema


def test_generation_reshape_preserves_seed_and_replace_input_records() -> None:
    """Fields untouched by the reshape ride through verbatim."""
    v1 = {
        "Generation": [
            {
                "name": "g",
                "inputs": ["image"],
                "output_schema": {"image": {"dtype": "uint8", "shape": [8, 8, 3]}},
                "seed": {"from": "master"},
                "applies_at": ["train"],
                "replace_input_records": True,
            }
        ]
    }
    v2 = generation_reshape_v1_to_v2(v1)
    gen = v2["Generation"][0]
    assert gen["seed"] == {"from": "master"}
    assert gen["replace_input_records"] is True


def test_generation_reshape_no_generation_is_noop() -> None:
    v1: dict[str, object] = {"plugin": "image_classification"}
    assert generation_reshape_v1_to_v2(v1) == v1
    v1b: dict[str, object] = {"Generation": []}
    assert generation_reshape_v1_to_v2(v1b) == v1b


def test_generation_reshape_is_idempotent_on_v2_input() -> None:
    """Already-v2 entries (with top-level ``op``/``splits``) pass through
    unchanged — the chain stays robust under partial application."""
    v2_in = {
        "Generation": [
            {
                "name": "g",
                "op": "duplicate_minority_class",
                "inputs": ["image"],
                "output_schema": "matches_input",
                "seed": 0,
                "splits": ["train"],
                "params": {"factor": 2},
            }
        ]
    }
    assert generation_reshape_v1_to_v2(v2_in) == v2_in


# ---------------------------------------------------------------------------
# End-to-end loader: v1 Generation block round-trips to v2 canonical bytes
# byte-identical to a directly-authored v2 recipe.
# ---------------------------------------------------------------------------


_V1_RECIPE_WITH_GENERATION = """\
schema_version: 1
plugin: image_classification
seed: 7
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
Generation:
  - name: duplicate_minority_class
    inputs: [image, label]
    output_schema:
      image: { dtype: uint8, shape: [32, 32, 3] }
      label: { dtype: int32 }
    seed: 99
    applies_at: [train]
    params:
      factor: 3
Splits:
  ratios:
    train: 0.8
    val: 0.1
    test: 0.1
  seed: 7
"""


_V2_RECIPE_WITH_GENERATION = """\
schema_version: 2
plugin: image_classification
seed: 7
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
Generation:
  - name: duplicate_minority_class
    op: duplicate_minority_class
    inputs: [image, label]
    output_schema:
      image: { dtype: uint8, shape: [32, 32, 3] }
      label: { dtype: int32 }
    seed: 99
    splits: [train]
    params:
      factor: 3
Splits:
  ratios:
    train: 0.8
    val: 0.1
    test: 0.1
  seed: 7
"""


def test_v1_generation_recipe_round_trips_to_v2_canonical_bytes(tmp_path: Path) -> None:
    v1_path = tmp_path / "v1.yaml"
    v1_path.write_text(_V1_RECIPE_WITH_GENERATION, encoding="utf-8")
    v2_path = tmp_path / "v2.yaml"
    v2_path.write_text(_V2_RECIPE_WITH_GENERATION, encoding="utf-8")
    v1_bytes = to_canonical_bytes(load(v1_path))
    v2_bytes = to_canonical_bytes(load(v2_path))
    assert v1_bytes == v2_bytes
    assert hashlib.sha256(v1_bytes).hexdigest() == hashlib.sha256(v2_bytes).hexdigest()
