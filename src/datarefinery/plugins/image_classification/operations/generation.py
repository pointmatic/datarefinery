# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: Generation operations (Story C.g, FR-9).

Operation signature for Generation is documented in
``datarefinery.pipeline.stages.generation``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from datarefinery.core.errors import PluginError
from datarefinery.recipe.models import FieldSpec

Record = Mapping[str, Any]


def duplicate_minority_class(
    records: list[Record],
    *,
    seed: int,
    inputs: list[str],
    output_schema: Mapping[str, FieldSpec],
    params: Mapping[str, Any],
    label_field: str | None,
) -> list[Record]:
    """Sample-with-replacement from minority classes to match the majority.

    Each non-majority class is brought up to the majority class's count by
    drawing additional records (with replacement) from that class's own
    pool. The op returns only the new records; the stage concatenates.

    v1 simplification: target count is the majority class size (no
    user-tunable target). Class iteration is stably ordered so output is
    seed-deterministic across hash-randomization variants.
    """
    del inputs, output_schema, params  # consumed via Output schema validation in stage
    if label_field is None:
        raise PluginError("duplicate_minority_class requires Labels.field to be declared")
    by_class: dict[Any, list[Record]] = {}
    for r in records:
        by_class.setdefault(r.get(label_field), []).append(r)
    if not by_class:
        return []
    target = max(len(v) for v in by_class.values())
    rng = np.random.default_rng(seed)
    new_records: list[Record] = []
    for cls in sorted(by_class.keys(), key=lambda x: (type(x).__name__, repr(x))):
        existing = by_class[cls]
        n_needed = target - len(existing)
        if n_needed <= 0:
            continue
        idx = rng.integers(0, len(existing), size=n_needed)
        new_records.extend(existing[int(i)] for i in idx)
    return new_records
