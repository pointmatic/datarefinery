# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Pydantic v2 models for `Recipe` and every section.

Plugin-specific operation parameters (`params`, `predicate`, `assertion`)
are intentionally typed as opaque mappings here; the recipe validator
(FR-2 check 18) cross-checks them against the declaring plugin's
`OperationSpec` in Story B.e.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["error", "warning"]


class _Frozen(BaseModel):
    """Shared config: explicit fields, immutable instances."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _default_filter_stages() -> list[Literal["pre_split", "post_split"]]:
    return ["pre_split"]


class InputSource(_Frozen):
    name: str
    type: str
    path: Path
    label_from: str | None = None


class InputSection(_Frozen):
    sources: list[InputSource]


class FieldSpec(_Frozen):
    dtype: str
    shape: list[int] | None = None


class OutputSection(_Frozen):
    record_schema: dict[str, FieldSpec]


class LabelSource(_Frozen):
    kind: Literal["direct", "derived"] = "direct"
    derivation: str | None = None


class LabelsSection(_Frozen):
    field: str
    source: LabelSource


class SampleSelector(_Frozen):
    n: int | None = None
    fraction: float | None = None
    seed: int | None = None


class SampleDataSection(_Frozen):
    selector: SampleSelector


class Contract(_Frozen):
    field: str | None = None
    assertion: dict[str, Any]
    severity: Severity = "error"


class Expectation(_Frozen):
    field: str | None = None
    assertion: dict[str, Any]
    severity: Severity = "error"


class FilterOp(_Frozen):
    name: str
    predicate: dict[str, Any]
    stages: list[Literal["pre_split", "post_split"]] = Field(
        default_factory=_default_filter_stages
    )
    splits: list[str] = Field(default_factory=list)
    seed: int | None = None


class GenerationOp(_Frozen):
    name: str
    inputs: list[str]
    output_schema: dict[str, FieldSpec]
    seed: int
    applies_at: list[str] = Field(default_factory=lambda: ["train"])


class KeyAssignment(_Frozen):
    field: str
    mapping: dict[str, str]


class SplitsSection(_Frozen):
    ratios: dict[str, float] | None = None
    key_assignment: KeyAssignment | None = None
    stratify_by: str | None = None
    seed: int | None = None
    class_balance: str | None = None


class TransformationOp(_Frozen):
    name: str
    op: str
    params: dict[str, Any] = Field(default_factory=dict)
    fit_source: str | None = None
    splits: list[str] = Field(default_factory=list)


class AugmentationOp(_Frozen):
    name: str
    op: str
    params: dict[str, Any] = Field(default_factory=dict)
    splits: list[str] = Field(default_factory=lambda: ["train"])
    seed: int | None = None


class FeaturizationOp(_Frozen):
    name: str
    inputs: list[str]
    output_field: str
    op: str
    params: dict[str, Any] = Field(default_factory=dict)
    splits: list[str] = Field(default_factory=list)
    fit_source: str | None = None


class VisualizationOp(_Frozen):
    name: str
    op: str
    params: dict[str, Any] = Field(default_factory=dict)
    stage: str
    mode: Literal["exploration", "reporting"]


class Recipe(_Frozen):
    schema_version: int
    plugin: str
    seed: int = 0
    Input: InputSection
    Output: OutputSection
    Labels: LabelsSection
    SampleData: SampleDataSection | None = None
    InputContracts: list[Contract] = Field(default_factory=list)
    Filters: list[FilterOp] = Field(default_factory=list)
    Generation: list[GenerationOp] = Field(default_factory=list)
    Splits: SplitsSection
    Transformations: list[TransformationOp] = Field(default_factory=list)
    Augmentations: list[AugmentationOp] = Field(default_factory=list)
    Featurizations: list[FeaturizationOp] = Field(default_factory=list)
    OutputExpectations: list[Expectation] = Field(default_factory=list)
    Visualizations: list[VisualizationOp] = Field(default_factory=list)
    variants: dict[str, dict[str, Any]] = Field(default_factory=dict)
