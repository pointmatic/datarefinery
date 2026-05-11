# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: Featurizations operations (Story C.i).

Both ops follow the Featurizations operation handle interface in
``datarefinery.pipeline.stages.featurizations``: a stateless object with
``fit`` (no-op for these v1 ops) and ``apply`` methods, plus a
``fit_on_train: bool`` attribute mirroring the plugin's
``OperationSpec``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePath
from typing import Any

import numpy as np

from datarefinery.core.errors import PluginError
from datarefinery.pipeline.stages.transformations import FittedValues

Record = Mapping[str, Any]


class LabelFromPathOp:
    """Derive a label from a record's path field.

    Default ``source`` is ``parent_directory_name`` - the standard
    ImageFolder convention where ``cats/foo.jpg`` yields ``"cats"``.
    """

    fit_on_train: bool = False

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> FittedValues:
        del records, params, inputs, output_field, label_field
        return FittedValues()

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> list[Record]:
        del fitted, label_field
        if not inputs:
            raise PluginError(
                "label_from_path requires at least one input field naming "
                "the path (e.g., 'path' or 'filename')"
            )
        path_field = inputs[0]
        source = str(params.get("source", "parent_directory_name"))
        derive = _PATH_SOURCES.get(source)
        if derive is None:
            raise PluginError(
                f"label_from_path 'source' must be one of "
                f"{sorted(_PATH_SOURCES)!r} (got {source!r})"
            )
        out: list[Record] = []
        for r in records:
            raw = r.get(path_field)
            if raw is None:
                raise PluginError(f"label_from_path: record missing input field {path_field!r}")
            derived = derive(PurePath(str(raw)))
            new = dict(r)
            new[output_field] = derived
            out.append(new)
        return out


_PATH_SOURCES: dict[str, Any] = {
    "parent_directory_name": lambda p: p.parent.name,
    "filename": lambda p: p.name,
    "stem": lambda p: p.stem,
}


class ImageSizeStatsOp:
    """Featurize each record with its image's spatial dimensions.

    Produces a list ``[H, W, C]`` (or ``[H, W]`` for 2-D images) under
    ``output_field``. Useful for downstream filtering or as a sanity-
    check featurizer; deterministic, no fit phase.
    """

    fit_on_train: bool = False

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> FittedValues:
        del records, params, inputs, output_field, label_field
        return FittedValues()

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> list[Record]:
        del params, fitted, label_field
        image_field = inputs[0] if inputs else "image"
        out: list[Record] = []
        for r in records:
            img = r.get(image_field)
            if img is None:
                raise PluginError(f"image_size_stats: record missing input field {image_field!r}")
            arr = np.asarray(img)
            if arr.ndim not in (2, 3):
                raise PluginError(
                    f"image_size_stats expects 2-D or 3-D image array (got ndim={arr.ndim})"
                )
            new = dict(r)
            new[output_field] = list(arr.shape)
            out.append(new)
        return out
