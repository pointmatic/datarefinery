# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Sinks (Story I.d) — disk-output declarations captured at materialize time.

See `docs/specs/phase-i-intermediate-artifact-persistence-spec.md` for
the design. Public surface:

- :func:`template.render_template`: per-record path resolution.
- :func:`template.parse_template`: parse-time validation hook.
- :func:`template.template_escapes_root`: validator-side path-escape check.
- :func:`writers.write_png_per_record`: the v1 writer.
- :func:`runner.execute_sinks`: stage-hook entry point used by the runner.
- :class:`runner.SinkResult`: per-sink materialize summary surfaced into the manifest.
"""

from datarefinery.pipeline.sinks.runner import SinkResult, execute_sinks
from datarefinery.pipeline.sinks.template import (
    parse_template,
    render_template,
    template_escapes_root,
)
from datarefinery.pipeline.sinks.writers import write_png_per_record

__all__ = [
    "SinkResult",
    "execute_sinks",
    "parse_template",
    "render_template",
    "template_escapes_root",
    "write_png_per_record",
]
