# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: ``imagecorruptions_apply`` Generation op.

FR-GEN-1 (Story H.m.2): apply Hendrycks-Dietterich corruptions to image
records. For each input record produce one output record per
``(corruption_type, severity)`` pair, optionally adding an untouched
"preserved-original" copy tagged ``corruption="none"``.

The vendored backend in ``_corruptions`` requires the ``[corruptions]``
extras (``scikit-image`` + ``opencv-python-headless``). The backend is
imported lazily at op-call time and a friendly error pointing at the
extras-install command is raised when the extras are missing. The
corruption-name *vocabulary* lives in ``_corruption_names`` (dependency-
free) so recipe-time validation works without the extras.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import numpy as np

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.workers import per_record_seed
from datarefinery.recipe.models import FieldSpec, ImageCorruptionsApplyParams

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from types import ModuleType

Record = Mapping[str, Any]

CORRUPTIONS_EXTRAS_INSTALL_HINT = (
    "imagecorruptions_apply requires the [corruptions] extras. "
    "Install with: pip install 'ml-datarefinery[corruptions]'"
)


def _load_backend() -> ModuleType:
    """Import the corruption backend with a friendly extras-missing error."""
    try:
        from datarefinery.plugins.image_classification import _corruptions
    except ImportError as exc:
        raise ImportError(CORRUPTIONS_EXTRAS_INSTALL_HINT) from exc
    return _corruptions


def _derive_output_record_id(input_record_id: Any, corruption_name: str, severity: int) -> str:
    payload = f"{input_record_id}|{corruption_name}|{severity}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    return f"{input_record_id}_{corruption_name}_s{severity}_{digest[:8]}"


def imagecorruptions_apply(
    records: list[Record],
    *,
    seed: int,
    inputs: list[str],
    output_schema: Mapping[str, FieldSpec],
    params: Mapping[str, Any],
    label_field: str | None,
) -> list[Record]:
    """Apply Hendrycks-Dietterich corruptions to each input record.

    Returned records are the NEW outputs added by Generation; per the
    stage contract they are concatenated onto the input split. The
    original input records remain in the split untouched.
    """
    del inputs, output_schema, label_field  # consumed elsewhere
    parsed = ImageCorruptionsApplyParams.model_validate(dict(params))
    backend = _load_backend()

    corruption_types = list(parsed.corruption_types)
    severities = list(parsed.severities)
    preserve_original = parsed.preserve_original
    tag_corruption = "corruption" in parsed.tag_fields
    tag_severity = "severity" in parsed.tag_fields
    tag_source_path = "source_path" in parsed.tag_fields

    new_records: list[Record] = []
    for record in records:
        if "record_id" not in record:
            raise MaterializeError("imagecorruptions_apply: input record missing 'record_id' field")
        if "image" not in record:
            raise MaterializeError(
                f"imagecorruptions_apply: input record {record['record_id']!r} missing "
                f"'image' field (numpy uint8 array)"
            )
        image_arr = np.asarray(record["image"])
        if image_arr.dtype != np.uint8:
            raise MaterializeError(
                f"imagecorruptions_apply: record {record['record_id']!r} image dtype must "
                f"be uint8 (got {image_arr.dtype})"
            )
        source_path = record.get("path", record["record_id"])
        prs = per_record_seed(seed, record)
        rng = np.random.default_rng(prs)

        if preserve_original:
            preserved = dict(record)
            preserved["record_id"] = _derive_output_record_id(record["record_id"], "none", 0)
            if tag_corruption:
                preserved["corruption"] = "none"
            if tag_severity:
                preserved["severity"] = 0
            if tag_source_path:
                preserved["source_path"] = source_path
            new_records.append(preserved)

        for corruption_name in corruption_types:
            for severity in severities:
                corrupted = backend.corrupt(
                    image_arr,
                    corruption_name=corruption_name,
                    severity=severity,
                    rng=rng,
                )
                out = dict(record)
                out["image"] = corrupted
                out["record_id"] = _derive_output_record_id(
                    record["record_id"], corruption_name, severity
                )
                if tag_corruption:
                    out["corruption"] = corruption_name
                if tag_severity:
                    out["severity"] = severity
                if tag_source_path:
                    out["source_path"] = source_path
                new_records.append(out)
    return new_records
