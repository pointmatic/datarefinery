# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: Featurizations operations (Story C.i).

Each op follows the Featurizations operation handle interface in
``datarefinery.pipeline.stages.featurizations``: a stateless object with
``fit`` and ``apply`` methods, plus a ``fit_on_train: bool`` attribute
mirroring the plugin's ``OperationSpec``. ``label_from_path``,
``image_size_stats`` (Story C.i), and ``flatten`` (Story I.m / G9) are
no-fit. ``categorical_encode`` (Story I.l / G3) supports both a
recipe-declared ``vocabulary`` mode (no-fit) and a fit-on-train mode
that persists the vocabulary under
``fitted_statistics/<op_name>/vocabulary.parquet`` and replays it on
every other declared split.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePath
from typing import Any

import numpy as np
import pyarrow as pa

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


_CATEGORICAL_ORDERINGS = ("alphabetical", "first_seen")


class CategoricalEncodeOp:
    """Encode a string-valued categorical input as an integer id.

    Two modes:

    - **Recipe-declared vocabulary** (``params.vocabulary`` set, no fit
      phase): the vocabulary is fixed by the recipe and the encoding is
      deterministic across runs without any persisted statistics.
    - **Fit-on-train** (``params.vocabulary`` unset): the vocabulary is
      derived from the train split's labels per the ``ordering`` policy
      (``alphabetical`` default, ``first_seen`` alternative), persisted
      to ``fitted_statistics/<op_name>/vocabulary.parquet``, and used on
      every declared split. Vocabulary may also be imported from a
      sibling instance via ``params.stats_from_instance`` (FR-TRANS-1).
    """

    fit_on_train: bool = True

    def fit(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> FittedValues:
        del output_field, label_field
        if "vocabulary" in params:
            return FittedValues(
                scalars={},
                vectors={"vocabulary": pa.table({"value": list(params["vocabulary"])})},
            )
        if not inputs:
            raise PluginError("categorical_encode requires at least one input field")
        source = inputs[0]
        ordering = str(params.get("ordering", "alphabetical"))
        if ordering not in _CATEGORICAL_ORDERINGS:
            raise PluginError(
                f"categorical_encode 'ordering' must be one of "
                f"{list(_CATEGORICAL_ORDERINGS)!r} (got {ordering!r})"
            )
        values = [str(r[source]) for r in records if source in r]
        if ordering == "alphabetical":
            vocab = sorted(set(values))
        else:
            vocab = list(dict.fromkeys(values))
        return FittedValues(scalars={}, vectors={"vocabulary": pa.table({"value": vocab})})

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
        del label_field
        if not inputs:
            raise PluginError("categorical_encode requires at least one input field")
        source = inputs[0]
        output_dtype = np.dtype(str(params.get("output_dtype", "int32")))
        if "vocabulary" in params:
            vocab = list(params["vocabulary"])
        elif "vocabulary" in fitted.vectors:
            vocab = fitted.vectors["vocabulary"].column("value").to_pylist()
        else:
            raise PluginError(
                "categorical_encode: no vocabulary available; either declare "
                "params.vocabulary or wire fit_source / stats_from_instance"
            )
        index = {label: i for i, label in enumerate(vocab)}
        out: list[Record] = []
        for r in records:
            raw = r.get(source)
            if raw is None:
                raise PluginError(f"categorical_encode: record missing input field {source!r}")
            key = str(raw)
            if key not in index:
                raise PluginError(f"categorical_encode: label {key!r} not in vocabulary {vocab!r}")
            new = dict(r)
            new[output_field] = output_dtype.type(index[key])
            out.append(new)
        return out


class FlattenOp:
    """Reshape a multi-dimensional input field to a 1-D vector.

    Deterministic, no fit phase. Writes ``output_field`` alongside the
    source field — the source is preserved so a downstream consumer can
    still observe the multi-dimensional view (e.g., a CNN-shaped variant
    and an MLP-shaped variant of the same recipe).
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
        if len(inputs) != 1:
            raise PluginError(
                f"flatten requires exactly one input field (got {len(inputs)}: {inputs!r})"
            )
        source = inputs[0]
        out: list[Record] = []
        for r in records:
            raw = r.get(source)
            if raw is None:
                raise PluginError(f"flatten: record missing input field {source!r}")
            new = dict(r)
            new[output_field] = np.asarray(raw).reshape(-1)
            out.append(new)
        return out
