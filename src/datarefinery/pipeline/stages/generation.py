# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-9 Generation stage: record-count-changing operations.

Each ``GenerationOp`` runs against the splits listed in ``applies_at``
(default ``["train"]`` per model). The op's ``name`` doubles as the
operation lookup key (Generation has no separate ``op`` field in the
model, unlike Transformations / Augmentations / etc.).

Operation signature (Generation section):

    def op(records: list[Record], *, seed: int,
           inputs: list[str],
           output_schema: Mapping[str, FieldSpec],
           params: Mapping[str, Any],
           label_field: str | None,
           op_name: str) -> list[Record]

``op_name`` is the recipe's ``GenerationOp.name`` — passed through so
per-record-stochastic ops can stamp a ``<op_name>_seed`` column on
each output record (Story I.e), keyed on the recipe identifier so two
ops of the same op kind never collide on a single seed column.

Operations return only the *new* records to add. By default the stage
concatenates them onto the split's existing records. When
``GenerationOp.replace_input_records`` is ``True`` (Story I.q / G18) the
stage instead replaces the split with just the generated records — the
transformation-style case (e.g. on-the-fly corruption) that emits N
records per input and does not want the originals carried along. Either
way each generated record is validated against ``Output.record_schema``
(every declared field must be present); schema mismatches raise
``MaterializeError`` per FR-9.

Counts before and after are exposed on ``GenerationResult`` so the runner
(Story C.m) can record pre/post counts in the manifest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from datarefinery.core.errors import MaterializeError
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import FieldSpec, GenerationOp
from datarefinery.recipe.seeds import resolve_seed

Record = Mapping[str, Any]
GenerationCallable = Callable[..., list[Record]]


@dataclass(frozen=True)
class GenerationResult:
    """Outcome of one generation pass over the splits."""

    splits: Mapping[str, list[Record]]
    counts_before: Mapping[str, int]
    counts_after: Mapping[str, int]
    warnings: tuple[str, ...]


def apply_generation(
    splits: Mapping[str, list[Record]],
    generation_ops: list[GenerationOp],
    *,
    plugin: Plugin,
    output_record_schema: Mapping[str, FieldSpec],
    label_field: str | None = None,
    master_seed: int = 0,
) -> GenerationResult:
    """Apply every declared generation op to its target splits.

    The returned ``splits`` are fresh dicts (callers may keep references
    to the originals safely). Pre/post counts include every input split,
    even those untouched by generation.
    """
    counts_before = {name: len(recs) for name, recs in splits.items()}
    out: dict[str, list[Record]] = {name: list(recs) for name, recs in splits.items()}
    warnings: list[str] = []
    output_fields = frozenset(output_record_schema.keys())

    for op in generation_ops:
        for split_name in op.applies_at:
            if split_name not in out:
                # Validator check 15 enforces that applies_at references a
                # declared split; if we somehow got here without that
                # check, fail loudly rather than silently.
                raise MaterializeError(
                    f"Generation[{op.name!r}].applies_at references undeclared split {split_name!r}"
                )
            if split_name not in {"train"}:
                warnings.append(
                    f"Generation[{op.name!r}] runs on non-train split "
                    f"{split_name!r}; atypical (FR-9 edge case)"
                )
            new_records = _invoke_one(op, out[split_name], plugin, label_field, master_seed)
            _validate_against_output_schema(op.name, split_name, new_records, output_fields)
            if op.replace_input_records:
                out[split_name] = list(new_records)
            else:
                out[split_name].extend(new_records)

    counts_after = {name: len(recs) for name, recs in out.items()}
    return GenerationResult(
        splits=out,
        counts_before=counts_before,
        counts_after=counts_after,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _invoke_one(
    op: GenerationOp,
    records: list[Record],
    plugin: Plugin,
    label_field: str | None,
    master_seed: int,
) -> list[Record]:
    callable_: GenerationCallable = plugin.operation_factory("Generation", op.name)
    resolved_seed = resolve_seed(op.seed, master_seed=master_seed, op_name=op.name)
    return callable_(
        records,
        seed=resolved_seed,
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=label_field,
        op_name=op.name,
    )


def _validate_against_output_schema(
    op_name: str,
    split_name: str,
    records: list[Record],
    output_fields: frozenset[str],
) -> None:
    for i, r in enumerate(records):
        missing = output_fields - r.keys()
        if missing:
            raise MaterializeError(
                f"Generation[{op_name!r}] on split {split_name!r}: "
                f"generated record at index {i} missing required "
                f"Output field(s) {sorted(missing)!r}"
            )
