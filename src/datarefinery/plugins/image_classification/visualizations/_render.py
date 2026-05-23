# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Shared matplotlib helpers for FR-VIZ visualizations.

Bypasses ``matplotlib.pyplot`` to keep the renders free of global state
and deterministic regardless of how the host process has configured the
backend. PNG encoding strips the timestamp metadata fields that
matplotlib otherwise injects, so identical inputs yield byte-identical
PNG output (a requirement for reporting-mode reproducibility — see
``features.md`` FR-4 and the ``report/visualizations/`` cross-repo
contract in FR-15).
"""

from __future__ import annotations

import io

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

DEFAULT_DPI = 100


def new_figure(width_in: float, height_in: float) -> Figure:
    """Return a Figure with an Agg canvas attached and DPI pinned.

    Uses ``Figure`` directly (not ``pyplot.figure``) to avoid touching
    pyplot's global state.
    """
    fig = Figure(figsize=(width_in, height_in), dpi=DEFAULT_DPI)
    FigureCanvasAgg(fig)
    return fig


def encode_png(fig: Figure) -> bytes:
    """Encode ``fig`` to PNG bytes with timestamp metadata suppressed."""
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=DEFAULT_DPI,
        metadata={"Software": None, "Creation Time": None, "Date": None},
    )
    return buf.getvalue()
