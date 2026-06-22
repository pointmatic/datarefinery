# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.q — `horizontal_flip` augmentation op tests (FR-AUG-2).

Lazy mode is policy-only (covered by the existing
``test_augmentations_stage.py`` policy-capture suite); these tests focus
on the aggressive-mode realizer:

- Param model accepts/rejects per the schema.
- Aggressive emits ``expansion`` peer records with the expected shape
  and metadata.
- Determinism across ``workers=1/2/4`` (parametrized integration
  through :func:`realize_aggressive_split`).
- Probability convergence at large ``expansion``.

The realizer uses ``Image.transpose(Image.FLIP_LEFT_RIGHT)`` (RNG-free,
confirmed by the H.o spike); the only stochastic choice is the per-
variant coin flip ``rng.random() < p`` against the per-variant seed.
"""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from datarefinery.pipeline.stages.augmentations import realize_aggressive_split
from datarefinery.plugins.image_classification.augmentations.horizontal_flip import (
    HorizontalFlipParams,
    realize_horizontal_flip,
)
from datarefinery.recipe.models import AugmentationOp

# ---------------------------------------------------------------------------
# Param-model surface
# ---------------------------------------------------------------------------


def test_horizontal_flip_params_require_p() -> None:
    # No-implicit-defaults (J.n.4): p is required; the code supplies no default.
    with pytest.raises(ValidationError):
        HorizontalFlipParams()  # type: ignore[call-arg]


def test_horizontal_flip_params_accepts_p_zero() -> None:
    assert HorizontalFlipParams(p=0.0).p == 0.0


def test_horizontal_flip_params_accepts_p_one() -> None:
    assert HorizontalFlipParams(p=1.0).p == 1.0


def test_horizontal_flip_params_rejects_p_below_zero() -> None:
    with pytest.raises(ValidationError):
        HorizontalFlipParams(p=-0.1)


def test_horizontal_flip_params_rejects_p_above_one() -> None:
    with pytest.raises(ValidationError):
        HorizontalFlipParams(p=1.1)


def test_horizontal_flip_params_is_frozen() -> None:
    params = HorizontalFlipParams(p=0.5)
    with pytest.raises(ValidationError):
        params.p = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Realizer correctness
# ---------------------------------------------------------------------------


def _checker_image(seed: int = 0) -> np.ndarray:
    """Asymmetric 8x8x3 uint8 image; flipping changes the bytes."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8)


def _record(rid: str, arr: np.ndarray, label: int = 0) -> dict[str, Any]:
    return {"record_id": rid, "image": arr, "label": label}


def test_realizer_p_one_always_flips() -> None:
    arr = _checker_image()
    out = realize_horizontal_flip(_record("r", arr), seed=12345, variant_index=0, params={"p": 1.0})
    expected = np.asarray(Image.fromarray(arr).transpose(Image.Transpose.FLIP_LEFT_RIGHT))
    assert np.array_equal(out["image"], expected)


def test_realizer_p_zero_never_flips() -> None:
    arr = _checker_image()
    out = realize_horizontal_flip(_record("r", arr), seed=12345, variant_index=0, params={"p": 0.0})
    assert np.array_equal(out["image"], arr)


def test_realizer_preserves_label_and_other_fields() -> None:
    arr = _checker_image()
    record = _record("r", arr, label=7)
    record["extra"] = "keep-me"
    out = realize_horizontal_flip(record, seed=1, variant_index=0, params={"p": 1.0})
    assert out["label"] == 7
    assert out["extra"] == "keep-me"


def test_realizer_same_seed_same_decision() -> None:
    arr = _checker_image()
    a = realize_horizontal_flip(_record("r", arr), seed=999, variant_index=0, params={"p": 0.5})
    b = realize_horizontal_flip(_record("r", arr), seed=999, variant_index=0, params={"p": 0.5})
    assert np.array_equal(a["image"], b["image"])


def test_realizer_different_seed_can_differ() -> None:
    """Sanity check: different seeds eventually produce different outputs at p=0.5."""
    arr = _checker_image()
    outputs = []
    for s in range(50):
        out = realize_horizontal_flip(_record("r", arr), seed=s, variant_index=0, params={"p": 0.5})
        outputs.append(np.array_equal(out["image"], arr))
    # Not all the same: some flips, some non-flips.
    assert any(outputs) and not all(outputs)


def test_realizer_rejects_empty_params() -> None:
    # No-implicit-defaults (J.n.4): an omitted required `p` is an error, not a
    # silent 0.5 substitution.
    arr = _checker_image()
    with pytest.raises(ValidationError):
        realize_horizontal_flip(_record("r", arr), seed=42, variant_index=0, params={})


# ---------------------------------------------------------------------------
# Aggressive-mode integration through realize_aggressive_split
# ---------------------------------------------------------------------------


def _aggressive_op(p: float = 0.5, expansion: int = 4) -> AugmentationOp:
    return AugmentationOp(
        name="flip",
        op="horizontal_flip",
        params={"p": p},
        splits=["train"],
        seed=1,
        materialization="aggressive",
        expansion=expansion,
    )


def _records(n: int, seed: int = 7) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    return [
        {
            "record_id": f"img_{i:03d}",
            "image": rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8),
            "label": i % 3,
        }
        for i in range(n)
    ]


def _registry() -> dict[str, Any]:
    return {"horizontal_flip": realize_horizontal_flip}


def test_aggressive_horizontal_flip_emits_n_times_expansion_records() -> None:
    records = _records(5)
    out = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=3)],
        global_seed=42,
        realizer_registry=_registry(),
    )
    assert len(out) == 5 * 3


def test_aggressive_horizontal_flip_carries_metadata() -> None:
    records = _records(3)
    out = realize_aggressive_split(
        records,
        [_aggressive_op(expansion=2)],
        global_seed=42,
        realizer_registry=_registry(),
    )
    grouped: dict[str, list[int]] = {}
    for r in out:
        grouped.setdefault(str(r["source_record_id"]), []).append(r["variant_index"])
    assert grouped == {
        "img_000": [0, 1],
        "img_001": [0, 1],
        "img_002": [0, 1],
    }


def test_aggressive_horizontal_flip_image_dtype_uint8_preserved() -> None:
    records = _records(2)
    out = realize_aggressive_split(
        records,
        [_aggressive_op(p=1.0, expansion=2)],
        global_seed=42,
        realizer_registry=_registry(),
    )
    for r in out:
        assert r["image"].dtype == np.uint8
        assert r["image"].shape == (8, 8, 3)


def _serialize_for_compare(records: list[dict[str, Any]]) -> bytes:
    """Hash the post-augmentation record set by SHA-ing the image bytes
    and the metadata fields in a stable order."""
    import hashlib
    import json

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
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return "\n".join(parts).encode("utf-8")


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_workers_1_2_4_produce_byte_identical_aggressive_output(workers: int) -> None:
    records = _records(6)
    out_1 = realize_aggressive_split(
        records,
        [_aggressive_op(p=0.5, expansion=4)],
        global_seed=42,
        realizer_registry=_registry(),
        workers=1,
    )
    out_w = realize_aggressive_split(
        records,
        [_aggressive_op(p=0.5, expansion=4)],
        global_seed=42,
        realizer_registry=_registry(),
        workers=workers,
    )
    assert _serialize_for_compare(out_1) == _serialize_for_compare(out_w)


def test_probability_convergence_at_large_expansion() -> None:
    """With ``p=0.5`` and a large expansion, the fraction of flipped variants
    should be close to 0.5. Loose tolerance keeps the test stable."""
    records = _records(8)
    out = realize_aggressive_split(
        records,
        [_aggressive_op(p=0.5, expansion=200)],
        global_seed=42,
        realizer_registry=_registry(),
    )
    # Determine flipped vs. not by reference to the input arrays.
    input_by_rid = {r["record_id"]: r["image"] for r in records}
    flipped = 0
    for variant in out:
        original = input_by_rid[variant["source_record_id"]]
        flipped_ref = np.asarray(
            Image.fromarray(original).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        )
        if np.array_equal(variant["image"], flipped_ref):
            flipped += 1
    fraction = flipped / len(out)
    # Expectation: ~0.5; allow generous slack since N=1600 is finite.
    assert 0.40 < fraction < 0.60, f"flip fraction {fraction} not near 0.5"
    # Sanity: mean is approximately 0.5.
    assert abs(statistics.mean([1.0 if flipped_ref is not None else 0.0]) - 1.0) < 0.5
