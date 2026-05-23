# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-3 PipelineRunner integration tests (Story C.m).

End-to-end orchestration: build a complete recipe + synthetic image
record list, run the pipeline, assert the materialized instance has the
expected layout, and verify cache-hit + failure-injection behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from datarefinery.cache.identity import compute_cache_key
from datarefinery.cache.layout import (
    dataset_dir,
    fitted_stats_dir,
    instance_dir,
    manifest_path,
    report_dir,
)
from datarefinery.cache.layout import (
    tmp_dir as tmp_dir_for,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import (
    Recipe,
    TransformationOp,
    VisualizationOp,
)


def _img(value: int) -> np.ndarray:
    return np.full((4, 4, 3), value, dtype=np.uint8)


def _records(n: int = 12, classes: int = 2) -> list[Mapping[str, Any]]:
    """Build a small synthetic image record set with stable record_ids."""
    return [
        {
            "record_id": f"rec_{i:04d}",
            "image": _img(20 + i * 5),
            "label": f"c{i % classes}",
            "path": f"/data/c{i % classes}/img_{i:04d}.png",
        }
        for i in range(n)
    ]


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    """Stable per-source content hash for tests; uses concatenated record ids."""
    import hashlib

    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _recipe(
    *,
    visualizations: list[VisualizationOp] | None = None,
    transformations: list[TransformationOp] | None = None,
    augmentations: list[dict[str, Any]] | None = None,
) -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [
                    {
                        "name": "train",
                        "type": "image_folder",
                        "path": "/data/train",
                    }
                ]
            },
            "Output": {
                "record_schema": {
                    "image": {"dtype": "uint8", "shape": [4, 4, 3]},
                    "label": {"dtype": "str"},
                }
            },
            "Labels": {
                "field": "label",
                "source": {"kind": "direct"},
            },
            "Splits": {
                "ratios": {"train": 0.6, "val": 0.2, "test": 0.2},
                "seed": 11,
            },
            "Transformations": [t.model_dump() for t in (transformations or [])],
            "Augmentations": augmentations or [],
            "Visualizations": [v.model_dump() for v in (visualizations or [])],
        }
    )


def _config(cache_root: Path) -> RuntimeConfig:
    return RuntimeConfig(cache_root=cache_root)


# ---------------------------------------------------------------------------
# End-to-end materialize
# ---------------------------------------------------------------------------


def test_runner_writes_report_md_and_drift_json(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe(
        transformations=[
            TransformationOp(
                name="norm",
                op="normalize",
                params={},
                fit_source="train",
                splits=["train", "val", "test"],
            )
        ],
    )
    records = _records(12)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    rd = report_dir(result.instance_dir)
    assert (rd / "report.md").exists()
    md = (rd / "report.md").read_text()
    assert "DataRefinery report" in md
    assert "norm" in md  # fitted op listed

    from datarefinery.reporting.drift import read_drift

    drift = read_drift(rd / "drift.json")
    assert drift.plugin == "image_classification"
    assert "train" in drift.splits
    assert sum(s.record_count for s in drift.splits.values()) == 12


def test_runner_materializes_complete_instance(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe(
        visualizations=[
            VisualizationOp(
                name="hist",
                op="class_distribution_histogram",
                params={},
                stage="post_pipeline",
                mode="reporting",
            ),
        ]
    )
    records = _records(12)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    assert result.cache_hit is False
    inst = result.instance_dir
    assert manifest_path(inst).exists()
    assert (dataset_dir(inst) / "train.jsonl").exists()
    assert (dataset_dir(inst) / "val.jsonl").exists()
    assert (dataset_dir(inst) / "test.jsonl").exists()
    assert (report_dir(inst) / "visualizations" / "hist.png").exists()


def test_runner_writes_well_formed_manifest(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(10)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    m = read_manifest(manifest_path(result.instance_dir))
    assert m.plugin == "image_classification"
    assert m.seed == 7
    assert m.schema_version == 1
    assert set(m.record_counts.keys()) == {"train", "val", "test"}
    assert sum(m.record_counts.values()) == 10
    assert m.is_partial is False
    assert m.failed_stage is None
    # Full SHA-256 hex (64 chars).
    assert len(m.recipe_hash) == 64
    assert len(m.input_hash) == 64


def test_runner_persists_fitted_stats_for_normalize(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe(
        transformations=[
            TransformationOp(
                name="norm",
                op="normalize",
                params={},
                fit_source="train",
                splits=["train", "val", "test"],
            )
        ]
    )
    records = _records(12)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    stats = fitted_stats_dir(result.instance_dir)
    assert (stats / "norm" / "mean.parquet").exists()
    assert (stats / "norm" / "std.parquet").exists()


def test_runner_temp_dir_is_cleaned_after_promote(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(8)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    assert not temp.exists()  # promoted away


def test_instance_dir_matches_cache_identity(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(8)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    expected_key = compute_cache_key(recipe, _input_hashes(records), 7)
    expected = instance_dir(cache_root, expected_key)
    assert result.instance_dir == expected


# ---------------------------------------------------------------------------
# Cache hit short-circuit
# ---------------------------------------------------------------------------


def test_second_run_with_same_inputs_hits_cache(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(8)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)

    temp1 = tmp_dir_for(cache_root, "run-1")
    first = runner.run(temp1, raw_records=records, raw_input_hashes=_input_hashes(records))
    assert first.cache_hit is False

    temp2 = tmp_dir_for(cache_root, "run-2")
    second = runner.run(temp2, raw_records=records, raw_input_hashes=_input_hashes(records))
    assert second.cache_hit is True
    assert second.instance_dir == first.instance_dir
    # Cache hit does not touch the temp dir.
    assert not temp2.exists()


def test_cache_hit_returns_persisted_manifest(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(8)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp1 = tmp_dir_for(cache_root, "run-1")
    first = runner.run(temp1, raw_records=records, raw_input_hashes=_input_hashes(records))

    temp2 = tmp_dir_for(cache_root, "run-2")
    second = runner.run(temp2, raw_records=records, raw_input_hashes=_input_hashes(records))
    # Cache-hit manifest equals the persisted one (modulo timestamp identity
    # which is preserved since we re-read from disk).
    assert second.manifest.recipe_hash == first.manifest.recipe_hash
    assert second.manifest.input_hash == first.manifest.input_hash
    assert second.manifest.record_counts == first.manifest.record_counts


def test_different_seed_misses_cache(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(8)
    runner_a = PipelineRunner(
        recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7
    )
    runner_b = PipelineRunner(
        recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=8
    )
    temp1 = tmp_dir_for(cache_root, "run-1")
    a = runner_a.run(temp1, raw_records=records, raw_input_hashes=_input_hashes(records))
    temp2 = tmp_dir_for(cache_root, "run-2")
    b = runner_b.run(temp2, raw_records=records, raw_input_hashes=_input_hashes(records))
    assert a.instance_dir != b.instance_dir
    assert a.cache_hit is False
    assert b.cache_hit is False


# ---------------------------------------------------------------------------
# Failure injection: temp dir + FAILED marker, never touches final cache
# ---------------------------------------------------------------------------


class _FailingPlugin:
    """Wraps the image plugin but raises during one named operation."""

    def __init__(self, fail_op: str) -> None:
        self.name = "failing_image"
        self.schema_version = 1
        self.supported_sections = IMAGE_PLUGIN.supported_sections
        self.supported_operations = IMAGE_PLUGIN.supported_operations
        self._fail_op = fail_op

    def operation_factory(self, section: str, op_name: str) -> Any:
        if op_name == self._fail_op:

            class _Boom:
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    raise RuntimeError(f"forced failure in {op_name}")

                def render(
                    self,
                    splits: Mapping[str, list[Mapping[str, Any]]],
                    params: Mapping[str, Any],
                    *,
                    label_field: str | None,
                ) -> bytes:
                    del splits, params, label_field
                    raise RuntimeError(f"forced failure in {op_name}")

                def fit(self, *args: Any, **kwargs: Any) -> Any:
                    raise RuntimeError(f"forced failure in {op_name}")

                def apply(self, *args: Any, **kwargs: Any) -> Any:
                    raise RuntimeError(f"forced failure in {op_name}")

            return _Boom()
        return IMAGE_PLUGIN.operation_factory(section, op_name)

    def is_stub(self) -> bool:
        return False


def test_visualization_failure_leaves_failed_marker(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe(
        visualizations=[
            VisualizationOp(
                name="hist",
                op="class_distribution_histogram",
                params={},
                stage="post_pipeline",
                mode="reporting",
            ),
        ]
    )
    records = _records(8)
    plugin = _FailingPlugin(fail_op="class_distribution_histogram")
    runner = PipelineRunner(
        recipe=recipe,
        plugin=plugin,
        config=_config(cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-1")

    with pytest.raises(MaterializeError, match="class_distribution_histogram"):
        runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    # Temp dir survives with FAILED marker.
    assert temp.exists()
    failed_path = temp / "FAILED"
    assert failed_path.exists()
    import json as _json

    payload = _json.loads(failed_path.read_text())
    assert payload["stage"] == "Visualizations"

    # Final cache path was never touched.
    cache_key = compute_cache_key(recipe, _input_hashes(records), 7)
    final_dir = instance_dir(cache_root, cache_key)
    assert not final_dir.exists()


def test_failure_does_not_leave_partial_promote(tmp_path: Path) -> None:
    """Confirm that a stage failure mid-run never produces a final
    manifest.json - the promote happens last and only on success."""
    cache_root = tmp_path / "cache"
    recipe = _recipe(
        visualizations=[
            VisualizationOp(
                name="hist",
                op="class_distribution_histogram",
                params={},
                stage="post_pipeline",
                mode="reporting",
            ),
        ]
    )
    records = _records(8)
    plugin = _FailingPlugin(fail_op="class_distribution_histogram")
    runner = PipelineRunner(
        recipe=recipe,
        plugin=plugin,
        config=_config(cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-1")
    with pytest.raises(MaterializeError):
        runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    cache_key = compute_cache_key(recipe, _input_hashes(records), 7)
    final_dir = instance_dir(cache_root, cache_key)
    assert not manifest_path(final_dir).exists()


# ---------------------------------------------------------------------------
# Dataset persistence shape
# ---------------------------------------------------------------------------


def test_dataset_jsonl_omits_image_arrays(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe = _recipe()
    records = _records(8)
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    train_jsonl = (dataset_dir(result.instance_dir) / "train.jsonl").read_text()
    import json as _json

    lines = [_json.loads(line) for line in train_jsonl.strip().splitlines() if line]
    for r in lines:
        assert "image" not in r  # numpy arrays are dropped
        assert "record_id" in r
        assert "label" in r


# ---------------------------------------------------------------------------
# H.r.1: aggressive-mode runner wiring + fail-loud guard
# ---------------------------------------------------------------------------


def _aggressive_recipe() -> Recipe:
    return _recipe(
        augmentations=[
            {
                "name": "flip",
                "op": "horizontal_flip",
                "params": {"p": 0.5},
                "splits": ["train"],
                "seed": 1,
                "materialization": "aggressive",
                "expansion": 3,
            }
        ]
    )


def test_runner_aggressive_wiring_fans_out_train_split(tmp_path: Path) -> None:
    """Story H.r.1 wired the runner; Story H.r.2 added image-bytes
    persistence. The runner invokes :func:`realize_aggressive_split` for
    the train split and the post-augmentation record count reflects the
    multiplicative expansion."""
    cache_root = tmp_path / "cache"
    runner = PipelineRunner(
        recipe=_aggressive_recipe(),
        plugin=IMAGE_PLUGIN,
        config=_config(cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-1")
    records = _records(12)  # 60/20/20 split -> 7 train, 2 val, 3 test (depending on seed)
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    manifest = read_manifest(manifest_path(result.instance_dir))
    train_jsonl = (dataset_dir(result.instance_dir) / "train.jsonl").read_text()
    lines = [line for line in train_jsonl.strip().splitlines() if line]
    train_count_post = manifest.record_counts["train"]
    # Expansion = 3 -> post-augmentation train count is 3x the pre-augmentation count.
    # We don't pin the pre-augmentation count exactly (depends on Splits seeding), but
    # we do pin that the post count is divisible by 3 and matches the JSONL line count.
    assert train_count_post == len(lines)
    assert train_count_post % 3 == 0
    assert train_count_post > 0

    # Each variant line carries the H.p metadata fields.
    import json as _json

    first = _json.loads(lines[0])
    assert "source_record_id" in first
    assert "variant_index" in first


def test_runner_lazy_only_augmentations_do_not_trigger_guard(tmp_path: Path) -> None:
    """Lazy-mode augmentations are unaffected by the H.r.2-pending guard."""
    recipe = _recipe(
        augmentations=[
            {
                "name": "flip",
                "op": "horizontal_flip",
                "params": {"p": 0.5},
                "splits": ["train"],
                "seed": 1,
            }
        ]
    )
    cache_root = tmp_path / "cache"
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    records = _records(12)
    # Should materialize cleanly — no guard for lazy.
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
    assert result.manifest.record_counts["train"] > 0


# ---------------------------------------------------------------------------
# H.r.2: aggressive-mode image-bytes persistence (sidecar PNGs)
# ---------------------------------------------------------------------------


def test_aggressive_materialize_writes_sidecar_pngs(tmp_path: Path) -> None:
    """Story H.r.2: every aggressive variant gets a sidecar PNG at
    ``dataset/<split>/images/<record_id>.png`` and the JSONL line
    carries ``image_path`` instead of ``image``."""
    cache_root = tmp_path / "cache"
    runner = PipelineRunner(
        recipe=_aggressive_recipe(),
        plugin=IMAGE_PLUGIN,
        config=_config(cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-1")
    records = _records(12)
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    ds = dataset_dir(result.instance_dir)
    images_dir = ds / "train" / "images"
    assert images_dir.is_dir()
    png_files = sorted(images_dir.glob("*.png"))
    assert len(png_files) > 0, "expected sidecar PNGs for aggressive variants"

    import json as _json

    train_jsonl = (ds / "train.jsonl").read_text()
    lines = [_json.loads(line) for line in train_jsonl.strip().splitlines() if line]
    assert len(lines) == len(png_files)
    for line in lines:
        assert "image" not in line  # bytes replaced by sidecar
        assert "image_path" in line
        rid = line["record_id"]
        # image_path is relative to dataset_root.
        assert line["image_path"] == f"train/images/{rid}.png"
        # File exists at the indicated relative path.
        assert (ds / line["image_path"]).is_file()


def test_aggressive_sidecar_png_round_trips_to_realizer_output(tmp_path: Path) -> None:
    """Reading a sidecar PNG back yields the same uint8 array as the
    in-memory realizer would have produced. Validates the FR-3 +
    FR-4 byte-identity contract extended over the sidecar layer."""
    from datarefinery.plugins.image_classification.augmentations._realizer import (
        emit_variants,
    )
    from datarefinery.plugins.image_classification.plugin import (
        PLUGIN as PLUGIN_LOCAL,
    )

    cache_root = tmp_path / "cache"
    seed = 7
    runner = PipelineRunner(
        recipe=_aggressive_recipe(),
        plugin=IMAGE_PLUGIN,
        config=_config(cache_root),
        seed=seed,
    )
    temp = tmp_dir_for(cache_root, "run-1")
    records = _records(12)
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    ds = dataset_dir(result.instance_dir)
    import json as _json

    from PIL import Image as _PIL

    train_jsonl = (ds / "train.jsonl").read_text()
    parsed = [_json.loads(line) for line in train_jsonl.strip().splitlines() if line]

    # Build a {record_id: numpy_image} map from the original records — the
    # Splits stage selects 60% of these for the train split deterministically
    # (seed=7), and the realizer expansion=3 multiplies them.
    rec_by_id = {r["record_id"]: r for r in records}

    # For each persisted variant, regenerate the in-memory output via
    # emit_variants and compare PNG bytes round-trip.
    for variant in parsed:
        source_rid = variant["source_record_id"]
        vi = variant["variant_index"]
        original = rec_by_id[source_rid]
        emitted = emit_variants(
            original,
            op_id="horizontal_flip",
            global_seed=seed,
            expansion=3,
            realize_fn=PLUGIN_LOCAL.augmentation_realizers["horizontal_flip"],
            params={"p": 0.5},
        )
        [in_mem] = [v for v in emitted if v["variant_index"] == vi]
        sidecar = _PIL.open(ds / variant["image_path"])
        sidecar_arr = np.asarray(sidecar)
        assert np.array_equal(sidecar_arr, in_mem["image"]), (
            f"sidecar PNG bytes differ from realizer output for {source_rid} v={vi}"
        )


def test_aggressive_materialize_is_deterministic_across_runs(tmp_path: Path) -> None:
    """Same recipe + seed + inputs across two fresh runs -> byte-identical
    sidecar PNGs. The FR-3/FR-4 determinism contract extends to the
    sidecar layer."""

    def _materialize(cache_root: Path, run_name: str) -> Path:
        r = PipelineRunner(
            recipe=_aggressive_recipe(),
            plugin=IMAGE_PLUGIN,
            config=_config(cache_root),
            seed=7,
        )
        temp = tmp_dir_for(cache_root, run_name)
        records = _records(12)
        result = r.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))
        return dataset_dir(result.instance_dir) / "train" / "images"

    images_a = _materialize(tmp_path / "cache_a", "run-1")
    images_b = _materialize(tmp_path / "cache_b", "run-2")

    pngs_a = {p.name: p.read_bytes() for p in images_a.glob("*.png")}
    pngs_b = {p.name: p.read_bytes() for p in images_b.glob("*.png")}
    assert pngs_a.keys() == pngs_b.keys()
    for name in pngs_a:
        assert pngs_a[name] == pngs_b[name], f"sidecar PNG byte mismatch for {name}"


def test_lazy_only_recipe_writes_no_sidecars(tmp_path: Path) -> None:
    """A recipe with only lazy (or no) augmentations must NOT write any
    sidecar PNG directory — the H.r.2 path is aggressive-only."""
    recipe = _recipe(
        augmentations=[
            {
                "name": "flip",
                "op": "horizontal_flip",
                "params": {"p": 0.5},
                "splits": ["train"],
                "seed": 1,
            }
        ]
    )
    cache_root = tmp_path / "cache"
    runner = PipelineRunner(recipe=recipe, plugin=IMAGE_PLUGIN, config=_config(cache_root), seed=7)
    temp = tmp_dir_for(cache_root, "run-1")
    records = _records(12)
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    ds = dataset_dir(result.instance_dir)
    assert not (ds / "train" / "images").exists()
    # And the JSONL retains the pre-H.r.2 schema: no image_path field.
    import json as _json

    line = _json.loads((ds / "train.jsonl").read_text().splitlines()[0])
    assert "image_path" not in line
