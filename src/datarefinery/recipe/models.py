# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Pydantic v2 models for `Recipe` and every section.

Plugin-specific operation parameters (`params`, `assertion`) are
intentionally typed as opaque mappings here; the recipe validator
(FR-2 check 18) cross-checks them against the declaring plugin's
`OperationSpec` in Story B.e.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    field_validator,
    model_validator,
)

Severity = Literal["error", "warning"]


class _Frozen(BaseModel):
    """Shared config: explicit fields, immutable instances."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SeedDerivationSpec(BaseModel):
    """G11 master-seed derivation form.

    YAML:
        seed:
          from: master

    Currently only ``from: master`` is recognized; resolution is
    performed at materialize time by ``recipe.seeds.resolve_seed``. The
    YAML key ``from`` is a Python keyword, so the field is exposed as
    ``from_`` with an alias.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        json_schema_serialization_defaults_required=True,
    )

    from_: Literal["master"] = Field(alias="from")


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


class AudioSource(InputSource):
    """Audio input source — the audio plugin's discriminated-union member.

    Story J.n.3 (design Q1): plugin-specific source *fields* are carried on
    a narrow subclass of the shared structural :class:`InputSource`, not on
    the base. The base's ``extra="forbid"`` therefore makes the audio-only
    ``target_sample_rate`` rejectable on a non-audio source — the structural
    enforcement of Finding A (audio fields never enter an image recipe's
    canonical bytes). The field is *version-governed* by ``plugin:audio``
    (the straddle rule) even though it serializes within the ``core`` Input
    structure; the audio plugin proper lands in Story J.o.
    """

    target_sample_rate: int = Field(gt=0)


class InputSection(_Frozen):
    # `SerializeAsAny` so a selected `AudioSource` serializes its *own* fields
    # (incl. `target_sample_rate`) instead of being narrowed to the declared
    # base `InputSource` schema — otherwise audio-only fields would be stripped
    # from canonical bytes and the discriminated-union representation would be
    # serialization-invisible.
    sources: list[SerializeAsAny[InputSource]]

    @field_validator("sources", mode="before")
    @classmethod
    def _select_source_subclass(cls, value: Any) -> Any:
        """Pick the plugin source subclass per the design Q1 union.

        The selection is *presence-based* (a source declaring an audio-only
        field is an :class:`AudioSource`) rather than keyed on ``type``: the
        concrete audio ``type`` vocabulary is the audio plugin's to define
        (Story J.o), and ``InputSource.type`` stays a free ``str`` (design
        § 0). Already-constructed model instances pass through untouched.
        """
        if not isinstance(value, list):
            return value
        selected: list[Any] = []
        for item in value:
            if isinstance(item, InputSource):
                selected.append(item)
            elif isinstance(item, dict) and "target_sample_rate" in item:
                selected.append(AudioSource.model_validate(item))
            else:
                selected.append(item)
        return selected


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
    seed: int | SeedDerivationSpec | None = None
    kind: Literal["uniform", "per_class"] = "uniform"
    splits: list[str] | None = None


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
    """G15 / Story I.x.1: flat-shape ``FilterOp`` mirroring every other
    section. ``op`` names the plugin operation; ``params`` carries its
    parameters; ``seed`` is the top-level seed source for stochastic
    filters (consistent with ``GenerationOp``/``AugmentationOp``).

    The v1 ``predicate: {op, ...rest, seed?}`` shape is migrated to v2
    by :func:`datarefinery.recipe.migrations.filters_reshape_v1_to_v2`
    inside the loader; the model itself only accepts v2 shape.
    """

    name: str
    op: str
    params: dict[str, Any] = Field(default_factory=dict)
    stages: list[Literal["pre_split", "post_split"]] = Field(default_factory=_default_filter_stages)
    splits: list[str] = Field(default_factory=list)
    seed: int | SeedDerivationSpec | None = None


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


_CORRUPTION_TAG_CANONICAL: frozenset[str] = frozenset({"corruption", "severity", "source_path"})


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
    preserve_original: bool  # no-implicit-defaults (J.n.4): required, no substitution
    tag_fields: list[str] | dict[str, str] = Field(
        default_factory=lambda: ["corruption", "severity", "source_path"]
    )

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
        if isinstance(self.tag_fields, dict):
            # G13 / Story I.u: dict form maps authored output-field name → canonical
            # tag name. Each value must be in the canonical set; each canonical may
            # appear at most once (one-to-one rename mapping).
            unknown = sorted(
                {v for v in self.tag_fields.values() if v not in _CORRUPTION_TAG_CANONICAL}
            )
            if unknown:
                raise ValueError(
                    f"imagecorruptions_apply: tag_fields dict values {unknown!r} are not "
                    f"in the canonical set {sorted(_CORRUPTION_TAG_CANONICAL)!r}"
                )
            values = list(self.tag_fields.values())
            if len(set(values)) != len(values):
                raise ValueError(
                    f"imagecorruptions_apply: tag_fields dict has duplicate canonical "
                    f"value(s) (got {self.tag_fields!r})"
                )
        return self


class GenerationOp(_Frozen):
    """G12 / Story I.x.2: flat-shape ``GenerationOp`` mirroring every
    other section. ``op`` names the plugin operation (lifted to top
    level from v1's ``name``-doubles-as-op convention); ``splits``
    replaces v1's ``applies_at``; ``output_schema`` accepts either a
    concrete ``dict[str, FieldSpec]`` or the literal ``"matches_input"``
    shorthand that the runtime expands to the input record shape plus
    declared ``tag_fields``.

    The v1 shape is auto-migrated by
    :func:`datarefinery.recipe.migrations.generation_reshape_v1_to_v2`
    inside the loader; the model itself only accepts v2 shape.
    """

    name: str
    op: str
    inputs: list[str]
    output_schema: dict[str, FieldSpec] | Literal["matches_input"]
    seed: int | SeedDerivationSpec
    splits: list[str] = Field(default_factory=lambda: ["train"])
    params: dict[str, Any] = Field(default_factory=dict)
    replace_input_records: bool = False


class KeyAssignment(_Frozen):
    field: str
    mapping: dict[str, str]


class SplitsSection(_Frozen):
    ratios: dict[str, float] | None = None
    key_assignment: KeyAssignment | None = None
    stratify_by: str | None = None
    seed: int | SeedDerivationSpec | None = None
    class_balance: str | dict[str, Any] | None = None
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
    seed: int | SeedDerivationSpec | None = None
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
    stage: VizStage
    mode: Literal["exploration", "reporting"]


# Closed vocabulary for the `stage` field on sinks (and, in a later
# story, visualizations — Story I.v / G7). The names are the
# point-in-pipeline at which records are captured: each value names the
# stage whose *output* the sink observes. See
# `phase-i-intermediate-artifact-persistence-spec.md` § 3.3 for the
# canonical mapping to `pipeline/runner.py:STAGE_NAMES`.
SinkStage = Literal[
    "post_InputContracts",
    "post_Filters",
    "post_Splits",
    "post_Generation",
    "post_Transformations",
    "post_Featurizations",
    "post_Augmentations",
    "post_OutputExpectations",
    "post_Visualizations",
]


# Closed vocabulary for `VisualizationOp.stage` (G7 / Story I.v). Each value
# names a snapshot of split records at the END of the named runner stage that
# a reporting-mode visualization can render against. Mirrors `SinkStage`'s
# grammar (`post_<Stage>`), but drops stages where viz dispatch would be
# functionally redundant (`post_OutputExpectations` / `post_Visualizations`
# don't change records) and adds the `post_pipeline` alias — the existing
# scaffolder default, equivalent to the final snapshot.
VizStage = Literal[
    "post_InputContracts",
    "post_Filters",
    "post_Splits",
    "post_Generation",
    "post_Transformations",
    "post_Augmentations",
    "post_Featurizations",
    "post_pipeline",
]


class SinkOp(_Frozen):
    """Disk-output declaration captured at materialize time.

    `name` is the on-disk root segment and the manifest key (unique
    within a recipe). `stage` selects the pipeline stage whose output
    the sink observes (closed vocabulary; see :data:`SinkStage`).
    `splits` defaults to None meaning *all splits known at the chosen
    stage*; passing a list restricts capture. `path_template` is
    interpreted relative to the cache instance directory.
    """

    name: str
    stage: SinkStage
    splits: list[str] | None = None
    field: str
    format: Literal["png_per_record", "npy_per_record"]
    path_template: str


class Recipe(_Frozen):
    schema_version: int = 3
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
    Sinks: list[SinkOp] = Field(default_factory=list)
    overlays: dict[str, dict[str, Any]] = Field(default_factory=dict)
    #: Story J.n.6 (design Q5): the sanctioned escape hatch for experimental,
    #: plugin-consumed parameters. Shape ``{<namespace>: {<key>: <value>}}``
    #: where ``namespace`` is the consuming plugin/owner. ``extra="forbid"`` is
    #: relaxed *only inside* a namespace (the inner mapping is a free
    #: ``dict[str, Any]``); every other recipe surface stays strict. The
    #: validator (check 28) refuses any namespace/key the bound plugin does not
    #: declare via :meth:`~datarefinery.plugins.base.Plugin.extension_keys`. An
    #: empty block collapses to the empty-segment marker, so the mechanism lands
    #: additively (no existing cache breaks). Extensions carry *declarative
    #: parameters* only — recipe-activated code is explicitly out of scope
    #: (spike memo § 6 trust boundary).
    extensions: dict[str, dict[str, Any]] = Field(default_factory=dict)
