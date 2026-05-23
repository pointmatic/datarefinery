# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.q — Cross-recipe bit-identity test (FR-AUG-1 + FR-AUG-2).

Same recipe + same inputs + same seed -> byte-identical aggressive-mode
output. The runner integration that wires this into the materialize
path is Story H.r.1; this test exercises the stage directly via
:func:`realize_aggressive_split` against the real plugin registry.

The test covers both ops in sequence — ``random_crop`` then
``horizontal_flip`` — to confirm that the determinism contract holds
across multi-op aggressive composition.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from datarefinery.pipeline.stages.augmentations import realize_aggressive_split
from datarefinery.plugins.image_classification.plugin import PLUGIN
from datarefinery.recipe.models import AugmentationOp


def _inputs(n: int = 6) -> list[dict[str, Any]]:
    rng = np.random.default_rng(0xC0FFEE)
    return [
        {
            "record_id": f"img_{i:03d}",
            "image": rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8),
            "label": i % 3,
        }
        for i in range(n)
    ]


def _ops_two_aggressive() -> list[AugmentationOp]:
    return [
        AugmentationOp(
            name="crop",
            op="random_crop",
            params={"size": 6, "padding": 2, "padding_mode": "reflect"},
            splits=["train"],
            seed=1,
            materialization="aggressive",
            expansion=2,
        ),
        AugmentationOp(
            name="flip",
            op="horizontal_flip",
            params={"p": 0.5},
            splits=["train"],
            seed=2,
            materialization="aggressive",
            expansion=2,
        ),
    ]


def _digest(records: list[dict[str, Any]]) -> str:
    """Hash the full record set in a stable order — covers image bytes
    AND metadata fields."""
    parts: list[str] = []
    for r in sorted(records, key=lambda x: str(x["record_id"])):
        img_hash = hashlib.sha256(np.ascontiguousarray(r["image"]).tobytes()).hexdigest()
        parts.append(
            json.dumps(
                {
                    "record_id": r["record_id"],
                    "source_record_id": r["source_record_id"],
                    "variant_index": r["variant_index"],
                    "label": r.get("label"),
                    "image_sha256": img_hash,
                    "image_shape": list(r["image"].shape),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def test_two_aggressive_ops_through_plugin_registry_are_deterministic() -> None:
    """Same inputs + same recipe + same seed -> byte-identical output
    via the real plugin's registered realizers, twice in a row."""
    inputs = _inputs()
    ops = _ops_two_aggressive()
    a = realize_aggressive_split(
        inputs,
        ops,
        global_seed=42,
        realizer_registry=PLUGIN.augmentation_realizers,
    )
    b = realize_aggressive_split(
        inputs,
        ops,
        global_seed=42,
        realizer_registry=PLUGIN.augmentation_realizers,
    )
    assert _digest(a) == _digest(b)


def test_different_global_seed_changes_output() -> None:
    """Sanity check the inverse: different seeds yield different outputs."""
    inputs = _inputs()
    ops = _ops_two_aggressive()
    a = realize_aggressive_split(
        inputs,
        ops,
        global_seed=42,
        realizer_registry=PLUGIN.augmentation_realizers,
    )
    b = realize_aggressive_split(
        inputs,
        ops,
        global_seed=43,
        realizer_registry=PLUGIN.augmentation_realizers,
    )
    assert _digest(a) != _digest(b)


def test_two_aggressive_ops_compose_count_multiplicatively() -> None:
    """N records * 2 (crop expansion) * 2 (flip expansion) = 4N variants."""
    inputs = _inputs(5)
    out = realize_aggressive_split(
        inputs,
        _ops_two_aggressive(),
        global_seed=42,
        realizer_registry=PLUGIN.augmentation_realizers,
    )
    assert len(out) == 5 * 2 * 2
