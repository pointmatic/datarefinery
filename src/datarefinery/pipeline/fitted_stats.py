# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-6 Fitted-statistics persistence.

Layout under ``<instance>/fitted_statistics/`` (per tech-spec):

    fitted_statistics/
      <op_id>/
        scalars.json     # {name: value, ...} for all scalar stats
        <name>.parquet   # one parquet table per vector stat

Scalars carry their JSON-native types (`float`, `int`, `str`, `bool`).
Vectors are persisted as ``pyarrow.Table`` instances - never opaque
pickles, per FR-6 #3.

The class is callable both during materialization (the runner constructs
one rooted at the in-flight temp directory and ``put_*`` -s during
fit-on-train; later it ``get_*`` -s to apply the same statistics across
non-train splits) and after promotion (downstream tools open the
materialized instance read-only via ``Instance.fitted_statistics``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from datarefinery.core.errors import MaterializeError

ScalarValue = float | int | str | bool


class FittedStatistics:
    """Read/write access to one instance's fitted-statistics directory."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Scalars
    # ------------------------------------------------------------------

    def put_scalar(self, op_id: str, name: str, value: ScalarValue) -> None:
        """Store a scalar stat under ``<root>/<op_id>/scalars.json``.

        Multiple ``put_scalar`` calls for the same ``op_id`` accumulate
        into the same JSON object; later writes overwrite the same name.
        """
        if not isinstance(value, (float, int, str, bool)):
            raise MaterializeError(
                f"FittedStatistics.put_scalar: value for {op_id!r}.{name!r} "
                f"is {type(value).__name__}; only float/int/str/bool allowed"
            )
        path = self._scalars_path(op_id)
        existing = self._read_scalars(path) if path.exists() else {}
        existing[name] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, sort_keys=True), encoding="utf-8")

    def get_scalar(self, op_id: str, name: str) -> ScalarValue:
        path = self._scalars_path(op_id)
        if not path.exists():
            raise MaterializeError(
                f"FittedStatistics.get_scalar: no scalars.json for op {op_id!r}"
            )
        scalars = self._read_scalars(path)
        if name not in scalars:
            raise MaterializeError(
                f"FittedStatistics.get_scalar: scalar {name!r} missing for "
                f"op {op_id!r} (have: {sorted(scalars)!r})"
            )
        value = scalars[name]
        if not isinstance(value, (float, int, str, bool)):
            raise MaterializeError(
                f"FittedStatistics: scalar {name!r} for op {op_id!r} has "
                f"non-scalar type {type(value).__name__}"
            )
        return value

    # ------------------------------------------------------------------
    # Vectors
    # ------------------------------------------------------------------

    def put_vector(self, op_id: str, name: str, table: pa.Table) -> None:
        """Store a vector stat as ``<root>/<op_id>/<name>.parquet``."""
        if not isinstance(table, pa.Table):
            raise MaterializeError(
                f"FittedStatistics.put_vector: value for {op_id!r}.{name!r} "
                f"is {type(table).__name__}; pyarrow.Table required"
            )
        path = self._vector_path(op_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)  # type: ignore[no-untyped-call]

    def get_vector(self, op_id: str, name: str) -> pa.Table:
        path = self._vector_path(op_id, name)
        if not path.exists():
            raise MaterializeError(
                f"FittedStatistics.get_vector: no {name}.parquet for "
                f"op {op_id!r}"
            )
        return pq.read_table(path)  # type: ignore[no-untyped-call]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _op_dir(self, op_id: str) -> Path:
        return self._root / op_id

    def _scalars_path(self, op_id: str) -> Path:
        return self._op_dir(op_id) / "scalars.json"

    def _vector_path(self, op_id: str, name: str) -> Path:
        return self._op_dir(op_id) / f"{name}.parquet"

    @staticmethod
    def _read_scalars(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MaterializeError(
                f"FittedStatistics: malformed scalars.json at {path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise MaterializeError(
                f"FittedStatistics: scalars.json at {path} is not a JSON "
                f"object (got {type(data).__name__})"
            )
        return data
