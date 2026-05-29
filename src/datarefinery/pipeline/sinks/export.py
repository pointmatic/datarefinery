# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""``datarefinery export`` dispatch (Story I.f).

Re-run recipe-declared `Sinks` against an already-materialized instance,
without re-running the full pipeline. The bound instance is located by
computing a *sinks-stripped* cache key — adding a sink to a recipe
changes its canonical bytes, but the instance produced by the previous
materialize is still the relevant one to read from.

v1 reconstructability table (consulted at validate-time and runtime):

- ``post_OutputExpectations`` / ``post_Visualizations`` — final record
  state; reads cached JSONL directly. Only viable when the sink's
  ``field`` survives JSONL serialization (i.e., is JSON-native).
- ``post_Generation`` — reconstructable when every cached record at
  this stage carries the per-record-seed stamp (Story I.e). Each
  unique source record is re-loaded from its ``source_path``; the
  stochastic Generation op (`imagecorruptions_apply` today) is
  re-invoked against it; outputs are matched back to cached records
  by ``record_id``.
- everything else — refused with a pointer to ``datarefinery materialize``.

Sink output lands under the same instance directory as the bound cache
state. Writes are atomic per-file (temp-then-rename) so an interrupted
export never leaves a half-written file under the promoted path.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from datarefinery.cache.identity import compute_cache_key
from datarefinery.cache.layout import (
    instance_dir as instance_dir_for,
)
from datarefinery.cache.layout import (
    manifest_path,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.inputs import load_raw_records
from datarefinery.pipeline.sinks.runner import SinkResult, _run_one_sink
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import Recipe, SinkOp

# Reconstructability table: stage -> the strategy used to produce the
# record map for the sink dispatcher. Stages not in this map are
# refused.
_TRIVIAL_STAGES = frozenset(
    {
        "post_OutputExpectations",
        "post_Visualizations",
    }
)
_GENERATION_STAGE = "post_Generation"

_RECONSTRUCTABLE_STAGES = _TRIVIAL_STAGES | {_GENERATION_STAGE}


@dataclass(frozen=True)
class ExportResult:
    """Outcome of a single ``datarefinery export`` invocation."""

    instance_dir: Path
    sinks_executed: list[SinkResult]


def export_sinks(
    recipe: Recipe,
    *,
    plugin: Plugin,
    config: RuntimeConfig,
    seed: int,
    sink_names: Sequence[str] | None = None,
    variant: str | None = None,
    raw_input_hashes: Mapping[str, str] | None = None,
    raw_records: Sequence[Mapping[str, Any]] | None = None,
) -> ExportResult:
    """Re-run sinks declared in ``recipe`` against the bound instance.

    ``sink_names``: limit execution to the named sinks (each must be
    declared on ``recipe``). When ``None`` every sink on the recipe is
    re-run.

    ``raw_input_hashes`` / ``raw_records`` mirror the materialize
    library API. Library callers that supplied records-and-hashes
    directly to ``materialize`` (bypassing the disk loader) MUST
    supply the same pair here — the record-id convention used by the
    original materialize is the one the export verb reconstructs
    against. When both are ``None`` the per-plugin disk loader inflates
    the recipe's ``Input`` sources from disk (the CLI path).
    """
    del variant  # cache-key lookup uses the recipe as supplied; the
    # variant has already been overlaid by the caller (`DataRefinery`).

    if not recipe.Sinks:
        raise MaterializeError("datarefinery export: recipe declares no Sinks; nothing to do.")
    if (raw_records is None) != (raw_input_hashes is None):
        raise MaterializeError(
            "datarefinery export: pass both raw_records and raw_input_hashes, "
            "or neither (to load from disk)."
        )

    declared_names = {s.name for s in recipe.Sinks}
    selected_names = _select_sink_names(declared_names, sink_names)

    instance_dir, cached_records_by_split, resolved_inputs = _resolve_bound_instance(
        recipe,
        plugin=plugin,
        config=config,
        seed=seed,
        raw_input_hashes=raw_input_hashes,
        raw_records=raw_records,
    )

    selected_sinks = [s for s in recipe.Sinks if s.name in selected_names]

    # Reconstructability validation: refuse early before we start
    # rebuilding stage record maps.
    for sink in selected_sinks:
        if sink.stage not in _RECONSTRUCTABLE_STAGES:
            raise MaterializeError(
                f"datarefinery export: sink {sink.name!r} targets stage "
                f"{sink.stage!r} which is not reconstructable from cached "
                f"state in v1; re-materialize the recipe instead "
                f"(`datarefinery materialize ...`)."
            )

    results: list[SinkResult] = []
    # Group sinks by stage so we only build each stage's record map once.
    by_stage: dict[str, list[SinkOp]] = {}
    for sink in selected_sinks:
        by_stage.setdefault(sink.stage, []).append(sink)

    for stage, sinks in by_stage.items():
        split_map = _record_map_for_stage(
            stage,
            cached_records_by_split=cached_records_by_split,
            instance_dir=instance_dir,
            recipe=recipe,
            resolved_inputs=resolved_inputs,
            plugin=plugin,
            master_seed=seed,
        )
        for sink in sinks:
            results.append(_run_one_sink_atomically(sink, split_map, instance_dir))

    return ExportResult(instance_dir=instance_dir, sinks_executed=results)


def _select_sink_names(declared: set[str], requested: Sequence[str] | None) -> set[str]:
    if requested is None:
        return set(declared)
    requested_set = set(requested)
    unknown = sorted(requested_set - declared)
    if unknown:
        raise MaterializeError(
            f"datarefinery export: sink(s) {unknown!r} not declared on the recipe; "
            f"declared: {sorted(declared)!r}"
        )
    return requested_set


def _strip_sinks(recipe: Recipe) -> Recipe:
    """Return a copy of ``recipe`` with the `Sinks` section cleared.

    The export verb uses this sinks-stripped form to look up the bound
    cache instance — adding a sink to a recipe perturbs canonical
    bytes, but the prior materialize (without that sink) is the
    instance we want to read from. See the spec § 5: "export
    deliberately bypasses the materialize gate by reading the bound
    instance directly."
    """
    return recipe.model_copy(update={"Sinks": []})


def _resolve_bound_instance(
    recipe: Recipe,
    *,
    plugin: Plugin,
    config: RuntimeConfig,
    seed: int,
    raw_input_hashes: Mapping[str, str] | None,
    raw_records: Sequence[Mapping[str, Any]] | None,
) -> tuple[Path, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Compute the sinks-stripped cache key, locate the instance, and
    read every per-split JSONL. Returns the instance path, the cached
    record map, and the resolved input records (re-loaded from disk
    when none were supplied) — the latter feed reconstruction for
    post-Generation sinks.

    Raises :class:`MaterializeError` if no matching instance exists or
    its manifest is missing.
    """
    stripped = _strip_sinks(recipe)
    if raw_records is None:
        loaded, computed_hashes = load_raw_records(stripped, plugin)
        inputs: list[dict[str, Any]] = [dict(r) for r in loaded]
        hashes = dict(computed_hashes)
    else:
        inputs = [dict(r) for r in raw_records]
        assert raw_input_hashes is not None  # guaranteed by `export_sinks`
        hashes = dict(raw_input_hashes)
    key = compute_cache_key(stripped, hashes, seed)
    inst = instance_dir_for(config.cache_root, key)
    if not manifest_path(inst).exists():
        raise MaterializeError(
            f"datarefinery export: no bound instance under {inst} — "
            f"run `datarefinery materialize <recipe>` first (export "
            f"reads from a cache, it does not produce one)."
        )

    records_by_split = _read_jsonl_splits(inst)
    return inst, records_by_split, inputs


def _read_jsonl_splits(instance: Path) -> dict[str, list[dict[str, Any]]]:
    import json

    out: dict[str, list[dict[str, Any]]] = {}
    dataset = instance / "dataset"
    if not dataset.is_dir():
        return out
    for path in sorted(dataset.glob("*.jsonl")):
        split = path.stem
        with path.open("r", encoding="utf-8") as fh:
            out[split] = [json.loads(line) for line in fh if line.strip()]
    return out


def _record_map_for_stage(
    stage: str,
    *,
    cached_records_by_split: Mapping[str, list[dict[str, Any]]],
    instance_dir: Path,
    recipe: Recipe,
    resolved_inputs: list[dict[str, Any]],
    plugin: Plugin,
    master_seed: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Produce the record map a sink at ``stage`` should iterate."""
    del instance_dir  # reserved for future per-stage strategies
    if stage in _TRIVIAL_STAGES:
        return {name: [dict(r) for r in recs] for name, recs in cached_records_by_split.items()}
    if stage == _GENERATION_STAGE:
        return _reconstruct_post_generation(
            cached_records_by_split, recipe, resolved_inputs, plugin, master_seed
        )
    raise MaterializeError(  # pragma: no cover — guarded upstream
        f"datarefinery export: stage {stage!r} not in reconstructability table"
    )


def _reconstruct_post_generation(
    cached_records_by_split: Mapping[str, list[dict[str, Any]]],
    recipe: Recipe,
    resolved_inputs: list[dict[str, Any]],
    plugin: Plugin,
    master_seed: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Rebuild the records as they existed at the post-Generation stage.

    Strategy:

    1. Identify which input records the cached corrupted variants
       came from by matching ``source_path`` (loader-stamped) to the
       resolved input records' ``path``.
    2. Re-run the recipe's Generation ops against that input subset
       — this is the same byte-deterministic pass the runner did,
       restricted to the inputs the sink actually needs.
    3. Index produced records by ``record_id`` and copy each one's
       uint8 ``image`` field onto the matching cached record.
    4. Pass-through records (pre-Generation inputs that survived
       under extend-not-replace semantics) get their ``image`` from
       the resolved input record directly.
    """
    from datarefinery.pipeline.stages.generation import apply_generation

    # Index resolved inputs by their `path` (the loader stamps this
    # canonically; `imagecorruptions_apply` propagates it onto cached
    # records as `source_path`). For library callers that supplied
    # `raw_records` without a `path`, fall back to indexing by
    # `record_id` — both work as long as the original materialize
    # used the same identity.
    by_path: dict[str, dict[str, Any]] = {}
    by_record_id: dict[str, dict[str, Any]] = {}
    for r in resolved_inputs:
        if "path" in r:
            by_path[str(r["path"])] = r
        if "record_id" in r:
            by_record_id[str(r["record_id"])] = r

    # Decide which inputs feed Generation. Any cached record whose
    # `source_path` (or `path`, for pass-through originals) names a
    # known input contributes its parent to the re-run set.
    needed_input_keys: set[str] = set()
    for recs in cached_records_by_split.values():
        for cr in recs:
            sp = cr.get("source_path") or cr.get("path")
            if sp is not None:
                needed_input_keys.add(str(sp))

    input_records: list[dict[str, Any]] = []
    for key in sorted(needed_input_keys):
        candidate = by_path.get(key) or by_record_id.get(key)
        if candidate is None:
            raise MaterializeError(
                f"datarefinery export: cached record references source "
                f"{key!r}, but the recipe's inputs do not include it. "
                f"This usually means the source files moved or the "
                f"recipe was materialized with library-supplied "
                f"raw_records that are not being supplied to export."
            )
        input_records.append(dict(candidate))

    # Re-run Generation against the filtered input subset. The split
    # name is incidental — Generation is record-level and ignores
    # cross-split coupling.
    gen_result = apply_generation(
        cast(dict[str, list[Mapping[str, Any]]], {"train": input_records}),
        list(recipe.Generation),
        plugin=plugin,
        output_record_schema=recipe.Output.record_schema,
        label_field=recipe.Labels.field,
        master_seed=master_seed,
    )

    # Index every record at the post-Generation state (originals +
    # produced) by `record_id` — extend-not-replace semantics mean
    # the originals also persist into post_Generation, so they need
    # to be reachable for sinks too.
    by_rid: dict[str, dict[str, Any]] = {
        str(r["record_id"]): dict(r) for r in gen_result.splits["train"]
    }

    out: dict[str, list[dict[str, Any]]] = {}
    for split, recs in cached_records_by_split.items():
        out[split] = []
        for cr in recs:
            rid = str(cr["record_id"])
            merged = dict(cr)
            if rid in by_rid and "image" in by_rid[rid]:
                merged["image"] = by_rid[rid]["image"]
            out[split].append(merged)
    return out


def _run_one_sink_atomically(
    sink: SinkOp,
    split_map: Mapping[str, list[dict[str, Any]]],
    instance_dir: Path,
) -> SinkResult:
    """Run one sink with atomic per-file temp-then-rename writes.

    The bound instance is already promoted — we cannot rely on the
    pipeline's wholesale temp-then-promote dance. Instead, each file
    is written to ``<final>.export_tmp_<token>`` and atomically
    renamed onto its final path; an interrupted export leaves at
    most one ``.export_tmp_*`` file behind, never a half-written
    sink artifact.
    """
    # Stage results into a private subdir, then rename each file
    # individually so the user-visible export tree never holds
    # partial files. `_run_one_sink` writes directly under its
    # `instance_dir` argument; we point it at the staging root and
    # then rename onto the final layout.
    staging = instance_dir / f".export_tmp_{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        # `_run_one_sink` accepts `list[Mapping[str, Any]]`; lists are
        # invariant, so a `list[dict[...]]` requires a cast at the
        # boundary. Conceptually safe — the function only reads from
        # each record.
        result = _run_one_sink(
            sink,
            cast(Mapping[str, list[Mapping[str, Any]]], split_map),
            staging,
        )
        _atomic_move_tree(staging, instance_dir)
    finally:
        if staging.exists():
            _rmtree(staging)
    return result


def _atomic_move_tree(src: Path, dst_root: Path) -> None:
    """Move every file under ``src`` onto its mirrored position under
    ``dst_root`` via :func:`os.replace` (atomic on POSIX). Directories
    are created as needed.
    """
    for path in sorted(src.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        target = dst_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, target)


def _rmtree(path: Path) -> None:
    """Best-effort tree removal; never raises."""
    import shutil

    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "ExportResult",
    "export_sinks",
]
