# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Plugin discovery via entry-point group plus developer extra paths."""

from __future__ import annotations

import importlib.metadata
import importlib.util
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType

from datarefinery.core.errors import PluginError
from datarefinery.plugins.base import Plugin

ENTRY_POINT_GROUP = "datarefinery.plugins"
PLUGIN_MODULE_ATTR = "PLUGIN"

_REQUIRED_PLUGIN_ATTRS = (
    "name",
    "supported_sections",
    "supported_operations",
    "schema_version",
    "operation_factory",
    "is_stub",
)


def discover_plugins(
    extra_paths: Iterable[Path] | None = None,
) -> dict[str, Plugin]:
    """Discover all installed plugins keyed by `Plugin.name`.

    Sources, in order:

    1. Entry-point group ``datarefinery.plugins``.
    2. Each entry in `extra_paths` — a directory of `*.py` plugin modules
       or a single `.py` file — scanned for a top-level ``PLUGIN``
       attribute satisfying the `Plugin` protocol.

    Raises `PluginError` on duplicate names or unloadable extra-path entries.
    """
    plugins: dict[str, Plugin] = {}

    for entry in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        loaded = entry.load()
        if isinstance(loaded, type):
            loaded = loaded()
        _register(plugins, loaded)

    for path in extra_paths or ():
        for module_path in _enumerate_module_files(path):
            try:
                module = _import_isolated_module(module_path)
            except Exception as exc:
                raise PluginError(
                    f"failed to import plugin from {module_path}: {exc}"
                ) from exc
            plugin_obj = getattr(module, PLUGIN_MODULE_ATTR, None)
            if plugin_obj is None:
                continue
            _register(plugins, plugin_obj)

    return plugins


def _enumerate_module_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix == ".py":
        return [path]
    if path.is_dir():
        return sorted(p for p in path.glob("*.py") if not p.name.startswith("_"))
    raise PluginError(f"plugin path does not exist: {path}")


def _import_isolated_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_dr_plugin_{path.stem}_{abs(hash(str(path.resolve())))}",
        path,
    )
    if spec is None or spec.loader is None:
        raise PluginError(f"could not import plugin module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _register(registry: dict[str, Plugin], plugin: object) -> None:
    if not _looks_like_plugin(plugin):
        raise PluginError(
            f"{type(plugin).__name__} does not satisfy the Plugin protocol"
        )
    name = plugin.name  # type: ignore[attr-defined]
    if name in registry:
        raise PluginError(f"duplicate plugin name: {name!r}")
    registry[name] = plugin  # type: ignore[assignment]


def _looks_like_plugin(obj: object) -> bool:
    return all(hasattr(obj, attr) for attr in _REQUIRED_PLUGIN_ATTRS)
