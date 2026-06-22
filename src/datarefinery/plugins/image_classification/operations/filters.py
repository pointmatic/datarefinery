# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: Filters operations (Story C.f, FR-8).

Operation signature for the Filters section is documented in
``datarefinery.pipeline.stages.filters``. Both operations are stateless
functions of (records, params, label_field).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from datarefinery.core.errors import PluginError

Record = Mapping[str, Any]


def filter_by_label(
    records: list[Record],
    params: Mapping[str, Any],
    *,
    label_field: str | None,
) -> list[Record]:
    """Include or exclude records by label-set membership."""
    if label_field is None:
        raise PluginError("filter_by_label requires Labels.field to be declared")
    labels_param = params.get("labels")
    if not isinstance(labels_param, (list, tuple)):
        raise PluginError(
            f"filter_by_label 'labels' must be a list/tuple (got {type(labels_param).__name__})"
        )
    label_set = set(labels_param)
    action = params["action"]
    if action == "include":
        return [r for r in records if r.get(label_field) in label_set]
    if action == "exclude":
        return [r for r in records if r.get(label_field) not in label_set]
    raise PluginError(f"filter_by_label 'action' must be 'include' or 'exclude' (got {action!r})")


def random_sample(
    records: list[Record],
    params: Mapping[str, Any],
    *,
    label_field: str | None,
) -> list[Record]:
    """Sample records reproducibly given a seed.

    Exactly one of ``fraction`` or ``n`` must be supplied; ``seed`` is
    required (validator check 18 enforces; this op re-checks defensively).
    Output preserves the original record order so downstream stages see
    a stable subsequence rather than a shuffled order.
    """
    del label_field
    seed = params.get("seed")
    if not isinstance(seed, int):
        raise PluginError(f"random_sample requires integer 'seed' (got {type(seed).__name__})")
    fraction = params.get("fraction")
    n_param = params.get("n")
    if (fraction is None) == (n_param is None):
        raise PluginError("random_sample requires exactly one of 'fraction' or 'n'")
    n_records = len(records)
    if fraction is not None:
        if not 0.0 <= float(fraction) <= 1.0:
            raise PluginError(f"random_sample 'fraction' must be in [0, 1] (got {fraction!r})")
        target = int(n_records * float(fraction))
    else:
        target = int(n_param)  # type: ignore[arg-type]
        if target < 0:
            raise PluginError(f"random_sample 'n' must be non-negative (got {n_param!r})")
    target = min(target, n_records)
    rng = np.random.default_rng(seed)
    indices = rng.permutation(n_records)[:target]
    chosen = sorted(int(i) for i in indices)
    return [records[i] for i in chosen]
