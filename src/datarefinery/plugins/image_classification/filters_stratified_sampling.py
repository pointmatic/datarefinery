# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Shared stratified-by-label seeded sampling + tagging helper.

Backs ``sample_per_class`` (FR-FILTER-1, Story H.j) and
``sample_per_class_fractional`` (FR-FILTER-2, Story H.k). The two ops
differ only in how the per-class target count is derived; the candidate-
pool exclusion, deterministic ranking, and label-tagging mechanics are
identical.

Determinism: per-record ranking via
``pipeline.workers.per_record_seed(seed, record)``. Within each class the
lowest-ranked ``n_for_class(label)`` records are chosen. The rank key is
a pure function of ``(global_seed, record_id)``, so selection is
invariant to input ordering, worker count, and process scheduling.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from datarefinery.pipeline.workers import per_record_seed

Record = Mapping[str, Any]

TAG_FIELD = "sample_per_class_tags"


def stratified_seeded_sample(
    records: list[Record],
    *,
    seed: int,
    label_field: str,
    n_for_class: Callable[[Any], int],
    label: str | None,
    exclude_already_labeled: Iterable[str] | None,
) -> list[Record]:
    """Pick records per class deterministically, optionally tagging.

    ``n_for_class(label)`` returns the per-class target. Records carrying
    any tag in ``exclude_already_labeled`` are dropped from the candidate
    pool before ranking. When ``label is None`` only the chosen records
    are returned (destructive); when ``label`` is set all records pass
    through with the chosen ones tagged in ``sample_per_class_tags``.
    """
    exclusion = set(exclude_already_labeled or ())

    by_class: dict[Any, list[tuple[int, Record]]] = {}
    for record in records:
        tags = record.get(TAG_FIELD, ())
        if exclusion and exclusion.intersection(tags):
            continue
        rank = per_record_seed(seed, record)
        by_class.setdefault(record.get(label_field), []).append((rank, record))

    chosen_ids: set[Any] = set()
    for class_label, bucket in by_class.items():
        target = n_for_class(class_label)
        if target <= 0:
            continue
        bucket.sort(key=lambda kv: kv[0])
        for _, record in bucket[:target]:
            chosen_ids.add(record["record_id"])

    if label is None:
        return [r for r in records if r["record_id"] in chosen_ids]

    out: list[Record] = []
    for record in records:
        if record["record_id"] not in chosen_ids:
            out.append(record)
            continue
        prior = record.get(TAG_FIELD, ())
        new_record = dict(record)
        new_record[TAG_FIELD] = (*tuple(prior), label)
        out.append(new_record)
    return out
