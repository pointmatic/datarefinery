# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""The `layout` path-template grammar + shared `path_tree` resolver (Story K.h, FR-K-1).

A `*_tree` input source declares a ``layout`` string describing the directory
structure from the source ``path`` root down to each file. Unlike the sink
``path_template`` grammar (`pipeline/sinks/template.py`), which *substitutes*
record field values into an output path, ``layout`` is a path-segment **matcher**:
it parses an existing directory tree to *extract* roles (the K.f spike memo § 1,
``docs/specs/phase-k-subphase-2-ingestion-resolver-spike.md``). They share the
brace surface for author familiarity but are semantically inverse, so this is a
separate parser, not a reuse of the sink template.

Grammar (one path segment per component, except the wildcards):

- ``{label}`` — the segment whose name is the record's label (subsumes
  ``Labels.source.derivation: parent_directory_name``). At most one.
- ``{split}`` — the segment whose name is the split assignment (folds
  partitioning into the tree). At most one; mutually exclusive with a per-source
  ``InputSource.partition`` (reconciled in the loader).
- ``{file}`` — the terminal file component, matched against the plugin's
  file-extension set. Exactly one, and it must be last.
- ``*`` — exactly one path level, ignored ("category" level).
- ``**`` — any depth (zero or more levels), ignored. At most one.

The resolver delegates enumeration to the shared, symlink-following
``pipeline.inputs.enumerate_files`` (Story K.g), so loader and hasher walk one
file set and the resolver is payload-agnostic — it returns ``(path, record_id,
label?, split?)`` and never decodes (decode stays in the plugin loader).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from datarefinery.core.errors import RecipeError

_LABEL = "{label}"
_SPLIT = "{split}"
_FILE = "{file}"
_STAR = "*"
_GLOBSTAR = "**"
_TOKENS = frozenset({_LABEL, _SPLIT, _FILE, _STAR, _GLOBSTAR})


@dataclass(frozen=True)
class ParsedLayout:
    """A validated ``layout`` template: its ordered component tokens.

    Each component is one of the role tokens (``{label}`` / ``{split}`` /
    ``{file}``), a wildcard (``*`` / ``**``), or a literal path segment.
    """

    components: tuple[str, ...]

    @property
    def has_globstar(self) -> bool:
        return _GLOBSTAR in self.components


@dataclass(frozen=True)
class ResolvedFile:
    """One resolved data file + the roles extracted from its path."""

    path: Path
    record_id: str
    label: str | None
    split: str | None


def parse_layout(layout: str) -> ParsedLayout:
    """Parse + structurally validate a ``layout`` string.

    Raises :class:`RecipeError` on malformed grammar: empty layout/segment, an
    unknown ``{token}``, more than one ``{label}`` / ``{split}`` / ``**``, or a
    missing/non-terminal ``{file}``. (Filesystem-satisfiability and label-source
    consistency are the FR-K-5 validator check's job, Story K.i — not here.)
    """
    if not layout:
        raise RecipeError("layout: must be a non-empty path template")
    components = layout.split("/")
    for comp in components:
        if comp == "":
            raise RecipeError(
                f"layout {layout!r}: empty path segment (check for '//' or leading/trailing '/')"
            )
        if comp.startswith("{") and comp.endswith("}") and comp not in _TOKENS:
            raise RecipeError(
                f"layout {layout!r}: unknown token {comp!r} "
                f"(valid role tokens: {sorted({_LABEL, _SPLIT, _FILE})!r})"
            )
    if components.count(_FILE) != 1:
        raise RecipeError(f"layout {layout!r}: must contain exactly one {_FILE!r} component")
    if components[-1] != _FILE:
        raise RecipeError(f"layout {layout!r}: {_FILE!r} must be the last component")
    if components.count(_LABEL) > 1:
        raise RecipeError(f"layout {layout!r}: at most one {_LABEL!r} component")
    if components.count(_SPLIT) > 1:
        raise RecipeError(f"layout {layout!r}: at most one {_SPLIT!r} component")
    if components.count(_GLOBSTAR) > 1:
        raise RecipeError(f"layout {layout!r}: at most one {_GLOBSTAR!r} component")
    return ParsedLayout(components=tuple(components))


def _match_segments(
    components: tuple[str, ...],
    parts: tuple[str, ...],
    extensions: frozenset[str],
) -> tuple[str | None, str | None] | None:
    """Match the (non-globstar) ``components`` against exactly ``parts``.

    Returns ``(label, split)`` on a match, or ``None`` if the path does not
    conform (wrong length, literal mismatch, or terminal extension not in set).
    """
    if len(components) != len(parts):
        return None
    label: str | None = None
    split: str | None = None
    for comp, part in zip(components, parts, strict=True):
        if comp == _FILE:
            if Path(part).suffix.lower() not in extensions:
                return None
        elif comp == _LABEL:
            label = part
        elif comp == _SPLIT:
            split = part
        elif comp == _STAR:
            continue
        else:  # literal segment
            if comp != part:
                return None
    return label, split


def _match(
    parsed: ParsedLayout, parts: tuple[str, ...], extensions: frozenset[str]
) -> tuple[str | None, str | None] | None:
    """Match a relative path's ``parts`` against ``parsed``; ``(label, split)`` or None.

    With at most one ``**`` (validated by :func:`parse_layout`), the template
    splits into a fixed prefix and suffix around the globstar; ``**`` absorbs any
    depth between them.
    """
    components = parsed.components
    if not parsed.has_globstar:
        return _match_segments(components, parts, extensions)
    idx = components.index(_GLOBSTAR)
    prefix = components[:idx]
    suffix = components[idx + 1 :]
    # ** absorbs >= 0 middle levels, so parts must cover prefix + suffix at least.
    if len(parts) < len(prefix) + len(suffix):
        return None
    head = parts[: len(prefix)]
    tail = parts[len(parts) - len(suffix) :]
    pre = _match_segments(prefix, head, extensions) if prefix else (None, None)
    if pre is None:
        return None
    suf = _match_segments(suffix, tail, extensions)
    if suf is None:
        return None
    # The terminal {file} (and any role tokens) live in the suffix; the prefix
    # carries no role tokens that the grammar would place before a **, except an
    # optional {split}. Merge captures, suffix winning for overlaps (none in v1).
    label = suf[0] if suf[0] is not None else pre[0]
    split = suf[1] if suf[1] is not None else pre[1]
    return label, split


def path_tree(
    root: Path,
    layout: str,
    *,
    extensions: frozenset[str],
    source_name: str,
) -> list[ResolvedFile]:
    """Resolve every data file under ``root`` that matches ``layout``.

    Enumeration is the shared, symlink-following, deterministically-sorted
    :func:`datarefinery.pipeline.inputs.enumerate_files` (Story K.g), so the
    resolver and the input hasher walk one file set. Files that do not match the
    layout (wrong depth, literal mismatch, terminal extension not in
    ``extensions``) are skipped. ``record_id`` is ``f"{source_name}/{rel_posix}"``
    — byte-identical to the bare-folder loaders' ids for the ``{label}/{file}``
    case (the file sits directly under its class dir).
    """
    from datarefinery.pipeline.inputs import enumerate_files

    parsed = parse_layout(layout)
    out: list[ResolvedFile] = []
    for path in enumerate_files(root):
        rel = path.relative_to(root)
        matched = _match(parsed, rel.parts, extensions)
        if matched is None:
            continue
        label, split = matched
        out.append(
            ResolvedFile(
                path=path,
                record_id=f"{source_name}/{rel.as_posix()}",
                label=label,
                split=split,
            )
        )
    return out
