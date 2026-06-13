# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Plugin protocol and operation-spec models for DataRefinery plugins.

The recipe validator (FR-2 check 18) consults a plugin's
`supported_operations` to validate operation parameters declared in a
recipe. The pipeline runner consults `operation_factory` to materialize
each operation. v1 keeps `Operation` as a generic `Any` until the runner
in Phase C nails down the call signature.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

# Loose for v1; refined when `pipeline.runner` lands in Story C.m.
Operation = Any


class ParameterSpec(BaseModel):
    """One parameter declared by an `OperationSpec`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str  # e.g., "int", "float", "str", "bool", "list[int]"
    required: bool = True
    default: object | None = None
    description: str | None = None


class OperationSpec(BaseModel):
    """Plugin-declared metadata for one operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
    fit_on_train: bool = False
    applicable_splits: frozenset[str] = frozenset({"train", "val", "test"})
    applicable_sections: frozenset[str]
    #: Story J.g: a Transformations op is *pixel-altering* when its
    #: ``apply`` changes the image array's bytes in a consumer-visible way
    #: that is NOT recoverable from persisted fitted statistics (e.g.
    #: ``resize`` changes geometry). Stat-based / consumer-applied ops
    #: (``normalize``, ``mean_subtract``) and parameter-deterministic
    #: numeric ops (``cast``) are NOT pixel-altering — the consumer
    #: reproduces them at load time from persisted stats or recipe params.
    #: Drives validator check 26 and the lazy-mode ``path`` rewrite.
    pixel_altering: bool = False
    #: Story J.i: a Transformations op is *dtype-altering* when its
    #: ``apply`` leaves the image array in a non-uint8 dtype (e.g.
    #: ``normalize`` / ``mean_subtract`` emit float64 z-scores / centered
    #: values). Such output breaks the aggressive-augmentation realizer's
    #: ``PIL.Image.fromarray`` uint8 assumption, so check 27 refuses a
    #: dtype-altering Transformation on a split that also carries an
    #: aggressive Augmentation. Independent of ``pixel_altering``:
    #: ``resize`` is pixel-altering but uint8-preserving (not dtype-
    #: altering); ``normalize`` is dtype-altering but consumer-applied
    #: (not pixel-altering).
    dtype_altering: bool = False


@runtime_checkable
class Plugin(Protocol):
    """Plugin contract surfaced by `plugins.discovery`."""

    name: str
    supported_sections: frozenset[str]
    supported_operations: dict[str, OperationSpec]
    schema_version: int

    def operation_factory(self, section: str, op_name: str) -> Operation: ...

    def is_stub(self) -> bool: ...
