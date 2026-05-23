# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Plugin contract tests for the image_classification plugin skeleton.

Operation implementations land in Stories C.f-C.k; this story (C.b)
verifies the *schemas* are sound and discoverable.
"""

from __future__ import annotations

import pytest

from datarefinery.plugins.base import OperationSpec, Plugin
from datarefinery.plugins.discovery import discover_plugins
from datarefinery.plugins.image_classification import PLUGIN

EXPECTED_OPERATIONS = frozenset(
    {
        "filter_by_label",
        "random_sample",
        "sample_per_class",
        "sample_per_class_fractional",
        "drop_by_label",
        "duplicate_minority_class",
        "imagecorruptions_apply",
        "resize",
        "normalize",
        "mean_subtract",
        "to_grayscale",
        "cast_dtype",
        "label_from_path",
        "image_size_stats",
        "random_crop",
        "horizontal_flip",
        "color_jitter",
        "random_erasing",
        "class_distribution_histogram",
        "sample_grid",
        "mean_image_per_class",
        "pixel_distribution",
    }
)


def test_plugin_satisfies_runtime_protocol() -> None:
    assert isinstance(PLUGIN, Plugin)


def test_plugin_metadata() -> None:
    assert PLUGIN.name == "image_classification"
    assert PLUGIN.schema_version == 1
    assert PLUGIN.is_stub() is False


def test_supported_sections_cover_recipe_section_set() -> None:
    required = {"Input", "Output", "Labels", "Splits"}
    assert required.issubset(PLUGIN.supported_sections)


def test_every_expected_operation_is_declared() -> None:
    declared = set(PLUGIN.supported_operations.keys())
    assert EXPECTED_OPERATIONS == declared, (
        f"missing: {EXPECTED_OPERATIONS - declared}; unexpected: {declared - EXPECTED_OPERATIONS}"
    )


@pytest.mark.parametrize("op_name", sorted(EXPECTED_OPERATIONS))
def test_every_operation_has_a_valid_operation_spec(op_name: str) -> None:
    spec = PLUGIN.supported_operations[op_name]
    assert isinstance(spec, OperationSpec)
    # `applicable_sections` is the only required field on OperationSpec; assert
    # it's a non-empty frozenset of recipe section names.
    assert isinstance(spec.applicable_sections, frozenset)
    assert spec.applicable_sections
    assert spec.applicable_sections.issubset(PLUGIN.supported_sections)


def test_fit_on_train_ops_are_in_transformations() -> None:
    fit_on_train_ops = {
        name for name, spec in PLUGIN.supported_operations.items() if spec.fit_on_train
    }
    for name in fit_on_train_ops:
        spec = PLUGIN.supported_operations[name]
        assert "Transformations" in spec.applicable_sections, name


def test_augmentation_ops_apply_to_train_only() -> None:
    aug_ops = {
        name: spec
        for name, spec in PLUGIN.supported_operations.items()
        if "Augmentations" in spec.applicable_sections
    }
    assert aug_ops, "expected at least one augmentation op"
    for name, spec in aug_ops.items():
        assert spec.applicable_splits == frozenset({"train"}), name


def test_resize_parameter_schema_validates_fixture_params() -> None:
    spec = PLUGIN.supported_operations["resize"]
    required = {k for k, v in spec.parameters.items() if v.required}
    fixture: dict[str, object] = {"size": 32}
    for name in required:
        assert name in fixture, f"required param {name!r} missing from fixture"


def test_normalize_marked_fit_on_train() -> None:
    assert PLUGIN.supported_operations["normalize"].fit_on_train is True


def test_label_from_path_default_source_is_parent_directory_name() -> None:
    spec = PLUGIN.supported_operations["label_from_path"]
    assert "source" in spec.parameters
    assert spec.parameters["source"].default == "parent_directory_name"


def test_operation_factory_raises_not_implemented_for_unimplemented_ops() -> None:
    """Ops still pending implementation should raise NotImplementedError.

    Augmentations remain policy-only in v1 (FR-11): the recipe declares
    them, the runner records the policy, but the plugin does not
    pre-materialize augmented examples - so the factory still refuses.
    """
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        PLUGIN.operation_factory("Transformations", "to_grayscale")
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        PLUGIN.operation_factory("Transformations", "cast_dtype")
    for aug_op in ("random_crop", "horizontal_flip", "color_jitter"):
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            PLUGIN.operation_factory("Augmentations", aug_op)


def test_operation_factory_returns_filter_ops_after_C_f() -> None:
    """Story C.f wires filter_by_label and random_sample through the factory."""
    assert callable(PLUGIN.operation_factory("Filters", "filter_by_label"))
    assert callable(PLUGIN.operation_factory("Filters", "random_sample"))


def test_operation_factory_returns_generation_ops_after_C_g() -> None:
    """Story C.g wires duplicate_minority_class through the factory."""
    assert callable(PLUGIN.operation_factory("Generation", "duplicate_minority_class"))


def test_operation_factory_returns_transformation_ops_after_C_h() -> None:
    """Story C.h wires resize, normalize, mean_subtract through the factory."""
    for op_name in ("resize", "normalize", "mean_subtract"):
        handle = PLUGIN.operation_factory("Transformations", op_name)
        assert hasattr(handle, "fit") and hasattr(handle, "apply"), op_name


def test_operation_factory_returns_featurization_ops_after_C_i() -> None:
    """Story C.i wires label_from_path and image_size_stats through the factory."""
    for op_name in ("label_from_path", "image_size_stats"):
        handle = PLUGIN.operation_factory("Featurizations", op_name)
        assert hasattr(handle, "fit") and hasattr(handle, "apply"), op_name


def test_operation_factory_returns_visualization_ops_after_C_k() -> None:
    """Story C.k wires the three visualization ops through the factory."""
    for op_name in (
        "class_distribution_histogram",
        "sample_grid",
        "mean_image_per_class",
    ):
        handle = PLUGIN.operation_factory("Visualizations", op_name)
        assert hasattr(handle, "render"), op_name


def test_discover_plugins_returns_image_classification() -> None:
    plugins = discover_plugins()
    assert "image_classification" in plugins
    assert plugins["image_classification"].name == "image_classification"
