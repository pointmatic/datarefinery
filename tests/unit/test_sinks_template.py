# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the Sink path-template grammar (Story I.d).

Covers field substitution, the v1 filter set (`stem`, `lower`, `upper`,
`str`), the `{split}` special variable, missing-field error, and the
parse-time path-escape check.
"""

from __future__ import annotations

import pytest

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.sinks.template import (
    parse_template,
    render_template,
    template_escapes_root,
)


def test_render_substitutes_field() -> None:
    out = render_template(
        "exports/{label}/{record_id}.png",
        record={"label": "cat", "record_id": "abc123"},
        split="train",
    )
    assert out == "exports/cat/abc123.png"


def test_render_with_split_variable() -> None:
    out = render_template(
        "exports/{split}/{record_id}.png",
        record={"record_id": "r1"},
        split="val",
    )
    assert out == "exports/val/r1.png"


def test_render_stem_filter_on_path_value() -> None:
    out = render_template(
        "exports/{source_path|stem}.png",
        record={"source_path": "data/raw/cifar-10/train/1234.png"},
        split="train",
    )
    assert out == "exports/1234.png"


def test_render_lower_and_upper_filters() -> None:
    assert (
        render_template(
            "{label|lower}/{label|upper}",
            record={"label": "CaT"},
            split="train",
        )
        == "cat/CAT"
    )


def test_render_str_filter_coerces_integer() -> None:
    out = render_template(
        "sev{severity|str}/{record_id}.png",
        record={"severity": 3, "record_id": "r"},
        split="train",
    )
    assert out == "sev3/r.png"


def test_render_missing_field_raises_materialize_error() -> None:
    with pytest.raises(MaterializeError, match="missing field"):
        render_template(
            "{corruption}/{record_id}.png",
            record={"record_id": "r"},
            split="train",
        )


def test_parse_rejects_unknown_filter() -> None:
    with pytest.raises(ValueError, match="unknown filter"):
        parse_template("{label|wat}")


def test_parse_rejects_malformed_brace() -> None:
    with pytest.raises(ValueError):
        parse_template("exports/{label")


def test_template_escapes_root_detects_dotdot() -> None:
    assert template_escapes_root("../outside/{record_id}.png") is True
    assert template_escapes_root("a/../../b/{record_id}.png") is True


def test_template_escapes_root_allows_nested() -> None:
    assert template_escapes_root("a/b/c/{record_id}.png") is False


def test_template_escapes_root_rejects_absolute_path() -> None:
    assert template_escapes_root("/etc/passwd") is True


def test_render_field_value_with_path_separator_strict() -> None:
    # Field values that themselves contain '/' do flow through verbatim
    # — the validator's path-escape check works on the template, not on
    # runtime field values. Documenting current behaviour so a future
    # change is a deliberate choice.
    out = render_template(
        "exports/{label}/{record_id}.png",
        record={"label": "a/b", "record_id": "r"},
        split="train",
    )
    assert out == "exports/a/b/r.png"
