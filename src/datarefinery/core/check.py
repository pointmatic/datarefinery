# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-18 environment-soundness probe.

`build_check_report()` is the library entry point; the CLI verb in
``datarefinery.cli.commands.check_cmd`` renders it as a `rich` table.
The probe never imports heavyweight optional deps speculatively — it
checks for spec presence first via ``importlib.util.find_spec`` and only
loads a module if its presence is the thing being reported.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import platform
from pathlib import Path

from datarefinery import __version__
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import PluginError
from datarefinery.plugins.base import Plugin
from datarefinery.plugins.discovery import ENTRY_POINT_GROUP, discover_plugins


@dataclasses.dataclass(frozen=True)
class PluginInfo:
    """One discovered plugin's identifying details."""

    name: str
    schema_version: int
    is_stub: bool
    module: str
    source: str | None  # filesystem path of the plugin module, if available


@dataclasses.dataclass(frozen=True)
class DependencyStatus:
    """One optional dependency or accelerator probe result."""

    name: str
    available: bool
    detail: str
    required: bool = False


@dataclasses.dataclass(frozen=True)
class CheckReport:
    """Structured environment-soundness report."""

    python_version: str
    platform: str
    datarefinery_version: str
    entry_point_group: str
    extra_plugin_paths: tuple[Path, ...]
    plugins: tuple[PluginInfo, ...]
    optional_extras: tuple[DependencyStatus, ...]
    accelerators: tuple[DependencyStatus, ...]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """``True`` iff no soundness failure was reported."""
        return not self.failures


def build_check_report(
    config: RuntimeConfig | None = None,
) -> CheckReport:
    """Probe the runtime environment and return a `CheckReport`.

    Plugin-discovery failures are caught and recorded as `failures` so
    the report itself remains constructible. Anything that is *only*
    missing optional capability surfaces in `optional_extras` /
    `accelerators` with `available=False`.
    """
    config = config if config is not None else RuntimeConfig()
    extra_paths = tuple(config.plugin_path)

    failures: list[str] = []
    plugins: tuple[PluginInfo, ...]
    try:
        discovered = discover_plugins(extra_paths=extra_paths or None)
        plugins = tuple(_plugin_info(p) for p in discovered.values())
    except PluginError as exc:
        plugins = ()
        failures.append(f"plugin discovery failed: {exc}")

    return CheckReport(
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.machine()}",
        datarefinery_version=__version__,
        entry_point_group=ENTRY_POINT_GROUP,
        extra_plugin_paths=extra_paths,
        plugins=tuple(sorted(plugins, key=lambda p: p.name)),
        optional_extras=_probe_optional_extras(),
        accelerators=_probe_accelerators(),
        failures=tuple(failures),
    )


def _plugin_info(plugin: Plugin) -> PluginInfo:
    cls = type(plugin)
    module = cls.__module__
    source: str | None = None
    spec = importlib.util.find_spec(module)
    if spec is not None and spec.origin:
        source = spec.origin
    return PluginInfo(
        name=plugin.name,
        schema_version=plugin.schema_version,
        is_stub=plugin.is_stub(),
        module=module,
        source=source,
    )


def _probe_optional_extras() -> tuple[DependencyStatus, ...]:
    """Optional `[llm]` extra: ``lmentry`` for FR-17 enhancement."""
    return (_probe_module("lmentry", purpose="LLM-enhanced init scaffolder"),)


def _probe_accelerators() -> tuple[DependencyStatus, ...]:
    """Optional GPU acceleration probes (Metal, CUDA).

    DataRefinery itself does not run on GPU in v1; the probe is
    informational for downstream tooling. We report what the *current*
    Python environment can see — if torch is not installed, we say so
    rather than guessing from `platform`.
    """
    torch_spec = importlib.util.find_spec("torch")
    if torch_spec is None:
        msg = "torch not installed; install torch to enable runtime detection"
        return (
            DependencyStatus(name="Metal (mps)", available=False, detail=msg),
            DependencyStatus(name="CUDA", available=False, detail=msg),
        )

    # torch is present; ask it what's available. Import is gated on the
    # spec check so a stripped-down environment doesn't pay the cost.
    import torch  # type: ignore[import-not-found]

    metal_available = bool(
        getattr(torch.backends, "mps", None) is not None
        and torch.backends.mps.is_available()
    )
    cuda_available = bool(torch.cuda.is_available())
    return (
        DependencyStatus(
            name="Metal (mps)",
            available=metal_available,
            detail="torch.backends.mps.is_available()",
        ),
        DependencyStatus(
            name="CUDA",
            available=cuda_available,
            detail=f"torch.cuda.is_available() (devices={torch.cuda.device_count()})",
        ),
    )


def _probe_module(name: str, *, purpose: str) -> DependencyStatus:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return DependencyStatus(
            name=name,
            available=False,
            detail=f"not installed ({purpose})",
        )
    return DependencyStatus(
        name=name,
        available=True,
        detail=f"installed ({purpose})",
    )


__all__ = [
    "CheckReport",
    "DependencyStatus",
    "PluginInfo",
    "build_check_report",
]
