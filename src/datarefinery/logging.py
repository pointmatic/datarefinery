# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""JSON line-formatted operational logging for DataRefinery.

`get_logger(name)` returns a logger under the `datarefinery` namespace and
idempotently attaches a `NullHandler` (library safety) plus a
`JsonFormatter` `StreamHandler(stderr)` to the package logger so calls
produce one JSON object per line. Importing this module alone does not add
handlers anywhere; root logging is never touched.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Final

_PACKAGE: Final = "datarefinery"

# `LogRecord` standard attributes — anything *not* in this set on
# `record.__dict__` was put there by a caller via `extra=...`.
_RECORD_RESERVED: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """Format each `LogRecord` as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        ts = (
            datetime.fromtimestamp(record.created, UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "stage": getattr(record, "stage", None),
            "op_id": getattr(record, "op_id", None),
            "message": record.getMessage(),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RECORD_RESERVED and key not in payload
        }
        if extras:
            payload["extras"] = extras
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _has_json_stream_handler(logger: logging.Logger) -> bool:
    return any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.NullHandler)
        and isinstance(h.formatter, JsonFormatter)
        for h in logger.handlers
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the `datarefinery` namespace.

    Idempotently attaches a `NullHandler` (library safety) and a
    `JsonFormatter` `StreamHandler(stderr)` to the package logger so callers
    see structured output. Root logging is never configured.
    """
    package_logger = logging.getLogger(_PACKAGE)
    if not any(isinstance(h, logging.NullHandler) for h in package_logger.handlers):
        package_logger.addHandler(logging.NullHandler())
    if not _has_json_stream_handler(package_logger):
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(JsonFormatter())
        package_logger.addHandler(stream_handler)
    if package_logger.level == logging.NOTSET:
        package_logger.setLevel(logging.INFO)
    qualified = (
        name
        if name == _PACKAGE or name.startswith(f"{_PACKAGE}.")
        else f"{_PACKAGE}.{name}"
    )
    return logging.getLogger(qualified)
