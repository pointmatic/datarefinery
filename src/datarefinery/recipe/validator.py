# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-2 recipe validator framework + checks 1-18.

Each enumerated check from features.md becomes a `check_NN_<descriptor>`
function returning a `CheckResult`. `validate(recipe, plugin)` runs every
registered check and never short-circuits - a check that raises
unexpectedly is captured as a `fail` result rather than aborting the
whole report.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from datarefinery.plugins.base import Plugin
from datarefinery.recipe.loader import SUPPORTED_SCHEMA_VERSIONS
from datarefinery.recipe.models import (
    AugmentationOp,
    FeaturizationOp,
    FilterOp,
    Recipe,
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


def check_01_schema_version_recognized(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
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


def check_02_plugin_name_discoverable(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    descriptor = "plugin_name_discoverable"
    if plugin.name == recipe.plugin:
        return _passed(2, descriptor)
    return CheckResult(
        check_id=2,
        descriptor=descriptor,
        status="fail",
        location="plugin",
        message=(
            f"recipe declares plugin={recipe.plugin!r} but supplied plugin "
            f"is {plugin.name!r}"
        ),
    )


def check_03_section_names_valid_for_plugin(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
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


def check_04_operations_declare_stages_and_splits(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    del plugin
    descriptor = "operations_declare_stages_and_splits"
    issues: list[str] = []
    for op in recipe.Filters:
        if "post_split" in op.stages and not op.splits:
            issues.append(
                f"Filters[{op.name!r}].splits is empty (required for post_split filters)"
            )
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
    return [
        f"{section}[{op.name!r}].splits is empty"
        for op in ops
        if not op.splits
    ]


def check_05_augmentations_train_only(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    del plugin
    descriptor = "augmentations_train_only"
    issues: list[str] = []
    for op in recipe.Augmentations:
        non_train = [s for s in op.splits if s != "train"]
        if non_train:
            issues.append(
                f"Augmentations[{op.name!r}] declares non-train splits {non_train}"
            )
    if not issues:
        return _passed(5, descriptor)
    return CheckResult(
        check_id=5,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_06_fit_on_train_uses_train_split(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    descriptor = "fit_on_train_uses_train_split"
    issues: list[str] = []
    for op in recipe.Transformations:
        spec = plugin.supported_operations.get(op.op)
        if spec is None:
            # Unknown operation — surfaced by check 18 in B.e.3.
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
    }
)


def _field_universe_pre_featurizations(recipe: Recipe) -> set[str]:
    return set(recipe.Output.record_schema.keys()) | {recipe.Labels.field}


def check_07_operations_reference_declared_fields(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
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
                f"Featurizations[{op.name!r}].inputs reference undeclared "
                f"fields {missing}"
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


def check_08_splits_partition_correctly(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    del plugin
    descriptor = "splits_partition_correctly"
    splits = recipe.Splits
    has_ratios = splits.ratios is not None
    has_keys = splits.key_assignment is not None
    if has_ratios and has_keys:
        return CheckResult(
            check_id=8,
            descriptor=descriptor,
            status="fail",
            location="Splits",
            message="declare exactly one of 'ratios' or 'key_assignment', got both",
        )
    if not has_ratios and not has_keys:
        return CheckResult(
            check_id=8,
            descriptor=descriptor,
            status="fail",
            location="Splits",
            message="must declare one of 'ratios' or 'key_assignment'",
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
    else:  # key_assignment present
        assert splits.key_assignment is not None  # narrow for mypy
        if not splits.key_assignment.mapping:
            return CheckResult(
                check_id=8,
                descriptor=descriptor,
                status="fail",
                location="Splits.key_assignment.mapping",
                message="key_assignment.mapping is empty",
            )
    return _passed(8, descriptor)


def check_09_stratification_keys_exist(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
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


def check_10_class_imbalance_strategy_in_one_place(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    """Heuristic v1 check: a `class_balance` strategy on `Splits` and a
    Filter whose predicate names `class_balance` collide and must be
    resolved to one site per imbalance concern.
    """
    del plugin
    descriptor = "class_imbalance_strategy_in_one_place"
    splits_handles = recipe.Splits.class_balance is not None
    filter_handles = any(
        "class_balance" in op.predicate for op in recipe.Filters
    )
    if splits_handles and filter_handles:
        return CheckResult(
            check_id=10,
            descriptor=descriptor,
            status="fail",
            location=None,
            message=(
                "class-imbalance strategy declared in both 'Splits.class_balance' "
                "and a Filters predicate; consolidate to one site"
            ),
        )
    return _passed(10, descriptor)


def check_11_visualization_mode_declared(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    """Tautological for valid recipes (the model already constrains
    `mode` to `Literal["exploration", "reporting"]`), but kept as a
    documented FR-2 check so the report is exhaustive.
    """
    del plugin
    descriptor = "visualization_mode_declared"
    issues: list[str] = []
    for op in recipe.Visualizations:
        if op.mode not in ("exploration", "reporting"):
            issues.append(
                f"Visualizations[{op.name!r}].mode={op.mode!r}"
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


def check_12_variants_reference_declared_sections(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    del plugin
    descriptor = "variants_reference_declared_sections"
    issues: list[str] = []
    for variant_name, overlay in recipe.variants.items():
        for key in overlay:
            if key not in _VALID_VARIANT_OVERRIDE_KEYS:
                issues.append(
                    f"variant {variant_name!r} overrides unknown section {key!r}"
                )
    if not issues:
        return _passed(12, descriptor)
    return CheckResult(
        check_id=12,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_13_labels_resolvable(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
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


def check_14_generation_output_schema_consistent(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    del plugin
    descriptor = "generation_output_schema_consistent"
    issues: list[str] = []
    record_schema = recipe.Output.record_schema
    for op in recipe.Generation:
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


def check_15_split_references_defined(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    del plugin
    descriptor = "split_references_defined"
    defined = _defined_split_names(recipe)
    issues: list[str] = []

    def _check(section: str, op_name: str, refs: list[str]) -> None:
        bad = [s for s in refs if s not in defined]
        if bad:
            issues.append(
                f"{section}[{op_name!r}] references undefined splits {bad}"
            )

    for filt in recipe.Filters:
        _check("Filters", filt.name, filt.splits)
    for tx in recipe.Transformations:
        _check("Transformations", tx.name, tx.splits)
    for aug in recipe.Augmentations:
        _check("Augmentations", aug.name, aug.splits)
    for feat in recipe.Featurizations:
        _check("Featurizations", feat.name, feat.splits)
    for gen in recipe.Generation:
        _check("Generation", gen.name, gen.applies_at)

    if not issues:
        return _passed(15, descriptor)
    return CheckResult(
        check_id=15,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_16_sample_data_strict_subset(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
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
    if has_fraction and selector.fraction is not None and not (
        0.0 < selector.fraction < 1.0
    ):
        return CheckResult(
            check_id=16,
            descriptor=descriptor,
            status="fail",
            location="SampleData.selector.fraction",
            message=(
                f"fraction must be in (0, 1) for a strict subset, "
                f"got {selector.fraction}"
            ),
        )
    return _passed(16, descriptor)


def check_17_contract_fields_exist_at_stage(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
    del plugin
    descriptor = "contract_fields_exist_at_stage"
    available = set(recipe.Output.record_schema.keys()) | {recipe.Labels.field}
    issues: list[str] = []
    for contract in recipe.InputContracts:
        if contract.field is not None and contract.field not in available:
            issues.append(
                f"InputContracts references undeclared field {contract.field!r}"
            )
    for expectation in recipe.OutputExpectations:
        if expectation.field is not None and expectation.field not in available:
            issues.append(
                f"OutputExpectations references undeclared field "
                f"{expectation.field!r}"
            )
    if not issues:
        return _passed(17, descriptor)
    return CheckResult(
        check_id=17,
        descriptor=descriptor,
        status="fail",
        location=None,
        message="; ".join(issues),
    )


def check_18_plugin_operation_params_validate(
    recipe: Recipe, plugin: Plugin
) -> CheckResult:
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
                f"{section}[{op_name!r}].op={op_kind!r} not declared by "
                f"plugin {plugin.name!r}"
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
                issues.append(
                    f"{section}[{op_name!r}] has unexpected param {given!r}"
                )

    for tx in recipe.Transformations:
        _validate("Transformations", tx.name, tx.op, tx.params)
    for aug in recipe.Augmentations:
        _validate("Augmentations", aug.name, aug.op, aug.params)
    for feat in recipe.Featurizations:
        _validate("Featurizations", feat.name, feat.op, feat.params)
    for viz in recipe.Visualizations:
        _validate("Visualizations", viz.name, viz.op, viz.params)

    if not issues:
        return _passed(18, descriptor)
    return CheckResult(
        check_id=18,
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
    (11, "visualization_mode_declared", check_11_visualization_mode_declared),
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
