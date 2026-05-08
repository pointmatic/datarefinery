# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin skeleton.

Declares every operation's `OperationSpec` parameter schema so the
recipe validator (FR-2 check 18) can validate recipes against this
plugin from day one. The actual operation implementations land in
stories C.f-C.k; `operation_factory` raises `NotImplementedError`
until then. `is_stub()` returns False because the schemas are real
(distinct from the tabular/text plugins in C.c, which are true stubs).
"""

from __future__ import annotations

from typing import Any

from datarefinery.plugins.base import Operation, OperationSpec, ParameterSpec
from datarefinery.plugins.image_classification.operations.filters import (
    filter_by_label,
    random_sample,
)
from datarefinery.plugins.image_classification.operations.generation import (
    duplicate_minority_class,
)

_FILTER_OPS: dict[str, Operation] = {
    "filter_by_label": filter_by_label,
    "random_sample": random_sample,
}

_GENERATION_OPS: dict[str, Operation] = {
    "duplicate_minority_class": duplicate_minority_class,
}

SUPPORTED_SECTIONS = frozenset(
    {
        "Input",
        "Output",
        "Labels",
        "SampleData",
        "InputContracts",
        "Filters",
        "Generation",
        "Splits",
        "Transformations",
        "Augmentations",
        "Featurizations",
        "OutputExpectations",
        "Visualizations",
    }
)


def _supported_operations() -> dict[str, OperationSpec]:
    return {
        # ----- Filters (FR-8) -----
        "filter_by_label": OperationSpec(
            parameters={
                "labels": ParameterSpec(type="list[str]", required=True),
                "action": ParameterSpec(
                    type="str", required=False, default="include"
                ),
            },
            applicable_sections=frozenset({"Filters"}),
        ),
        "random_sample": OperationSpec(
            parameters={
                "fraction": ParameterSpec(type="float", required=False),
                "n": ParameterSpec(type="int", required=False),
                "seed": ParameterSpec(type="int", required=True),
            },
            applicable_sections=frozenset({"Filters"}),
        ),
        # ----- Generation (FR-9) -----
        "duplicate_minority_class": OperationSpec(
            parameters={
                "label_field": ParameterSpec(type="str", required=True),
                "target_count": ParameterSpec(type="int", required=True),
                "seed": ParameterSpec(type="int", required=True),
            },
            applicable_sections=frozenset({"Generation"}),
        ),
        # ----- Transformations (FR-10) -----
        "resize": OperationSpec(
            parameters={
                "size": ParameterSpec(type="int", required=True),
                "method": ParameterSpec(
                    type="str", required=False, default="bilinear"
                ),
            },
            applicable_sections=frozenset({"Transformations"}),
        ),
        "normalize": OperationSpec(
            parameters={
                "mean": ParameterSpec(type="list[float]", required=False),
                "std": ParameterSpec(type="list[float]", required=False),
            },
            fit_on_train=True,
            applicable_sections=frozenset({"Transformations"}),
        ),
        "mean_subtract": OperationSpec(
            fit_on_train=True,
            applicable_sections=frozenset({"Transformations"}),
        ),
        "to_grayscale": OperationSpec(
            applicable_sections=frozenset({"Transformations"}),
        ),
        "cast_dtype": OperationSpec(
            parameters={"dtype": ParameterSpec(type="str", required=True)},
            applicable_sections=frozenset({"Transformations"}),
        ),
        # ----- Featurizations (FR-12, FR-22) -----
        "label_from_path": OperationSpec(
            parameters={
                "source": ParameterSpec(
                    type="str",
                    required=False,
                    default="parent_directory_name",
                ),
            },
            applicable_sections=frozenset({"Featurizations"}),
        ),
        "image_size_stats": OperationSpec(
            applicable_sections=frozenset({"Featurizations"}),
        ),
        # ----- Augmentations (FR-11; train-only) -----
        "random_crop": OperationSpec(
            parameters={
                "size": ParameterSpec(type="int", required=True),
                "seed": ParameterSpec(type="int", required=True),
            },
            applicable_sections=frozenset({"Augmentations"}),
            applicable_splits=frozenset({"train"}),
        ),
        "horizontal_flip": OperationSpec(
            parameters={
                "p": ParameterSpec(type="float", required=False, default=0.5),
                "seed": ParameterSpec(type="int", required=True),
            },
            applicable_sections=frozenset({"Augmentations"}),
            applicable_splits=frozenset({"train"}),
        ),
        "color_jitter": OperationSpec(
            parameters={
                "brightness": ParameterSpec(
                    type="float", required=False, default=0.0
                ),
                "contrast": ParameterSpec(
                    type="float", required=False, default=0.0
                ),
                "saturation": ParameterSpec(
                    type="float", required=False, default=0.0
                ),
                "seed": ParameterSpec(type="int", required=True),
            },
            applicable_sections=frozenset({"Augmentations"}),
            applicable_splits=frozenset({"train"}),
        ),
        # ----- Visualizations (FR-13) -----
        "class_distribution_histogram": OperationSpec(
            applicable_sections=frozenset({"Visualizations"}),
        ),
        "sample_grid": OperationSpec(
            parameters={
                "n": ParameterSpec(type="int", required=False, default=16),
                "per_class": ParameterSpec(
                    type="bool", required=False, default=False
                ),
            },
            applicable_sections=frozenset({"Visualizations"}),
        ),
        "mean_image_per_class": OperationSpec(
            applicable_sections=frozenset({"Visualizations"}),
        ),
    }


class ImageClassificationPlugin:
    """Skeleton plugin: schemas declared, operations not yet implemented."""

    name = "image_classification"
    schema_version = 1
    supported_sections = SUPPORTED_SECTIONS

    def __init__(self) -> None:
        self.supported_operations = _supported_operations()

    def operation_factory(self, section: str, op_name: str) -> Operation:
        if section == "Filters" and op_name in _FILTER_OPS:
            return _FILTER_OPS[op_name]
        if section == "Generation" and op_name in _GENERATION_OPS:
            return _GENERATION_OPS[op_name]
        raise NotImplementedError(
            f"image_classification operation factory not yet implemented "
            f"(section={section!r}, op={op_name!r}); remaining operations "
            f"land in Stories C.h-C.k"
        )

    def is_stub(self) -> bool:
        return False


PLUGIN: Any = ImageClassificationPlugin()
