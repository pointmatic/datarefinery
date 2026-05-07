# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Precedence tests for `RuntimeConfig.resolve`: CLI > env > default."""

from __future__ import annotations

import os
from pathlib import Path

from datarefinery.core.config import RuntimeConfig


def test_defaults_apply_when_no_cli_and_no_env() -> None:
    cfg = RuntimeConfig.resolve(env={})
    assert cfg.cache_root == Path("./data")
    assert cfg.log_level == "INFO"
    assert cfg.log_target is None
    assert cfg.plugin_path == ()
    assert cfg.workers == 1


def test_env_only_populates_every_field() -> None:
    env = {
        "DATAREFINERY_CACHE_ROOT": "/tmp/dr-cache",
        "DATAREFINERY_LOG_LEVEL": "DEBUG",
        "DATAREFINERY_LOG_TARGET": "/var/log/dr.log",
        "DATAREFINERY_PLUGIN_PATH": f"/a{os.pathsep}/b",
        "DATAREFINERY_WORKERS": "4",
    }
    cfg = RuntimeConfig.resolve(env=env)
    assert cfg.cache_root == Path("/tmp/dr-cache")
    assert cfg.log_level == "DEBUG"
    assert cfg.log_target == "/var/log/dr.log"
    assert cfg.plugin_path == (Path("/a"), Path("/b"))
    assert cfg.workers == 4


def test_cli_only_populates_every_field() -> None:
    cfg = RuntimeConfig.resolve(
        cache_root=Path("/cli/cache"),
        log_level="ERROR",
        log_target="/cli/log",
        plugin_path=[Path("/cli/p1"), Path("/cli/p2")],
        workers=8,
        env={},
    )
    assert cfg.cache_root == Path("/cli/cache")
    assert cfg.log_level == "ERROR"
    assert cfg.log_target == "/cli/log"
    assert cfg.plugin_path == (Path("/cli/p1"), Path("/cli/p2"))
    assert cfg.workers == 8


def test_cli_overrides_env_when_both_are_set() -> None:
    env = {
        "DATAREFINERY_CACHE_ROOT": "/env/cache",
        "DATAREFINERY_LOG_LEVEL": "DEBUG",
        "DATAREFINERY_LOG_TARGET": "/env/log",
        "DATAREFINERY_PLUGIN_PATH": "/env/p",
        "DATAREFINERY_WORKERS": "4",
    }
    cfg = RuntimeConfig.resolve(
        cache_root=Path("/cli/cache"),
        log_level="WARNING",
        log_target="/cli/log",
        plugin_path=[Path("/cli/p")],
        workers=2,
        env=env,
    )
    assert cfg.cache_root == Path("/cli/cache")
    assert cfg.log_level == "WARNING"
    assert cfg.log_target == "/cli/log"
    assert cfg.plugin_path == (Path("/cli/p"),)
    assert cfg.workers == 2


def test_partial_overrides_fall_through_to_env_then_default() -> None:
    env = {"DATAREFINERY_LOG_LEVEL": "DEBUG"}
    cfg = RuntimeConfig.resolve(workers=16, env=env)
    assert cfg.workers == 16
    assert cfg.log_level == "DEBUG"
    assert cfg.cache_root == Path("./data")  # neither CLI nor env -> default


def test_empty_env_strings_treated_as_unset() -> None:
    env = {
        "DATAREFINERY_CACHE_ROOT": "",
        "DATAREFINERY_LOG_LEVEL": "",
        "DATAREFINERY_PLUGIN_PATH": "",
        "DATAREFINERY_WORKERS": "",
    }
    cfg = RuntimeConfig.resolve(env=env)
    assert cfg.cache_root == Path("./data")
    assert cfg.log_level == "INFO"
    assert cfg.plugin_path == ()
    assert cfg.workers == 1


def test_plugin_path_env_splits_on_os_pathsep() -> None:
    env = {"DATAREFINERY_PLUGIN_PATH": os.pathsep.join(["/a", "/b", "/c"])}
    cfg = RuntimeConfig.resolve(env=env)
    assert cfg.plugin_path == (Path("/a"), Path("/b"), Path("/c"))


def test_runtime_config_is_frozen() -> None:
    import pytest
    from pydantic import ValidationError as PydanticValidationError

    cfg = RuntimeConfig.resolve(env={})
    with pytest.raises((PydanticValidationError, TypeError, AttributeError)):
        cfg.cache_root = Path("/elsewhere")  # type: ignore[misc]


def test_runtime_config_rejects_extra_fields() -> None:
    import pytest
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        RuntimeConfig(cache_root=Path("/x"), unknown_field="oops")  # type: ignore[call-arg]
