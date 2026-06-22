# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Minimal `_test_dummy` plugin for plugin-discovery tests.

Loaded ad-hoc via `discover_plugins(extra_paths=[...])` — not registered
under the `datarefinery.plugins` entry-point group.
"""

from datarefinery.plugins.base import Operation, OperationSpec


class _TestDummyPlugin:
    name = "_test_dummy"
    supported_sections = frozenset({"Filters", "Transformations"})
    schema_version = 1

    def __init__(self) -> None:
        self.supported_operations = {
            "noop": OperationSpec(
                applicable_sections=frozenset({"Filters", "Transformations"}),
            ),
        }

    def operation_factory(self, section: str, op_name: str) -> Operation:
        del section, op_name
        return lambda record: record

    def is_stub(self) -> bool:
        return False

    def recommended_params(self, section: str, op_name: str) -> dict[str, object]:
        del section, op_name
        return {}

    def extension_keys(self) -> dict[str, set[str]]:
        return {}


PLUGIN = _TestDummyPlugin()
