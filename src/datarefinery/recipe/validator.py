# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-2 recipe validator framework + checks 1-22.

Each enumerated check from features.md becomes a `check_NN_<descriptor>`
function returning a `CheckResult`. `validate(recipe, plugin)` runs every
registered check and never short-circuits - a check that raises
unexpectedly is captured as a `fail` result rather than aborting the
whole report.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from datarefinery.plugins.base import Plugin
from datarefinery.recipe.loader import SUPPORTED_SCHEMA_VERSIONS
from datarefinery.recipe.models import (
    AugmentationOp,
    FeaturizationOp,
    FilterOp,
    Recipe,
    StatsFromInstanceSpec,
    TransformationOp,
)

CheckStatus = Literal["pass", "fail", "warn"]


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single FR-2 check."""

    check_id: int
    descriptor: str
    status: CheckStatus
    location: str | None
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """Aggregated results of `validate(recipe, plugin)`."""

    results: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return not any(r.status == "fail" for r in self.results)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if r.status == "fail")

    @property
    def warnings(self) -> tuple[CheckResult, ...]:
        return tuple(r for r in self.results if r.status == "warn")


def _passed(check_id: int, descriptor: str) -> CheckResult:
    return CheckResult(check_id, descriptor, "pass", None, "ok")


_NON_LIST_SECTIONS = ("Input", "Output", "Labels", "Splits", "SampleData")
_LIST_SECTIONS = (
    "InputContracts",
    "Filters",
    "Generation",
    "Transformations",
    "Augmentations",
    "Featurizations",
    "OutputExpectations",
    "Visualizations",
    "Sinks",
)


def _declared_sections(recipe: Recipe) -> list[str]:
    declared: list[str] = []
    for name in _NON_LIST_SECTIONS:
        if getattr(recipe, name) is not None:
            declared.append(name)
    for name in _LIST_SECTIONS:
        if getattr(recipe, name):  # non-empty
            declared.append(name)
    return declared


def check_01_schema_version_recognized(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "schema_version_recognized"
    if recipe.schema_version in SUPPORTED_SCHEMA_VERSIONS:
        return _passed(1, descriptor)
    return CheckResult(
        check_id=1,
        descriptor=descriptor,
        status="fail",
        location="schema_version",
        message=(
            f"unrecognized schema_version={recipe.schema_version}; "
            f"supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        ),
    )


def check_02_plugin_name_discoverable(recipe: Recipe, plugin: Plugin) -> CheckResult:
    descriptor = "plugin_name_discoverable"
    if plugin.name == recipe.plugin:
        return _passed(2, descriptor)
    return CheckResult(
        check_id=2,
        descriptor=descriptor,
        status="fail",
        location="plugin",
        message=(
            f"recipe declares plugin={recipe.plugin!r} but supplied plugin is {plugin.name!r}"
        ),
    )


def check_03_section_names_valid_for_plugin(recipe: Recipe, plugin: Plugin) -> CheckResult:
    descriptor = "section_names_valid_for_plugin"
    declared = _declared_sections(recipe)
    invalid = [s for s in declared if s not in plugin.supported_sections]
    if not invalid:
        return _passed(3, descriptor)
    return CheckResult(
        check_id=3,
        descriptor=descriptor,
        status="fail",
        location=",".join(invalid),
        message=(
            f"sections {invalid} not supported by plugin {plugin.name!r}; "
            f"supported: {sorted(plugin.supported_sections)}"
        ),
    )


def check_04_operations_declare_stages_and_splits(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "operations_declare_stages_and_splits"
    issues: list[str] = []
    for op in recipe.Filters:
        if "post_split" in op.stages and not op.splits:
            issues.append(f"Filters[{op.name!r}].splits is empty (required for post_split filters)")
    issues.extend(_empty_splits_issue("Transformations", recipe.Transformations))
    issues.extend(_empty_splits_issue("Augmentations", recipe.Augmentations))
    issues.extend(_empty_splits_issue("Featurizations", recipe.Featurizations))
    if not issues:
        return _passed(4, descriptor)
    return CheckResult(
        check_id=4,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def _empty_splits_issue(
    section: str,
    ops: Iterable[TransformationOp | AugmentationOp | FeaturizationOp | FilterOp],
) -> list[str]:
    return [f"{section}[{op.name!r}].splits is empty" for op in ops if not op.splits]


def check_05_augmentations_train_only(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "augmentations_train_only"
    issues: list[str] = []
    for op in recipe.Augmentations:
        non_train = [s for s in op.splits if s != "train"]
        if non_train:
            issues.append(f"Augmentations[{op.name!r}] declares non-train splits {non_train}")
    if not issues:
        return _passed(5, descriptor)
    return CheckResult(
        check_id=5,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_06_fit_on_train_uses_train_split(recipe: Recipe, plugin: Plugin) -> CheckResult:
    descriptor = "fit_on_train_uses_train_split"
    issues: list[str] = []
    for op in recipe.Transformations:
        spec = plugin.supported_operations.get(op.op)
        if spec is None:
            # Unknown operation — surfaced by check 18 in B.e.3.
            continue
        # `stats_from_instance` imports statistics from a sibling instance and
        # skips the local fit entirely (check 22 enforces fit_source is unset).
        if "stats_from_instance" in op.params:
            continue
        if spec.fit_on_train and op.fit_source != "train":
            issues.append(
                f"Transformations[{op.name!r}].fit_source={op.fit_source!r} "
                f"but operation {op.op!r} is fit-on-train (must declare 'train')"
            )
    if not issues:
        return _passed(6, descriptor)
    return CheckResult(
        check_id=6,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


_VALID_VARIANT_OVERRIDE_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "plugin",
        "seed",
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
        "Sinks",
    }
)


def _field_universe_pre_featurizations(recipe: Recipe) -> set[str]:
    return set(recipe.Output.record_schema.keys()) | {recipe.Labels.field}


def check_07_operations_reference_declared_fields(recipe: Recipe, plugin: Plugin) -> CheckResult:
    """Featurization inputs must reference declared/upstream-produced fields.

    Operations whose models do not expose explicit field references
    (`FilterOp`, `TransformationOp`, `AugmentationOp`) cannot be checked
    statically here; their `params` are opaque and are validated by
    check 18 against the plugin's `OperationSpec`.
    """
    del plugin
    descriptor = "operations_reference_declared_fields"
    issues: list[str] = []
    available = _field_universe_pre_featurizations(recipe)
    for op in recipe.Featurizations:
        missing = [name for name in op.inputs if name not in available]
        if missing:
            issues.append(
                f"Featurizations[{op.name!r}].inputs reference undeclared fields {missing}"
            )
        available.add(op.output_field)
    if not issues:
        return _passed(7, descriptor)
    return CheckResult(
        check_id=7,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_08_splits_partition_correctly(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "splits_partition_correctly"
    splits = recipe.Splits
    has_ratios = splits.ratios is not None
    has_keys = splits.key_assignment is not None
    # Source-declared partitions provide the partitioning surface; ratios
    # and key_assignment become optional under that mode (Story H.b).
    sources_partition = any(s.partition is not None for s in recipe.Input.sources)
    if has_ratios and has_keys:
        return CheckResult(
            check_id=8,
            descriptor=descriptor,
            status="fail",
            location="Splits",
            message="declare exactly one of 'ratios' or 'key_assignment', got both",
        )
    if not has_ratios and not has_keys and not sources_partition:
        return CheckResult(
            check_id=8,
            descriptor=descriptor,
            status="fail",
            location="Splits",
            message=(
                "must declare one of 'ratios', 'key_assignment', or "
                "InputSource.partition on every source"
            ),
        )
    if has_ratios:
        ratios = splits.ratios or {}
        negative = {k: v for k, v in ratios.items() if v < 0}
        if negative:
            return CheckResult(
                check_id=8,
                descriptor=descriptor,
                status="fail",
                location="Splits.ratios",
                message=f"ratios must be non-negative, got {negative}",
            )
        total = sum(ratios.values())
        if total > 1.0 + 1e-9:
            return CheckResult(
                check_id=8,
                descriptor=descriptor,
                status="fail",
                location="Splits.ratios",
                message=f"ratios sum to {total}, must be <= 1.0",
            )
    elif has_keys:  # key_assignment branch
        assert splits.key_assignment is not None  # narrow for mypy
        if not splits.key_assignment.mapping:
            return CheckResult(
                check_id=8,
                descriptor=descriptor,
                status="fail",
                location="Splits.key_assignment.mapping",
                message="key_assignment.mapping is empty",
            )
    # else: source partitions provide the partitioning surface;
    # check 20 enforces consistency.
    return _passed(8, descriptor)


def check_09_stratification_keys_exist(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "stratification_keys_exist"
    if recipe.Splits.stratify_by is None:
        return _passed(9, descriptor)
    available = _field_universe_pre_featurizations(recipe)
    available.update(op.output_field for op in recipe.Featurizations)
    if recipe.Splits.stratify_by in available:
        return _passed(9, descriptor)
    return CheckResult(
        check_id=9,
        descriptor=descriptor,
        status="fail",
        location="Splits.stratify_by",
        message=(
            f"stratify_by={recipe.Splits.stratify_by!r} not declared in "
            f"Output.record_schema, Labels, or Featurizations outputs"
        ),
    )


def check_10_class_imbalance_strategy_in_one_place(recipe: Recipe, plugin: Plugin) -> CheckResult:
    """Heuristic v1 check: a `class_balance` strategy on `Splits` and a
    Filter whose op is `class_balance` (or whose params name it) collide
    and must be resolved to one site per imbalance concern.
    """
    del plugin
    descriptor = "class_imbalance_strategy_in_one_place"
    class_balance = recipe.Splits.class_balance
    splits_handles = class_balance is not None
    filter_handles = any(
        op.op == "class_balance" or "class_balance" in op.params for op in recipe.Filters
    )
    if splits_handles and filter_handles:
        return CheckResult(
            check_id=10,
            descriptor=descriptor,
            status="fail",
            location=None,
            message=(
                "class-imbalance strategy declared in both 'Splits.class_balance' "
                "and a Filters op/params; consolidate to one site"
            ),
        )
    # G10 (Story I.s): the dict shape is a forward-declared MF-binding hint
    # `{strategy: <str>, applies_to: [<split>, …]}`. DataRefinery passes it
    # through verbatim and never resamples; this only validates the shape.
    if isinstance(class_balance, dict):
        shape_error = _class_balance_dict_error(class_balance, _defined_split_names(recipe))
        if shape_error is not None:
            return CheckResult(
                check_id=10,
                descriptor=descriptor,
                status="fail",
                location="Splits.class_balance",
                message=shape_error,
            )
    return _passed(10, descriptor)


def _class_balance_dict_error(value: dict[str, object], defined_splits: set[str]) -> str | None:
    """Return a failure message for a malformed class_balance dict, else None."""
    allowed = {"strategy", "applies_to"}
    unknown = set(value) - allowed
    if unknown:
        return (
            f"class_balance dict has unknown key(s) {sorted(unknown)}; allowed: {sorted(allowed)}"
        )
    strategy = value.get("strategy")
    if not isinstance(strategy, str) or not strategy:
        return "class_balance dict requires a non-empty string 'strategy'"
    applies_to = value.get("applies_to")
    if not isinstance(applies_to, list) or not all(isinstance(s, str) for s in applies_to):
        return "class_balance dict requires 'applies_to' as a list of split names"
    if not applies_to:
        return "class_balance dict 'applies_to' must be non-empty"
    bad = [s for s in applies_to if s not in defined_splits]
    if bad:
        return f"class_balance 'applies_to' references undefined splits {bad}"
    return None


def check_11_visualization_well_formed(recipe: Recipe, plugin: Plugin) -> CheckResult:
    """Mode is well-formed AND the declared stage's pipeline section is non-empty.

    Mode is already constrained at the model level (`Literal["exploration",
    "reporting"]`); kept as a documented FR-2 check so the report is exhaustive.

    G7 (Story I.v): viz `stage` is now a closed `VizStage` vocabulary. Stages
    whose corresponding recipe section is empty are bypassed — the snapshot
    would be identical to a prior stage, so the author's intent is unclear.
    Reject such recipes at validate time. Stages that always exist
    (`post_InputContracts`, `post_Filters`, `post_Splits`, `post_pipeline`)
    pass regardless of section content.
    """
    del plugin
    descriptor = "visualization_well_formed"
    issues: list[str] = []
    for op in recipe.Visualizations:
        if op.mode not in ("exploration", "reporting"):
            issues.append(f"Visualizations[{op.name!r}].mode={op.mode!r}")
        section_attr = _VIZ_STAGE_REQUIRES_SECTION.get(op.stage)
        if section_attr is not None and not getattr(recipe, section_attr):
            issues.append(
                f"Visualizations[{op.name!r}].stage={op.stage!r} but the "
                f"{section_attr!r} section is empty; the snapshot would be "
                f"identical to a prior stage. Declare at least one {section_attr} "
                f"op or pick a different stage."
            )
    if not issues:
        return _passed(11, descriptor)
    return CheckResult(
        check_id=11,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


#: Viz stages whose snapshot only differs from a prior stage's snapshot when
#: the corresponding recipe section has at least one op. Stages absent from
#: this map (`post_InputContracts`, `post_Filters`, `post_Splits`,
#: `post_pipeline`) are always valid viz targets regardless of section
#: content. Story I.v / G7.
_VIZ_STAGE_REQUIRES_SECTION: dict[str, str] = {
    "post_Generation": "Generation",
    "post_Transformations": "Transformations",
    "post_Augmentations": "Augmentations",
    "post_Featurizations": "Featurizations",
}


def check_12_variants_reference_declared_sections(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "variants_reference_declared_sections"
    issues: list[str] = []
    for variant_name, overlay in recipe.variants.items():
        for key in overlay:
            if key not in _VALID_VARIANT_OVERRIDE_KEYS:
                issues.append(f"variant {variant_name!r} overrides unknown section {key!r}")
    if not issues:
        return _passed(12, descriptor)
    return CheckResult(
        check_id=12,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_13_labels_resolvable(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "labels_resolvable"
    if recipe.Labels.field not in recipe.Output.record_schema:
        return CheckResult(
            check_id=13,
            descriptor=descriptor,
            status="fail",
            location="Labels.field",
            message=(
                f"Labels.field={recipe.Labels.field!r} not declared in "
                f"Output.record_schema (declared fields: "
                f"{sorted(recipe.Output.record_schema.keys())})"
            ),
        )
    return _passed(13, descriptor)


def _defined_split_names(recipe: Recipe) -> set[str]:
    splits = recipe.Splits
    if splits.ratios:
        return set(splits.ratios.keys())
    if splits.key_assignment:
        return set(splits.key_assignment.mapping.values())
    return set()


def check_14_generation_output_schema_consistent(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "generation_output_schema_consistent"
    issues: list[str] = []
    record_schema = recipe.Output.record_schema
    for op in recipe.Generation:
        # G12 / Story I.x.2: ``"matches_input"`` is resolved at materialize
        # time from ``Output.record_schema`` (+ declared tag fields), so it
        # is structurally consistent by construction; skip the per-field check.
        if op.output_schema == "matches_input":
            continue
        for field_name, field_spec in op.output_schema.items():
            target = record_schema.get(field_name)
            if target is None:
                issues.append(
                    f"Generation[{op.name!r}] produces field {field_name!r} "
                    f"not in Output.record_schema"
                )
                continue
            if target.dtype != field_spec.dtype:
                issues.append(
                    f"Generation[{op.name!r}].{field_name!r} dtype "
                    f"{field_spec.dtype!r} != Output.record_schema "
                    f"{target.dtype!r}"
                )
            if target.shape != field_spec.shape:
                issues.append(
                    f"Generation[{op.name!r}].{field_name!r} shape "
                    f"{field_spec.shape!r} != Output.record_schema "
                    f"{target.shape!r}"
                )
    if not issues:
        return _passed(14, descriptor)
    return CheckResult(
        check_id=14,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_15_split_references_defined(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "split_references_defined"
    defined = _defined_split_names(recipe)
    issues: list[str] = []

    def _check(section: str, op_name: str, refs: list[str]) -> None:
        bad = [s for s in refs if s not in defined]
        if bad:
            issues.append(f"{section}[{op_name!r}] references undefined splits {bad}")

    for filt in recipe.Filters:
        _check("Filters", filt.name, filt.splits)
    for tx in recipe.Transformations:
        _check("Transformations", tx.name, tx.splits)
    for aug in recipe.Augmentations:
        _check("Augmentations", aug.name, aug.splits)
    for feat in recipe.Featurizations:
        _check("Featurizations", feat.name, feat.splits)
    for gen in recipe.Generation:
        _check("Generation", gen.name, gen.splits)

    if not issues:
        return _passed(15, descriptor)
    return CheckResult(
        check_id=15,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_16_sample_data_strict_subset(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "sample_data_strict_subset"
    if recipe.SampleData is None:
        return _passed(16, descriptor)
    selector = recipe.SampleData.selector
    has_n = selector.n is not None
    has_fraction = selector.fraction is not None
    if has_n and has_fraction:
        return CheckResult(
            check_id=16,
            descriptor=descriptor,
            status="fail",
            location="SampleData.selector",
            message="set exactly one of 'n' or 'fraction', got both",
        )
    if not has_n and not has_fraction:
        return CheckResult(
            check_id=16,
            descriptor=descriptor,
            status="fail",
            location="SampleData.selector",
            message="must declare 'n' or 'fraction'",
        )
    if has_n and selector.n is not None and selector.n < 1:
        return CheckResult(
            check_id=16,
            descriptor=descriptor,
            status="fail",
            location="SampleData.selector.n",
            message=f"n must be >= 1 for a strict subset, got {selector.n}",
        )
    if has_fraction and selector.fraction is not None and not (0.0 < selector.fraction < 1.0):
        return CheckResult(
            check_id=16,
            descriptor=descriptor,
            status="fail",
            location="SampleData.selector.fraction",
            message=(f"fraction must be in (0, 1) for a strict subset, got {selector.fraction}"),
        )
    # G14 (Story I.r): kind / splits coherence. Schema-only — the selector
    # is not yet honored at runtime (see stories.md Story I.r.0 spike); these
    # checks keep an author from declaring an unsatisfiable selector.
    if selector.kind == "per_class" and not any(not src.unlabeled for src in recipe.Input.sources):
        return CheckResult(
            check_id=16,
            descriptor=descriptor,
            status="fail",
            location="SampleData.selector.kind",
            message=(
                "kind 'per_class' requires a label source, but every Input source "
                "is unlabeled; declare at least one labeled source or use kind 'uniform'"
            ),
        )
    if selector.splits is not None:
        defined = _defined_split_names(recipe)
        bad_splits = [s for s in selector.splits if s not in defined]
        if bad_splits:
            return CheckResult(
                check_id=16,
                descriptor=descriptor,
                status="fail",
                location="SampleData.selector.splits",
                message=f"references undefined splits {bad_splits}",
            )
    return _passed(16, descriptor)


def check_17_contract_fields_exist_at_stage(recipe: Recipe, plugin: Plugin) -> CheckResult:
    del plugin
    descriptor = "contract_fields_exist_at_stage"
    available = set(recipe.Output.record_schema.keys()) | {recipe.Labels.field}
    issues: list[str] = []
    for contract in recipe.InputContracts:
        if contract.field is not None and contract.field not in available:
            issues.append(f"InputContracts references undeclared field {contract.field!r}")
    for expectation in recipe.OutputExpectations:
        if expectation.field is not None and expectation.field not in available:
            issues.append(f"OutputExpectations references undeclared field {expectation.field!r}")
    if not issues:
        return _passed(17, descriptor)
    return CheckResult(
        check_id=17,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_18_plugin_operation_params_validate(recipe: Recipe, plugin: Plugin) -> CheckResult:
    """Cross-check each operation's `params` against the plugin's
    declared `OperationSpec`. v1 enforces operation existence,
    required-parameter presence, and rejection of unknown parameters.
    Type-checking parameter values lands when the runner does the
    materialize side of FR-3.
    """
    descriptor = "plugin_operation_params_validate"
    issues: list[str] = []

    def _validate(section: str, op_name: str, op_kind: str, params: dict[str, object]) -> None:
        spec = plugin.supported_operations.get(op_kind)
        if spec is None:
            issues.append(
                f"{section}[{op_name!r}].op={op_kind!r} not declared by plugin {plugin.name!r}"
            )
            return
        for required_name, param_spec in spec.parameters.items():
            if param_spec.required and required_name not in params:
                issues.append(
                    f"{section}[{op_name!r}] missing required param "
                    f"{required_name!r} (type={param_spec.type!r})"
                )
        for given in params:
            if given not in spec.parameters:
                issues.append(f"{section}[{op_name!r}] has unexpected param {given!r}")

    for tx in recipe.Transformations:
        _validate("Transformations", tx.name, tx.op, tx.params)
    for aug in recipe.Augmentations:
        _validate("Augmentations", aug.name, aug.op, aug.params)
    for feat in recipe.Featurizations:
        _validate("Featurizations", feat.name, feat.op, feat.params)
    for viz in recipe.Visualizations:
        _validate("Visualizations", viz.name, viz.op, viz.params)
    for gen in recipe.Generation:
        # Story I.x.2 / G12: ``op`` is now a top-level field.
        _validate("Generation", gen.name, gen.op, gen.params)

    if not issues:
        return _passed(18, descriptor)
    return CheckResult(
        check_id=18,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_19_label_from_spec_resolves(recipe: Recipe, plugin: Plugin) -> CheckResult:
    """Validate `InputSource.label_from` against the source's `type` and
    against the on-disk manifest file (when present).

    Cross-rules:
    - `image_folder` + `label_from` set → fail (one source of truth).
    - `image_flat` + `label_from` unset → fail (no other label source).

    When `label_from` is set:
    - manifest file exists and is non-empty;
    - column-name references resolve (against the file's header row, or
      against `header` when provided);
    - `header` (when provided) column count matches the file's actual
      column count;
    - `by_id`: no duplicate id values in the manifest;
    - `by_row_order`: row count equals the input source's enumerated
      record count, when the source path is a readable directory.

    Plugin-specific check: only applies to `image_classification`.
    """
    del plugin
    descriptor = "label_from_spec_resolves"
    if recipe.plugin != "image_classification":
        return _passed(19, descriptor)
    issues: list[str] = []
    for src in recipe.Input.sources:
        location = f"Input.sources[{src.name!r}]"
        if src.type == "image_folder" and src.label_from is not None:
            issues.append(
                f"{location}: type='image_folder' with label_from set; "
                f"image_folder takes labels from class subdirectories"
            )
            continue
        if src.type == "image_flat" and src.label_from is None and not src.unlabeled:
            issues.append(
                f"{location}: type='image_flat' but no label_from declared; "
                f"flat sources require a sidecar manifest (or set unlabeled=true "
                f"for inference-only partitions)"
            )
            continue
        if src.label_from is None:
            continue
        # label_from is set; validate the manifest.
        spec = src.label_from
        manifest_path = Path(spec.path)
        if not manifest_path.is_file():
            issues.append(f"{location}.label_from.path: file not found at {manifest_path!s}")
            continue
        try:
            columns, data_rows = _read_manifest_for_validation(spec)
        except _ManifestValidationError as exc:
            issues.append(f"{location}.label_from: {exc}")
            continue
        if spec.label_field not in columns:
            issues.append(
                f"{location}.label_from.label_field: {spec.label_field!r} "
                f"not in declared columns {columns!r}"
            )
        if spec.join == "by_id":
            if spec.id_field is None or spec.id_field not in columns:
                issues.append(
                    f"{location}.label_from.id_field: {spec.id_field!r} "
                    f"not in declared columns {columns!r}"
                )
            elif spec.id_field in columns:
                id_idx = columns.index(spec.id_field)
                ids = [row[id_idx] for row in data_rows]
                seen: set[str] = set()
                dupes: set[str] = set()
                for rid in ids:
                    if rid in seen:
                        dupes.add(rid)
                    seen.add(rid)
                if dupes:
                    issues.append(
                        f"{location}.label_from: duplicate ids in manifest: {sorted(dupes)!r}"
                    )
        elif spec.join == "by_row_order":
            source_root = Path(src.path)
            if source_root.is_dir():
                from datarefinery.pipeline.inputs import _enumerate_flat_images

                expected = len(_enumerate_flat_images(source_root))
                if len(data_rows) != expected:
                    issues.append(
                        f"{location}.label_from: by_row_order requires equal counts; "
                        f"manifest has {len(data_rows)} rows but source has {expected} images"
                    )
    if not issues:
        return _passed(19, descriptor)
    return CheckResult(
        check_id=19,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


class _ManifestValidationError(Exception):
    """Internal: signals that the manifest can't be parsed for validation."""


def _read_manifest_for_validation(
    spec: object,
) -> tuple[list[str], list[list[str]]]:
    """Validator-side manifest reader.

    Same rules as the loader's `_read_manifest_rows`, but raises a
    validator-local exception so each per-source issue can be collected
    into the aggregated check result instead of aborting the whole run.
    """
    import csv

    from datarefinery.recipe.models import LabelFromSpec

    assert isinstance(spec, LabelFromSpec)
    manifest_path = Path(spec.path)
    with manifest_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        all_rows = [row for row in reader if row]
    if not all_rows:
        raise _ManifestValidationError(f"manifest {manifest_path!s} is empty")
    if spec.header is not None:
        columns = list(spec.header)
        data_rows = all_rows
        # When header is recipe-supplied, every row must match its column count.
        file_col_count = max(len(row) for row in all_rows)
        if file_col_count != len(columns):
            raise _ManifestValidationError(
                f"header declares {len(columns)} columns but manifest has "
                f"{file_col_count} columns in at least one row"
            )
    else:
        columns = all_rows[0]
        data_rows = all_rows[1:]
    for i, row in enumerate(data_rows):
        if len(row) != len(columns):
            raise _ManifestValidationError(
                f"manifest row {i} has {len(row)} columns but header has {len(columns)}"
            )
    return columns, data_rows


_PARTITION_PLUGINS = frozenset({"image_classification"})


_SAMPLE_TAG_OPS = frozenset({"sample_per_class", "sample_per_class_fractional"})


def _sample_filter_labels(recipe: Recipe) -> set[str]:
    """Tag labels emitted by non-destructive sample_per_class* filters.

    A `sample_per_class` / `sample_per_class_fractional` filter with a
    `label` param tags the chosen records (in `sample_per_class_tags`)
    rather than dropping the rest. `Splits.applies_to` may target such
    a label (G1 / Story I.t).
    """
    labels: set[str] = set()
    for op in recipe.Filters:
        if op.op in _SAMPLE_TAG_OPS:
            label = op.params.get("label")
            if isinstance(label, str):
                labels.add(label)
    return labels


def check_20_partitions_consistent(recipe: Recipe, plugin: Plugin) -> CheckResult:
    """Validate `InputSource.partition` + `SplitsSection.applies_to`.

    Cross-rules:
    - All-or-nothing: if any source declares `partition`, every source must.
    - `Output.record_schema` must not declare a `partition` field (reserved
      for the loader-stamped value, analogous to `record_id`).
    - `Splits.applies_to` (when set) must reference a partition declared
      by some source.
    - `Splits.ratios` keys (when set with `applies_to`) must not collide
      with sibling partition names.
    - When source partitions are declared but `Splits.applies_to` is unset,
      `Splits.ratios` must be empty (or omitted) — otherwise the recipe is
      simultaneously asking to honor sources and re-shuffle globally.

    Plugin-specific: only applies to plugins whose loader stamps `partition`
    (initially `image_classification`); for other plugins this check
    short-circuits as `pass`.
    """
    del plugin
    descriptor = "partitions_consistent"
    if recipe.plugin not in _PARTITION_PLUGINS:
        return _passed(20, descriptor)
    issues: list[str] = []
    sources = recipe.Input.sources
    declared = [s for s in sources if s.partition is not None]
    if 0 < len(declared) < len(sources):
        names = [s.name for s in sources if s.partition is None]
        issues.append(
            f"Input.sources: some sources declare 'partition' and some do not "
            f"(missing on {names!r}); declare on all or none"
        )
    if "partition" in recipe.Output.record_schema:
        issues.append(
            "Output.record_schema declares a 'partition' field; the name is "
            "reserved for the loader-stamped partition value (see Story H.b)"
        )

    partition_names = {s.partition for s in declared if s.partition is not None}
    # G1 (Story I.t): applies_to may instead name a tag emitted by a
    # sample_per_class / sample_per_class_fractional filter (its `label`
    # param). Such records carry the tag in `sample_per_class_tags`; the
    # Splits stage sub-partitions the tagged records and passes the others
    # through under their own tag name.
    tag_labels = _sample_filter_labels(recipe)
    splits_section = recipe.Splits
    applies_to = splits_section.applies_to
    if applies_to is not None:
        if applies_to in partition_names:
            if splits_section.ratios:
                sub_names = set(splits_section.ratios.keys())
                siblings = partition_names - {applies_to}
                collision = sub_names & siblings
                if collision:
                    issues.append(
                        f"Splits.ratios produces split name(s) {sorted(collision)!r} that "
                        f"collide with sibling partition(s)"
                    )
        elif applies_to not in tag_labels:
            issues.append(
                f"Splits.applies_to={applies_to!r} matches no source partition "
                f"{sorted(partition_names)!r} and no sample_per_class / "
                f"sample_per_class_fractional filter label {sorted(tag_labels)!r}"
            )
    else:
        if partition_names and splits_section.ratios:
            issues.append(
                "Input.sources declare 'partition' but Splits.applies_to is unset "
                "while Splits.ratios is non-empty; either omit ratios (to honor "
                "source partitions verbatim) or set applies_to"
            )

    if not issues:
        return _passed(20, descriptor)
    return CheckResult(
        check_id=20,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def unlabeled_split_names(recipe: Recipe) -> set[str]:
    """Names of splits that materialize without labels.

    A split is unlabeled when it is either (a) a source partition
    declared with ``unlabeled: true`` and not selected for sub-partitioning
    by ``Splits.applies_to``, or (b) a sub-split produced by sub-partitioning
    such an unlabeled partition. Source partitions selected for
    sub-partitioning lose their original name in favor of the
    ``Splits.ratios`` keys; those sub-splits inherit unlabeled-ness.
    """
    unlabeled_partitions = {
        s.partition for s in recipe.Input.sources if s.unlabeled and s.partition is not None
    }
    if not unlabeled_partitions:
        return set()
    applies_to = recipe.Splits.applies_to
    ratios = recipe.Splits.ratios or {}
    if applies_to in unlabeled_partitions and ratios:
        # The named partition is exploded into sub-splits, all unlabeled.
        return (unlabeled_partitions - {applies_to}) | set(ratios.keys())
    return unlabeled_partitions


def check_21_unlabeled_consistency(recipe: Recipe, plugin: Plugin) -> CheckResult:
    """Validate ``InputSource.unlabeled`` cross-section interactions.

    Cross-rules:
    - ``unlabeled: true`` requires ``type == "image_flat"`` (v1 restriction;
      ``image_folder`` derives labels from class subdirectories so the
      combination is contradictory). Model-level validators already
      enforce that ``unlabeled`` requires ``partition`` and forbids
      ``label_from``; this check covers the type rule.
    - ``Splits.stratify_by`` is incompatible with
      ``Splits.applies_to == <unlabeled-partition>`` (cannot stratify by
      a field that does not exist on the records).
    - Filters using ``filter_by_label`` must not target an unlabeled split.
    - Featurizations whose op is ``label_from_path`` or whose ``inputs``
      reference the recipe's label field must not target an unlabeled
      split (label is absent from those records).

    Plugin-specific: only applies to plugins whose loader honors
    ``unlabeled`` (initially ``image_classification``); for other plugins
    this check short-circuits as ``pass``.
    """
    del plugin
    descriptor = "unlabeled_consistency"
    if recipe.plugin not in _PARTITION_PLUGINS:
        return _passed(21, descriptor)
    issues: list[str] = []
    for src in recipe.Input.sources:
        if src.unlabeled and src.type != "image_flat":
            issues.append(
                f"Input.sources[{src.name!r}]: unlabeled=true requires "
                f"type='image_flat' in v1 (got {src.type!r}); image_folder "
                f"derives labels from class subdirectories"
            )

    unlabeled_splits = unlabeled_split_names(recipe)
    applies_to = recipe.Splits.applies_to
    unlabeled_partitions = {
        s.partition for s in recipe.Input.sources if s.unlabeled and s.partition is not None
    }

    if recipe.Splits.stratify_by is not None and applies_to in unlabeled_partitions:
        issues.append(
            f"Splits.stratify_by={recipe.Splits.stratify_by!r} is incompatible "
            f"with applies_to={applies_to!r} (an unlabeled partition has no "
            f"label field to stratify by)"
        )

    label_field = recipe.Labels.field
    for filt in recipe.Filters:
        if filt.op == "filter_by_label":
            bad = [s for s in filt.splits if s in unlabeled_splits]
            if bad:
                issues.append(
                    f"Filters[{filt.name!r}] uses 'filter_by_label' on unlabeled "
                    f"split(s) {sorted(bad)!r}; the label field is absent there"
                )
    for feat in recipe.Featurizations:
        reads_label = feat.op == "label_from_path" or label_field in feat.inputs
        if reads_label:
            bad = [s for s in feat.splits if s in unlabeled_splits]
            if bad:
                issues.append(
                    f"Featurizations[{feat.name!r}] (op={feat.op!r}) reads/produces "
                    f"label but targets unlabeled split(s) {sorted(bad)!r}"
                )

    if not issues:
        return _passed(21, descriptor)
    return CheckResult(
        check_id=21,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_22_stats_from_instance_mutually_exclusive_with_fit_source(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    """FR-TRANS-1: `stats_from_instance` and `fit_source` are mutually exclusive.

    On a fit-on-train transformation, exactly one of the two must be set:
    `fit_source` (local fit) or `stats_from_instance` (import from sibling
    instance). Declaring both is contradictory; declaring neither leaves
    the apply path without statistics. The `stats_from_instance` value is
    additionally parsed against `StatsFromInstanceSpec` so a misshapen
    spec surfaces here rather than at materialize time.
    """
    del plugin
    descriptor = "stats_from_instance_mutually_exclusive_with_fit_source"
    issues: list[str] = []
    for op in recipe.Transformations:
        raw = op.params.get("stats_from_instance")
        if raw is None:
            continue
        if op.fit_source is not None:
            issues.append(
                f"Transformations[{op.name!r}]: declares both 'fit_source' and "
                f"'stats_from_instance' (mutually exclusive — pick one)"
            )
        if not isinstance(raw, dict):
            issues.append(
                f"Transformations[{op.name!r}].params['stats_from_instance']: "
                f"must be a mapping with 'recipe' and 'op_id' (got {type(raw).__name__})"
            )
            continue
        try:
            StatsFromInstanceSpec.model_validate(raw)
        except Exception as exc:
            issues.append(f"Transformations[{op.name!r}].params['stats_from_instance']: {exc}")
    if not issues:
        return _passed(22, descriptor)
    return CheckResult(
        check_id=22,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_23_featurization_output_field_loader_collision(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    """G4 (dependency-gaps-v0.16.0.md): Featurization `output_field` must not
    collide with a field the loader stamps on every record.

    The image_classification loader (`pipeline/inputs.py`) writes these
    fields on every loaded record:

    - ``record_id`` (always)
    - ``image`` (always)
    - ``path`` (always)
    - ``label`` — when ``Labels.source.kind == "direct"`` and a label source
      is available (parent dir for ``image_folder``; sidecar manifest via
      ``label_from`` for ``image_flat``).
    - ``partition`` — when any ``InputSource.partition`` is declared.

    A Featurization declaring `output_field` equal to any of these is
    caught at materialize time by ``pipeline/stages/featurizations.py``
    with a "collides with an existing field" error. This check surfaces
    the same collision at validate time so the failure is reported
    before any loading work runs.
    """
    del plugin
    descriptor = "featurization_output_field_loader_collision"
    issues: list[str] = []

    # Loader-stamped field set, derived from the recipe's Input/Labels config.
    # Keep in sync with the loader at `pipeline/inputs.py` — the runtime
    # collision check at `pipeline/stages/featurizations.py` is the
    # authoritative second-line defense.
    reserved: set[str] = {"record_id", "image", "path"}
    if recipe.Labels.source.kind == "direct":
        # `direct` labels are populated by the loader when a label source
        # exists. For image_folder the parent dir is the label; for
        # image_flat the sidecar `label_from` manifest is the source.
        any_labeled_source = any(
            (src.type == "image_folder" or src.label_from is not None) and not src.unlabeled
            for src in recipe.Input.sources
        )
        if any_labeled_source:
            reserved.add(recipe.Labels.field)
    if any(src.partition is not None for src in recipe.Input.sources):
        reserved.add("partition")

    for feat in recipe.Featurizations:
        if feat.output_field in reserved:
            issues.append(
                f"Featurizations[{feat.name!r}].output_field {feat.output_field!r} "
                f"collides with a field stamped by the input loader "
                f"(reserved: {sorted(reserved)!r}). Either rename "
                f"output_field, or remove the loader-side source for "
                f"{feat.output_field!r} (e.g., for label collisions: drop "
                f"the InputSource.label_from sidecar or change "
                f"Labels.source.kind from 'direct' to 'derived')."
            )

    if not issues:
        return _passed(23, descriptor)
    return CheckResult(
        check_id=23,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_24_sinks(recipe: Recipe, plugin: Plugin) -> CheckResult:
    """Sink-section validation (Story I.d).

    Checks: sink names unique within the recipe; path templates parse
    cleanly; templates do not escape the instance directory (`..` or
    absolute paths rejected); the referenced `field` appears in the
    recipe's known-field universe (loader-stamped fields + Output
    record schema + Generation outputs + Featurization output fields);
    each `splits` entry names a defined split.

    Per spec § 8 (`phase-i-intermediate-artifact-persistence-spec.md`),
    v1 does NOT enforce that the field exists *at the chosen stage* —
    a `post_Filters` sink legitimately captures pre-normalize uint8
    that's not in the final cached `Output.record_schema` shape. The
    runtime path resolver and the writer raise `MaterializeError` if a
    referenced field genuinely is missing at materialize time.
    """
    del plugin
    descriptor = "sinks"
    issues: list[str] = []
    if not recipe.Sinks:
        return _passed(24, descriptor)

    # Local imports keep `recipe/` free of a `pipeline/` import cycle
    # in the common case where this check is skipped.
    from datarefinery.pipeline.sinks.template import (
        parse_template,
        template_escapes_root,
    )

    # Name uniqueness.
    seen_names: dict[str, int] = {}
    for sink in recipe.Sinks:
        seen_names[sink.name] = seen_names.get(sink.name, 0) + 1
    duplicates = sorted(name for name, count in seen_names.items() if count > 1)
    if duplicates:
        issues.append(f"duplicate sink names {duplicates!r} (must be unique within a recipe)")

    # Field universe — loader-stamped + record schema + Generation outputs +
    # Featurization output fields. Augmentations / Transformations don't
    # introduce new fields (they mutate values on existing fields).
    field_universe: set[str] = {"record_id", "image", "path", recipe.Labels.field}
    if any(s.partition is not None for s in recipe.Input.sources):
        field_universe.add("partition")
    field_universe.update(recipe.Output.record_schema.keys())
    for gen in recipe.Generation:
        if isinstance(gen.output_schema, dict):
            field_universe.update(gen.output_schema.keys())
        # The "matches_input" shorthand resolves to Output.record_schema
        # at runtime; all those keys are already in the universe above.
    for feat in recipe.Featurizations:
        field_universe.add(feat.output_field)

    defined_splits = _defined_split_names(recipe)

    for sink in recipe.Sinks:
        try:
            parse_template(sink.path_template)
        except ValueError as exc:
            issues.append(f"Sinks[{sink.name!r}].path_template: {exc}")

        if template_escapes_root(sink.path_template):
            issues.append(
                f"Sinks[{sink.name!r}].path_template {sink.path_template!r} "
                f"escapes the instance directory (absolute path or '..' traversal)"
            )

        if sink.field not in field_universe:
            issues.append(
                f"Sinks[{sink.name!r}].field {sink.field!r} not in the recipe's "
                f"known fields ({sorted(field_universe)}); rename, or add it "
                f"to Output.record_schema / a Generation output / a Featurization output."
            )

        if sink.splits is not None:
            bad = [s for s in sink.splits if s not in defined_splits]
            if bad:
                issues.append(f"Sinks[{sink.name!r}].splits references undefined splits {bad}")

    if not issues:
        return _passed(24, descriptor)
    return CheckResult(
        check_id=24,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def _known_field_universe(recipe: Recipe) -> set[str]:
    """Fields a recipe is known to produce, for field-reference checks.

    Loader-stamped fields + ``Output.record_schema`` + Generation
    ``output_schema`` keys + Generation ``tag_fields`` params +
    Featurization ``output_field``s. Mirrors the universe used by
    check 24 (sinks), extended with Generation tag-field params (those
    introduce fields like ``corruption`` / ``severity`` that are not
    necessarily declared in ``output_schema``).
    """
    universe: set[str] = {"record_id", "image", "path", recipe.Labels.field}
    if any(s.partition is not None for s in recipe.Input.sources):
        universe.add("partition")
    universe.update(recipe.Output.record_schema.keys())
    for gen in recipe.Generation:
        if isinstance(gen.output_schema, dict):
            universe.update(gen.output_schema.keys())
        # The "matches_input" shorthand resolves to Output.record_schema
        # (already in the universe above) at materialize time.
        tag_fields = gen.params.get("tag_fields")
        if isinstance(tag_fields, list):
            universe.update(str(t) for t in tag_fields)
    for feat in recipe.Featurizations:
        universe.add(feat.output_field)
    return universe


def check_25_visualization_group_by_resolvable(recipe: Recipe, plugin: Plugin) -> CheckResult:
    """G17 (Story I.p): a Visualization's ``group_by`` param must name a
    field the recipe is known to produce.

    Keys on the ``group_by`` param rather than a specific op name so any
    visualization that grows the param is covered. The field universe is
    the same one check 24 uses for sinks, extended with Generation
    ``tag_fields``.
    """
    del plugin
    descriptor = "visualization_group_by_resolvable"
    issues: list[str] = []
    universe = _known_field_universe(recipe)
    for viz in recipe.Visualizations:
        group_by = viz.params.get("group_by")
        if group_by is None:
            continue
        if not isinstance(group_by, str):
            issues.append(
                f"Visualizations[{viz.name!r}].params['group_by'] must be a string "
                f"(got {type(group_by).__name__})"
            )
        elif group_by not in universe:
            issues.append(
                f"Visualizations[{viz.name!r}].params['group_by'] {group_by!r} not in "
                f"the recipe's known fields ({sorted(universe)}); name a field in "
                f"Output.record_schema, a Generation output / tag_field, or a "
                f"Featurization output."
            )
    if not issues:
        return _passed(25, descriptor)
    return CheckResult(
        check_id=25,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


_CHECKS: tuple[tuple[int, str, Callable[[Recipe, Plugin], CheckResult]], ...] = (
    (1, "schema_version_recognized", check_01_schema_version_recognized),
    (2, "plugin_name_discoverable", check_02_plugin_name_discoverable),
    (
        3,
        "section_names_valid_for_plugin",
        check_03_section_names_valid_for_plugin,
    ),
    (
        4,
        "operations_declare_stages_and_splits",
        check_04_operations_declare_stages_and_splits,
    ),
    (5, "augmentations_train_only", check_05_augmentations_train_only),
    (
        6,
        "fit_on_train_uses_train_split",
        check_06_fit_on_train_uses_train_split,
    ),
    (
        7,
        "operations_reference_declared_fields",
        check_07_operations_reference_declared_fields,
    ),
    (8, "splits_partition_correctly", check_08_splits_partition_correctly),
    (9, "stratification_keys_exist", check_09_stratification_keys_exist),
    (
        10,
        "class_imbalance_strategy_in_one_place",
        check_10_class_imbalance_strategy_in_one_place,
    ),
    (11, "visualization_well_formed", check_11_visualization_well_formed),
    (
        12,
        "variants_reference_declared_sections",
        check_12_variants_reference_declared_sections,
    ),
    (13, "labels_resolvable", check_13_labels_resolvable),
    (
        14,
        "generation_output_schema_consistent",
        check_14_generation_output_schema_consistent,
    ),
    (15, "split_references_defined", check_15_split_references_defined),
    (16, "sample_data_strict_subset", check_16_sample_data_strict_subset),
    (
        17,
        "contract_fields_exist_at_stage",
        check_17_contract_fields_exist_at_stage,
    ),
    (
        18,
        "plugin_operation_params_validate",
        check_18_plugin_operation_params_validate,
    ),
    (
        19,
        "label_from_spec_resolves",
        check_19_label_from_spec_resolves,
    ),
    (
        20,
        "partitions_consistent",
        check_20_partitions_consistent,
    ),
    (
        21,
        "unlabeled_consistency",
        check_21_unlabeled_consistency,
    ),
    (
        22,
        "stats_from_instance_mutually_exclusive_with_fit_source",
        check_22_stats_from_instance_mutually_exclusive_with_fit_source,
    ),
    (
        23,
        "featurization_output_field_loader_collision",
        check_23_featurization_output_field_loader_collision,
    ),
    (24, "sinks", check_24_sinks),
    (
        25,
        "visualization_group_by_resolvable",
        check_25_visualization_group_by_resolvable,
    ),
)


def validate(recipe: Recipe, plugin: Plugin) -> ValidationReport:
    """Run every registered FR-2 check; never short-circuit on first failure."""
    results: list[CheckResult] = []
    for check_id, descriptor, fn in _CHECKS:
        try:
            result = fn(recipe, plugin)
        except Exception as exc:  # surface bugs in checks as failures
            result = CheckResult(
                check_id=check_id,
                descriptor=descriptor,
                status="fail",
                location=None,
                message=f"check raised: {type(exc).__name__}: {exc}",
            )
        results.append(result)
    return ValidationReport(results=tuple(results))
