# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-J-1 SampleData runtime stage (Story J.a).

P-postpipeline + M-sidecar runtime: subset the materialized per-split
records *after* the pipeline has run, emit a ``sample/`` sidecar
alongside the full ``dataset/``. The full materialized instance is
unchanged - this stage produces an additional artifact whose purpose
is fast iteration / quick-look / smoke-test consumption.

Two kinds, mirroring the v0.18.0 schema landed by Story I.r:

- ``uniform``    random subset of ``n`` (or ``floor(fraction * len)``)
                 records per selected split.
- ``per_class``  stratified subset of ``n`` (or ``floor(fraction)``)
                 records *per class label* per selected split. Refuses
                 (at runtime) any selected split whose records lack the
                 recipe's ``Labels.field``.

Determinism contract: per-record-seed ranking via
``pipeline.workers.per_record_seed(seed, record)`` makes selection
invariant to input ordering, worker count, and process scheduling -
the same contract ``stratified_seeded_sample`` (Story H.j) uses for
the ``sample_per_class`` filter.

Seed resolution mirrors the Splits stage: ``selector.seed`` of ``None``
inherits the master seed; an ``int`` literal wins; a
:class:`SeedDerivationSpec` derives via ``derive_seed(master, "SampleData")``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.workers import per_record_seed
from datarefinery.recipe.models import SampleDataSection, SeedDerivationSpec
from datarefinery.recipe.seeds import derive_seed

Record = Mapping[str, Any]


@dataclass(frozen=True)
class SampleResult:
    """Outcome of subsetting one ``split_map`` by a ``SampleDataSection``.

    ``samples`` is keyed by split name and contains only the splits the
    selector targeted (after ``selector.splits`` honoring). ``selector_echo``
    is the JSON-shaped dump of the resolved selector for the manifest's
    ``sample.selector`` field. ``seed`` is the resolved seed actually used
    for selection (post-precedence).
    """

    samples: Mapping[str, list[Record]]
    selector_echo: dict[str, Any]
    seed: int


def resolve_sample_seed(section: SampleDataSection, fallback: int) -> int:
    """Resolve the SampleData seed with the same precedence as Splits.

    ``None`` inherits the master seed; an ``int`` literal wins; a
    :class:`SeedDerivationSpec` derives via the G11 master-keyed
    derivation function with the op name ``"SampleData"``.
    """
    seed = section.selector.seed
    if seed is None:
        return fallback
    if isinstance(seed, SeedDerivationSpec):
        return derive_seed(fallback, "SampleData")
    return int(seed)


def apply_sample_data(
    split_map: Mapping[str, list[Record]],
    section: SampleDataSection,
    *,
    seed: int,
    label_field: str,
) -> SampleResult:
    """Subset ``split_map`` per ``section.selector`` post-pipeline.

    The caller resolves seed precedence (see :func:`resolve_sample_seed`);
    this function takes the final resolved seed for clarity at call sites.

    Splits not named in ``selector.splits`` (when set) are omitted from
    the result. When ``selector.splits`` is ``None``, every split in
    ``split_map`` is sampled. Splits not present in ``split_map`` are
    silently skipped - validator check 16 covers the schema-time
    catch for unknown split names.
    """
    selector = section.selector
    targets = list(selector.splits) if selector.splits is not None else list(split_map.keys())

    samples: dict[str, list[Record]] = {}
    for split_name in targets:
        if split_name not in split_map:
            continue
        records = list(split_map[split_name])
        if selector.kind == "uniform":
            samples[split_name] = _uniform(records, selector, seed)
        elif selector.kind == "per_class":
            samples[split_name] = _per_class(records, selector, seed, label_field, split_name)
        else:  # pragma: no cover - pydantic Literal narrows this branch away
            raise MaterializeError(f"SampleSelector.kind={selector.kind!r} not recognized")

    return SampleResult(
        samples=samples,
        selector_echo=selector.model_dump(mode="json"),
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _target_count(n_records: int, selector_n: int | None, fraction: float | None) -> int:
    """Compute the target subset size for ``n_records`` candidates."""
    if selector_n is not None:
        return min(selector_n, n_records)
    if fraction is not None:
        return int(fraction * n_records)
    # Validator check 16 catches the both-None case; defensive only.
    raise MaterializeError("SampleSelector requires exactly one of 'n' or 'fraction'")


def _ranked(records: list[Record], seed: int) -> list[tuple[int, Record]]:
    """Pair each record with its per-record-seed rank, sorted ascending."""
    ranked = [(per_record_seed(seed, r), r) for r in records]
    ranked.sort(key=lambda kv: kv[0])
    return ranked


def _uniform(records: list[Record], selector: Any, seed: int) -> list[Record]:
    target = _target_count(len(records), selector.n, selector.fraction)
    if target <= 0:
        return []
    ranked = _ranked(records, seed)
    return [r for _, r in ranked[:target]]


def _per_class(
    records: list[Record],
    selector: Any,
    seed: int,
    label_field: str,
    split_name: str,
) -> list[Record]:
    missing = [r.get("record_id") for r in records if label_field not in r]
    if missing:
        raise MaterializeError(
            f"SampleData.selector.kind='per_class' on split {split_name!r}: "
            f"{len(missing)} record(s) lack the label field {label_field!r} "
            f"(first: {missing[0]!r}); per_class sampling requires every "
            f"record to carry the label field at materialize time"
        )
    by_class: dict[Any, list[Record]] = {}
    for r in records:
        by_class.setdefault(r[label_field], []).append(r)

    out: list[Record] = []
    # Stable iteration order across classes for cross-run determinism
    # (mirrors splits._stratified_ratios).
    sorted_classes = sorted(by_class.keys(), key=lambda x: (type(x).__name__, repr(x)))
    for cls in sorted_classes:
        bucket = by_class[cls]
        target = _target_count(len(bucket), selector.n, selector.fraction)
        if target <= 0:
            continue
        ranked = _ranked(bucket, seed)
        out.extend(r for _, r in ranked[:target])
    return out
