# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-3 deterministic parallel worker pool.

This module is the implementation of the determinism contract documented
in ``docs/project-guide/go.md`` ("Determinism contract in
``pipeline.workers``"). The contract has two parts that must both hold,
because together they make worker count irrelevant to materialized output
bytes:

1. **Per-record seeding.** Each record's seed is derived as
   ``sha256(global_seed.to_bytes(8, "big") + record_id_bytes).digest()[:8]``
   decoded as a 64-bit unsigned int. The seed depends only on
   ``(global_seed, record_id)`` - not on which worker picks the record
   up or in what order.

2. **Reorder by ``record_id`` before yielding.** Worker output is
   collected, sorted by ``record_id`` (stable across types via a
   ``(type, str)`` key), and yielded in that order. There is NO
   ``as_completed`` streaming across stage boundaries; that would leak
   scheduling order into downstream stages and break byte-identical
   re-runs.

Serial fast-path: when ``workers <= 1`` the executor is bypassed
entirely (still per-record-seeded, still reorder-by-record-id).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Iterator, Mapping
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from datarefinery.core.errors import MaterializeError

Record = Mapping[str, Any]
WorkerFn = Callable[[Record, int], Record]


def per_record_seed(
    global_seed: int,
    record: Record,
    *,
    record_id_field: str = "record_id",
) -> int:
    """Derive the per-record seed from the global seed and the record_id.

    Public so tests, downstream stages, and plugin operations can compute
    the same seed without re-implementing the formula.
    """
    if record_id_field not in record:
        raise MaterializeError(
            f"per_record_seed: record missing record_id field "
            f"{record_id_field!r}; cannot derive deterministic seed"
        )
    rid = record[record_id_field]
    rid_bytes = str(rid).encode("utf-8")
    digest = hashlib.sha256(int(global_seed).to_bytes(8, "big") + rid_bytes).digest()
    return int.from_bytes(digest[:8], "big")


def run_parallel(
    seed: int,
    fn: WorkerFn,
    items: Iterable[Record],
    workers: int,
    *,
    record_id_field: str = "record_id",
) -> Iterator[Record]:
    """Apply ``fn(record, per_record_seed)`` to every record in parallel.

    ``fn`` must be picklable when ``workers > 1`` (the standard
    multiprocessing constraint - module-level functions, not closures).
    Each ``fn`` call receives a deterministic per-record seed; the
    function is responsible for using it (any RNG inside ``fn`` must be
    seeded from the supplied value, not from a global RNG, to honor the
    contract).
    """
    materialized = [
        (
            _sort_key(r, record_id_field),
            per_record_seed(seed, r, record_id_field=record_id_field),
            r,
        )
        for r in items
    ]
    if workers <= 1:
        results: list[tuple[Any, Record]] = [
            (key, fn(record, prs)) for key, prs, record in materialized
        ]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [(key, executor.submit(fn, record, prs)) for key, prs, record in materialized]
            results = [(key, fut.result()) for key, fut in futures]

    results.sort(key=lambda kv: kv[0])
    yield from (record for _, record in results)


def _sort_key(record: Record, record_id_field: str) -> tuple[str, str]:
    """Stable sort key for ``record_id`` values across types.

    Mixed-type record-id sets (e.g. ``int`` and ``str`` in the same
    pipeline) would crash a naive ``<`` comparison; converting to
    ``(type, str)`` produces a total order without that hazard.
    """
    if record_id_field not in record:
        raise MaterializeError(
            f"run_parallel: record missing record_id field "
            f"{record_id_field!r}; cannot reorder deterministically"
        )
    rid = record[record_id_field]
    return (type(rid).__name__, str(rid))
