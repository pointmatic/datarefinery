# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Project-wide pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.fixtures.build_cifar10_shaped import (
    DEFAULT_NUM_CLASSES,
    DEFAULT_PER_CLASS,
    build_cifar10_shaped,
)


@pytest.fixture(scope="session")
def cifar10_shaped_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Session-scoped CIFAR-10-shaped ImageFolder fixture.

    Built once per session (10 classes x 5 PNGs = 50 images) and reused
    across every test that consumes it. Tests that need a fresh root
    (e.g., to mutate the inputs) should copy from this directory or
    call :func:`tests.fixtures.build_cifar10_shaped.build_cifar10_shaped`
    directly into their own ``tmp_path``.
    """
    root = tmp_path_factory.mktemp("cifar10_shaped")
    build_cifar10_shaped(root)
    yield root


__all__ = [
    "DEFAULT_NUM_CLASSES",
    "DEFAULT_PER_CLASS",
    "cifar10_shaped_dir",
]
