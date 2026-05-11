# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for `datarefinery.logging`."""

from __future__ import annotations

import json
import logging

from datarefinery.logging import JsonFormatter, get_logger


def _make_record(**extras: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="datarefinery.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, value in extras.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_single_line_with_required_fields() -> None:
    formatter = JsonFormatter()
    record = _make_record(stage="train", op_id="resize_0")
    output = formatter.format(record)

    assert "\n" not in output
    payload = json.loads(output)
    for field in ("ts", "level", "logger", "stage", "op_id", "message"):
        assert field in payload, f"missing field {field!r}"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "datarefinery.test"
    assert payload["stage"] == "train"
    assert payload["op_id"] == "resize_0"
    assert payload["message"] == "hello world"


def test_formatter_records_extras_in_extras_bucket() -> None:
    formatter = JsonFormatter()
    record = _make_record(stage="train", op_id="x", custom_key="value")
    payload = json.loads(formatter.format(record))

    assert payload["extras"] == {"custom_key": "value"}


def test_formatter_omits_extras_when_none_present() -> None:
    formatter = JsonFormatter()
    record = _make_record(stage="train", op_id="x")
    payload = json.loads(formatter.format(record))

    assert "extras" not in payload


def test_library_import_does_not_configure_root_logger() -> None:
    # pytest itself may attach handlers to root for log capture; the claim
    # is that *we* do not — i.e., no handler on root carries our JsonFormatter.
    import datarefinery.logging  # noqa: F401  side-effect import under test

    root_handlers = logging.getLogger().handlers
    assert not any(isinstance(getattr(h, "formatter", None), JsonFormatter) for h in root_handlers)


def test_get_logger_returns_namespaced_child() -> None:
    log = get_logger("recipe.loader")
    assert log.name == "datarefinery.recipe.loader"


def test_get_logger_round_trips_extras_through_json_output() -> None:
    log = get_logger("smoke")
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    capture = _Capture()
    log.addHandler(capture)
    try:
        log.info("hi", extra={"stage": "s", "op_id": "o"})
    finally:
        log.removeHandler(capture)

    assert len(captured) == 1
    payload = json.loads(JsonFormatter().format(captured[0]))
    assert payload["stage"] == "s"
    assert payload["op_id"] == "o"
    assert payload["message"] == "hi"
