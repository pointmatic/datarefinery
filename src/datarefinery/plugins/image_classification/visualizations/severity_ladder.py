# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-VIZ-4: ``severity_ladder`` visualization.

For a single ``corruption_type``, render ``n_examples`` train-split
records across all five severities (1..5). Output is an
``n_examples x 5`` matplotlib figure: rows = examples, columns =
severities. Single PNG, persisted as ``<op.name>.png``.

Complements ``corruption_severity_grid`` (H.v) by isolating the
severity dimension for one corruption — useful for documenting how a
single corruption degrades images as severity climbs, without the
visual noise of other corruption types in the same figure.

Self-contained params (not derived from ``recipe.Generation``);
train-only sampling; ``[corruptions]`` extras loaded lazily inside
``render(...)`` so the plugin remains importable without them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
from matplotlib.figure import Figure
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
SEVERITIES: tuple[int, ...] = (1, 2, 3, 4, 5)

CORRUPTIONS_EXTRAS_INSTALL_HINT = (
    "severity_ladder requires the [corruptions] extras. "
    "Install with: pip install 'ml-datarefinery[corruptions]'"
)


def _load_backend() -> ModuleType:
    """Import the corruption backend with a friendly extras-missing error."""
    try:
        from datarefinery.plugins.image_classification import _corruptions
    except ImportError as exc:
        raise ImportError(CORRUPTIONS_EXTRAS_INSTALL_HINT) from exc
    return _corruptions


class SeverityLadderParams(BaseModel):
    """Params for ``severity_ladder``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_examples: int = Field(gt=0)
    corruption_type: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_corruption_vocabulary(self) -> SeverityLadderParams:
        if self.corruption_type not in CORRUPTION_NAMES_ALL:
            raise ValueError(
                f"severity_ladder: unknown corruption_type {self.corruption_type!r}; "
                f"canonical names are {list(CORRUPTION_NAMES_ALL)!r}"
            )
        return self


# ---------------------------------------------------------------------------
# Figure construction
# ---------------------------------------------------------------------------


def build_severity_ladder_figure(
    rows: Sequence[Sequence[np.ndarray]],
    *,
    corruption_type: str,
) -> Figure:
    """Build an ``n_examples x 5`` subplot figure.

    ``rows[i]`` must have length 5 (one image per severity 1..5).
    """
    n_examples = len(rows)
    n_cols = 5
    fig = new_figure(
        width_in=max(3.0, n_cols * 1.4),
        height_in=max(2.0, n_examples * 1.4 + 0.5),
    )
    fig.suptitle(corruption_type)
    for r_idx in range(n_examples):
        for c_idx in range(n_cols):
            ax = fig.add_subplot(n_examples, n_cols, r_idx * n_cols + c_idx + 1)
            ax.imshow(rows[r_idx][c_idx])
            ax.set_xticks([])
            ax.set_yticks([])
            if r_idx == 0:
                ax.set_title(f"sev {c_idx + 1}")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Op handle
# ---------------------------------------------------------------------------


def _to_uint8_rgb(arr: np.ndarray) -> np.ndarray:
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    elif arr.ndim == 3 and arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    return np.asarray(Image.fromarray(arr))


class SeverityLadderOp:
    """Visualization handle for ``severity_ladder``.

    Single PNG return; pipeline stage writes it as ``<op.name>.png``.
    Lazy-imports the corruption backend inside ``render(...)`` so the
    plugin remains importable without the ``[corruptions]`` extras.
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
        p = SeverityLadderParams(**dict(params))
        train_records = list(splits.get("train", []))
        if len(train_records) < p.n_examples:
            raise ValueError(
                f"severity_ladder: train split has {len(train_records)} records, "
                f"fewer than n_examples={p.n_examples}"
            )
        backend = _load_backend()

        base_images: list[np.ndarray] = []
        for rec in train_records[: p.n_examples]:
            arr = np.asarray(rec["image"])
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
            if arr.ndim == 2:
                arr = np.stack([arr, arr, arr], axis=-1)
            base_images.append(arr)

        rows: list[list[np.ndarray]] = []
        for img in base_images:
            row: list[np.ndarray] = []
            for severity in SEVERITIES:
                # Same SHA-256 seeding contract as corruption_severity_grid:
                # stable across processes, FR-4-compatible.
                payload = f"{p.corruption_type}|{severity}".encode()
                digest = hashlib.sha256(payload).digest()
                rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
                corrupted = backend.corrupt(
                    img,
                    corruption_name=p.corruption_type,
                    severity=severity,
                    rng=rng,
                )
                row.append(_to_uint8_rgb(np.asarray(corrupted)))
            rows.append(row)

        fig = build_severity_ladder_figure(rows, corruption_type=p.corruption_type)
        return encode_png(fig)
