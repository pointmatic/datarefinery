# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.l: the cache-identity resolution surface is reachable top-level.

A consumer should locate an instance via the blessed resolver without
spelunking submodules — and without reimplementing the cache-key math.
"""

from __future__ import annotations


def test_resolve_instance_is_top_level_importable() -> None:
    from datarefinery import resolve_instance

    assert callable(resolve_instance)


def test_status_report_is_top_level_importable() -> None:
    from datarefinery import StatusReport, resolve_status

    assert isinstance(StatusReport, type)
    assert callable(resolve_status)


def test_resolve_instance_in_dunder_all() -> None:
    import datarefinery

    assert "resolve_instance" in datarefinery.__all__
    assert "StatusReport" in datarefinery.__all__
