# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story I.l (G3) integration test for `categorical_encode` + `stats_from_instance`.

A sibling instance writes its categorical-encode vocabulary to
`fitted_statistics/<op_id>/vocabulary.parquet`; a consumer recipe
references the sibling via `stats_from_instance` and the
Featurizations stage imports the vocabulary verbatim instead of
re-fitting locally. Mirrors the Transformations-side normalize sibling
test pattern.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa

from datarefinery.cache.identity import CacheKey
from datarefinery.cache.layout import (
    fitted_stats_dir,
    instance_dir,
    manifest_path,
)
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.manifest import Manifest, write_manifest
from datarefinery.pipeline.stages.featurizations import apply_featurizations
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.loader import load as load_recipe
from datarefinery.recipe.models import FeaturizationOp
from datarefinery.recipe.overlays import apply_overlays
from datarefinery.recipe.segments import recipe_identity_hash

_SIBLING_RECIPE_YAML = textwrap.dedent(
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
    Featurizations:
      - name: lbl_id
        inputs: [label]
        output_field: label_id
        op: categorical_encode
        params: {ordering: alphabetical, output_dtype: int32}
        fit_source: train
        splits: [train, val, test]
    """
)


def _write_sibling_recipe(path: Path) -> Path:
    path.write_text(_SIBLING_RECIPE_YAML, encoding="utf-8")
    return path


def _sibling_recipe_hash(recipe_path: Path) -> str:
    recipe = apply_overlays(load_recipe(recipe_path), None)
    return recipe_identity_hash(recipe)


def _build_sibling_with_vocabulary(
    cache_root: Path,
    recipe_path: Path,
    op_id: str,
    vocab: list[str],
) -> Path:
    """Materialize a fake promoted sibling instance with a vocabulary
    parquet under fitted_statistics/<op_id>/.
    """
    recipe_hash = _sibling_recipe_hash(recipe_path)
    key = CacheKey(recipe_hash=recipe_hash, input_hash="a" * 64, seed=7)
    inst = instance_dir(cache_root, key)
    inst.mkdir(parents=True, exist_ok=True)
    write_manifest(
        manifest_path(inst),
        Manifest(
            datarefinery_version="0.0.0-test",
            plugin="image_classification",
            plugin_version="1",
            recipe_hash=recipe_hash,
            input_hash="a" * 64,
            seed=7,
            created_at=datetime(2026, 5, 27, tzinfo=UTC),
            elapsed_seconds=0.0,
            record_counts={"train": 1},
        ),
    )
    FittedStatistics(fitted_stats_dir(inst)).put_vector(
        op_id, "vocabulary", pa.table({"value": vocab})
    )
    return inst


def _label_record(label: str) -> Mapping[str, Any]:
    return {"label": label}


def test_categorical_encode_imports_vocabulary_via_stats_from_instance(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    sibling_path = _write_sibling_recipe(tmp_path / "train_recipe.yaml")
    _build_sibling_with_vocabulary(
        cache_root,
        sibling_path,
        op_id="lbl_id",
        vocab=["bird", "cat", "dog"],
    )

    op = FeaturizationOp(
        name="lbl_id_consumer",
        inputs=["label"],
        output_field="label_id",
        op="categorical_encode",
        params={
            "ordering": "alphabetical",
            "output_dtype": "int32",
            "stats_from_instance": {
                "recipe": str(sibling_path),
                "op_id": "lbl_id",
            },
        },
        splits=["train", "val"],
    )
    splits: dict[str, list[Mapping[str, Any]]] = {
        "train": [_label_record("cat"), _label_record("dog")],
        "val": [_label_record("bird")],
    }
    fs = FittedStatistics(tmp_path / "consumer_stats")
    result = apply_featurizations(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        fitted_stats=fs,
        cache_root=cache_root,
    )
    # Sibling vocabulary applied: bird=0, cat=1, dog=2.
    assert [int(r["label_id"]) for r in result.splits["train"]] == [1, 2]
    assert [int(r["label_id"]) for r in result.splits["val"]] == [0]
    # Sibling-import path does not persist into the consumer's fitted_statistics.
    assert "lbl_id_consumer" not in result.fitted_op_ids
    assert not (tmp_path / "consumer_stats" / "lbl_id_consumer").exists()
