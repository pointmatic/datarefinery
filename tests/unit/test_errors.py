# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Exception hierarchy and exit-code mapping unit tests."""

from __future__ import annotations

import pytest

from datarefinery.cli._exit_codes import (
    EXIT_INTERRUPT,
    EXIT_OK,
    EXIT_SYSTEM,
    EXIT_USER,
    exit_code_for,
)
from datarefinery.core.errors import (
    CacheError,
    ContractError,
    DataRefineryError,
    MaterializeError,
    PluginError,
    RecipeError,
    ValidationError,
)


@pytest.mark.parametrize(
    "subclass",
    [
        RecipeError,
        ValidationError,
        PluginError,
        ContractError,
        MaterializeError,
        CacheError,
    ],
)
def test_subclass_inherits_from_datarefinery_error(
    subclass: type[DataRefineryError],
) -> None:
    assert issubclass(subclass, DataRefineryError)
    assert issubclass(subclass, Exception)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RecipeError("x"), EXIT_USER),
        (ValidationError("x"), EXIT_USER),
        (ContractError("x"), EXIT_USER),
        (MaterializeError("x"), EXIT_USER),
        (PluginError("x"), EXIT_SYSTEM),
        (CacheError("x"), EXIT_SYSTEM),
        (KeyboardInterrupt(), EXIT_INTERRUPT),
        (RuntimeError("x"), EXIT_SYSTEM),
        (ValueError("x"), EXIT_SYSTEM),
        (DataRefineryError("x"), EXIT_USER),
    ],
)
def test_exit_code_mapping(exc: BaseException, expected: int) -> None:
    assert exit_code_for(exc) == expected


def test_documented_exit_code_constants() -> None:
    assert EXIT_OK == 0
    assert EXIT_USER == 1
    assert EXIT_SYSTEM == 2
    assert EXIT_INTERRUPT == 130
