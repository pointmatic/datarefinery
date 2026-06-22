# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Disk-backed input loader for the materialize CLI verb (FR-3).

Disk loading was intentionally left out of :class:`PipelineRunner` so
the runner stays focused on stage orchestration. The materialize CLI
verb invokes :func:`load_raw_records` to inflate ``recipe.Input.sources``
into a list of records plus a per-source SHA-256 content hash dict for
cache-key construction.

v1 supports the ``image_classification`` plugin's two source types:

* ``image_folder`` — ImageFolder layout (one class-named subdirectory
  per class); labels come from the subdir name.
* ``image_flat`` — flat directory of image files; labels come from a
  sidecar manifest declared via ``InputSource.label_from``.

Tabular and text plugins are stubs (Story C.c) and refuse with a
documented :class:`PluginError` until their full implementations land
post-v1.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from datarefinery.cache.layout import dataset_dir
from datarefinery.core.errors import MaterializeError, PluginError, RecipeError
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import InputSource, LabelFromSpec, Recipe

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
        return _load_image_classification(recipe.Input.sources, attach_label=attach_label)
    if plugin.name == "audio_classification":
        # Lazy import keeps librosa (and the audio module) out of the core
        # input path; the audio reader decodes loader-side (Story J.p).
        from datarefinery.plugins.audio_classification.inputs import load_audio_records

        attach_label = recipe.Labels.source.kind == "direct"
        return load_audio_records(recipe.Input.sources, attach_label=attach_label)
    if plugin.name in {"tabular", "text"}:
        raise PluginError(
            f"materialize: input loading for plugin {plugin.name!r} is not "
            f"available in v1; the {plugin.name} plugin is a stub."
        )
    raise PluginError(
        f"materialize: no disk-backed input loader registered for plugin {plugin.name!r}"
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
        root = Path(src.path)
        if not root.is_dir():
            raise RecipeError(
                f"image_classification loader: source {src.name!r} path {root!s} is not a directory"
            )
        if src.type == "image_folder":
            if src.label_from is not None:
                raise RecipeError(
                    f"image_classification loader: source {src.name!r} has type "
                    f"'image_folder' with label_from set; image_folder takes labels "
                    f"from class subdirectories, not from a sidecar manifest"
                )
            if src.unlabeled:
                raise RecipeError(
                    f"image_classification loader: source {src.name!r} has type "
                    f"'image_folder' with unlabeled=true; declare type='image_flat' "
                    f"for unlabeled partitions (image_folder derives labels from "
                    f"class subdirectories)"
                )
            per_source = _load_one_image_folder(src.name, root, seen_ids, attach_label=attach_label)
            hashes[src.name] = _hash_image_folder(root)
        elif src.type == "image_flat":
            if src.unlabeled:
                per_source = _load_one_image_flat_unlabeled(src.name, root, seen_ids)
                hashes[src.name] = _hash_image_folder(root)
            else:
                if src.label_from is None:
                    raise RecipeError(
                        f"image_classification loader: source {src.name!r} has type "
                        f"'image_flat' but no label_from is declared; flat sources "
                        f"require a sidecar manifest (or set unlabeled=true for "
                        f"inference-only partitions)"
                    )
                per_source = _load_one_image_flat(
                    src.name, root, src.label_from, seen_ids, attach_label=attach_label
                )
                hashes[src.name] = _hash_image_flat(root, src.label_from)
        else:
            raise RecipeError(
                f"image_classification loader: source {src.name!r} has "
                f"type={src.type!r}; expected 'image_folder' or 'image_flat'"
            )
        if src.partition is not None:
            for record in per_source:
                record["partition"] = src.partition
        records.extend(per_source)

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


def _enumerate_flat_images(root: Path) -> list[Path]:
    """Recursive sorted enumeration of image files under a flat source root.

    Determinism: caller relies on the sort being stable across machines and
    Python versions for `by_row_order` joins. We sort by POSIX-form path
    relative to `root` so filesystem walk order does not leak in.
    """
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _IMAGE_EXTENSIONS:
            candidates.append(path)
    candidates.sort(key=lambda p: p.relative_to(root).as_posix())
    return candidates


def _read_manifest_rows(
    spec: LabelFromSpec,
) -> tuple[list[str], list[list[str]]]:
    """Read the manifest CSV; return (column_names, data_rows).

    Recipe-as-truth: if `spec.header` is provided, the file is treated
    as headerless and `spec.header` *is* the column-name list. If the
    file actually contains a header line, that line is read as a data
    row — by design.
    """
    manifest_path = Path(spec.path)
    if not manifest_path.is_file():
        raise MaterializeError(f"label_from: manifest file not found at {manifest_path!s}")
    with manifest_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        all_rows = [row for row in reader if row]  # drop blank lines
    if not all_rows:
        raise MaterializeError(f"label_from: manifest file {manifest_path!s} is empty")
    if spec.header is not None:
        columns = list(spec.header)
        data_rows = all_rows
    else:
        columns = all_rows[0]
        data_rows = all_rows[1:]
    # Column-count consistency check: every data row must match the
    # declared column count. Mismatch is a manifest authoring error.
    for i, row in enumerate(data_rows):
        if len(row) != len(columns):
            raise MaterializeError(
                f"label_from: manifest row {i} has {len(row)} columns but "
                f"declared header has {len(columns)} columns"
            )
    return columns, data_rows


def _build_label_index(
    spec: LabelFromSpec,
) -> dict[str, str] | list[str]:
    """Parse the manifest into an id→label dict (by_id) or label list (by_row_order)."""
    columns, data_rows = _read_manifest_rows(spec)
    if spec.label_field not in columns:
        raise MaterializeError(
            f"label_from: label_field {spec.label_field!r} not in declared columns {columns!r}"
        )
    label_idx = columns.index(spec.label_field)
    if spec.join == "by_id":
        if spec.id_field is None or spec.id_field not in columns:
            raise MaterializeError(
                f"label_from: id_field {spec.id_field!r} not in declared columns {columns!r}"
            )
        id_idx = columns.index(spec.id_field)
        index: dict[str, str] = {}
        for row in data_rows:
            rid = row[id_idx]
            if rid in index:
                raise MaterializeError(
                    f"label_from: duplicate id {rid!r} in manifest {spec.path!s}"
                )
            index[rid] = row[label_idx]
        return index
    # by_row_order
    return [row[label_idx] for row in data_rows]


def _load_one_image_flat(
    source_name: str,
    root: Path,
    label_from: LabelFromSpec,
    seen_ids: set[str],
    *,
    attach_label: bool,
) -> list[Record]:
    images = _enumerate_flat_images(root)
    if not images:
        raise RecipeError(
            f"image_classification loader: source {source_name!r} root "
            f"{root!s} contains no .png/.jpg/.jpeg files"
        )
    label_index = _build_label_index(label_from)
    if isinstance(label_index, list):  # by_row_order
        if len(label_index) != len(images):
            raise MaterializeError(
                f"label_from: manifest has {len(label_index)} rows but source "
                f"{source_name!r} has {len(images)} images "
                f"(join=by_row_order requires equal counts)"
            )
    out: list[Record] = []
    for i, path in enumerate(images):
        rid = f"{source_name}/{path.relative_to(root).as_posix()}"
        if rid in seen_ids:
            raise RecipeError(
                f"image_classification loader: duplicate record_id {rid!r} across input sources"
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
            if isinstance(label_index, dict):
                join_key = path.stem
                if join_key not in label_index:
                    raise MaterializeError(
                        f"label_from: image {path!s} has no matching id "
                        f"{join_key!r} in manifest {label_from.path!s}"
                    )
                record["label"] = label_index[join_key]
            else:
                record["label"] = label_index[i]
        out.append(record)
    return out


def _load_one_image_flat_unlabeled(
    source_name: str,
    root: Path,
    seen_ids: set[str],
) -> list[Record]:
    """Load an `image_flat` source declared `unlabeled: true`.

    Walks the flat directory with the same sorted enumeration as the
    labeled `image_flat` path; produces records without a `label` field.
    Downstream stages that need labels (stratify_by, filter_by_label,
    label-reading featurizations) are rejected at validate time via
    check 21.
    """
    images = _enumerate_flat_images(root)
    if not images:
        raise RecipeError(
            f"image_classification loader: source {source_name!r} root "
            f"{root!s} contains no .png/.jpg/.jpeg files"
        )
    out: list[Record] = []
    for path in images:
        rid = f"{source_name}/{path.relative_to(root).as_posix()}"
        if rid in seen_ids:
            raise RecipeError(
                f"image_classification loader: duplicate record_id {rid!r} across input sources"
            )
        seen_ids.add(rid)
        with Image.open(path) as im:
            arr = np.asarray(im)
        out.append({"record_id": rid, "image": arr, "path": str(path)})
    return out


def _hash_image_flat(root: Path, label_from: LabelFromSpec) -> str:
    """Content hash for an image_flat source: images + manifest bytes.

    Re-uses :func:`_hash_image_folder` for the image-tree portion so the
    two source types share enumeration semantics, then appends a digest
    of the manifest file's raw bytes so manifest edits invalidate the
    cache without re-touching any image.
    """
    h = hashlib.sha256()
    h.update(_hash_image_folder(root).encode("ascii"))
    manifest_path = Path(label_from.path)
    if manifest_path.is_file():
        h.update(b";manifest:")
        h.update(hashlib.sha256(manifest_path.read_bytes()).hexdigest().encode("ascii"))
    return h.hexdigest()


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
        raise PluginError(f"reload_dataset: not implemented for plugin {plugin.name!r}")

    root = dataset_dir(instance_dir)
    if not root.is_dir():
        raise RecipeError(f"reload_dataset: no dataset directory at {root}")

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
    if plugin.name == "audio_classification":
        from datarefinery.plugins.audio_classification.inputs import hash_audio_sources

        return hash_audio_sources(recipe.Input.sources)
    if plugin.name != "image_classification":
        raise PluginError(
            f"hash_inputs: no disk-backed loader registered for plugin {plugin.name!r}"
        )
    hashes: dict[str, str] = {}
    for src in recipe.Input.sources:
        root = Path(src.path)
        if src.type == "image_flat" and src.label_from is not None:
            hashes[src.name] = _hash_image_flat(root, src.label_from)
        else:
            hashes[src.name] = _hash_image_folder(root)
    return hashes
