# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: ``sample_per_class`` Filters operation.

FR-FILTER-1 (Story H.j): balanced per-class subsampling with optional
partition tagging and disjoint-pool selection. Shares the stratified-by-
label sampling + tagging mechanics with ``sample_per_class_fractional``
via ``filters_stratified_sampling.stratified_seeded_sample``.

Two modes, distinguished by whether ``label`` is supplied:

- **Destructive (``label`` omitted):** returns exactly ``n_per_class``
  records per class. Use when the balanced subsample is itself the
  desired filter output.
- **Non-destructive tagging (``label`` set):** returns the full record
  set, with the chosen ``n_per_class`` per class carrying ``label`` in
  ``sample_per_class_tags``. The destructive cut happens later — either
  via another ``sample_per_class`` with ``exclude_already_labeled``
  (disjoint-pool case) or via ``drop_by_label`` (Story H.l).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datarefinery.core.errors import PluginError
from datarefinery.plugins.image_classification.filters_stratified_sampling import (
    TAG_FIELD,
    stratified_seeded_sample,
)
from datarefinery.recipe.models import SamplePerClassParams

__all__ = ["TAG_FIELD", "sample_per_class"]

Record = Mapping[str, Any]


def sample_per_class(
    records: list[Record],
    params: Mapping[str, Any],
    *,
    label_field: str | None,
) -> list[Record]:
    """Balanced subsample of ``n_per_class`` records per label."""
    if label_field is None:
        raise PluginError("sample_per_class requires Labels.field to be declared")
    seed = params.get("seed")
    if not isinstance(seed, int):
        raise PluginError(f"sample_per_class requires integer 'seed' (got {type(seed).__name__})")
    parsed = SamplePerClassParams.model_validate({k: v for k, v in params.items() if k != "seed"})

    return stratified_seeded_sample(
        records,
        seed=seed,
        label_field=label_field,
        n_for_class=lambda _label: parsed.n_per_class,
        label=parsed.label,
        exclude_already_labeled=parsed.exclude_already_labeled,
    )
