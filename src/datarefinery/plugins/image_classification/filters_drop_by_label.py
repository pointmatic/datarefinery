# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: ``drop_by_label`` Filters operation.

FR-FILTER-3 (Story H.l): drop records carrying any of the named tags.
The destructive companion to FR-FILTER-1 / FR-FILTER-2 tagging — reads
``sample_per_class_tags`` (written by ``sample_per_class`` /
``sample_per_class_fractional``) and removes any record whose tag set
intersects ``labels``.

Records without the tag field are passed through unchanged. Label values
that no record carries are no-ops rather than errors, by design.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datarefinery.plugins.image_classification.filters_stratified_sampling import (
    TAG_FIELD,
)
from datarefinery.recipe.models import DropByLabelParams

Record = Mapping[str, Any]


def drop_by_label(
    records: list[Record],
    params: Mapping[str, Any],
    *,
    label_field: str | None,
) -> list[Record]:
    """Drop records carrying any tag in ``params['labels']``."""
    del label_field  # tag-based; does not depend on Labels.field
    parsed = DropByLabelParams.model_validate(dict(params))
    drop = set(parsed.labels)
    return [r for r in records if not drop.intersection(r.get(TAG_FIELD, ()))]
