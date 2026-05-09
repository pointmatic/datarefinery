# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Plugin-contract test parametrization (Story E.h).

The contract tests in this directory split into two layers:

- **Generic** (``test_protocol.py``): every plugin discovered via the
  entry-point group ``datarefinery.plugins`` is parametrized through the
  ``plugin`` fixture and asserted to satisfy the cross-plugin contract
  (sane ``supported_sections``, valid ``OperationSpec`` per declared op,
  and ``is_stub()`` reflecting the actual ``operation_factory``
  behavior).
- **Plugin-specific** (``test_image_classification.py``,
  ``test_tabular.py``, ``test_text.py``): per-plugin schema assertions
  that go beyond the protocol — operation lists, parameter schemas,
  invariants specific to the plugin's domain.

Adding a new plugin to the package automatically opts it into the
generic contract suite via this fixture; no per-plugin file is
required just to satisfy the protocol.
"""

from __future__ import annotations

import pytest

from datarefinery.plugins.base import Plugin
from datarefinery.plugins.discovery import discover_plugins


def _discovered() -> dict[str, Plugin]:
    return discover_plugins()


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize tests that consume the ``plugin`` fixture.

    Discovery runs once per collection; the result is fanned out as one
    test invocation per plugin with the plugin name as the test id so
    failures call out which plugin tripped the contract.
    """
    if "plugin" not in metafunc.fixturenames:
        return
    discovered = _discovered()
    metafunc.parametrize(
        "plugin",
        list(discovered.values()),
        ids=list(discovered.keys()),
    )
