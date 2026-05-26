# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""`datarefinery export` parity test (Story I.f).

The export verb re-runs sinks against an already-materialized instance.
The load-bearing contract is **byte-identical parity with a re-materialize**:
running ``export`` against an instance materialized without sinks must
produce the same sink bytes as a fresh materialize of the same recipe
with the sink declared.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("cv2", reason="requires the [corruptions] extras")

from datarefinery.cache.layout import (
    tmp_dir as tmp_dir_for,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.pipeline.sinks.export import export_sinks
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import Recipe


def _img(value: int) -> np.ndarray:
    return np.full((32, 32, 3), value, dtype=np.uint8)


def _make_records_on_disk(image_root: Path, n: int = 6) -> list[Mapping[str, Any]]:
    """Materialize n synthetic PNGs on disk and return loader-style records.

    The export verb's post-Generation reconstruction re-reads source
    images from disk via the cached records' ``source_path`` field, so
    the records' ``path`` must point at real files for parity with the
    materialize-time sink.
    """
    from PIL import Image

    records: list[Mapping[str, Any]] = []
    for i in range(n):
        cls_dir = image_root / f"c{i % 2}"
        cls_dir.mkdir(parents=True, exist_ok=True)
        path = cls_dir / f"img_{i:04d}.png"
        arr = _img(20 + i * 5)
        Image.fromarray(arr).save(path, format="PNG", optimize=False)
        # `record_id` mirrors the image_classification loader's
        # path-stem convention so the export verb's source-path-based
        # reconstruction generates record_ids identical to the
        # original materialize run.
        records.append(
            {
                "record_id": path.stem,
                "image": arr,
                "label": f"c{i % 2}",
                "path": str(path),
            }
        )
    return records


def _input_hashes(records: list[Mapping[str, Any]]) -> dict[str, str]:
    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _base_recipe_dict(*, with_sink: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": 1,
        "plugin": "image_classification",
        "Input": {"sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]},
        "Output": {
            "record_schema": {
                "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                "label": {"dtype": "str"},
            }
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {
            "ratios": {"train": 0.5, "val": 0.25, "test": 0.25},
            "seed": 11,
        },
        "Generation": [
            {
                "name": "imagecorruptions_apply",
                "inputs": ["image"],
                "output_schema": {
                    "image": {"dtype": "uint8", "shape": [32, 32, 3]},
                    "label": {"dtype": "str"},
                },
                "seed": 42,
                "applies_at": ["train"],
                "params": {
                    "corruption_types": ["gaussian_noise"],
                    "severities": [3],
                    "preserve_original": False,
                    "tag_fields": ["corruption", "severity", "source_path"],
                },
            }
        ],
    }
    if with_sink:
        body["Sinks"] = [
            {
                "name": "corrupted",
                "stage": "post_Generation",
                "splits": ["train"],
                "field": "image",
                "format": "png_per_record",
                "path_template": "exports/{record_id}.png",
            }
        ]
    return body


def test_export_produces_byte_identical_parity_with_materialize(tmp_path: Path) -> None:
    """Cache A: materialize without sinks. Cache B: materialize same
    recipe with sinks. Run export against cache A using the with-sinks
    recipe. Assert: export's sink output bytes == cache B's sink
    output bytes."""
    cache_a = tmp_path / "cache_a"  # materialized without sinks; export target
    cache_b = tmp_path / "cache_b"  # materialized with sinks; parity reference
    records = _make_records_on_disk(tmp_path / "images", n=6)
    hashes = _input_hashes(records)

    # --- cache_a: materialize the no-sinks recipe ---
    recipe_no_sinks = Recipe.model_validate(_base_recipe_dict(with_sink=False))
    runner_a = PipelineRunner(
        recipe=recipe_no_sinks,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_a),
        seed=7,
    )
    temp_a = tmp_dir_for(cache_a, "run-a")
    result_a = runner_a.run(temp_a, raw_records=records, raw_input_hashes=hashes)
    instance_a = result_a.instance_dir
    assert not (instance_a / "exports").exists(), "control: no sink output yet"

    # --- cache_b: materialize the with-sinks recipe (parity reference) ---
    recipe_with_sinks = Recipe.model_validate(_base_recipe_dict(with_sink=True))
    runner_b = PipelineRunner(
        recipe=recipe_with_sinks,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_b),
        seed=7,
    )
    temp_b = tmp_dir_for(cache_b, "run-b")
    result_b = runner_b.run(temp_b, raw_records=records, raw_input_hashes=hashes)
    reference_exports = result_b.instance_dir / "exports"
    reference_files = sorted(reference_exports.glob("*.png"))
    assert reference_files, "reference materialize produced no sink files"

    # --- export against cache_a using the with-sinks recipe ---
    export_result = export_sinks(
        recipe_with_sinks,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_a),
        seed=7,
        raw_input_hashes=hashes,
        raw_records=records,
    )
    # Export must have located cache_a's instance via the sinks-stripped
    # cache key (since the with-sinks recipe's canonical bytes do not
    # match cache_a's recipe_hash on the nose).
    assert export_result.instance_dir == instance_a

    exported_files = sorted((instance_a / "exports").glob("*.png"))
    assert {p.name for p in exported_files} == {p.name for p in reference_files}
    for exported, reference in zip(
        exported_files,
        sorted(reference_files, key=lambda p: p.name),
        strict=True,
    ):
        assert exported.read_bytes() == reference.read_bytes(), (
            f"export bytes for {exported.name} != materialize bytes "
            f"({len(exported.read_bytes())} vs {len(reference.read_bytes())} bytes)"
        )


def test_export_refuses_when_no_bound_instance(tmp_path: Path) -> None:
    """No materialized instance under the cache root → export refuses
    cleanly with a pointer to ``materialize`` (not a stack trace)."""
    cache_root = tmp_path / "empty_cache"
    recipe = Recipe.model_validate(_base_recipe_dict(with_sink=True))
    from datarefinery.core.errors import MaterializeError

    # Empty cache → loader cannot resolve hashes from a nonexistent
    # source either; supply the hashes the test would have used had a
    # real materialize happened, so the failure is the bound-instance
    # check (the contract we are pinning) rather than a hash-input
    # path lookup.
    with pytest.raises(MaterializeError, match="no bound instance"):
        export_sinks(
            recipe,
            plugin=IMAGE_PLUGIN,
            config=RuntimeConfig(cache_root=cache_root),
            seed=7,
            raw_input_hashes={"train": "0" * 64},
            raw_records=[],
        )


def test_export_sink_name_filter(tmp_path: Path) -> None:
    """`sink_names=["a"]` runs only sink ``a``; an unknown name refuses cleanly."""
    cache_root = tmp_path / "cache"
    records = _make_records_on_disk(tmp_path / "images", n=6)
    hashes = _input_hashes(records)

    base = _base_recipe_dict(with_sink=False)
    runner = PipelineRunner(
        recipe=Recipe.model_validate(base),
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    runner.run(tmp_dir_for(cache_root, "run-1"), raw_records=records, raw_input_hashes=hashes)

    # Recipe with two sinks; export filters to one.
    body = _base_recipe_dict(with_sink=True)
    body["Sinks"].append(
        {
            "name": "second",
            "stage": "post_Generation",
            "splits": ["train"],
            "field": "image",
            "format": "png_per_record",
            "path_template": "second_exports/{record_id}.png",
        }
    )
    recipe = Recipe.model_validate(body)

    result = export_sinks(
        recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
        sink_names=["corrupted"],
        raw_input_hashes=hashes,
        raw_records=records,
    )
    names = {s.name for s in result.sinks_executed}
    assert names == {"corrupted"}
    assert (result.instance_dir / "exports").is_dir()
    assert not (result.instance_dir / "second_exports").exists()

    from datarefinery.core.errors import MaterializeError

    with pytest.raises(MaterializeError, match="not declared"):
        export_sinks(
            recipe,
            plugin=IMAGE_PLUGIN,
            config=RuntimeConfig(cache_root=cache_root),
            seed=7,
            sink_names=["bogus"],
            raw_input_hashes=hashes,
            raw_records=records,
        )


def test_export_refuses_non_reconstructable_stage(tmp_path: Path) -> None:
    """v1 reconstructability: a sink at ``post_Filters`` (uint8 stomped
    by Transformations) refuses with a pointer to re-materialize."""
    cache_root = tmp_path / "cache"
    records = _make_records_on_disk(tmp_path / "images", n=6)
    hashes = _input_hashes(records)

    runner = PipelineRunner(
        recipe=Recipe.model_validate(_base_recipe_dict(with_sink=False)),
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    runner.run(tmp_dir_for(cache_root, "run-1"), raw_records=records, raw_input_hashes=hashes)

    body = _base_recipe_dict(with_sink=False)
    body["Sinks"] = [
        {
            "name": "filtered_bytes",
            "stage": "post_Filters",
            "field": "image",
            "format": "png_per_record",
            "path_template": "filt/{record_id}.png",
        }
    ]
    recipe = Recipe.model_validate(body)

    from datarefinery.core.errors import MaterializeError

    with pytest.raises(MaterializeError, match="re-materialize"):
        export_sinks(
            recipe,
            plugin=IMAGE_PLUGIN,
            config=RuntimeConfig(cache_root=cache_root),
            seed=7,
            raw_input_hashes=hashes,
            raw_records=records,
        )
