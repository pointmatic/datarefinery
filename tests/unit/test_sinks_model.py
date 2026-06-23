# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the Sinks recipe section (Story I.d).

Covers `SinkOp` pydantic shape, the closed `stage` Literal, defaulting
behaviour for `splits`, and participation of the `Sinks` list in
canonical recipe bytes.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.models import Recipe, SinkOp


def _minimal_recipe_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 42,
        "Input": {
            "sources": [
                {
                    "name": "train",
                    "type": "image_folder",
                    "path": "/data/train",
                }
            ],
        },
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                "label": {"dtype": "int32"},
            },
        },
        "Labels": {
            "field": "label",
            "source": {"kind": "derived", "derivation": "parent_directory_name"},
        },
        "Splits": {
            "ratios": {"train": 0.8, "val": 0.1, "test": 0.1},
            "stratify_by": "label",
            "seed": 7,
        },
    }


def _sink_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "pngs",
        "stage": "post_Filters",
        "field": "image",
        "format": "png_per_record",
        "path_template": "exports/{label}/{record_id}.png",
    }
    base.update(overrides)
    return base


def test_sink_op_minimal_validates() -> None:
    sink = SinkOp.model_validate(_sink_dict())
    assert sink.name == "pngs"
    assert sink.stage == "post_Filters"
    assert sink.field == "image"
    assert sink.format == "png_per_record"
    assert sink.path_template == "exports/{label}/{record_id}.png"
    assert sink.splits is None  # default: all splits at the chosen stage


def test_sink_op_with_splits_list() -> None:
    sink = SinkOp.model_validate(_sink_dict(splits=["train", "val"]))
    assert sink.splits == ["train", "val"]


def test_sink_op_rejects_unknown_stage() -> None:
    with pytest.raises(ValidationError):
        SinkOp.model_validate(_sink_dict(stage="post_bogus"))


def test_sink_op_rejects_unknown_format() -> None:
    with pytest.raises(ValidationError):
        SinkOp.model_validate(_sink_dict(format="parquet"))


def test_sink_op_accepts_npy_per_record_format() -> None:
    # Story K.c: additive `npy_per_record` float-array sink format.
    sink = SinkOp.model_validate(
        _sink_dict(
            field="mel", format="npy_per_record", path_template="features/{split}/{record_id}.npy"
        )
    )
    assert sink.format == "npy_per_record"
    assert sink.field == "mel"


def test_sink_op_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SinkOp.model_validate(_sink_dict(unexpected=True))


def test_sink_op_is_frozen() -> None:
    sink = SinkOp.model_validate(_sink_dict())
    with pytest.raises((ValidationError, TypeError, AttributeError)):
        sink.name = "renamed"  # type: ignore[misc]


def test_recipe_sinks_defaults_empty() -> None:
    recipe = Recipe.model_validate(_minimal_recipe_dict())
    assert recipe.Sinks == []


def test_recipe_accepts_sinks_section() -> None:
    payload = _minimal_recipe_dict()
    payload["Sinks"] = [_sink_dict()]
    recipe = Recipe.model_validate(payload)
    assert len(recipe.Sinks) == 1
    assert recipe.Sinks[0].name == "pngs"


def test_recipe_sinks_participates_in_canonical_bytes() -> None:
    base_payload = _minimal_recipe_dict()
    with_sink = _minimal_recipe_dict()
    with_sink["Sinks"] = [_sink_dict()]
    base_hash = hashlib.sha256(to_canonical_bytes(Recipe.model_validate(base_payload))).hexdigest()
    sink_hash = hashlib.sha256(to_canonical_bytes(Recipe.model_validate(with_sink))).hexdigest()
    assert base_hash != sink_hash, (
        "Adding a Sinks entry must shift canonical bytes (cache identity participation)"
    )


def test_recipe_sinks_path_template_alone_changes_canonical_bytes() -> None:
    payload_a = _minimal_recipe_dict()
    payload_a["Sinks"] = [_sink_dict(path_template="a/{record_id}.png")]
    payload_b = _minimal_recipe_dict()
    payload_b["Sinks"] = [_sink_dict(path_template="b/{record_id}.png")]
    hash_a = hashlib.sha256(to_canonical_bytes(Recipe.model_validate(payload_a))).hexdigest()
    hash_b = hashlib.sha256(to_canonical_bytes(Recipe.model_validate(payload_b))).hexdigest()
    assert hash_a != hash_b
