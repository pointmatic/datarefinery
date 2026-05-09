# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Per-stage failure-mode integration tests (Story E.e).

For each pipeline stage, a forced failure is injected and the test
asserts:

1. The runner re-raises the failure (the temp dir is *not* swallowed
   silently).
2. ``mark_failed`` writes a ``FAILED`` JSON marker into the temp dir
   naming the stage that failed.
3. The final cache path (``<cache>/instances/<recipe16>/<input16>/<seed>/``)
   is never touched - no partial promote.

Tests bypass the FR-2 validator and instantiate :class:`PipelineRunner`
directly because some failure recipes intentionally violate FR-2 checks
(e.g., a non-train augmentation declaration is the trigger for the
augmentations-stage failure path).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from datarefinery.cache.identity import compute_cache_key
from datarefinery.cache.layout import (
    instance_dir,
    manifest_path,
)
from datarefinery.cache.layout import (
    tmp_dir as tmp_dir_for,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import (
    ContractError,
    MaterializeError,
)
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe

# ---------------------------------------------------------------------------
# Failing-plugin wrapper (extends the test_runner.py pattern)
# ---------------------------------------------------------------------------


class _FailingPlugin:
    """Wraps the image plugin but raises whenever ``fail_op`` is requested."""

    def __init__(self, fail_op: str | None) -> None:
        self.name = "failing_image"
        self.schema_version = 1
        self.supported_sections = IMAGE_PLUGIN.supported_sections
        self.supported_operations = IMAGE_PLUGIN.supported_operations
        self._fail_op = fail_op

    def operation_factory(self, section: str, op_name: str) -> Any:
        if op_name == self._fail_op:
            raise RuntimeError(f"forced failure in {op_name}")
        return IMAGE_PLUGIN.operation_factory(section, op_name)

    def is_stub(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Recipe + record helpers
# ---------------------------------------------------------------------------


def _img(value: int) -> np.ndarray:
    return np.full((4, 4, 3), value, dtype=np.uint8)


def _records(n: int = 12, classes: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": _img(20 + i * 5),
            "label": f"c{i % classes}",
            "path": f"/data/c{i % classes}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[dict[str, Any]]) -> dict[str, str]:
    import hashlib

    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _base_recipe_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "Input": {
            "sources": [
                {"name": "train", "type": "image_folder", "path": "/data/train"}
            ]
        },
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                "label": {"dtype": "str"},
            }
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {
            "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
            "seed": 11,
        },
    }


# ---------------------------------------------------------------------------
# Per-stage recipe modifiers
# ---------------------------------------------------------------------------


def _fail_input_contracts(d: dict[str, Any]) -> dict[str, Any]:
    d["InputContracts"] = [
        {
            "field": None,
            "assertion": {"kind": "record_count_min", "value": 10000},
            "severity": "error",
        }
    ]
    return d


def _fail_pre_split_filter(d: dict[str, Any]) -> dict[str, Any]:
    d["Filters"] = [
        {
            "name": "boom_filter",
            "predicate": {"op": "filter_by_label", "labels": ["c0"]},
            "stages": ["pre_split"],
        }
    ]
    return d


def _fail_post_split_filter(d: dict[str, Any]) -> dict[str, Any]:
    d["Filters"] = [
        {
            "name": "boom_filter",
            "predicate": {"op": "filter_by_label", "labels": ["c0"]},
            "stages": ["post_split"],
            "splits": ["train"],
        }
    ]
    return d


def _fail_splits(d: dict[str, Any]) -> dict[str, Any]:
    """Use a key_assignment that the records do not satisfy."""
    d["Splits"] = {
        "key_assignment": {
            "field": "label",
            "mapping": {"unmapped_class": "train"},
        },
        "seed": 11,
    }
    return d


def _fail_generation(d: dict[str, Any]) -> dict[str, Any]:
    d["Generation"] = [
        {
            "name": "boom_gen",
            "inputs": ["image", "label"],
            "output_schema": {
                "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                "label": {"dtype": "str"},
            },
            "seed": 1,
            "applies_at": ["train"],
        }
    ]
    # Use a real op name that we'll force the plugin to fail on.
    d["Generation"][0]["name"] = "duplicate_minority_class"
    return d


def _fail_transformation(d: dict[str, Any]) -> dict[str, Any]:
    d["Transformations"] = [
        {
            "name": "norm",
            "op": "normalize",
            "params": {},
            "fit_source": "train",
            "splits": ["train", "val", "test"],
        }
    ]
    return d


def _fail_featurization(d: dict[str, Any]) -> dict[str, Any]:
    # Switch Labels to derived so label_from_path is the resolution
    # path and a featurization op is required.
    d["Labels"] = {
        "field": "label",
        "source": {"kind": "derived", "derivation": "parent_directory_name"},
    }
    d["Featurizations"] = [
        {
            "name": "derive_label",
            "inputs": ["path"],
            "output_field": "label",
            "op": "label_from_path",
            "params": {"source": "parent_directory_name"},
            "splits": ["train", "val", "test"],
        }
    ]
    # Drop the pre-attached label so the loader-equivalent records don't
    # collide; the test record fixture still attaches `label`, so this
    # exercise is only for the failure path.
    return d


def _fail_augmentations(d: dict[str, Any]) -> dict[str, Any]:
    """Non-train augmentation -> trips the runner's defensive guard."""
    d["Augmentations"] = [
        {
            "name": "boom_aug",
            "op": "horizontal_flip",
            "splits": ["val"],
            "seed": 1,
        }
    ]
    return d


def _fail_output_expectations(d: dict[str, Any]) -> dict[str, Any]:
    d["OutputExpectations"] = [
        {
            "field": None,
            "assertion": {"kind": "record_count_min", "value": 10000},
            "severity": "error",
        }
    ]
    return d


def _fail_visualizations(d: dict[str, Any]) -> dict[str, Any]:
    d["Visualizations"] = [
        {
            "name": "boom_viz",
            "op": "class_distribution_histogram",
            "params": {},
            "stage": "post_pipeline",
            "mode": "reporting",
        }
    ]
    return d


# ---------------------------------------------------------------------------
# Parametrized failure cases
#
# Each entry: (stage_name, recipe_modifier, fail_op_name | None, expected_exc)
#
# `fail_op_name` is the plugin op that the FailingPlugin should raise on;
# `None` means the failure originates in stage-driver code, not a plugin op.
# ---------------------------------------------------------------------------


_CASES: list[tuple[str, Any, str | None, type[Exception]]] = [
    ("InputContracts", _fail_input_contracts, None, ContractError),
    ("Filters/pre_split", _fail_pre_split_filter, "filter_by_label", RuntimeError),
    ("Splits", _fail_splits, None, MaterializeError),
    ("Filters/post_split", _fail_post_split_filter, "filter_by_label", RuntimeError),
    ("Generation", _fail_generation, "duplicate_minority_class", RuntimeError),
    ("Transformations", _fail_transformation, "normalize", RuntimeError),
    ("Featurizations", _fail_featurization, "label_from_path", RuntimeError),
    ("Augmentations", _fail_augmentations, None, MaterializeError),
    ("OutputExpectations", _fail_output_expectations, None, ContractError),
    ("Visualizations", _fail_visualizations, "class_distribution_histogram", MaterializeError),
]


@pytest.mark.parametrize(
    ("stage_name", "modifier", "fail_op", "expected_exc"),
    _CASES,
    ids=[c[0] for c in _CASES],
)
def test_stage_failure_leaves_failed_marker_and_skips_promote(
    tmp_path: Path,
    stage_name: str,
    modifier: Any,
    fail_op: str | None,
    expected_exc: type[Exception],
) -> None:
    cache_root = tmp_path / "cache"
    payload = modifier(copy.deepcopy(_base_recipe_dict()))
    recipe = Recipe.model_validate(payload)
    plugin: Mapping[str, Any] = (
        _FailingPlugin(fail_op) if fail_op is not None else IMAGE_PLUGIN  # type: ignore[assignment]
    )
    config = RuntimeConfig(cache_root=cache_root)
    records = _records()

    runner = PipelineRunner(
        recipe=recipe,
        plugin=plugin,  # type: ignore[arg-type]
        config=config,
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-failure")

    with pytest.raises(expected_exc):
        runner.run(
            temp,
            raw_records=records,
            raw_input_hashes=_input_hashes(records),
        )

    # Temp dir survives with a FAILED marker naming the stage.
    assert temp.exists(), f"temp dir was removed; {stage_name=}"
    failed_path = temp / "FAILED"
    assert failed_path.exists(), (
        f"FAILED marker missing at {failed_path}; {stage_name=}"
    )
    payload_marker = json.loads(failed_path.read_text(encoding="utf-8"))
    assert payload_marker["stage"] == stage_name, (
        f"FAILED marker stage={payload_marker['stage']!r}; "
        f"expected {stage_name!r}"
    )

    # Final cache path was never touched by the failed run.
    cache_key = compute_cache_key(recipe, _input_hashes(records), 7)
    final_dir = instance_dir(cache_root, cache_key)
    assert not manifest_path(final_dir).exists()
