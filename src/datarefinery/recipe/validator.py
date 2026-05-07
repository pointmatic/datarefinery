# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-2 recipe validator framework + checks 1-6.

Each enumerated check from features.md becomes a `check_NN_<descriptor>`
function returning a `CheckResult`. `validate(recipe, plugin)` runs every
registered check and never short-circuits - a check that raises
unexpectedly is captured as a `fail` result rather than aborting the
whole report.

Checks 7-18 land in stories B.e.2 and B.e.3.
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
