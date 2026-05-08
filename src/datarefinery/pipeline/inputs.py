# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Disk-backed input loader for the materialize CLI verb (FR-3).

Disk loading was intentionally left out of :class:`PipelineRunner` so
the runner stays focused on stage orchestration. The materialize CLI
verb invokes :func:`load_raw_records` to inflate ``recipe.Input.sources``
into a list of records plus a per-source SHA-256 content hash dict for
cache-key construction.

v1 supports the ``image_classification`` plugin's ``image_folder`` source
type. Tabular and text plugins are stubs (Story C.c) and refuse with a
documented :class:`PluginError` until their full implementations land
post-v1.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from datarefinery.cache.layout import dataset_dir
from datarefinery.core.errors import PluginError, RecipeError
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import InputSource, Recipe

Record = dict[str, Any]
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


def load_raw_records(
    recipe: Recipe,
    plugin: Plugin,
) -> tuple[list[Record], dict[str, str]]:
    """Inflate `recipe.Input.sources` into records + per-source content hashes.

    Returns ``(records, raw_input_hashes)``. ``raw_input_hashes`` maps
    each input source name to a SHA-256 hex digest over its content,
    suitable for `compute_cache_key`. Records carry plugin-specific
    fields; for image_classification the keys are
    ``record_id``, ``image``, ``path``, plus ``label`` if the recipe
    declares ``Labels.source.kind == "direct"``. When the label is
    derived (e.g., via ``label_from_path``) the loader leaves the
    field unset so the featurization stage can produce it without
    colliding with a pre-populated value.
    """
    if plugin.name == "image_classification":
        attach_label = recipe.Labels.source.kind == "direct"
        return _load_image_classification(
            recipe.Input.sources, attach_label=attach_label
        )
    if plugin.name in {"tabular", "text"}:
        raise PluginError(
            f"materialize: input loading for plugin {plugin.name!r} is not "
            f"available in v1; the {plugin.name} plugin is a stub."
        )
    raise PluginError(
        f"materialize: no disk-backed input loader registered for "
        f"plugin {plugin.name!r}"
    )


def _load_image_classification(
    sources: list[InputSource],
    *,
    attach_label: bool,
) -> tuple[list[Record], dict[str, str]]:
    records: list[Record] = []
    hashes: dict[str, str] = {}
    seen_ids: set[str] = set()

    for src in sources:
        if src.type != "image_folder":
            raise RecipeError(
                f"image_classification loader: source {src.name!r} has "
                f"type={src.type!r}; expected 'image_folder'"
            )
        root = Path(src.path)
        if not root.is_dir():
            raise RecipeError(
                f"image_classification loader: source {src.name!r} path "
                f"{root!s} is not a directory"
            )
        per_source = _load_one_image_folder(
            src.name, root, seen_ids, attach_label=attach_label
        )
        records.extend(per_source)
        hashes[src.name] = _hash_image_folder(root)

    return records, hashes


def _load_one_image_folder(
    source_name: str,
    root: Path,
    seen_ids: set[str],
    *,
    attach_label: bool,
) -> list[Record]:
    classes = sorted(p.name for p in root.iterdir() if p.is_dir())
    if not classes:
        raise RecipeError(
            f"image_classification loader: source {source_name!r} root "
            f"{root!s} has no class subdirectories"
        )
    out: list[Record] = []
    for cls in classes:
        cls_dir = root / cls
        for ext in _IMAGE_EXTENSIONS:
            for path in sorted(cls_dir.glob(f"*{ext}")):
                rid = f"{source_name}/{cls}/{path.name}"
                if rid in seen_ids:
                    raise RecipeError(
                        f"image_classification loader: duplicate record_id "
                        f"{rid!r} across input sources"
                    )
                seen_ids.add(rid)
                with Image.open(path) as im:
                    arr = np.asarray(im)
                record: Record = {
                    "record_id": rid,
                    "image": arr,
                    "path": str(path),
                }
                if attach_label:
                    record["label"] = cls
                out.append(record)
    if not out:
        raise RecipeError(
            f"image_classification loader: source {source_name!r} root "
            f"{root!s} contains no .png/.jpg/.jpeg files"
        )
    return out


def _hash_image_folder(root: Path) -> str:
    """Order-stable content hash for one image_folder source.

    Hashes ``(<relative_path>:<sha256(file_bytes)>;)`` for every regular
    file under ``root`` in sorted order. Sorting and the explicit
    delimiter make the digest invariant under filesystem-walk order.
    """
    h = hashlib.sha256()
    for path in sorted(_iter_files(root)):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        content_digest = hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii")
        h.update(rel)
        h.update(b":")
        h.update(content_digest)
        h.update(b";")
    return h.hexdigest()


def _iter_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def reload_dataset(
    instance_dir: Path,
    plugin: Plugin,
) -> dict[str, list[Record]]:
    """Re-inflate the persisted per-split dataset for report re-rendering.

    Reads ``<instance>/dataset/<split>.jsonl`` and, for plugins whose
    visualizations need raw bytes, reloads the on-disk artifacts via
    each record's source-path field. For ``image_classification`` the
    ``path`` field is read with PIL into a numpy array, restoring the
    ``image`` key the runner had at materialize time.

    Used by :func:`reporting.report.re_render_report` to drive
    drift.json + visualization regeneration without rerunning the
    pipeline.
    """
    if plugin.name != "image_classification":
        raise PluginError(
            f"reload_dataset: not implemented for plugin {plugin.name!r}"
        )

    root = dataset_dir(instance_dir)
    if not root.is_dir():
        raise RecipeError(
            f"reload_dataset: no dataset directory at {root}"
        )

    splits: dict[str, list[Record]] = {}
    for split_path in sorted(root.glob("*.jsonl")):
        split_name = split_path.stem
        records: list[Record] = []
        with split_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if "path" in row:
                    image_path = Path(row["path"])
                    if image_path.exists():
                        with Image.open(image_path) as im:
                            row["image"] = np.asarray(im)
                records.append(row)
        splits[split_name] = records
    return splits


def hash_inputs(recipe: Recipe, plugin: Plugin) -> Mapping[str, str]:
    """Return the per-source input hash dict without inflating records.

    Useful for resolving cache identity ahead of materialize (e.g., the
    ``status`` verb in Story D.f).
    """
    if plugin.name != "image_classification":
        raise PluginError(
            f"hash_inputs: no disk-backed loader registered for "
            f"plugin {plugin.name!r}"
        )
    return {
        src.name: _hash_image_folder(Path(src.path))
        for src in recipe.Input.sources
    }
