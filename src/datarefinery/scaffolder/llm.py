# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-17 optional LLM enhancement layer.

``lmentry`` is a lazy import - DataRefinery never imports it from the
deterministic path (per features.md FR-17 #2 and tech-spec). This module
is the only entry point that may touch the optional extra; callers
must pass ``enhance=True`` to the scaffolder to opt in.

Edge-case behaviors per FR-17:

- ``lmentry`` not installed -> ``PluginError`` pointing at ``[llm]``.
- Offline detection succeeds (we are offline) -> warning note appended
  to the recipe; the deterministic recipe is emitted as if ``enhance``
  had not been requested.

v1 enhancement is a placeholder: the LLM-driven judgment work
(column-name semantics, augmentation policy suggestions, plain-English
comments) lands post-v1. The v1 implementation exercises the lazy
import + offline detection plumbing so DataMachine consumers and the
``[llm]`` extra can begin coding against the contract.
"""

from __future__ import annotations

import socket
from collections.abc import Mapping
from typing import Any

from datarefinery.core.errors import PluginError


def enhance(
    recipe: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Apply LLM enhancement; return ``(possibly-augmented recipe, notes)``.

    Notes are surfaced in the scaffolded YAML header so users see what
    the enhancement layer did (or skipped). The recipe dict is copied
    before mutation so callers' inputs are untouched.
    """
    try:
        import lmentry  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as exc:
        raise PluginError(
            "LLM enhancement requested but `lmentry` is not installed. "
            "Install with: pip install 'datarefinery[llm]'"
        ) from exc

    out = dict(recipe)
    notes: list[str] = []
    if not _is_online():
        notes.append(
            "LLM enhancement skipped: offline detection failed. "
            "Deterministic recipe emitted unchanged."
        )
        return out, notes

    notes.append(
        "LLM enhancement applied (v1 placeholder; recipe unchanged). "
        "Full LLM-driven recipe judgment lands post-v1."
    )
    return out, notes


def _is_online(host: str = "8.8.8.8", port: int = 53, timeout: float = 2.0) -> bool:
    """Probe outbound connectivity via a UDP-level DNS reachability check.

    Public for monkey-patching in tests; otherwise an internal detail.
    """
    try:
        socket.setdefaulttimeout(timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
        return True
    except OSError:
        return False
