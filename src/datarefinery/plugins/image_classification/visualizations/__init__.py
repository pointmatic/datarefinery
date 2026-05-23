# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Image-classification plugin: FR-VIZ matplotlib-backed visualizations.

These ops differ from the Pillow-backed visualizations in
``operations/visualizations.py``: they emit one PNG per *split* (or
other sub-key), so their ``render()`` returns
``Mapping[str, bytes]`` rather than a single ``bytes`` payload. The
pipeline stage writes each entry as ``<op.name>_<key>.png`` under
``report/visualizations/``.
"""
