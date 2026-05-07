# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Exception hierarchy for DataRefinery.

Every module raises subclasses of `DataRefineryError`. The CLI's exit-code
mapping (in `datarefinery.cli._exit_codes`) splits these into:

- user errors (exit 1): `RecipeError`, `ValidationError`, `ContractError`,
  `MaterializeError`.
- system errors (exit 2): `PluginError`, `CacheError`.
"""

from __future__ import annotations


class DataRefineryError(Exception):
    """Base class for all DataRefinery-raised errors."""


class RecipeError(DataRefineryError):
    """Recipe loading, parsing, or schema-version failure (FR-1, FR-22)."""


class ValidationError(DataRefineryError):
    """Recipe validator check failure (FR-2)."""


class PluginError(DataRefineryError):
    """Plugin discovery, duplicate-name, or missing-extra failure (FR-16)."""


class ContractError(DataRefineryError):
    """InputContracts or OutputExpectations failure (FR-23)."""


class MaterializeError(DataRefineryError):
    """Pipeline stage failure or atomic-promote failure (FR-3, FR-5)."""


class CacheError(DataRefineryError):
    """Cache key, layout, or clean-related failure (FR-4, FR-21)."""
