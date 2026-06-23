# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story K.i (FR-K-5): check 31 — a labeled `*_tree` source needs one label source.

Static (filesystem-blind) closure of the validate/materialize asymmetry: a
labeled `*_tree` source must carry exactly one label source — a `{label}` token
in its `layout` OR a `label_from` sidecar — and never both. Caught at `validate`
(naming the source + layout) instead of deep in `materialize`.
"""

from __future__ import annotations

from typing import Any

from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import CheckResult, ValidationReport, validate

_CHECK_ID = 31


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


def _fails(report: ValidationReport, check_id: int) -> list[CheckResult]:
    return [r for r in report.results if r.check_id == check_id and r.status == "fail"]


def test_check_31_passes_label_token_source() -> None:
    report = validate(
        _recipe({"name": "i", "type": "image_tree", "path": "/d", "layout": "{label}/{file}"}),
        IMAGE_PLUGIN,
    )
    assert _fails(report, _CHECK_ID) == []


def test_check_31_passes_label_from_source() -> None:
    report = validate(
        _recipe(
            {
                "name": "i",
                "type": "image_tree",
                "path": "/d",
                "layout": "**/{file}",
                "label_from": {"path": "/d/l.csv", "join": "by_row_order", "label_field": "c"},
            }
        ),
        IMAGE_PLUGIN,
    )
    assert _fails(report, _CHECK_ID) == []


def test_check_31_passes_unlabeled_source() -> None:
    report = validate(
        _recipe(
            {
                "name": "i",
                "type": "image_tree",
                "path": "/d",
                "layout": "**/{file}",
                "unlabeled": True,
                "partition": "test",
            }
        ),
        IMAGE_PLUGIN,
    )
    assert _fails(report, _CHECK_ID) == []


def test_check_31_fails_no_label_source() -> None:
    # labeled tree, no {label}, no label_from -> no label source.
    report = validate(
        _recipe({"name": "i", "type": "image_tree", "path": "/d", "layout": "**/{file}"}),
        IMAGE_PLUGIN,
    )
    failures = _fails(report, _CHECK_ID)
    assert len(failures) == 1
    assert "i" in failures[0].message and "no label source" in failures[0].message.lower()


def test_check_31_fails_two_label_sources() -> None:
    # {label} token AND label_from -> contradictory.
    report = validate(
        _recipe(
            {
                "name": "i",
                "type": "image_tree",
                "path": "/d",
                "layout": "{label}/{file}",
                "label_from": {"path": "/d/l.csv", "join": "by_row_order", "label_field": "c"},
            }
        ),
        IMAGE_PLUGIN,
    )
    failures = _fails(report, _CHECK_ID)
    assert len(failures) == 1
    assert "both" in failures[0].message.lower() or "two" in failures[0].message.lower()


def test_check_31_ignores_non_tree_sources() -> None:
    report = validate(
        _recipe({"name": "i", "type": "image_folder", "path": "/d"}),
        IMAGE_PLUGIN,
    )
    assert _fails(report, _CHECK_ID) == []
