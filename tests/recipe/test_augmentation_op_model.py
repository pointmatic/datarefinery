# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.p — `AugmentationOp` materialization mode + expansion field tests.

Pins the model surface for the FR-11 extension. Cross-checks happy paths
(lazy default, aggressive opt-in) and the model-level validator
rejections (`expansion < 1`, `expansion > 1` paired with `lazy`).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from datarefinery.recipe.models import AugmentationOp


def _op(**overrides: object) -> AugmentationOp:
    base: dict[str, object] = {
        "name": "flip",
        "op": "horizontal_flip",
        "params": {"p": 0.5},
        "splits": ["train"],
        "seed": 1,
    }
    base.update(overrides)
    return AugmentationOp.model_validate(base)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_materialization_defaults_to_lazy() -> None:
    op = _op()
    assert op.materialization == "lazy"


def test_expansion_defaults_to_one() -> None:
    op = _op()
    assert op.expansion == 1


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_aggressive_mode_with_expansion_gt_one_accepted() -> None:
    op = _op(materialization="aggressive", expansion=4)
    assert op.materialization == "aggressive"
    assert op.expansion == 4


def test_aggressive_with_expansion_one_accepted() -> None:
    """Legal but no-op: aggressive realization with one variant per record
    is still aggressive (records become peer records, just N*1)."""
    op = _op(materialization="aggressive", expansion=1)
    assert op.materialization == "aggressive"
    assert op.expansion == 1


def test_lazy_with_expansion_one_accepted() -> None:
    """The default pairing — lazy + expansion=1 — must round-trip cleanly
    so existing recipes without these fields parse unchanged."""
    op = _op(materialization="lazy", expansion=1)
    assert op.materialization == "lazy"
    assert op.expansion == 1


# ---------------------------------------------------------------------------
# Model-level validator rejections
# ---------------------------------------------------------------------------


def test_expansion_zero_rejected() -> None:
    with pytest.raises(ValidationError, match="expansion"):
        _op(expansion=0)


def test_expansion_negative_rejected() -> None:
    with pytest.raises(ValidationError, match="expansion"):
        _op(expansion=-3)


def test_lazy_with_expansion_gt_one_rejected() -> None:
    with pytest.raises(ValidationError, match="aggressive"):
        _op(materialization="lazy", expansion=2)


def test_aggressive_with_expansion_gt_one_accepted_high() -> None:
    op = _op(materialization="aggressive", expansion=100)
    assert op.expansion == 100


def test_unknown_materialization_rejected() -> None:
    with pytest.raises(ValidationError):
        _op(materialization="ultra")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Frozen + canonical-form behavior
# ---------------------------------------------------------------------------


def test_augmentation_op_is_frozen() -> None:
    op = _op()
    with pytest.raises(ValidationError):
        op.materialization = "aggressive"  # type: ignore[misc]


def test_model_dump_includes_new_fields() -> None:
    """Canonical bytes are produced from `model_dump(mode='json')` — every
    field default participates in the cache identity. Pin the dump shape
    so a future field reorder is caught."""
    op = _op()
    dumped = op.model_dump(mode="json")
    assert dumped["materialization"] == "lazy"
    assert dumped["expansion"] == 1
