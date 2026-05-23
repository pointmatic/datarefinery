# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-VIZ-3: ``corruption_severity_grid`` visualization.

A single ``K-corruption x L-severity`` figure: each subplot tiles the
same ``n_images`` base records side-by-side under that
``(corruption_type, severity)`` combination. Renders as one PNG,
persisted as ``<op.name>.png``.

Sourcing: the op is self-contained — ``corruption_types`` /
``severities`` / ``n_images`` come from the visualization's own params,
not from ``recipe.Generation``. This lets a recipe declare a
corruption-coverage visualization independent of (or in addition to)
any ``imagecorruptions_apply`` Generation op.

Train-only sampling by default (highest cardinality, best for
reporting). The Hendrycks-Dietterich corruption *vocabulary* lives in
the dependency-free ``_corruption_names`` module so recipe-time
validation of the params works without the ``[corruptions]`` extras;
the actual ``corrupt(...)`` call lazy-imports the backend and surfaces
a friendly install-pointer error when the extras are missing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
from matplotlib.figure import Figure
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from datarefinery.plugins.image_classification._corruption_names import (
    CORRUPTION_NAMES_ALL,
)
from datarefinery.plugins.image_classification.visualizations._render import (
    encode_png,
    new_figure,
)

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from types import ModuleType

Record = Mapping[str, Any]

CORRUPTIONS_EXTRAS_INSTALL_HINT = (
    "corruption_severity_grid requires the [corruptions] extras. "
    "Install with: pip install 'ml-datarefinery[corruptions]'"
)


def _load_backend() -> ModuleType:
    """Import the corruption backend with a friendly extras-missing error."""
    try:
        from datarefinery.plugins.image_classification import _corruptions
    except ImportError as exc:
        raise ImportError(CORRUPTIONS_EXTRAS_INSTALL_HINT) from exc
    return _corruptions


class CorruptionSeverityGridParams(BaseModel):
    """Params for ``corruption_severity_grid``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_images: int = Field(gt=0)
    corruption_types: list[str] = Field(min_length=1)
    severities: list[int] = Field(min_length=1)

    @field_validator("severities")
    @classmethod
    def _severities_in_range(cls, value: list[int]) -> list[int]:
        for sev in value:
            if sev not in (1, 2, 3, 4, 5):
                raise ValueError(f"severities must each be in [1, 5] (got {sev})")
        return value

    @model_validator(mode="after")
    def _validate_corruption_vocabulary(self) -> CorruptionSeverityGridParams:
        unknown = [c for c in self.corruption_types if c not in CORRUPTION_NAMES_ALL]
        if unknown:
            raise ValueError(
                f"corruption_severity_grid: unknown corruption_types {unknown!r}; "
                f"canonical names are {list(CORRUPTION_NAMES_ALL)!r}"
            )
        if len(set(self.corruption_types)) != len(self.corruption_types):
            raise ValueError(
                f"corruption_severity_grid: corruption_types contains duplicates "
                f"({self.corruption_types!r})"
            )
        return self


# ---------------------------------------------------------------------------
# Figure construction
# ---------------------------------------------------------------------------


def _tile_horizontal(images: Sequence[np.ndarray]) -> np.ndarray:
    """Concatenate a list of uint8 RGB images horizontally into one image.

    Assumes all images share the same shape (the corruption backend
    preserves H x W x 3).
    """
    if not images:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    return np.concatenate(list(images), axis=1)


def build_corruption_severity_grid_figure(
    cells: Mapping[tuple[str, int], list[np.ndarray]],
    *,
    corruption_types: Sequence[str],
    severities: Sequence[int],
) -> Figure:
    """Build a ``len(corruption_types) x len(severities)`` subplot figure.

    Each subplot shows the same ``n_images`` base images horizontally
    concatenated under one ``(corruption, severity)`` combination.
    Rows = corruption types (top to bottom); columns = severities
    (left to right).
    """
    n_rows = len(corruption_types)
    n_cols = len(severities)
    # Width grows with severities and the per-cell tile-strip; height with corruptions.
    fig = new_figure(
        width_in=max(3.0, n_cols * 2.0),
        height_in=max(2.0, n_rows * 1.6 + 0.5),
    )
    for r_idx, corruption in enumerate(corruption_types):
        for c_idx, severity in enumerate(severities):
            ax = fig.add_subplot(n_rows, n_cols, r_idx * n_cols + c_idx + 1)
            images = cells.get((corruption, severity), [])
            tile = _tile_horizontal(images)
            ax.imshow(tile)
            ax.set_xticks([])
            ax.set_yticks([])
            if r_idx == 0:
                ax.set_title(f"sev {severity}")
            if c_idx == 0:
                ax.set_ylabel(corruption)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Op handle
# ---------------------------------------------------------------------------


class CorruptionSeverityGridOp:
    """Visualization handle for ``corruption_severity_grid``.

    Returns single PNG ``bytes``; the pipeline stage writes it as
    ``<op.name>.png``. Lazy-imports the corruption backend inside
    ``render(...)`` so the plugin remains importable without the
    ``[corruptions]`` extras (mirrors ``generation_imagecorruptions``).
    """

    def render(
        self,
        splits: Mapping[str, list[Record]],
        params: Mapping[str, Any],
        *,
        label_field: str | None,
        recipe: Any = None,
    ) -> bytes:
        del label_field, recipe
        p = CorruptionSeverityGridParams(**dict(params))
        train_records = list(splits.get("train", []))
        if len(train_records) < p.n_images:
            raise ValueError(
                f"corruption_severity_grid: train split has {len(train_records)} "
                f"records, fewer than n_images={p.n_images}"
            )
        backend = _load_backend()

        base_records = train_records[: p.n_images]
        base_images: list[np.ndarray] = []
        for rec in base_records:
            arr = np.asarray(rec["image"])
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
            if arr.ndim == 2:
                arr = np.stack([arr, arr, arr], axis=-1)
            base_images.append(arr)

        # Deterministic RNG seeded by the corruption + severity pair so the
        # same grid renders byte-identically across runs.
        cells: dict[tuple[str, int], list[np.ndarray]] = {}
        for corruption in p.corruption_types:
            for severity in p.severities:
                # Stable seed: Python's hash() randomizes strings/tuples per
                # process. sha256 gives byte-determinism across runs (an
                # FR-4 reproducibility-contract requirement).
                payload = f"{corruption}|{severity}".encode()
                digest = hashlib.sha256(payload).digest()
                rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
                cell_images: list[np.ndarray] = []
                for img in base_images:
                    corrupted = backend.corrupt(
                        img,
                        corruption_name=corruption,
                        severity=severity,
                        rng=rng,
                    )
                    cell_images.append(_to_uint8_rgb(np.asarray(corrupted)))
                cells[(corruption, severity)] = cell_images

        fig = build_corruption_severity_grid_figure(
            cells,
            corruption_types=p.corruption_types,
            severities=p.severities,
        )
        return encode_png(fig)


def _to_uint8_rgb(arr: np.ndarray) -> np.ndarray:
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    elif arr.ndim == 3 and arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    # PIL ensures consistent shape for matplotlib.imshow.
    return np.asarray(Image.fromarray(arr))
