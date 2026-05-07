# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Execution-context runtime configuration.

Data-pipeline semantics never read from `RuntimeConfig`; only execution
context does. Recipe is the authoritative source for what the pipeline does
(see `project-essentials.md` "Recipe is authoritative for data-pipeline
semantics").
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_ENV_CACHE_ROOT = "DATAREFINERY_CACHE_ROOT"
_ENV_LOG_LEVEL = "DATAREFINERY_LOG_LEVEL"
_ENV_LOG_TARGET = "DATAREFINERY_LOG_TARGET"
_ENV_PLUGIN_PATH = "DATAREFINERY_PLUGIN_PATH"
_ENV_WORKERS = "DATAREFINERY_WORKERS"


class RuntimeConfig(BaseModel):
    """Frozen execution-context configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cache_root: Path = Path("./data")
    log_level: str = "INFO"
    log_target: str | None = None
    plugin_path: tuple[Path, ...] = ()
    workers: int = 1

    @classmethod
    def resolve(
        cls,
        *,
        cache_root: Path | None = None,
        log_level: str | None = None,
        log_target: str | None = None,
        plugin_path: Iterable[Path] | None = None,
        workers: int | None = None,
        env: Mapping[str, str] | None = None,
    ) -> RuntimeConfig:
        """Build a `RuntimeConfig` honoring the CLI > env > default precedence.

        Each keyword argument represents a CLI-supplied value. `None` means
        the CLI did not specify the field; environment variables are then
        consulted; finally the model defaults apply. `env` defaults to
        `os.environ` and is overridable for testing.
        """
        env_map = env if env is not None else os.environ

        resolved_cache_root = (
            cache_root
            if cache_root is not None
            else _maybe_path(env_map.get(_ENV_CACHE_ROOT))
        )
        resolved_log_level = (
            log_level
            if log_level is not None
            else _nonempty(env_map.get(_ENV_LOG_LEVEL))
        )
        resolved_log_target = (
            log_target
            if log_target is not None
            else _nonempty(env_map.get(_ENV_LOG_TARGET))
        )
        resolved_plugin_path = _resolve_plugin_path(plugin_path, env_map)
        resolved_workers = (
            workers
            if workers is not None
            else _maybe_int(env_map.get(_ENV_WORKERS))
        )

        overrides: dict[str, object] = {}
        if resolved_cache_root is not None:
            overrides["cache_root"] = resolved_cache_root
        if resolved_log_level is not None:
            overrides["log_level"] = resolved_log_level
        if resolved_log_target is not None:
            overrides["log_target"] = resolved_log_target
        if resolved_plugin_path is not None:
            overrides["plugin_path"] = tuple(resolved_plugin_path)
        if resolved_workers is not None:
            overrides["workers"] = resolved_workers
        return cls(**overrides)


def _maybe_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _maybe_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _nonempty(value: str | None) -> str | None:
    return value if value else None


def _resolve_plugin_path(
    cli_value: Iterable[Path] | None, env_map: Mapping[str, str]
) -> Sequence[Path] | None:
    if cli_value is not None:
        cli_list = list(cli_value)
        if cli_list:
            return cli_list
    raw = env_map.get(_ENV_PLUGIN_PATH, "")
    if not raw:
        return None
    return [Path(p) for p in raw.split(os.pathsep) if p]
