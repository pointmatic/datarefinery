# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Disk-backed audio input loader (Story J.p, R1 + R2).

Mirrors the image loader in :mod:`datarefinery.pipeline.inputs` for the two
audio source kinds, then **decodes** each clip loader-side (per the audio design
memo § 3): librosa reads the file and resamples it to the source's declared
canonical ``target_sample_rate``, so every record reaches the pipeline as
``{record_id, sample_array, sample_rate, path[, label]}`` with one uniform
sample rate regardless of how the clips were recorded.

- ``audio_folder`` — class-named subdirectory per label; labels come from the
  subdir name (parallel to ``image_folder``).
- ``audio_flat`` — flat directory of audio files; labels come from a sidecar
  manifest declared via ``InputSource.label_from`` (parallel to ``image_flat``),
  or ``unlabeled: true`` for inference-only partitions.

librosa is imported **lazily** inside :func:`_decode` so this module (and the
plugin) stay importable for discovery / contract tests without the ``[audio]``
extra installed; decoding without it raises an actionable :class:`PluginError`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from datarefinery.core.errors import MaterializeError, PluginError, RecipeError
from datarefinery.recipe.models import AudioSource, InputSource, LabelFromSpec

if TYPE_CHECKING:
    import numpy as np

Record = dict[str, Any]

#: Audio container formats librosa/soundfile decode. Mono is assumed (v1).
_AUDIO_EXTENSIONS = (".wav", ".flac", ".ogg", ".mp3")


def load_audio_records(
    sources: list[InputSource],
    *,
    attach_label: bool,
) -> tuple[list[Record], dict[str, str]]:
    """Inflate audio ``sources`` into decoded records + per-source content hashes.

    Returns ``(records, raw_input_hashes)`` exactly like the image loader.
    Every source must be an :class:`AudioSource` (i.e. declare
    ``target_sample_rate``) — the canonical sample rate is required for audio.
    """
    records: list[Record] = []
    hashes: dict[str, str] = {}
    seen_ids: set[str] = set()

    for src in sources:
        if not isinstance(src, AudioSource):
            raise RecipeError(
                f"audio_classification loader: source {src.name!r} is missing "
                f"'target_sample_rate'; audio sources must declare the canonical "
                f"sample rate (it has no default — see the no-implicit-defaults rule)"
            )
        root = Path(src.path)
        if not root.is_dir():
            raise RecipeError(
                f"audio_classification loader: source {src.name!r} path {root!s} is not a directory"
            )
        if src.type == "audio_folder":
            if src.label_from is not None:
                raise RecipeError(
                    f"audio_classification loader: source {src.name!r} has type "
                    f"'audio_folder' with label_from set; audio_folder takes labels "
                    f"from class subdirectories, not from a sidecar manifest"
                )
            if src.unlabeled:
                raise RecipeError(
                    f"audio_classification loader: source {src.name!r} has type "
                    f"'audio_folder' with unlabeled=true; declare type='audio_flat' "
                    f"for unlabeled partitions (audio_folder derives labels from "
                    f"class subdirectories)"
                )
            per_source = _load_one_audio_folder(src, root, seen_ids, attach_label=attach_label)
        elif src.type == "audio_flat":
            if src.unlabeled:
                per_source = _load_one_audio_flat_unlabeled(src, root, seen_ids)
            else:
                if src.label_from is None:
                    raise RecipeError(
                        f"audio_classification loader: source {src.name!r} has type "
                        f"'audio_flat' but no label_from is declared; flat sources "
                        f"require a sidecar manifest (or set unlabeled=true for "
                        f"inference-only partitions)"
                    )
                per_source = _load_one_audio_flat(
                    src, root, src.label_from, seen_ids, attach_label=attach_label
                )
        elif src.type == "audio_tree":
            per_source = _load_one_audio_tree(src, root, seen_ids, attach_label=attach_label)
        else:
            raise RecipeError(
                f"audio_classification loader: source {src.name!r} has "
                f"type={src.type!r}; expected 'audio_folder', 'audio_flat', or 'audio_tree'"
            )
        hashes[src.name] = _hash_dir(root, src.label_from)
        if src.partition is not None:
            for record in per_source:
                record["partition"] = src.partition
        records.extend(per_source)

    return records, hashes


def hash_audio_sources(sources: list[InputSource]) -> dict[str, str]:
    """Per-source content hashes without decoding (for cache resolution)."""
    hashes: dict[str, str] = {}
    for src in sources:
        if not isinstance(src, AudioSource):
            raise RecipeError(
                f"audio_classification loader: source {src.name!r} is missing "
                f"'target_sample_rate' (required for audio sources)"
            )
        hashes[src.name] = _hash_dir(Path(src.path), src.label_from)
    return hashes


def _load_one_audio_folder(
    src: AudioSource,
    root: Path,
    seen_ids: set[str],
    *,
    attach_label: bool,
) -> list[Record]:
    classes = sorted(p.name for p in root.iterdir() if p.is_dir())
    if not classes:
        raise RecipeError(
            f"audio_classification loader: source {src.name!r} root {root!s} "
            f"has no class subdirectories"
        )
    out: list[Record] = []
    for cls in classes:
        for path in _enumerate_audio(root / cls):
            rid = f"{src.name}/{cls}/{path.name}"
            _claim_id(rid, seen_ids)
            record = _decode_record(rid, path, src.target_sample_rate)
            if attach_label:
                record["label"] = cls
            out.append(record)
    if not out:
        raise RecipeError(
            f"audio_classification loader: source {src.name!r} root {root!s} "
            f"contains no {'/'.join(_AUDIO_EXTENSIONS)} files"
        )
    return out


def _load_one_audio_flat(
    src: AudioSource,
    root: Path,
    label_from: LabelFromSpec,
    seen_ids: set[str],
    *,
    attach_label: bool,
) -> list[Record]:
    from datarefinery.pipeline.inputs import _build_label_index

    index = _build_label_index(label_from)
    files = _enumerate_audio(root)
    out: list[Record] = []
    for i, path in enumerate(files):
        rid = f"{src.name}/{path.name}"
        _claim_id(rid, seen_ids)
        record = _decode_record(rid, path, src.target_sample_rate)
        if attach_label:
            record["label"] = _resolve_flat_label(label_from, index, path, i)
        out.append(record)
    if not out:
        raise RecipeError(
            f"audio_classification loader: source {src.name!r} root {root!s} "
            f"contains no {'/'.join(_AUDIO_EXTENSIONS)} files"
        )
    return out


def _load_one_audio_flat_unlabeled(
    src: AudioSource,
    root: Path,
    seen_ids: set[str],
) -> list[Record]:
    out: list[Record] = []
    for path in _enumerate_audio(root):
        rid = f"{src.name}/{path.name}"
        _claim_id(rid, seen_ids)
        out.append(_decode_record(rid, path, src.target_sample_rate))
    if not out:
        raise RecipeError(
            f"audio_classification loader: source {src.name!r} root {root!s} "
            f"contains no {'/'.join(_AUDIO_EXTENSIONS)} files"
        )
    return out


def _load_one_audio_tree(
    src: AudioSource,
    root: Path,
    seen_ids: set[str],
    *,
    attach_label: bool,
) -> list[Record]:
    """Load an ``audio_tree`` source via the shared ``path_tree`` resolver (Story K.h).

    Labels come from the layout's ``{label}`` token when present, else from
    ``label_from`` / ``unlabeled``. A ``{split}`` token stamps each record's
    ``partition``. Decode stays here (the resolver is payload-agnostic).
    """
    from datarefinery.pipeline.inputs import _build_label_index
    from datarefinery.recipe.layout import path_tree

    assert src.layout is not None  # model validator guarantees layout on *_tree
    resolved = path_tree(
        root, src.layout, extensions=frozenset(_AUDIO_EXTENSIONS), source_name=src.name
    )
    if not resolved:
        raise RecipeError(
            f"audio_classification loader: source {src.name!r} root {root!s} matched no "
            f"{'/'.join(_AUDIO_EXTENSIONS)} files for layout {src.layout!r}"
        )
    has_label_token = "{label}" in src.layout
    label_index = (
        _build_label_index(src.label_from)
        if (attach_label and src.label_from is not None)
        else None
    )
    out: list[Record] = []
    for i, rf in enumerate(resolved):
        _claim_id(rf.record_id, seen_ids)
        record = _decode_record(rf.record_id, rf.path, src.target_sample_rate)
        if rf.split is not None:
            record["partition"] = rf.split
        if attach_label:
            if has_label_token:
                record["label"] = rf.label
            elif src.label_from is not None:
                assert label_index is not None
                record["label"] = _resolve_flat_label(src.label_from, label_index, rf.path, i)
            elif not src.unlabeled:
                raise RecipeError(
                    f"audio_classification loader: source {src.name!r} layout {src.layout!r} "
                    f"has no '{{label}}' token, no label_from, and is not unlabeled"
                )
        out.append(record)
    return out


def _resolve_flat_label(
    label_from: LabelFromSpec,
    index: dict[str, str] | list[str],
    path: Path,
    row_idx: int,
) -> str:
    if label_from.join == "by_id":
        assert isinstance(index, dict)
        rid_key = path.stem
        if rid_key not in index:
            raise MaterializeError(
                f"label_from: no manifest row for audio file {path.name!r} "
                f"(join=by_id on stem {rid_key!r})"
            )
        return index[rid_key]
    assert isinstance(index, list)
    if row_idx >= len(index):
        raise MaterializeError(
            f"label_from: manifest has {len(index)} rows but audio source has "
            f"more files (join=by_row_order); row {row_idx} unmatched"
        )
    return index[row_idx]


def _decode_record(record_id: str, path: Path, target_sample_rate: int) -> Record:
    sample_array, sample_rate = _decode(path, target_sample_rate)
    return {
        "record_id": record_id,
        "sample_array": sample_array,
        "sample_rate": sample_rate,
        "path": str(path),
    }


def _decode(path: Path, target_sample_rate: int) -> tuple[np.ndarray, int]:
    """Decode + resample one clip to ``target_sample_rate`` (mono).

    librosa is imported here (lazily) so the module stays importable without the
    ``[audio]`` extra. Decoding is deterministic for a given file + target rate.
    """
    try:
        import librosa
    except ImportError as exc:  # pragma: no cover - exercised only without [audio]
        raise PluginError(
            "audio_classification decode requires the 'audio' extra; "
            "install it with: pip install 'ml-datarefinery[audio]'"
        ) from exc
    samples, sample_rate = librosa.load(str(path), sr=target_sample_rate, mono=True)
    return samples.astype("float32"), int(sample_rate)


def _enumerate_audio(root: Path) -> list[Path]:
    """Sorted (POSIX-relative) enumeration of audio files under ``root``.

    Sorting by relative POSIX path keeps enumeration order stable across
    machines so ``by_row_order`` joins and content hashing are deterministic.
    """
    # Route through the shared symlink-following enumeration (Story K.g) so the
    # audio loader and the input hasher walk the same file set, then filter to
    # audio extensions. enumerate_files already returns deterministically sorted.
    # Local import mirrors `_build_label_index` below — avoids a core↔plugin cycle.
    from datarefinery.pipeline.inputs import enumerate_files

    return [p for p in enumerate_files(root) if p.suffix.lower() in _AUDIO_EXTENSIONS]


def _claim_id(rid: str, seen_ids: set[str]) -> None:
    if rid in seen_ids:
        raise RecipeError(
            f"audio_classification loader: duplicate record_id {rid!r} across input sources"
        )
    seen_ids.add(rid)


def _hash_dir(root: Path, label_from: LabelFromSpec | None) -> str:
    """Order-stable content hash over every file under ``root`` (+ manifest bytes).

    Mirrors the image loader's content hash: ``(<rel>:<sha256(bytes)>;)`` per
    file in sorted order, so the digest is invariant to filesystem-walk order.
    A declared ``label_from`` manifest's bytes are appended so manifest edits
    invalidate the cache without re-touching any clip.
    """
    from datarefinery.pipeline.inputs import enumerate_files

    h = hashlib.sha256()
    for path in enumerate_files(root):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        h.update(rel)
        h.update(b":")
        h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        h.update(b";")
    if label_from is not None:
        manifest_path = Path(label_from.path)
        if manifest_path.is_file():
            h.update(b";manifest:")
            h.update(hashlib.sha256(manifest_path.read_bytes()).hexdigest().encode("ascii"))
    return h.hexdigest()
