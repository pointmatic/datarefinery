# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-7 split-determinism Hypothesis properties (Story E.c).

Two property tests assert the determinism contract of
:func:`pipeline.stages.splits.apply_splits`:

1. **Repeat-run determinism.** Same record list + same seed produces
   identical partitions across two independent calls. This is the
   inner determinism contract for FR-7.
2. **Cross-worker determinism.** When records are pre-shuffled by the
   parallel-worker reorder-by-record-id primitive
   (``pipeline.workers.run_parallel``) at ``workers=1/2/4``, splitting
   the result yields identical partitions across all three worker
   counts. This validates the ``project-essentials.md`` "Determinism
   contract in ``pipeline.workers``" rule that worker count must not
   leak into downstream stage output.

The cross-worker test uses fewer Hypothesis examples than the
repeat-run test because spawning a ``ProcessPoolExecutor`` per example
is significantly more expensive than the in-memory comparison.
"""

from __future__ import annotations

import string
from collections.abc import Mapping
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from datarefinery.pipeline.stages.splits import apply_splits
from datarefinery.pipeline.workers import run_parallel
from datarefinery.recipe.models import SplitsSection

Record = dict[str, Any]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _ratios_strategy() -> st.SearchStrategy[dict[str, float]]:
    """Two-way and three-way ratio shapes that sum within ratios-section
    tolerance and avoid degenerate splits (no zero-width splits)."""
    return st.one_of(
        st.tuples(
            st.floats(min_value=0.1, max_value=0.9, allow_nan=False),
        ).map(lambda t: {"train": round(t[0], 4), "val": round(1.0 - t[0], 4)}),
        st.tuples(
            st.floats(min_value=0.1, max_value=0.7, allow_nan=False),
            st.floats(min_value=0.1, max_value=0.4, allow_nan=False),
        )
        .filter(lambda ab: ab[0] + ab[1] < 0.95)
        .map(
            lambda ab: {
                "train": round(ab[0], 4),
                "val": round(ab[1], 4),
                "test": round(1.0 - ab[0] - ab[1], 4),
            }
        ),
    )


def _records_strategy() -> st.SearchStrategy[list[Record]]:
    """Generate record lists of varying size with ``record_id`` + ``label``.

    Record ids are unique strings so the parallel-worker reorder is
    well-defined. Labels are drawn from a small alphabet so
    stratification has multiple records per class.
    """

    def _build(n: int, classes: tuple[str, ...]) -> list[Record]:
        return [
            {
                "record_id": f"r_{i:05d}",
                "label": classes[i % len(classes)],
            }
            for i in range(n)
        ]

    return st.builds(
        _build,
        st.integers(min_value=8, max_value=120),
        st.lists(
            st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=3),
            min_size=2,
            max_size=4,
            unique=True,
        ).map(tuple),
    )


def _splits_section(
    *,
    ratios: dict[str, float],
    seed: int,
    stratify: str | None,
) -> SplitsSection:
    return SplitsSection.model_validate(
        {
            "ratios": ratios,
            "seed": seed,
            **({"stratify_by": stratify} if stratify is not None else {}),
        }
    )


# ---------------------------------------------------------------------------
# Property 1: repeat-run determinism
# ---------------------------------------------------------------------------


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    records=_records_strategy(),
    ratios=_ratios_strategy(),
    seed=st.integers(min_value=0, max_value=10000),
    stratify=st.sampled_from([None, "label"]),
)
def test_apply_splits_repeats_byte_identically(
    records: list[Record],
    ratios: dict[str, float],
    seed: int,
    stratify: str | None,
) -> None:
    section = _splits_section(ratios=ratios, seed=seed, stratify=stratify)
    a = apply_splits(records, section, seed=seed)
    b = apply_splits(records, section, seed=seed)
    assert _normalize(a.splits) == _normalize(b.splits)
    assert a.unassigned == b.unassigned


# ---------------------------------------------------------------------------
# Property 2: cross-worker determinism
#
# Pre-process records through ``run_parallel`` at three worker counts;
# split each pre-processed list with the same seed; assert all three
# partitions match. ``ProcessPoolExecutor`` spawn cost makes this test
# expensive per example, so the example budget is intentionally small.
# ---------------------------------------------------------------------------


def _identity(record: Mapping[str, Any], _seed: int) -> Mapping[str, Any]:
    """Module-level identity fn — picklable for ProcessPoolExecutor."""
    return dict(record)


@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    records=_records_strategy(),
    ratios=_ratios_strategy(),
    seed=st.integers(min_value=0, max_value=10000),
    stratify=st.sampled_from([None, "label"]),
)
def test_split_partitions_are_invariant_across_worker_counts(
    records: list[Record],
    ratios: dict[str, float],
    seed: int,
    stratify: str | None,
) -> None:
    section = _splits_section(ratios=ratios, seed=seed, stratify=stratify)

    partitions: list[dict[str, list[str]]] = []
    for workers in (1, 2, 4):
        pre = list(run_parallel(seed=seed, fn=_identity, items=records, workers=workers))
        result = apply_splits(pre, section, seed=seed)
        partitions.append(_normalize(result.splits))

    # All three worker counts must produce byte-identical partitions.
    assert partitions[0] == partitions[1] == partitions[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(splits: Any) -> dict[str, list[str]]:
    """Reduce a SplitResult.splits mapping to a comparison-friendly form.

    Records are summarized by record_id (the stable identity field used
    by run_parallel's reorder); list order is preserved so a partitioner
    that re-shuffled records would produce a detectable diff.
    """
    return {name: [r["record_id"] for r in recs] for name, recs in splits.items()}
