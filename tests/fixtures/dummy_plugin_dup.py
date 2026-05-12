# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Second fixture exposing the same `_test_dummy` name to drive the
duplicate-name failure path in `discover_plugins`.
"""

from datarefinery.plugins.base import Operation, OperationSpec


class _TestDummyDupPlugin:
    name = "_test_dummy"
    supported_sections = frozenset({"Filters"})
    schema_version = 1

    def __init__(self) -> None:
        self.supported_operations = {
            "noop": OperationSpec(applicable_sections=frozenset({"Filters"})),
        }

    def operation_factory(self, section: str, op_name: str) -> Operation:
        del section, op_name
        return lambda record: record

    def is_stub(self) -> bool:
        return False


PLUGIN = _TestDummyDupPlugin()
