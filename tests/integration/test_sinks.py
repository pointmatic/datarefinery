# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Integration tests for Sinks (Story I.d).

Spec § 6 worked example, scoped down to the v1 surface:

- A recipe declaring two sinks (post_Generation and post_Filters,
  both png_per_record) materializes; both sinks write the expected
  files under the promoted instance directory; both report a
  ``sinks.<name>`` manifest entry.
- Atomic temp-then-promote (FR-5): when a stage raises after a sink
  has written output, the temp dir is left flagged FAILED and no
  partial sink output appears under the final promoted path.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from datarefinery.cache.atomic import FAILED_MARKER
from datarefinery.cache.layout import (
    instance_dir,
    manifest_path,
)
from datarefinery.cache.layout import (
    tmp_dir as tmp_dir_for,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.manifest import read_manifest
from datarefinery.pipeline.runner import PipelineRunner
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import (
    Recipe,
    TransformationOp,
)


def _img(value: int) -> np.ndarray:
    return np.full((4, 4, 3), value, dtype=np.uint8)


def _records(n: int = 12, classes: int = 2) -> list[Mapping[str, Any]]:
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
    import hashlib

    payload = ";".join(sorted(r["record_id"] for r in records))
    return {"train": hashlib.sha256(payload.encode()).hexdigest()}


def _recipe_with_sinks(
    sinks: list[dict[str, Any]],
    *,
    transformations: list[TransformationOp] | None = None,
) -> Recipe:
    return Recipe.model_validate(
        {
            "schema_version": 1,
            "plugin": "image_classification",
            "Input": {
                "sources": [{"name": "train", "type": "image_folder", "path": "/data/train"}]
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
            "Transformations": [t.model_dump() for t in (transformations or [])],
            "Sinks": sinks,
        }
    )


def test_two_sinks_write_files_and_manifest_entries(tmp_path: Path) -> None:
    """Spec § 6 worked example: two png_per_record sinks at
    `post_Filters` and `post_Generation` both materialize."""
    cache_root = tmp_path / "cache"
    recipe = _recipe_with_sinks(
        sinks=[
            {
                "name": "base_pngs",
                "stage": "post_Filters",
                "field": "image",
                "format": "png_per_record",
                "path_template": "exports/base/{split}/{label}/{record_id}.png",
            },
            {
                "name": "gen_pngs",
                "stage": "post_Generation",
                "field": "image",
                "format": "png_per_record",
                "path_template": "exports/gen/{split}/{record_id}.png",
            },
        ],
    )
    records = _records(12)
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=7,
    )
    temp = tmp_dir_for(cache_root, "run-1")
    result = runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    inst = result.instance_dir
    # Both sink trees exist under the promoted instance.
    base_root = inst / "exports" / "base"
    gen_root = inst / "exports" / "gen"
    assert base_root.is_dir(), "post_Filters sink tree should be promoted"
    assert gen_root.is_dir(), "post_Generation sink tree should be promoted"

    base_files = list(base_root.rglob("*.png"))
    gen_files = list(gen_root.rglob("*.png"))
    assert len(base_files) == 12, base_files
    assert len(gen_files) == 12, gen_files

    # Manifest carries both entries with non-zero counts.
    m = read_manifest(manifest_path(inst))
    assert set(m.sinks.keys()) == {"base_pngs", "gen_pngs"}
    assert m.sinks["base_pngs"].stage == "post_Filters"
    assert m.sinks["base_pngs"].format == "png_per_record"
    assert m.sinks["base_pngs"].files_written == 12
    assert m.sinks["base_pngs"].bytes_total > 0
    assert m.sinks["gen_pngs"].stage == "post_Generation"
    assert m.sinks["gen_pngs"].files_written == 12


def test_atomic_failure_leaves_no_sink_output_under_promoted_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a later stage raises, the temp dir is flagged FAILED and
    the final promoted path never appears, so no half-baked sink output
    survives — even though the sink itself wrote files before the
    failure (FR-5)."""
    cache_root = tmp_path / "cache"
    recipe = _recipe_with_sinks(
        sinks=[
            {
                "name": "early",
                "stage": "post_Filters",
                "field": "image",
                "format": "png_per_record",
                "path_template": "exports/{record_id}.png",
            }
        ],
        # Inject a transformation that will explode at apply time.
        transformations=[
            TransformationOp(
                name="boom",
                op="this_op_does_not_exist",
                params={},
                splits=["train", "val", "test"],
            )
        ],
    )
    records = _records(8)
    runner = PipelineRunner(
        recipe=recipe,
        plugin=IMAGE_PLUGIN,
        config=RuntimeConfig(cache_root=cache_root),
        seed=11,
    )
    temp = tmp_dir_for(cache_root, "run-fail")

    # The failing transformation raises out of the runner; the surface
    # exception type is incidental — what we are pinning is that the
    # runner cleans up via mark_failed and never promotes.
    with pytest.raises(Exception):  # noqa: B017 — surface error type is incidental
        runner.run(temp, raw_records=records, raw_input_hashes=_input_hashes(records))

    # Temp dir survives with a FAILED marker; final promoted path does not exist.
    assert temp.is_dir()
    assert (temp / FAILED_MARKER).exists()
    # Sink output is visible in the temp dir...
    assert (temp / "exports").is_dir()
    assert len(list((temp / "exports").glob("*.png"))) == 8
    # ...but no `instances/<hash>/...` final promotion ever happened.
    from datarefinery.cache.identity import compute_cache_key

    cache_key = compute_cache_key(recipe, _input_hashes(records), 11)
    final = instance_dir(cache_root, cache_key)
    assert not final.exists(), f"final promoted dir {final} must not exist after pipeline failure"
