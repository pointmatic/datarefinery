# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Per-record-seed persistence tests (Story I.e).

Every stochastic op stamps `<op_name>_seed` onto each record it
produces. Today the surface is:

- `imagecorruptions_apply` (Generation) — stamps the per-input
  `per_record_seed` value on every corrupted output (and the
  preserved-original, if emitted).
- Aggressive-mode augmentation realizer (`emit_variants`) — stamps
  the per-variant `per_record_variant_seed` on every variant.

Lazy-mode augmentations and deterministic ops (Filters,
Transformations) are out of scope per the spec § 5 / story I.e.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pytest

# The corruption backend ships with the `[corruptions]` extras; gate
# this whole module behind it, mirroring `test_generation_imagecorruptions`.
pytest.importorskip("cv2", reason="requires the [corruptions] extras")

from datarefinery.pipeline.workers import per_record_seed, per_record_variant_seed
from datarefinery.plugins.image_classification.augmentations._realizer import (
    emit_variants,
)
from datarefinery.plugins.image_classification.generation_imagecorruptions import (
    imagecorruptions_apply,
)
from datarefinery.recipe.models import FieldSpec

Record = Mapping[str, Any]


def _output_schema() -> dict[str, FieldSpec]:
    return {
        "record_id": FieldSpec(dtype="str"),
        "image": FieldSpec(dtype="uint8", shape=[64, 64, 3]),
        "path": FieldSpec(dtype="str"),
    }


def _input_records(n: int = 3) -> list[Record]:
    rng = np.random.default_rng(42)
    return [
        {
            "record_id": f"img_{i}",
            "image": rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8),
            "path": f"/data/{i}.png",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Generation: imagecorruptions_apply
# ---------------------------------------------------------------------------


def test_imagecorruptions_stamps_op_name_seed_on_every_output() -> None:
    records = _input_records(2)
    out = imagecorruptions_apply(
        records,
        seed=42,
        inputs=["image"],
        output_schema=_output_schema(),
        params={
            "corruption_types": ["gaussian_noise"],
            "severities": [1, 3],
            "preserve_original": True,
        },
        label_field=None,
        op_name="my_corruption_run",
    )
    # 2 inputs * (1 preserved + 1 corruption * 2 severities) = 6 outputs.
    assert len(out) == 6
    for r in out:
        assert "my_corruption_run_seed" in r, r
        assert isinstance(r["my_corruption_run_seed"], int)


def test_imagecorruptions_stamp_value_matches_per_record_seed() -> None:
    records = _input_records(2)
    out = imagecorruptions_apply(
        records,
        seed=42,
        inputs=["image"],
        output_schema=_output_schema(),
        params={
            "corruption_types": ["gaussian_noise"],
            "severities": [1],
            "preserve_original": False,
        },
        label_field=None,
        op_name="apply",
    )
    # Map source record_id -> the seed used by the op's RNG.
    expected = {r["record_id"]: per_record_seed(42, r) for r in records}
    for outr in out:
        # Output record_id starts with the source record_id.
        source = outr["record_id"].split("_gaussian_noise_")[0]
        assert outr["apply_seed"] == expected[source]


def test_imagecorruptions_stamp_is_deterministic_across_runs() -> None:
    records = _input_records(2)
    kwargs = dict(
        seed=42,
        inputs=["image"],
        output_schema=_output_schema(),
        params={
            "corruption_types": ["gaussian_noise"],
            "severities": [1],
            "preserve_original": False,
        },
        label_field=None,
        op_name="apply",
    )
    a = imagecorruptions_apply(records, **kwargs)  # type: ignore[arg-type]
    b = imagecorruptions_apply(records, **kwargs)  # type: ignore[arg-type]
    assert [r["apply_seed"] for r in a] == [r["apply_seed"] for r in b]


def test_imagecorruptions_op_name_required_no_default() -> None:
    # The op signature must require op_name explicitly — silently
    # falling back to a hardcoded field name would let two ops of the
    # same kind collide on a single field.
    records = _input_records(1)
    with pytest.raises(TypeError):
        imagecorruptions_apply(  # type: ignore[call-arg]
            records,
            seed=42,
            inputs=["image"],
            output_schema=_output_schema(),
            params={
                "corruption_types": ["gaussian_noise"],
                "severities": [1],
                "preserve_original": False,
            },
            label_field=None,
        )


# ---------------------------------------------------------------------------
# Aggressive Augmentation: emit_variants
# ---------------------------------------------------------------------------


def _identity_realizer(record: Record, seed: int, vi: int, params: Mapping[str, Any]) -> Record:
    del seed, vi, params
    return dict(record)


def test_emit_variants_stamps_seed_field_on_every_variant() -> None:
    record = {"record_id": "r0", "image": np.zeros((4, 4, 3), dtype=np.uint8)}
    variants = emit_variants(
        record,
        op_id="random_crop",
        global_seed=99,
        expansion=3,
        realize_fn=_identity_realizer,
        stamp_field="my_crop_seed",
    )
    assert len(variants) == 3
    for vi, v in enumerate(variants):
        assert v["my_crop_seed"] == per_record_variant_seed(99, record, vi, op_id="random_crop")


def test_emit_variants_stamp_field_is_required_when_stamping() -> None:
    # When stamp_field is omitted (None), no seed is stamped — the
    # realizer module stays usable for callers that haven't migrated
    # to the persistence contract (defensive default; the pipeline
    # stage always supplies it).
    record = {"record_id": "r0", "image": np.zeros((4, 4, 3), dtype=np.uint8)}
    variants = emit_variants(
        record,
        op_id="random_crop",
        global_seed=1,
        expansion=2,
        realize_fn=_identity_realizer,
    )
    assert all("random_crop_seed" not in v for v in variants)
    # No stamp_field — no <op_id>_seed leakage.
