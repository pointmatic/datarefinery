# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Path-template grammar for Sinks (Story I.d).

The grammar is the smallest one that covers the v1 use cases documented
in `phase-i-intermediate-artifact-persistence-spec.md` § 3.5:

- ``{field}`` substitutes the record's value of ``field`` as a string.
- ``{field|filter}`` applies one of: ``stem``, ``lower``, ``upper``,
  ``str``.
- ``{split}`` is a special variable resolved from the split being
  written, not from the record dict.

Paths are interpreted relative to the cache instance directory; a
template that escapes the instance root (via ``..`` or an absolute
prefix) is rejected at validate time by
:func:`template_escapes_root`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from datarefinery.core.errors import MaterializeError

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_VALID_FILTERS = frozenset({"stem", "lower", "upper", "str"})


def parse_template(template: str) -> list[tuple[str, str | None] | str]:
    """Parse ``template`` into an alternating sequence of literal and
    placeholder segments. Each placeholder is a ``(field, filter)``
    tuple where ``filter`` is one of :data:`_VALID_FILTERS` or ``None``.

    Raises ``ValueError`` if the template has an unmatched brace or
    references an unknown filter.
    """
    # Unmatched braces: a stray '{' or '}' that does not belong to a
    # complete `{...}` placeholder is a malformed template.
    stripped = _PLACEHOLDER_RE.sub("", template)
    if "{" in stripped or "}" in stripped:
        raise ValueError(f"sink path_template has unmatched brace: {template!r}")

    parts: list[tuple[str, str | None] | str] = []
    last = 0
    for m in _PLACEHOLDER_RE.finditer(template):
        if m.start() > last:
            parts.append(template[last : m.start()])
        body = m.group(1).strip()
        if not body:
            raise ValueError(f"sink path_template has empty placeholder: {template!r}")
        if "|" in body:
            field, _, filt = body.partition("|")
            field = field.strip()
            filt = filt.strip()
            if filt not in _VALID_FILTERS:
                raise ValueError(
                    f"sink path_template references unknown filter {filt!r} "
                    f"(valid filters: {sorted(_VALID_FILTERS)!r})"
                )
            parts.append((field, filt))
        else:
            parts.append((body, None))
        last = m.end()
    if last < len(template):
        parts.append(template[last:])
    return parts


def render_template(
    template: str,
    *,
    record: Mapping[str, Any],
    split: str,
) -> str:
    """Substitute placeholders in ``template`` against ``record`` + ``split``.

    Raises :class:`MaterializeError` if a referenced field is missing
    from ``record`` (the only resolution failure that can occur at
    runtime; the template itself is parsed at validate time).
    """
    parts = parse_template(template)
    out: list[str] = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
            continue
        field, filt = part
        if field == "split":
            value: Any = split
        else:
            if field not in record:
                raise MaterializeError(
                    f"sink path_template references missing field {field!r} "
                    f"on record (record_id={record.get('record_id')!r}, "
                    f"split={split!r})"
                )
            value = record[field]
        out.append(_apply_filter(value, filt))
    return "".join(out)


def _apply_filter(value: Any, filt: str | None) -> str:
    if filt is None:
        return str(value)
    if filt == "stem":
        return PurePosixPath(str(value)).stem
    if filt == "lower":
        return str(value).lower()
    if filt == "upper":
        return str(value).upper()
    if filt == "str":
        return str(value)
    # parse_template guarantees a valid filter; this branch is
    # defensive only.
    raise ValueError(f"unknown filter {filt!r}")  # pragma: no cover


def template_escapes_root(template: str) -> bool:
    """Return True if ``template`` could resolve outside the instance directory.

    Detection looks at the static template — absolute paths and
    ``..`` traversal segments are rejected. Runtime field values that
    happen to contain ``..`` are *not* checked here; recipe authors are
    expected to declare templates whose static structure is safe and
    to choose fields whose values do not contain traversal segments.
    """
    if not template:
        return False
    # Absolute on POSIX or via a Windows-style drive prefix.
    if template.startswith("/") or (len(template) >= 2 and template[1] == ":"):
        return True
    # Strip placeholders so a literal '..' in a placeholder body
    # (e.g. an unlikely field name) does not raise a false positive.
    static = _PLACEHOLDER_RE.sub("X", template)
    parts = Path(static).parts
    return any(p == ".." for p in parts)
