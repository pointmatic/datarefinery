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

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["error", "warning"]


class _Frozen(BaseModel):
    """Shared config: explicit fields, immutable instances."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _default_filter_stages() -> list[Literal["pre_split", "post_split"]]:
    return ["pre_split"]


class LabelFromSpec(_Frozen):
    """Sidecar-manifest label source for `image_flat` input sources.

    Recipe-as-truth: when `header` is provided, the file is treated as
    headerless and the recipe-supplied names *are* the column names. If
    the file actually contains a header line, it is read as a data row.
    """

    path: Path
    join: Literal["by_id", "by_row_order"]
    header: list[str] | None = None
    id_field: str | None = None
    label_field: str

    @model_validator(mode="after")
    def _validate_spec(self) -> LabelFromSpec:
        if self.join == "by_id" and self.id_field is None:
            raise ValueError("label_from: id_field is required when join == 'by_id'")
        if self.header is not None:
            if len(self.header) == 0:
                raise ValueError("label_from.header: must be non-empty when provided")
            if len(set(self.header)) != len(self.header):
                raise ValueError("label_from.header: column names must be unique")
            if self.label_field not in self.header:
                raise ValueError(
                    f"label_from.label_field {self.label_field!r} not present in header"
                )
            if self.id_field is not None and self.id_field not in self.header:
                raise ValueError(f"label_from.id_field {self.id_field!r} not present in header")
        return self


class InputSource(_Frozen):
    name: str
    type: str
    path: Path
    label_from: LabelFromSpec | None = None
    partition: str | None = None
    unlabeled: bool = False

    @model_validator(mode="after")
    def _validate_unlabeled(self) -> InputSource:
        if self.unlabeled:
            if self.partition is None:
                raise ValueError(
                    f"InputSource {self.name!r}: unlabeled=true requires 'partition' "
                    f"to be declared (unlabeled records must live in a named partition)"
                )
            if self.label_from is not None:
                raise ValueError(
                    f"InputSource {self.name!r}: unlabeled=true is incompatible with "
                    f"label_from (a sidecar manifest provides labels, contradicting "
                    f"unlabeled-ness)"
                )
        return self


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
    stages: list[Literal["pre_split", "post_split"]] = Field(default_factory=_default_filter_stages)
    splits: list[str] = Field(default_factory=list)
    seed: int | None = None


class SamplePerClassParams(_Frozen):
    """FR-FILTER-1 params for `sample_per_class` (Story H.j).

    `n_per_class` is required and must be positive. `label` tags surviving
    records via the plugin's `sample_per_class_tags` field;
    `exclude_already_labeled` removes records already carrying any of the
    named tags from the candidate pool, enabling disjoint-pool selection.
    """

    n_per_class: int = Field(gt=0)
    label: str | None = None
    exclude_already_labeled: list[str] | None = None


class SamplePerClassFractionalParams(_Frozen):
    """FR-FILTER-2 params for `sample_per_class_fractional` (Story H.k).

    Per-class surviving count = `floor(n_per_class_base * fractions.get(label, 1.0))`.
    Missing labels default to 1.0 (full base count). Each fraction must be
    in `[0.0, 1.0]`. Inherits `label` / `exclude_already_labeled` semantics
    from `SamplePerClassParams`.
    """

    n_per_class_base: int = Field(gt=0)
    fractions: dict[str, float] = Field(default_factory=dict)
    label: str | None = None
    exclude_already_labeled: list[str] | None = None

    @model_validator(mode="after")
    def _validate_fractions(self) -> SamplePerClassFractionalParams:
        for k, v in self.fractions.items():
            if not 0.0 <= v <= 1.0:
                raise ValueError(
                    f"sample_per_class_fractional: fractions[{k!r}]={v} must be in [0.0, 1.0]"
                )
        return self


class DropByLabelParams(_Frozen):
    """FR-FILTER-3 params for `drop_by_label` (Story H.l).

    `labels` must be non-empty. Records carrying any of these tags in
    `sample_per_class_tags` are dropped; records without the tag field or
    carrying only non-matching tags pass through unchanged.
    """

    labels: list[str] = Field(min_length=1)


class ImageCorruptionsApplyParams(_Frozen):
    """FR-GEN-1 params for `imagecorruptions_apply` (Story H.m.2).

    `corruption_types` lists the H-D corruption names to apply (must be
    non-empty; vocabulary checked against the in-tree
    `_corruption_names.CORRUPTION_NAMES_ALL`). `severities` lists severity
    levels in 1..5 (non-empty). `preserve_original` controls whether the
    op also emits an untouched copy of each input with `corruption="none"`
    and `severity=0`. `tag_fields` names the metadata fields written onto
    each output record.
    """

    corruption_types: list[str] = Field(min_length=1)
    severities: list[int] = Field(min_length=1)
    preserve_original: bool = False
    tag_fields: list[str] = Field(default_factory=lambda: ["corruption", "severity", "source_path"])

    @model_validator(mode="after")
    def _validate(self) -> ImageCorruptionsApplyParams:
        # Local import avoids a top-level dependency on the plugin from the
        # recipe-models layer; the names module is dependency-free.
        from datarefinery.plugins.image_classification._corruption_names import (
            CORRUPTION_NAMES_ALL,
        )

        unknown = [c for c in self.corruption_types if c not in CORRUPTION_NAMES_ALL]
        if unknown:
            raise ValueError(
                f"imagecorruptions_apply: unknown corruption_types {unknown!r}; "
                f"canonical names are {list(CORRUPTION_NAMES_ALL)!r}"
            )
        if len(set(self.corruption_types)) != len(self.corruption_types):
            raise ValueError(
                f"imagecorruptions_apply: corruption_types contains duplicates "
                f"({self.corruption_types!r})"
            )
        for sev in self.severities:
            if sev not in (1, 2, 3, 4, 5):
                raise ValueError(
                    f"imagecorruptions_apply: severities must each be in [1, 5] (got {sev})"
                )
        if len(set(self.severities)) != len(self.severities):
            raise ValueError(
                f"imagecorruptions_apply: severities contains duplicates ({self.severities!r})"
            )
        return self


class GenerationOp(_Frozen):
    name: str
    inputs: list[str]
    output_schema: dict[str, FieldSpec]
    seed: int
    applies_at: list[str] = Field(default_factory=lambda: ["train"])
    params: dict[str, Any] = Field(default_factory=dict)


class KeyAssignment(_Frozen):
    field: str
    mapping: dict[str, str]


class SplitsSection(_Frozen):
    ratios: dict[str, float] | None = None
    key_assignment: KeyAssignment | None = None
    stratify_by: str | None = None
    seed: int | None = None
    class_balance: str | None = None
    applies_to: str | None = None


class StatsFromInstanceSpec(_Frozen):
    """FR-TRANS-1 spec for importing fitted statistics from a sibling instance.

    `recipe` is a filesystem path (string) to the sibling recipe YAML; `op_id`
    names the operation within the sibling whose `fitted_statistics/<op_id>/`
    directory will be read. Mutually exclusive with `TransformationOp.fit_source`
    (enforced by validator check 22).
    """

    recipe: str
    op_id: str


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
    materialization: Literal["lazy", "aggressive"] = "lazy"
    expansion: int = 1

    @model_validator(mode="after")
    def _validate_materialization(self) -> AugmentationOp:
        if self.expansion < 1:
            raise ValueError(
                f"AugmentationOp[{self.name!r}]: expansion must be >= 1 (got {self.expansion})"
            )
        if self.expansion > 1 and self.materialization != "aggressive":
            raise ValueError(
                f"AugmentationOp[{self.name!r}]: expansion={self.expansion} "
                f"requires materialization='aggressive' (got "
                f"materialization={self.materialization!r})"
            )
        return self


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
