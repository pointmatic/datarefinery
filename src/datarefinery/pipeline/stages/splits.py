# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-7 Splits stage: train/val/test partitioning.

Two splitting modes per ``SplitsSection``:

- ``ratios``           cumulative-fraction partitioning; ratios summing to
                       <1.0 leave a recorded ``unassigned`` remainder
                       (features.md FR-7 edge case).
- ``key_assignment``   per-record lookup ``mapping[str(record[field])]``;
                       any unmapped record raises ``MaterializeError``.

Stratification (``stratify_by``) is supported in ratio mode by partitioning
each class's records by the same ratio shape. Sparse-class detection emits
a warning string when any class has fewer records than the number of
positive-ratio splits (so at least one split would receive zero of that
class).

``class_balance`` is a tag passed through to ``SplitResult.class_balance``
for downstream tools (ModelFoundry handles weighting/resampling at training
time per features.md FR-7 #4); this stage does no resampling.

Determinism: shuffles use ``numpy.random.default_rng(seed)``. The same seed
+ same record order produces identical partitions, irrespective of worker
count or system scheduling. Class iteration is stably ordered by
``(type, repr)`` so stratified output is also seed-deterministic across
hash-randomization variants.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from datarefinery.core.errors import MaterializeError
from datarefinery.recipe.models import SeedDerivationSpec, SplitsSection
from datarefinery.recipe.seeds import derive_seed

Record = Mapping[str, Any]


@dataclass(frozen=True)
class SplitResult:
    """Outcome of partitioning one record stream by a ``SplitsSection``."""

    splits: Mapping[str, list[Record]]
    unassigned: list[Record]
    class_balance: str | None
    warnings: tuple[str, ...]
    seed: int


def resolve_seed(section: SplitsSection, fallback: int) -> int:
    """Resolve the Splits seed for materialize-time RNG seeding.

    Three forms accepted on the section: ``None`` (use the recipe-level
    fallback / master seed), a literal ``int``, or a
    ``SeedDerivationSpec`` that derives from the master seed via the
    G11 derivation function. The op name for derivation is the literal
    string ``"Splits"`` (one Splits section per recipe).
    """
    if section.seed is None:
        return fallback
    if isinstance(section.seed, SeedDerivationSpec):
        return derive_seed(fallback, "Splits")
    return int(section.seed)


def apply_splits(
    records: Iterable[Record],
    section: SplitsSection,
    *,
    seed: int,
) -> SplitResult:
    """Partition ``records`` according to ``section``.

    The caller resolves seed precedence (section seed wins over recipe
    seed - see :func:`resolve_seed`); this function takes a single
    final seed for clarity at call sites.

    Three top-level modes:

    1. **Source partitions, no sub-partitioning** — when any record
       carries a loader-stamped ``partition`` field and the section
       has no ``ratios``/``key_assignment``/``applies_to``, group by
       ``partition`` and return verbatim (Story H.b "Form A").
    2. **Source partitions + applies_to sub-partitioning** — group by
       ``partition``; pull out the named partition; run the existing
       ratio-based partitioning on it; preserve the other partitions
       as-is (Story H.b "Form B").
    3. **Global pool** — no record carries ``partition``; behave as
       before (ratios or key_assignment over the whole stream).
    """
    materialized = list(records)
    has_partition = any("partition" in r for r in materialized)
    if has_partition:
        return _apply_partitioned(materialized, section, seed)
    if section.applies_to is not None:
        raise MaterializeError(
            "Splits.applies_to is set but no record carries a 'partition' field; "
            "declare InputSource.partition on each source or remove applies_to"
        )
    if section.key_assignment is not None:
        return _apply_key_assignment(materialized, section, seed)
    if section.ratios:
        return _apply_ratios(materialized, section, seed)
    # Validator check 8 prevents this combination; defensive only.
    raise MaterializeError("SplitsSection has neither ratios nor key_assignment")


# ---------------------------------------------------------------------------
# Partition-honoring splits (Story H.b)
# ---------------------------------------------------------------------------


def _apply_partitioned(
    records: list[Record],
    section: SplitsSection,
    seed: int,
) -> SplitResult:
    """Honor loader-stamped ``partition`` values.

    If ``section.applies_to`` is set, the named partition is fed
    through the existing ratio-based partitioning logic; sibling
    partitions are returned verbatim.
    """
    by_partition: dict[str, list[Record]] = {}
    missing: list[int] = []
    for i, r in enumerate(records):
        p = r.get("partition")
        if p is None:
            missing.append(i)
            continue
        by_partition.setdefault(str(p), []).append(r)
    if missing:
        raise MaterializeError(
            f"records[{missing[0]}:] are missing 'partition' field but the stream "
            f"otherwise has partition declarations; mixed partitioned/unpartitioned "
            f"records are not supported"
        )

    applies_to = section.applies_to
    if applies_to is None:
        if section.ratios:
            raise MaterializeError(
                "Splits.ratios is set with source partitions but no applies_to; "
                "either remove ratios (to honor source partitions verbatim) or "
                "set applies_to to name the partition to sub-partition"
            )
        return SplitResult(
            splits=by_partition,
            unassigned=[],
            class_balance=section.class_balance,
            warnings=(),
            seed=seed,
        )

    if applies_to not in by_partition:
        raise MaterializeError(
            f"Splits.applies_to={applies_to!r} not present in source partitions "
            f"{sorted(by_partition.keys())!r}"
        )
    if not section.ratios:
        raise MaterializeError(
            "Splits.applies_to is set but no ratios declared; "
            "applies_to is only meaningful with a ratio-based sub-partition"
        )

    target_records = by_partition.pop(applies_to)
    sub_result = _apply_ratios(target_records, section, seed)
    merged: dict[str, list[Record]] = dict(sub_result.splits)
    for sibling, sibling_records in by_partition.items():
        if sibling in merged:
            raise MaterializeError(
                f"applies_to sub-partition produced a split named {sibling!r} "
                f"that collides with an existing source partition"
            )
        merged[sibling] = sibling_records
    return SplitResult(
        splits=merged,
        unassigned=sub_result.unassigned,
        class_balance=section.class_balance,
        warnings=sub_result.warnings,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Key-based splits
# ---------------------------------------------------------------------------


def _apply_key_assignment(
    records: list[Record],
    section: SplitsSection,
    seed: int,
) -> SplitResult:
    ka = section.key_assignment
    assert ka is not None  # narrowed by caller
    splits: dict[str, list[Record]] = {target: [] for target in set(ka.mapping.values())}
    unmapped: list[tuple[int, Any]] = []
    for i, r in enumerate(records):
        key = r.get(ka.field)
        if key is None:
            unmapped.append((i, key))
            continue
        target = ka.mapping.get(str(key))
        if target is None:
            unmapped.append((i, key))
            continue
        splits[target].append(r)
    if unmapped:
        sample = unmapped[:3]
        more = "" if len(unmapped) <= 3 else f" (+{len(unmapped) - 3} more)"
        raise MaterializeError(
            f"key_assignment: {len(unmapped)} record(s) with field "
            f"{ka.field!r} not in mapping (sample {sample}{more})"
        )
    return SplitResult(
        splits=splits,
        unassigned=[],
        class_balance=section.class_balance,
        warnings=(),
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Ratio-based splits (with optional stratification)
# ---------------------------------------------------------------------------


def _apply_ratios(
    records: list[Record],
    section: SplitsSection,
    seed: int,
) -> SplitResult:
    ratios = section.ratios
    assert ratios is not None  # narrowed by caller
    split_names = list(ratios.keys())
    weights = np.array([ratios[n] for n in split_names], dtype=float)
    rng = np.random.default_rng(seed)

    if section.stratify_by is not None:
        return _stratified_ratios(records, section, seed, rng, split_names, weights)

    n = len(records)
    indices = rng.permutation(n)
    boundaries = (np.cumsum(weights) * n).astype(int)
    splits: dict[str, list[Record]] = {}
    start = 0
    for i, name in enumerate(split_names):
        end = int(boundaries[i])
        splits[name] = [records[int(j)] for j in indices[start:end]]
        start = end
    unassigned = [records[int(j)] for j in indices[start:]]
    return SplitResult(
        splits=splits,
        unassigned=unassigned,
        class_balance=section.class_balance,
        warnings=(),
        seed=seed,
    )


def _stratified_ratios(
    records: list[Record],
    section: SplitsSection,
    seed: int,
    rng: np.random.Generator,
    split_names: list[str],
    weights: np.ndarray,
) -> SplitResult:
    field = section.stratify_by
    assert field is not None  # narrowed by caller
    by_class: dict[Any, list[int]] = {}
    for i, r in enumerate(records):
        by_class.setdefault(r.get(field), []).append(i)

    splits: dict[str, list[Record]] = {n: [] for n in split_names}
    unassigned_idx: list[int] = []
    warnings: list[str] = []
    n_positive_splits = int(sum(1 for w in weights if w > 0))

    # Stable iteration order over classes for cross-run determinism.
    sorted_classes = sorted(by_class.keys(), key=lambda x: (type(x).__name__, repr(x)))
    for cls in sorted_classes:
        cls_indices = by_class[cls]
        cls_n = len(cls_indices)
        if cls_n < n_positive_splits:
            warnings.append(
                f"sparse stratify class {cls!r}: {cls_n} record(s); "
                f"{n_positive_splits} positive-ratio split(s) declared, "
                f"some splits will receive 0"
            )
        idx_arr = rng.permutation(np.array(cls_indices))
        boundaries = (np.cumsum(weights) * cls_n).astype(int)
        start = 0
        for i, name in enumerate(split_names):
            end = int(boundaries[i])
            splits[name].extend(records[int(j)] for j in idx_arr[start:end])
            start = end
        unassigned_idx.extend(int(j) for j in idx_arr[start:])

    unassigned = [records[j] for j in unassigned_idx]
    return SplitResult(
        splits=splits,
        unassigned=unassigned,
        class_balance=section.class_balance,
        warnings=tuple(warnings),
        seed=seed,
    )
