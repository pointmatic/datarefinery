# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-18 ``DataRefinery.check()`` library API tests."""

from __future__ import annotations

import dataclasses
import importlib.util
from typing import Any

import pytest

from datarefinery import __version__
from datarefinery.core.check import (
    CheckReport,
    DependencyStatus,
    PluginInfo,
    build_check_report,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.datarefinery import DataRefinery
from datarefinery.core.errors import PluginError


def test_build_check_report_returns_structured_report() -> None:
    report = build_check_report()
    assert isinstance(report, CheckReport)
    assert report.datarefinery_version == __version__
    assert report.python_version
    assert report.entry_point_group == "datarefinery.plugins"


def test_check_lists_installed_plugins() -> None:
    report = build_check_report()
    names = {p.name for p in report.plugins}
    assert {"image_classification", "tabular", "text"} <= names
    image = next(p for p in report.plugins if p.name == "image_classification")
    assert image.is_stub is False
    assert image.module.startswith("datarefinery.plugins.image_classification")
    tabular = next(p for p in report.plugins if p.name == "tabular")
    assert tabular.is_stub is True


def test_check_marks_optional_extras() -> None:
    report = build_check_report()
    extras = {dep.name: dep for dep in report.optional_extras}
    assert "lmentry" in extras
    assert extras["lmentry"].available == (importlib.util.find_spec("lmentry") is not None)


def test_check_reports_accelerators_without_torch_when_missing() -> None:
    """When torch is not installed, accelerators are reported missing
    with a documented message rather than crashing."""
    if importlib.util.find_spec("torch") is not None:
        pytest.skip("torch is installed; this test covers the no-torch branch")
    report = build_check_report()
    accel = {dep.name: dep for dep in report.accelerators}
    assert {"Metal (mps)", "CUDA"} <= set(accel)
    for dep in accel.values():
        assert dep.available is False
        assert "torch" in dep.detail


def test_passed_property_true_on_healthy_environment() -> None:
    report = build_check_report()
    assert report.passed is True


def test_check_records_plugin_discovery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery errors land in `failures` rather than crashing the report."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise PluginError("forced discovery failure for tests")

    monkeypatch.setattr("datarefinery.core.check.discover_plugins", boom)
    report = build_check_report()
    assert report.passed is False
    assert any("forced discovery failure" in msg for msg in report.failures)
    assert report.plugins == ()


def test_datarefinery_check_static_delegates(tmp_path: Any) -> None:
    """The class method shape matches the tech-spec: static + optional config."""
    del tmp_path
    report = DataRefinery.check()
    assert isinstance(report, CheckReport)


def test_datarefinery_check_honors_runtime_config_extra_paths(
    tmp_path: Any,
) -> None:
    """`config.plugin_path` flows into the report's `extra_plugin_paths`."""
    config = RuntimeConfig(plugin_path=(tmp_path,))
    report = DataRefinery.check(config)
    assert report.extra_plugin_paths == (tmp_path,)


def test_dependency_status_dataclass_is_frozen() -> None:
    dep = DependencyStatus(name="x", available=True, detail="d")
    with pytest.raises(dataclasses.FrozenInstanceError):
        dep.available = False  # type: ignore[misc]


def test_plugin_info_dataclass_is_frozen() -> None:
    info = PluginInfo(name="n", schema_version=1, is_stub=False, module="m", source=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.name = "other"  # type: ignore[misc]
