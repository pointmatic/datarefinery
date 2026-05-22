# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: ``sample_per_class_fractional`` Filters op.

FR-FILTER-2 (Story H.k): per-class subsampling at independent rates.
Per-class surviving count = ``floor(n_per_class_base * fractions.get(label, 1.0))``.
Missing labels default to 1.0 (full base count); ``fractions=0.0`` drops
that class entirely.

Shares the stratified-by-label sampling + tagging mechanics with
``sample_per_class`` via
``filters_stratified_sampling.stratified_seeded_sample``. The two ops
differ only in how the per-class target is derived.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datarefinery.core.errors import PluginError
from datarefinery.plugins.image_classification.filters_stratified_sampling import (
    stratified_seeded_sample,
)
from datarefinery.recipe.models import SamplePerClassFractionalParams

Record = Mapping[str, Any]


def sample_per_class_fractional(
    records: list[Record],
    params: Mapping[str, Any],
    *,
    label_field: str | None,
) -> list[Record]:
    """Per-class subsample with class-specific surviving counts."""
    if label_field is None:
        raise PluginError("sample_per_class_fractional requires Labels.field to be declared")
    seed = params.get("seed")
    if not isinstance(seed, int):
        raise PluginError(
            f"sample_per_class_fractional requires integer 'seed' (got {type(seed).__name__})"
        )
    parsed = SamplePerClassFractionalParams.model_validate(
        {k: v for k, v in params.items() if k != "seed"}
    )

    base = parsed.n_per_class_base
    fractions = parsed.fractions

    def n_for_class(class_label: Any) -> int:
        fraction = fractions.get(class_label, 1.0)
        return int(base * fraction)  # floor for non-negative floats

    return stratified_seeded_sample(
        records,
        seed=seed,
        label_field=label_field,
        n_for_class=n_for_class,
        label=parsed.label,
        exclude_already_labeled=parsed.exclude_already_labeled,
    )
