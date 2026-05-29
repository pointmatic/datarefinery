# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Tests for the G11 master-seed derivation helper.

Pins the exact derivation function — any change here invalidates every
cached instance for every recipe that uses ``seed_derive_from: master``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from datarefinery.recipe.models import (
    AugmentationOp,
    FilterOp,
    GenerationOp,
    SampleSelector,
    SeedDerivationSpec,
    SplitsSection,
)
from datarefinery.recipe.seeds import derive_seed, resolve_seed

# ---------------------------------------------------------------------------
# derive_seed — pinned by fixture
# ---------------------------------------------------------------------------


def test_derive_seed_is_pinned_for_a_known_master_op_pair() -> None:
    """Canonical-derivation pin: changing this value invalidates every
    cached instance that used the derivation form. Bump deliberately and
    follow the ceremonious-invalidation rules in project-essentials.md.
    """
    assert derive_seed(20260509, "filter_train_pool") == 15455891160210205198


def test_derive_seed_same_master_different_op_produces_distinct_seeds() -> None:
    a = derive_seed(100, "alpha")
    b = derive_seed(100, "beta")
    c = derive_seed(100, "gamma")
    assert len({a, b, c}) == 3


def test_derive_seed_different_master_propagates_to_every_op() -> None:
    pairs = ("alpha", "beta", "gamma")
    before = {name: derive_seed(100, name) for name in pairs}
    after = {name: derive_seed(200, name) for name in pairs}
    for name in pairs:
        assert before[name] != after[name]
    # And no collision between the two sets either.
    assert set(before.values()).isdisjoint(after.values())


def test_derive_seed_same_master_and_op_is_idempotent() -> None:
    assert derive_seed(42, "k") == derive_seed(42, "k")


def test_derive_seed_handles_negative_master_seed() -> None:
    # Master seed could be any int; negative should produce a stable
    # 64-bit byte representation rather than raising OverflowError.
    derived = derive_seed(-1, "filter")
    assert isinstance(derived, int)
    assert 0 <= derived < (1 << 64)


# ---------------------------------------------------------------------------
# resolve_seed — three cases (None, int, SeedDerivationSpec)
# ---------------------------------------------------------------------------


def test_resolve_seed_passes_none_through_unchanged() -> None:
    assert resolve_seed(None, master_seed=11, op_name="x") is None


def test_resolve_seed_passes_literal_int_through_unchanged() -> None:
    assert resolve_seed(42, master_seed=11, op_name="x") == 42


def test_resolve_seed_derives_when_spec_supplied() -> None:
    spec = SeedDerivationSpec(from_="master")
    derived = resolve_seed(spec, master_seed=11, op_name="x")
    assert derived == derive_seed(11, "x")


# ---------------------------------------------------------------------------
# SeedDerivationSpec parses both YAML alias and Python attribute name
# ---------------------------------------------------------------------------


def test_seed_derivation_spec_parses_yaml_alias_form() -> None:
    spec = SeedDerivationSpec.model_validate({"from": "master"})
    assert spec.from_ == "master"


def test_seed_derivation_spec_parses_python_attribute_name_form() -> None:
    spec = SeedDerivationSpec(from_="master")
    assert spec.from_ == "master"


def test_seed_derivation_spec_rejects_unknown_from_value() -> None:
    with pytest.raises(ValidationError):
        SeedDerivationSpec.model_validate({"from": "sibling"})


def test_seed_derivation_spec_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        SeedDerivationSpec.model_validate({"from": "master", "rounds": 2})


# ---------------------------------------------------------------------------
# Model field widening — each seed-bearing model accepts both forms
# ---------------------------------------------------------------------------


def test_splits_section_accepts_literal_int_seed() -> None:
    section = SplitsSection.model_validate({"ratios": {"train": 0.6, "val": 0.4}, "seed": 11})
    assert section.seed == 11


def test_splits_section_accepts_seed_derivation_spec() -> None:
    section = SplitsSection.model_validate(
        {"ratios": {"train": 0.6, "val": 0.4}, "seed": {"from": "master"}}
    )
    assert isinstance(section.seed, SeedDerivationSpec)
    assert section.seed.from_ == "master"


def test_generation_op_accepts_seed_derivation_spec() -> None:
    op = GenerationOp.model_validate(
        {
            "name": "corrupt",
            "inputs": ["image"],
            "output_schema": {"image": {"dtype": "uint8", "shape": [4, 4, 3]}},
            "seed": {"from": "master"},
        }
    )
    assert isinstance(op.seed, SeedDerivationSpec)


def test_augmentation_op_accepts_seed_derivation_spec() -> None:
    op = AugmentationOp.model_validate(
        {
            "name": "hflip",
            "op": "horizontal_flip",
            "seed": {"from": "master"},
            "splits": ["train"],
        }
    )
    assert isinstance(op.seed, SeedDerivationSpec)


def test_filter_op_accepts_seed_derivation_spec_at_top_level() -> None:
    op = FilterOp.model_validate(
        {
            "name": "f1",
            "predicate": {"op": "filter_by_label", "labels": ["a"]},
            "seed": {"from": "master"},
            "splits": ["train"],
        }
    )
    assert isinstance(op.seed, SeedDerivationSpec)


def test_sample_selector_accepts_seed_derivation_spec() -> None:
    sel = SampleSelector.model_validate({"n": 10, "seed": {"from": "master"}})
    assert isinstance(sel.seed, SeedDerivationSpec)
