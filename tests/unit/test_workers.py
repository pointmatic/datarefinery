# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-3 deterministic worker tests (Story C.l).

Worker functions in this module are at module scope so they pickle
cleanly for ``ProcessPoolExecutor`` (the standard multiprocessing
constraint - closures and lambdas don't pickle).
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Mapping
from typing import Any

import pytest

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.workers import per_record_seed, run_parallel


def _records(n: int) -> list[Mapping[str, Any]]:
    return [{"record_id": f"rec_{i:04d}", "value": i} for i in range(n)]


# ---------------------------------------------------------------------------
# Module-level worker fns (must be picklable for ProcessPoolExecutor)
# ---------------------------------------------------------------------------


def _identity_with_seed(record: Mapping[str, Any], prs: int) -> dict[str, Any]:
    out = dict(record)
    out["seen_seed"] = prs
    return out


def _double_value(record: Mapping[str, Any], prs: int) -> dict[str, Any]:
    del prs
    out = dict(record)
    out["value"] = int(record["value"]) * 2
    return out


def _slow_worker(record: Mapping[str, Any], prs: int) -> dict[str, Any]:
    """Sleeps a tiny amount based on record_id to maximize the chance
    that worker scheduling jumbles completion order if reorder is
    broken."""
    del prs
    rid = str(record["record_id"])
    # Hash the id to get a deterministic but order-jumbling delay.
    h = int(hashlib.md5(rid.encode()).hexdigest(), 16) % 5
    time.sleep(0.001 * h)
    return dict(record)


def _failing_worker(record: Mapping[str, Any], prs: int) -> dict[str, Any]:
    del prs
    if record["record_id"] == "rec_0003":
        raise ValueError("kaboom on rec_0003")
    return dict(record)


# ---------------------------------------------------------------------------
# per_record_seed: independent of worker count and scheduling
# ---------------------------------------------------------------------------


def test_per_record_seed_is_deterministic() -> None:
    record = {"record_id": "abc", "value": 42}
    a = per_record_seed(7, record)
    b = per_record_seed(7, record)
    assert a == b


def test_per_record_seed_differs_for_different_records() -> None:
    a = per_record_seed(7, {"record_id": "x"})
    b = per_record_seed(7, {"record_id": "y"})
    assert a != b


def test_per_record_seed_differs_for_different_global_seeds() -> None:
    record = {"record_id": "abc"}
    assert per_record_seed(7, record) != per_record_seed(8, record)


def test_per_record_seed_matches_documented_formula() -> None:
    """Pin the formula: changing this is a determinism-contract event."""
    expected_digest = hashlib.sha256((7).to_bytes(8, "big") + b"abc").digest()
    expected = int.from_bytes(expected_digest[:8], "big")
    assert per_record_seed(7, {"record_id": "abc"}) == expected


def test_per_record_seed_record_id_can_be_int() -> None:
    a = per_record_seed(0, {"record_id": 42})
    b = per_record_seed(0, {"record_id": 42})
    assert a == b


def test_per_record_seed_missing_id_raises() -> None:
    with pytest.raises(MaterializeError, match="record_id"):
        per_record_seed(0, {"value": 1})


def test_per_record_seed_custom_field_name() -> None:
    a = per_record_seed(0, {"key": "x"}, record_id_field="key")
    b = per_record_seed(0, {"record_id": "x"})
    assert a == b


# ---------------------------------------------------------------------------
# Worker-count invariance: workers=1, 2, 4 produce identical output
# ---------------------------------------------------------------------------


def test_workers_1_2_4_produce_byte_identical_output() -> None:
    records = _records(20)
    out1 = list(run_parallel(seed=7, fn=_double_value, items=records, workers=1))
    out2 = list(run_parallel(seed=7, fn=_double_value, items=records, workers=2))
    out4 = list(run_parallel(seed=7, fn=_double_value, items=records, workers=4))
    assert out1 == out2
    assert out2 == out4


def test_per_record_seed_preserved_through_run_parallel() -> None:
    records = _records(10)
    out_serial = list(run_parallel(seed=42, fn=_identity_with_seed, items=records, workers=1))
    out_parallel = list(run_parallel(seed=42, fn=_identity_with_seed, items=records, workers=4))
    # Each record sees the same per-record seed regardless of worker count.
    serial_seeds = {r["record_id"]: r["seen_seed"] for r in out_serial}
    parallel_seeds = {r["record_id"]: r["seen_seed"] for r in out_parallel}
    assert serial_seeds == parallel_seeds
    # And each seed matches the documented formula.
    for rid, observed in serial_seeds.items():
        expected = per_record_seed(42, {"record_id": rid})
        assert observed == expected


# ---------------------------------------------------------------------------
# Reorder-by-record-id invariant
# ---------------------------------------------------------------------------


def test_output_is_sorted_by_record_id_in_serial_mode() -> None:
    # Provide records out of order to confirm reorder.
    records = [
        {"record_id": "rec_0003", "value": 3},
        {"record_id": "rec_0000", "value": 0},
        {"record_id": "rec_0002", "value": 2},
        {"record_id": "rec_0001", "value": 1},
    ]
    out = list(run_parallel(seed=0, fn=_double_value, items=records, workers=1))
    assert [r["record_id"] for r in out] == [
        "rec_0000",
        "rec_0001",
        "rec_0002",
        "rec_0003",
    ]


def test_output_is_sorted_by_record_id_in_parallel_mode() -> None:
    """Even with order-jumbling worker delays, output stays sorted."""
    records = _records(8)
    out = list(run_parallel(seed=0, fn=_slow_worker, items=records, workers=4))
    assert [r["record_id"] for r in out] == [f"rec_{i:04d}" for i in range(8)]


def test_run_parallel_handles_mixed_type_record_ids_without_crash() -> None:
    records: list[dict[str, Any]] = [
        {"record_id": "abc", "value": 1},
        {"record_id": 42, "value": 2},
        {"record_id": "xyz", "value": 3},
    ]
    # The (type, str) sort key prevents `<` between str and int from crashing.
    out = list(run_parallel(seed=0, fn=_double_value, items=records, workers=1))
    assert len(out) == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_input_yields_empty_output() -> None:
    out = list(run_parallel(seed=0, fn=_double_value, items=[], workers=4))
    assert out == []


def test_workers_zero_is_serial_fast_path() -> None:
    records = _records(5)
    out = list(run_parallel(seed=0, fn=_double_value, items=records, workers=0))
    assert len(out) == 5


def test_run_parallel_propagates_worker_exception_serial() -> None:
    records = _records(5)
    with pytest.raises(ValueError, match="kaboom"):
        list(run_parallel(seed=0, fn=_failing_worker, items=records, workers=1))


def test_run_parallel_propagates_worker_exception_parallel() -> None:
    records = _records(5)
    with pytest.raises(ValueError, match="kaboom"):
        list(run_parallel(seed=0, fn=_failing_worker, items=records, workers=2))


def test_missing_record_id_raises_materialize_error() -> None:
    bad_records: list[Mapping[str, Any]] = [
        {"record_id": "x", "value": 1},
        {"value": 2},
    ]
    with pytest.raises(MaterializeError, match="record_id"):
        list(run_parallel(seed=0, fn=_double_value, items=bad_records, workers=1))


# ---------------------------------------------------------------------------
# Determinism integration: same input + seed -> same output across runs
# ---------------------------------------------------------------------------


def test_same_seed_same_input_same_output_across_runs() -> None:
    records = _records(15)
    a = list(run_parallel(seed=99, fn=_identity_with_seed, items=records, workers=2))
    b = list(run_parallel(seed=99, fn=_identity_with_seed, items=records, workers=2))
    assert a == b


def test_different_seed_yields_different_seeds_per_record() -> None:
    records = _records(5)
    a = list(run_parallel(seed=1, fn=_identity_with_seed, items=records, workers=1))
    b = list(run_parallel(seed=2, fn=_identity_with_seed, items=records, workers=1))
    a_seeds = [r["seen_seed"] for r in a]
    b_seeds = [r["seen_seed"] for r in b]
    assert a_seeds != b_seeds


# Parametrize once over worker counts for the headline determinism check.
@pytest.mark.parametrize("workers", [1, 2, 4])
def test_determinism_across_worker_counts(workers: int) -> None:
    records = _records(12)
    out = list(run_parallel(seed=7, fn=_double_value, items=records, workers=workers))
    expected = sorted(
        ({**r, "value": r["value"] * 2} for r in records),
        key=lambda r: r["record_id"],
    )
    assert out == expected


# Sanity: PID is an example of why per-record seed must NOT depend on the
# worker process; we don't actually inspect it but this comment documents
# that introducing os.getpid() into per_record_seed would break the
# contract.
def test_serial_mode_uses_main_process() -> None:
    main_pid = os.getpid()
    records = _records(3)

    def _check_pid(record: Mapping[str, Any], prs: int) -> dict[str, Any]:
        del prs
        out = dict(record)
        out["pid"] = os.getpid()
        return out

    out = list(run_parallel(seed=0, fn=_check_pid, items=records, workers=1))
    assert all(r["pid"] == main_pid for r in out)
