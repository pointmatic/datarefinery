# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Aggressive-mode augmentation realizer scaffolding (Story H.p).

The FR-11 ``materialization: aggressive`` path replaces each input record
with ``expansion`` augmented variant records. Concrete ops (H.q, H.r)
plug into this scaffolding via a small :data:`Realizer` callable contract
and let :func:`emit_variants` handle the deterministic seed derivation,
the variant-index loop, and the metadata tagging
(``source_record_id``, ``variant_index``).

The seed-derivation contract is shared with :func:`pipeline.workers.per_record_variant_seed`
— the H.o architectural spike confirmed it is byte-identical across
``workers=1/2/4`` and across separate Python processes. Concrete ops MUST
call :func:`per_record_variant_seed` (or this module's :func:`emit_variants`
which calls it for them) rather than reaching for any other RNG source.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from datarefinery.pipeline.workers import per_record_variant_seed

Record = Mapping[str, Any]
Realizer = Callable[[Record, int, int], Record]
"""Single-variant realize function.

Signature: ``realize_fn(record, seed, variant_index) -> record``.

Receives the input record, a deterministic per-variant seed (already
derived via :func:`per_record_variant_seed`), and the variant index. The
return value is the augmented record's *payload* — image data and any
op-specific fields. :func:`emit_variants` adds the metadata fields
(``source_record_id``, ``variant_index``) and rewrites ``record_id``
after the realizer returns.
"""


def derive_variant_record_id(source_record_id: Any, variant_index: int) -> str:
    """Stable, unique record_id for an aggressive variant.

    Format: ``f"{source_record_id}__v{variant_index:03d}"``. The
    zero-padded variant index keeps lexicographic order matching numeric
    order for ``expansion <= 999`` — sufficient for foreseeable
    augmentation budgets and matches the ``(record_id,)`` reorder
    invariant in :func:`pipeline.workers.run_parallel` without needing
    a tuple sort key.
    """
    return f"{source_record_id}__v{variant_index:03d}"


def emit_variants(
    record: Record,
    *,
    op_id: str,
    global_seed: int,
    expansion: int,
    realize_fn: Realizer,
    record_id_field: str = "record_id",
) -> list[dict[str, Any]]:
    """Realize one input record into ``expansion`` augmented variants.

    Each variant:

    - Receives a deterministic seed from :func:`per_record_variant_seed`.
    - Gets ``source_record_id`` and ``variant_index`` metadata.
    - Has its ``record_id`` rewritten via :func:`derive_variant_record_id`.

    The output list is in variant-index order. Callers that need a fully
    flat, sort-stable sequence across many records must collect outputs
    from all input records and sort by ``record_id`` themselves — the
    zero-padded record_id format makes this a single ``sorted(...)`` call.
    """
    if record_id_field not in record:
        raise KeyError(
            f"emit_variants: record missing record_id field "
            f"{record_id_field!r}; cannot tag variants deterministically"
        )
    source_record_id = record[record_id_field]
    out: list[dict[str, Any]] = []
    for vi in range(expansion):
        seed = per_record_variant_seed(
            global_seed,
            record,
            vi,
            op_id=op_id,
            record_id_field=record_id_field,
        )
        realized = realize_fn(record, seed, vi)
        merged = dict(realized)
        merged["record_id"] = derive_variant_record_id(source_record_id, vi)
        merged["source_record_id"] = source_record_id
        merged["variant_index"] = vi
        out.append(merged)
    return out
