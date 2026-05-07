# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Exception-to-exit-code mapping for the DataRefinery CLI.

Per tech-spec:

| code | meaning                                                       |
|------|---------------------------------------------------------------|
| 0    | success                                                       |
| 1    | user/recipe error (Recipe, Validation, Contract, Materialize) |
| 2    | system error (Plugin, Cache, environment, uncaught)           |
| 130  | SIGINT / Ctrl-C                                               |
"""

from __future__ import annotations

from datarefinery.core.errors import (
    CacheError,
    ContractError,
    DataRefineryError,
    MaterializeError,
    PluginError,
    RecipeError,
    ValidationError,
)

EXIT_OK = 0
EXIT_USER = 1
EXIT_SYSTEM = 2
EXIT_INTERRUPT = 130

_USER_ERROR_TYPES: tuple[type[DataRefineryError], ...] = (
    RecipeError,
    ValidationError,
    ContractError,
    MaterializeError,
)
_SYSTEM_ERROR_TYPES: tuple[type[DataRefineryError], ...] = (
    PluginError,
    CacheError,
)


def exit_code_for(exc: BaseException) -> int:
    """Return the documented CLI exit code for `exc`."""
    if isinstance(exc, KeyboardInterrupt):
        return EXIT_INTERRUPT
    if isinstance(exc, _USER_ERROR_TYPES):
        return EXIT_USER
    if isinstance(exc, _SYSTEM_ERROR_TYPES):
        return EXIT_SYSTEM
    if isinstance(exc, DataRefineryError):
        # Unknown future DataRefineryError subclass — treat as user-facing
        # by default; widen the explicit tuples above when adding new types.
        return EXIT_USER
    return EXIT_SYSTEM
