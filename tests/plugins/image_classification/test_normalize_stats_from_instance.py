# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.n.2 integration tests for `normalize` + `stats_from_instance`.

End-to-end via `PipelineRunner`: a "train" recipe writes
`fitted_statistics/norm/`, and an "eval" recipe imports those statistics
via `stats_from_instance` instead of fitting locally. Plus the three
sibling-resolver failure modes surfaced through the apply path and the
check-22 mutual-exclusion validator.
"""

from __future__ import annotations

import hashlib
import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from datarefinery.cache.layout import (
    fitted_stats_dir,
)
from datarefinery.cache.layout import (
    tmp_dir as tmp_dir_for,
)
from datarefinery.cache.sibling_stats import (
    SiblingInstanceNotFoundError,
    SiblingOpNotFoundError,
    SiblingStatsIncompatibleError,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.pipeline.stages.transformations import apply_transformations
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.loader import load as load_recipe
from datarefinery.recipe.models import Recipe, TransformationOp
from datarefinery.recipe.validator import validate

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_TRAIN_RECIPE_YAML = textwrap.dedent(
    """\
    schema_version: 1
    plugin: image_classification
    seed: 0
    Input:
      sources:
        - name: train
          type: image_folder
          path: /data/train
    Output:
      record_schema:
        image: {dtype: uint8, shape: [4, 4, 3]}
        label: {dtype: str}
    Labels:
      field: label
      source: {kind: direct}
    Splits:
      ratios: {train: 0.6, val: 0.2, test: 0.2}
      seed: 11
    Transformations:
      - name: norm
        op: normalize
        params: {}
        fit_source: train
        splits: [train, val, test]
    """
)


def _img(value: int) -> np.ndarray:
    return np.full((4, 4, 3), value, dtype=np.uint8)


def _train_records(n: int = 12) -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"trn_{i:04d}",
            "image": _img(20 + i * 5),
            "label": f"c{i % 2}",
            "path": f"/data/train/c{i % 2}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _eval_records(n: int = 9) -> list[Mapping[str, Any]]:
    return [
        {
            "record_id": f"evl_{i:04d}",
            "image": _img(100 + i * 3),
            "label": f"c{i % 2}",
            "path": f"/data/eval/c{i % 2}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _write_train_recipe(path: Path) -> Path:
    path.write_text(_TRAIN_RECIPE_YAML, encoding="utf-8")
    return path


def _eval_recipe(*, sibling_recipe: Path, sibling_op_id: str = "norm") -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {"sources": [{"name": "train", "type": "image_folder", "path": "/data/eval"}]},
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {"field": "label", "source": {"kind": "direct"}},
            "Splits": {
                "ratios": {"train": 0.34, "val": 0.33, "test": 0.33},
                "seed": 11,
            },
            "Transformations": [
                {
                    "name": "norm",
                    "op": "normalize",
                    "params": {
                        "stats_from_instance": {
                            "recipe": str(sibling_recipe),
                            "op_id": sibling_op_id,
                        }
                    },
                    "splits": ["train", "val", "test"],
                }
            ],
        }
    )


def _materialize_train(cache_root: Path, recipe_path: Path) -> Path:
    """Run the train recipe so its `fitted_statistics/norm/` exists."""
    recipe = load_recipe(recipe_path)
    records = _train_records()
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "train-run")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    return result.instance_dir


# ---------------------------------------------------------------------------
# End-to-end through PipelineRunner
# ---------------------------------------------------------------------------


def test_eval_recipe_imports_sibling_fitted_stats_end_to_end(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    train_recipe_path = _write_train_recipe(tmp_path / "train_recipe.yaml")

    train_inst = _materialize_train(cache_root, train_recipe_path)
    # Sanity: train recipe persisted fitted stats locally.
    assert (fitted_stats_dir(train_inst) / "norm" / "mean.parquet").exists()
    assert (fitted_stats_dir(train_inst) / "norm" / "std.parquet").exists()

    eval_recipe = _eval_recipe(sibling_recipe=train_recipe_path)
    eval_runner = PipelineRunner(
        recipe=eval_recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=11,
    )
    eval_records = _eval_records()
    eval_temp = tmp_dir_for(cache_root, "eval-run-1")
    eval_result = eval_runner.run(
        eval_temp,
        raw_records=eval_records,
        raw_input_hashes=_input_hashes(eval_records),
    )

    # Eval did not perform its own fit, so no fitted_statistics/norm/.
    assert not (fitted_stats_dir(eval_result.instance_dir) / "norm").exists()
    # Dataset JSONL still emitted across all declared splits.
    from datarefinery.cache.layout import dataset_dir

    for split in ("train", "val", "test"):
        assert (dataset_dir(eval_result.instance_dir) / f"{split}.jsonl").exists()


def test_eval_recipe_is_byte_identical_across_repeated_runs(tmp_path: Path) -> None:
    cache_root_a = tmp_path / "cache-a"
    cache_root_b = tmp_path / "cache-b"
    # Each eval-only cache root needs its own train materialization to
    # populate the sibling instance. The train recipe path is shared.
    train_recipe_path = _write_train_recipe(tmp_path / "train_recipe.yaml")
    _materialize_train(cache_root_a, train_recipe_path)
    _materialize_train(cache_root_b, train_recipe_path)

    eval_recipe = _eval_recipe(sibling_recipe=train_recipe_path)
    eval_records = _eval_records()

    def _run(cache_root: Path, run_id: str) -> Path:
        runner = PipelineRunner(
            recipe=eval_recipe,
            plugin=IMAGE_PLUGIN,
            config=RuntimeConfig(cache_root=cache_root),
            seed=11,
        )
        temp = tmp_dir_for(cache_root, run_id)
        return runner.run(
            temp,
            raw_records=eval_records,
            raw_input_hashes=_input_hashes(eval_records),
        ).instance_dir

    inst_a = _run(cache_root_a, "eval-a")
    inst_b = _run(cache_root_b, "eval-b")

    from datarefinery.cache.layout import dataset_dir

    for split in ("train", "val", "test"):
        bytes_a = (dataset_dir(inst_a) / f"{split}.jsonl").read_bytes()
        bytes_b = (dataset_dir(inst_b) / f"{split}.jsonl").read_bytes()
        assert bytes_a == bytes_b, f"split {split!r} differs between runs"


# ---------------------------------------------------------------------------
# Parity: imported stats == in-recipe fit_source: train (same train data)
# ---------------------------------------------------------------------------


def test_imported_stats_apply_matches_in_recipe_fit_source(tmp_path: Path) -> None:
    """Calling apply_transformations with stats_from_instance against
    eval records produces the same per-record output as applying the
    sibling's recorded mean/std directly. This is the cross-recipe
    parity contract: the apply phase uses the sibling's statistics
    rather than refitting locally.
    """
    cache_root = tmp_path / "cache"
    train_recipe_path = _write_train_recipe(tmp_path / "train_recipe.yaml")
    train_inst = _materialize_train(cache_root, train_recipe_path)

    # Read what the train materialization actually persisted.
    sibling_handle = FittedStatistics(fitted_stats_dir(train_inst))
    sibling_mean = np.asarray(
        sibling_handle.get_vector("norm", "mean")["value"].to_pylist(),
        dtype=np.float64,
    )
    sibling_std = np.asarray(
        sibling_handle.get_vector("norm", "std")["value"].to_pylist(),
        dtype=np.float64,
    )

    eval_records = _eval_records()
    splits = {"train": list(eval_records), "val": [], "test": []}

    op = TransformationOp(
        name="norm",
        op="normalize",
        params={
            "stats_from_instance": {
                "recipe": str(train_recipe_path),
                "op_id": "norm",
            }
        },
        splits=["train"],
    )
    fitted_stats_handle = FittedStatistics(tmp_path / "unused")  # not written
    result = apply_transformations(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=fitted_stats_handle,
        label_field="label",
        cache_root=cache_root,
    )
    # No local fit happened, so no op id was persisted by this run.
    assert result.fitted_op_ids == ()

    # Reference: apply normalize with the sibling-recorded mean/std
    # straight on the eval records.
    std_safe = np.where(sibling_std == 0, 1.0, sibling_std)
    expected_outputs = [
        (r["image"].astype(np.float64) - sibling_mean) / std_safe for r in eval_records
    ]

    actual_outputs = [r["image"] for r in result.splits["train"]]
    assert len(actual_outputs) == len(expected_outputs)
    for actual, expected in zip(actual_outputs, expected_outputs, strict=True):
        np.testing.assert_array_almost_equal(actual, expected)


# ---------------------------------------------------------------------------
# Failure modes surface through apply_transformations
# ---------------------------------------------------------------------------


def test_apply_path_raises_sibling_instance_not_found(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    train_recipe_path = _write_train_recipe(tmp_path / "train_recipe.yaml")
    # Note: no instance was materialized — shard dir does not exist.
    op = TransformationOp(
        name="norm",
        op="normalize",
        params={
            "stats_from_instance": {
                "recipe": str(train_recipe_path),
                "op_id": "norm",
            }
        },
        splits=["train"],
    )
    with pytest.raises(SiblingInstanceNotFoundError, match="no promoted instance"):
        apply_transformations(
            {"train": _eval_records(3)},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path / "unused"),
            label_field="label",
            cache_root=cache_root,
        )


def test_apply_path_raises_sibling_op_not_found(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    train_recipe_path = _write_train_recipe(tmp_path / "train_recipe.yaml")
    _materialize_train(cache_root, train_recipe_path)

    op = TransformationOp(
        name="norm",
        op="normalize",
        params={
            "stats_from_instance": {
                "recipe": str(train_recipe_path),
                "op_id": "does_not_exist",
            }
        },
        splits=["train"],
    )
    with pytest.raises(SiblingOpNotFoundError, match="does_not_exist"):
        apply_transformations(
            {"train": _eval_records(3)},
            [op],
            plugin=IMAGE_PLUGIN,
            fitted_stats=FittedStatistics(tmp_path / "unused"),
            label_field="label",
            cache_root=cache_root,
        )


def test_apply_path_raises_stats_incompatible_when_required_missing(
    tmp_path: Path,
) -> None:
    """When the sibling op directory exists but a required vector is
    missing, the resolver surfaces ``SiblingStatsIncompatibleError``. We
    exercise it by writing a sibling op dir with only ``mean`` (no
    ``std``) and asking the resolver to require both via a direct call —
    this mirrors how a future op with stricter requirements would error.
    """
    from datarefinery.cache.sibling_stats import resolve_sibling_stats

    cache_root = tmp_path / "cache"
    train_recipe_path = _write_train_recipe(tmp_path / "train_recipe.yaml")
    train_inst = _materialize_train(cache_root, train_recipe_path)

    # Remove std.parquet to simulate an incompatible sibling.
    (fitted_stats_dir(train_inst) / "norm" / "std.parquet").unlink()

    with pytest.raises(SiblingStatsIncompatibleError, match="std"):
        resolve_sibling_stats(
            cache_root=cache_root,
            recipe_path=train_recipe_path,
            op_id="norm",
            required_vectors=("mean", "std"),
        )


# ---------------------------------------------------------------------------
# Validator check 22: mutual exclusion
# ---------------------------------------------------------------------------


def _valid_recipe_with_normalize_overrides(overrides: dict[str, Any]) -> Recipe:
    base = {
        "schema_version": 1,
        "plugin": "image_classification",
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]},
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                "label": {"dtype": "str"},
            }
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {"ratios": {"train": 0.6, "val": 0.2, "test": 0.2}, "seed": 11},
        "Transformations": [
            {
                "name": "norm",
                "op": "normalize",
                "params": {},
                "splits": ["train", "val", "test"],
            }
            | overrides
        ],
    }
    return Recipe.model_validate(base)


def test_validator_rejects_both_fit_source_and_stats_from_instance(tmp_path: Path) -> None:
    recipe = _valid_recipe_with_normalize_overrides(
        {
            "fit_source": "train",
            "params": {
                "stats_from_instance": {
                    "recipe": str(tmp_path / "sibling.yaml"),
                    "op_id": "norm",
                }
            },
        }
    )
    report = validate(recipe, IMAGE_PLUGIN)
    check_22 = next(r for r in report.results if r.check_id == 22)
    assert check_22.status == "fail"
    assert "mutually exclusive" in check_22.message
