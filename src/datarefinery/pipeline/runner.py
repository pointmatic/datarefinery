# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-3 PipelineRunner: validate -> cache check -> stages -> manifest -> promote.

This is the conductor. It sequences every stage built across Phase C in
the order documented in tech-spec, materializes the instance into a
temp directory, writes the manifest, and atomically promotes to the
cache layout. Cache hits short-circuit before any temp work.

Scope notes for v1:

- Raw input loading is the caller's responsibility. ``run`` accepts
  ``raw_records`` (the loaded record list) and ``raw_input_hashes``
  (per-source SHA-256 hex digests for cache-key construction).
  Disk-based input loading lives in the CLI layer (Story D.e); this
  module's job is stage orchestration, not I/O.
- Dataset persistence is intentionally minimal: a JSON-lines file per
  split under ``<instance>/dataset/`` with each record's serializable
  fields (``record_id``, ``label``, scalar metadata). Numpy arrays and
  other non-JSON-native values are dropped from the persisted form.
  The image bytes for image_classification recipes live on disk via
  the source ``path`` field; downstream tools resolve images from
  there. Full-fidelity dataset persistence is a follow-up story.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from datarefinery import __version__
from datarefinery.cache.atomic import atomic_promote, mark_failed
from datarefinery.cache.identity import compute_cache_key
from datarefinery.cache.layout import (
    dataset_dir,
    fitted_stats_dir,
    instance_dir,
    manifest_path,
    recipe_path,
    report_dir,
    sample_dir,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.contracts import (
    evaluate_input_contracts,
    evaluate_output_expectations,
)
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.manifest import (
    Manifest,
    ManifestWarning,
    SampleManifestEntry,
    SinkManifestEntry,
    write_manifest,
)
from datarefinery.pipeline.path_rewrite import path_rewrite_plan
from datarefinery.pipeline.sinks import SinkResult, execute_sinks
from datarefinery.pipeline.stages.augmentations import (
    collect_augmentation_policies,
    realize_aggressive_split,
)
from datarefinery.pipeline.stages.featurizations import apply_featurizations
from datarefinery.pipeline.stages.filters import (
    apply_post_split_filters,
    apply_pre_split_filters,
)
from datarefinery.pipeline.stages.generation import apply_generation
from datarefinery.pipeline.stages.sample_data import (
    SampleResult,
    apply_sample_data,
    resolve_sample_seed,
)
from datarefinery.pipeline.stages.splits import apply_splits, resolve_seed
from datarefinery.pipeline.stages.transformations import apply_transformations
from datarefinery.pipeline.stages.visualizations import (
    apply_reporting_visualizations,
)
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import Recipe, SinkOp
from datarefinery.recipe.validator import unlabeled_split_names
from datarefinery.reporting.drift import (
    compute_drift_placeholder,
    write_drift,
)
from datarefinery.reporting.report import (
    DRIFT_FILENAME,
    REPORT_FILENAME,
    render_report_md,
    write_report,
)

Record = Mapping[str, Any]
ProgressCallback = Callable[[str], None]

#: Stage names accepted by the ``stop_after`` partial-run option, in
#: execution order. The runner refuses any other value with
#: :class:`MaterializeError` rather than silently running to completion.
STAGE_NAMES: tuple[str, ...] = (
    "InputContracts",
    "Filters/pre_split",
    "Splits",
    "Filters/post_split",
    "Generation",
    "Transformations",
    "Featurizations",
    "Augmentations",
    "OutputExpectations",
    "Visualizations",
)


@dataclass(frozen=True)
class RunnerResult:
    """Outcome of one pipeline run."""

    instance_dir: Path
    cache_hit: bool
    manifest: Manifest
    is_partial: bool = False


class PipelineRunner:
    """Sequence every Phase-C stage and produce a materialized instance."""

    def __init__(
        self,
        recipe: Recipe,
        plugin: Plugin,
        config: RuntimeConfig,
        seed: int,
        *,
        variant: str | None = None,
    ) -> None:
        self.recipe = recipe
        self.plugin = plugin
        self.config = config
        self.seed = seed
        self.variant = variant

    def run(
        self,
        temp_dir: Path,
        *,
        raw_records: list[Record],
        raw_input_hashes: Mapping[str, str],
        stop_after: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> RunnerResult:
        """Execute the pipeline against ``raw_records`` into ``temp_dir``.

        Returns a :class:`RunnerResult` indicating whether the run hit
        cache or materialized fresh. On cache hit, ``temp_dir`` is not
        touched.

        ``progress_callback`` is invoked with each pipeline-stage name at
        the moment that stage starts (suitable for driving a `rich`
        progress bar). ``stop_after`` is one of :data:`STAGE_NAMES`;
        when set, the runner stops cleanly after that stage, writes a
        partial manifest (``is_partial=True``,
        ``completed_through=<stage>``) into ``temp_dir``, and does NOT
        promote into the final cache layout.
        """
        if stop_after is not None and stop_after not in STAGE_NAMES:
            raise MaterializeError(
                f"PipelineRunner.run: stop_after={stop_after!r} not "
                f"recognized; valid stages: {list(STAGE_NAMES)}"
            )

        cache_key = compute_cache_key(self.recipe, raw_input_hashes, self.seed)
        final_dir = instance_dir(self.config.cache_root, cache_key)

        if manifest_path(final_dir).exists() and stop_after is None:
            return RunnerResult(
                instance_dir=final_dir,
                cache_hit=True,
                manifest=_read_manifest(final_dir),
            )

        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        start = time.monotonic()
        warnings: list[ManifestWarning] = []
        label_field = self.recipe.Labels.field
        current_stage: str = "init"
        split_map: dict[str, list[Record]] = {}
        fitted_op_ids: list[str] = []
        records: list[Record] = list(raw_records)
        sink_results: list[SinkResult] = []
        reached_sink_stages: set[str] = set()
        # G7 / Story I.v: per-stage snapshots of the split-map for stage-aware
        # visualization dispatch. Each entry is a shallow copy of `split_map`
        # at the END of the named runner stage (or the flat record stream
        # wrapped under `_records` for `post_InputContracts`, which is
        # pre-Splits). `post_pipeline` is the final snapshot, populated just
        # before `apply_reporting_visualizations` runs.
        viz_snapshots: dict[str, Mapping[str, list[Record]]] = {}

        def _emit(stage: str) -> None:
            nonlocal current_stage
            current_stage = stage
            if progress_callback is not None:
                progress_callback(stage)

        def _run_sinks(sink_stage: str, smap: Mapping[str, list[Record]]) -> None:
            # Track that this sink stage was reached even when no sink
            # matches; the set drives the partial manifest's
            # `sinks_skipped` map (Story I.f.1).
            reached_sink_stages.add(sink_stage)
            if not self.recipe.Sinks:
                return
            sink_results.extend(
                execute_sinks(
                    sinks=list(self.recipe.Sinks),
                    stage=sink_stage,
                    split_map=smap,
                    instance_dir=temp_dir,
                )
            )

        try:
            _emit("InputContracts")
            ic = evaluate_input_contracts(raw_records, self.recipe.InputContracts)
            ic.raise_for_status()
            warnings.extend(_wrap(current_stage, (w.message for w in ic.warnings)))
            _run_sinks("post_InputContracts", {"_records": records})
            viz_snapshots["post_InputContracts"] = {"_records": list(records)}
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            _emit("Filters/pre_split")
            pre_filter = apply_pre_split_filters(
                raw_records,
                self.recipe.Filters,
                plugin=self.plugin,
                label_field=label_field,
                master_seed=self.seed,
            )
            warnings.extend(_wrap(current_stage, pre_filter.warnings))
            records = pre_filter.records
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            _emit("Splits")
            splits = apply_splits(
                records,
                self.recipe.Splits,
                seed=resolve_seed(self.recipe.Splits, self.seed),
            )
            warnings.extend(_wrap(current_stage, splits.warnings))
            split_map = dict(splits.splits)
            if splits.unassigned:
                warnings.append(
                    ManifestWarning(
                        stage=current_stage,
                        message=(
                            f"{len(splits.unassigned)} records left unassigned "
                            "(ratios summed below 1.0)"
                        ),
                    )
                )
            _run_sinks("post_Splits", split_map)
            viz_snapshots["post_Splits"] = dict(split_map)
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            _emit("Filters/post_split")
            post_filter = apply_post_split_filters(
                split_map,
                self.recipe.Filters,
                plugin=self.plugin,
                label_field=label_field,
                master_seed=self.seed,
            )
            for split_name, fr in post_filter.items():
                split_map[split_name] = fr.records
                warnings.extend(_wrap(current_stage, fr.warnings))
            _run_sinks("post_Filters", split_map)
            viz_snapshots["post_Filters"] = dict(split_map)
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            _emit("Generation")
            gen_result = apply_generation(
                split_map,
                self.recipe.Generation,
                plugin=self.plugin,
                output_record_schema=self.recipe.Output.record_schema,
                label_field=label_field,
                master_seed=self.seed,
            )
            split_map = dict(gen_result.splits)
            warnings.extend(_wrap(current_stage, gen_result.warnings))
            _run_sinks("post_Generation", split_map)
            viz_snapshots["post_Generation"] = dict(split_map)
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            _emit("Transformations")
            fitted_stats = FittedStatistics(fitted_stats_dir(temp_dir))
            tx_result = apply_transformations(
                split_map,
                self.recipe.Transformations,
                plugin=self.plugin,
                fitted_stats=fitted_stats,
                label_field=label_field,
                cache_root=self.config.cache_root,
            )
            split_map = dict(tx_result.splits)
            fitted_op_ids = list(tx_result.fitted_op_ids)
            _run_sinks("post_Transformations", split_map)
            viz_snapshots["post_Transformations"] = dict(split_map)
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            _emit("Featurizations")
            feat_result = apply_featurizations(
                split_map,
                self.recipe.Featurizations,
                plugin=self.plugin,
                fitted_stats=fitted_stats,
                label_field=label_field,
                cache_root=self.config.cache_root,
            )
            split_map = dict(feat_result.splits)
            fitted_op_ids.extend(feat_result.fitted_op_ids)
            _run_sinks("post_Featurizations", split_map)
            viz_snapshots["post_Featurizations"] = dict(split_map)
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            _emit("Augmentations")
            # FR-11 aggressive-mode dispatch (Story H.p framework +
            # H.q/H.r ops + H.r.1 wiring + H.r.2 sidecar persistence).
            # Aggressive ops fan out the train split into N x expansion
            # variants via the plugin-registered realizer; image bytes
            # for each variant land in
            # ``dataset/<split>/images/<record_id>.png`` at write time
            # (see :func:`_prepare_record_for_persistence`).
            aggressive_ops = [
                op for op in self.recipe.Augmentations if op.materialization == "aggressive"
            ]
            if aggressive_ops:
                realizer_registry = getattr(self.plugin, "augmentation_realizers", {})
                train_records: list[Mapping[str, Any]] = list(split_map.get("train", []))
                split_map["train"] = list(
                    realize_aggressive_split(
                        train_records,
                        self.recipe.Augmentations,
                        global_seed=self.seed,
                        realizer_registry=realizer_registry,
                    )
                )
            collect_augmentation_policies(self.recipe.Augmentations, master_seed=self.seed)
            # Policies are descriptive only in v1 (FR-11); the
            # serialized block is recorded in the manifest's eventual
            # `augmentations` field via the runner's report writer
            # (Story C.n) - here we just defensively re-validate.
            _run_sinks("post_Augmentations", split_map)
            viz_snapshots["post_Augmentations"] = dict(split_map)
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            _emit("OutputExpectations")
            has_unlabeled = any(s.unlabeled for s in self.recipe.Input.sources)
            oe = evaluate_output_expectations(
                split_map,
                self.recipe.OutputExpectations,
                skip_missing_label_field=(self.recipe.Labels.field if has_unlabeled else None),
            )
            oe.raise_for_status()
            warnings.extend(_wrap(current_stage, (w.message for w in oe.warnings)))
            _run_sinks("post_OutputExpectations", split_map)
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            _emit("Visualizations")
            viz_dir = report_dir(temp_dir) / "visualizations"
            viz_snapshots["post_pipeline"] = dict(split_map)
            apply_reporting_visualizations(
                viz_snapshots,
                self.recipe.Visualizations,
                plugin=self.plugin,
                output_dir=viz_dir,
                label_field=label_field,
                recipe=self.recipe,
            )
            _run_sinks("post_Visualizations", split_map)
            if stop_after == current_stage:
                return self._partial_finish(
                    temp_dir,
                    cache_key,
                    current_stage,
                    split_map,
                    warnings,
                    start,
                    sink_results=sink_results,
                    reached_sink_stages=reached_sink_stages,
                )

            current_stage = "Dataset"
            # Story J.g: lazy-mode `path` rewrite for pixel-altering
            # Transformations. validate() (check 26) guarantees every
            # affected split has a qualifying sink, so the plan covers
            # every split that needs it.
            rewrite_plan = path_rewrite_plan(self.recipe, self.plugin)
            _write_dataset(dataset_dir(temp_dir), split_map, rewrite_plan=rewrite_plan)

            # FR-J-1 SampleData runtime (Story J.a). P-postpipeline +
            # M-sidecar: sample the final split_map *after* the full
            # dataset has been persisted, write the sidecar under
            # ``<instance>/sample/`` inside the same atomic temp-then-
            # promote unit. dataset/ is unchanged by sampling.
            sample_result: SampleResult | None = None
            if self.recipe.SampleData is not None:
                current_stage = "SampleData"
                sample_result = apply_sample_data(
                    split_map,
                    self.recipe.SampleData,
                    seed=resolve_sample_seed(self.recipe.SampleData, self.seed),
                    label_field=label_field,
                )
                _write_dataset(
                    sample_dir(temp_dir),
                    dict(sample_result.samples),
                    rewrite_plan=rewrite_plan,
                )

            current_stage = "Recipe"
            recipe_path(temp_dir).write_text(
                self.recipe.model_dump_json(indent=2), encoding="utf-8"
            )

            current_stage = "Manifest"
            elapsed = time.monotonic() - start
            manifest = Manifest(
                datarefinery_version=__version__,
                plugin=self.plugin.name,
                plugin_version=str(self.plugin.schema_version),
                recipe_hash=cache_key.recipe_hash,
                input_hash=cache_key.input_hash,
                seed=cache_key.seed,
                variant=self.variant,
                created_at=datetime.now(UTC),
                elapsed_seconds=elapsed,
                record_counts={name: len(records) for name, records in split_map.items()},
                warnings=warnings,
                class_balance=self.recipe.Splits.class_balance,
                sinks={
                    r.name: SinkManifestEntry(
                        stage=r.stage,
                        format=r.format,
                        files_written=r.files_written,
                        bytes_total=r.bytes_total,
                        path_template_resolved_root=r.path_template_resolved_root,
                    )
                    for r in sink_results
                },
                sample=(
                    SampleManifestEntry(
                        selector=sample_result.selector_echo,
                        record_counts={
                            name: len(records) for name, records in sample_result.samples.items()
                        },
                    )
                    if sample_result is not None
                    else None
                ),
                label_classes=_compute_label_classes(
                    split_map,
                    label_field=label_field,
                    unlabeled_splits=unlabeled_split_names(self.recipe),
                ),
            )
            write_manifest(manifest_path(temp_dir), manifest)

            current_stage = "Report"
            report_root = report_dir(temp_dir)
            write_report(
                report_root / REPORT_FILENAME,
                render_report_md(self.recipe, manifest, fitted_op_ids=fitted_op_ids),
            )
            drift = compute_drift_placeholder(
                split_map,
                plugin_name=self.plugin.name,
                label_field=label_field,
                unlabeled_splits=unlabeled_split_names(self.recipe),
                recipe_hash=cache_key.recipe_hash,
            )
            write_drift(report_root / DRIFT_FILENAME, drift)

            atomic_promote(temp_dir, final_dir)
        except Exception as exc:
            mark_failed(temp_dir, exc, current_stage)
            raise

        return RunnerResult(instance_dir=final_dir, cache_hit=False, manifest=manifest)

    def _partial_finish(
        self,
        temp_dir: Path,
        cache_key: Any,
        completed_through: str,
        split_map: Mapping[str, list[Record]],
        warnings: list[ManifestWarning],
        start: float,
        *,
        sink_results: list[SinkResult],
        reached_sink_stages: set[str],
    ) -> RunnerResult:
        """Write a partial manifest and return without promoting.

        Used by the ``--stage`` partial-run option. The temp dir is left
        in place so callers can inspect the partially-materialized
        artifacts; ``RunnerResult.is_partial`` is set so the CLI can
        surface the partial status.

        ``sink_results`` carries every sink that fired up to the stop
        point; ``reached_sink_stages`` is the set of sink-stage names
        whose host runner stage executed. The latter drives
        ``manifest.sinks_skipped``: any sink declared on the recipe
        whose stage is *not* in ``reached_sink_stages`` is recorded as
        announced-skipped (Story I.f.1).
        """
        elapsed = time.monotonic() - start
        record_counts = {name: len(rs) for name, rs in split_map.items()} if split_map else {}
        sinks_map = {
            r.name: SinkManifestEntry(
                stage=r.stage,
                format=r.format,
                files_written=r.files_written,
                bytes_total=r.bytes_total,
                path_template_resolved_root=r.path_template_resolved_root,
            )
            for r in sink_results
        }
        sinks_skipped = {
            s.name: s.stage for s in self.recipe.Sinks if s.stage not in reached_sink_stages
        }
        manifest = Manifest(
            datarefinery_version=__version__,
            plugin=self.plugin.name,
            plugin_version=str(self.plugin.schema_version),
            recipe_hash=cache_key.recipe_hash,
            input_hash=cache_key.input_hash,
            seed=cache_key.seed,
            variant=self.variant,
            created_at=datetime.now(UTC),
            elapsed_seconds=elapsed,
            is_partial=True,
            completed_through=completed_through,
            record_counts=record_counts,
            warnings=warnings,
            class_balance=self.recipe.Splits.class_balance,
            sinks=sinks_map,
            sinks_skipped=sinks_skipped,
            label_classes=_compute_label_classes(
                split_map,
                label_field=self.recipe.Labels.field,
                unlabeled_splits=unlabeled_split_names(self.recipe),
            ),
        )
        # Persist enough state to make the temp dir inspectable. We
        # write the recipe so `Instance.load` can reconstruct it; the
        # full report/dataset/visualizations are intentionally skipped
        # because the run did not reach those stages.
        recipe_path(temp_dir).write_text(self.recipe.model_dump_json(indent=2), encoding="utf-8")
        write_manifest(manifest_path(temp_dir), manifest)
        return RunnerResult(
            instance_dir=temp_dir,
            cache_hit=False,
            manifest=manifest,
            is_partial=True,
        )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _wrap(stage: str, messages: Any) -> list[ManifestWarning]:
    return [ManifestWarning(stage=stage, message=str(m)) for m in messages]


def _read_manifest(final_dir: Path) -> Manifest:
    from datarefinery.pipeline.manifest import read_manifest

    return read_manifest(manifest_path(final_dir))


def _compute_label_classes(
    split_map: Mapping[str, list[Record]],
    *,
    label_field: str,
    unlabeled_splits: set[str],
) -> list[Any] | None:
    """Canonical class set across every labeled record (Story J.f, FR-J-2).

    Scans every record in every split except those listed in
    ``unlabeled_splits`` (FR-22), collects the distinct values of
    ``label_field``, and returns them sorted ascending via Python
    ``sorted`` semantics. Records missing the label field within an
    otherwise-labeled split are silently skipped (matches the existing
    OutputExpectations ``skip_missing_label_field`` discipline).

    Returns ``None`` when no labeled record contributes a label —
    distinguishing "fully unlabeled instance" from "instance with an
    empty class set". Downstream MF consumers bind against this list
    for label→logit-index mapping; the producer-side commitment is the
    point.
    """
    seen: set[Any] = set()
    for split_name, records in split_map.items():
        if split_name in unlabeled_splits:
            continue
        for r in records:
            if label_field in r:
                seen.add(r[label_field])
    if not seen:
        return None
    return sorted(seen)


def _write_dataset(
    dataset_root: Path,
    splits: Mapping[str, list[Record]],
    *,
    rewrite_plan: Mapping[str, SinkOp] | None = None,
) -> None:
    """Write per-split JSON-lines summaries and aggressive-variant sidecar PNGs.

    Each line is one record with non-JSON-native fields (numpy arrays,
    bytes, Path) coerced to strings or dropped.

    Two persistence modes for image content coexist:

    - **Non-aggressive records** keep the existing "image bytes resolve
      via source ``path``" behavior. The numpy ``image`` field is
      dropped at JSONL serialization; downstream tools read the source
      file referenced by ``path``.
    - **Aggressive-variant records** (Story H.r.2) — detected by the
      presence of both ``source_record_id`` and ``variant_index`` on the
      record — get a sidecar PNG written to
      ``dataset/<split>/images/<record_id>.png`` and the record's
      ``image`` field replaced by ``image_path`` (a string relative to
      ``dataset_root``) before JSONL serialization. This keeps the
      materialized instance self-contained: a consumer reading the
      JSONL can resolve every variant's image bytes without referring
      back to the (now-augmented-away) source image.

    ``rewrite_plan`` (Story J.g) maps a split name to the qualifying image
    sink that persists its transformed pixels. For non-aggressive records
    in such a split, the record's ``path`` is rewritten to the sink's
    per-record output (instance-relative) so a consumer reading ``path``
    sees the *prepared* pixels, not the diverged source. Splits absent
    from the plan keep their source ``path`` unchanged.
    """
    from PIL import Image as _PIL_Image

    plan = rewrite_plan or {}
    dataset_root.mkdir(parents=True, exist_ok=True)
    for split_name, records in splits.items():
        sidecar_dir = dataset_root / split_name / "images"
        rewrite_sink = plan.get(split_name)
        prepared: list[dict[str, Any]] = []
        for r in records:
            prepared.append(
                _prepare_record_for_persistence(
                    r, split_name, sidecar_dir, _PIL_Image, rewrite_sink
                )
            )
        path = dataset_root / f"{split_name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for r_prepared in prepared:
                fh.write(json.dumps(_serializable(r_prepared), sort_keys=True))
                fh.write("\n")


def _is_aggressive_variant(record: Mapping[str, Any]) -> bool:
    """Aggressive-variant detection rule (Story H.r.2).

    A record is an aggressive variant iff it carries both
    ``source_record_id`` and ``variant_index`` — the metadata fields
    that :func:`...augmentations._realizer.emit_variants` stamps on
    every realized variant. Plain (non-aggressive) records may have an
    ``image`` field too, but they lack these metadata fields and so
    keep the source-path resolution path.
    """
    return "source_record_id" in record and "variant_index" in record


def _prepare_record_for_persistence(
    record: Mapping[str, Any],
    split_name: str,
    sidecar_dir: Path,
    pil_image_module: Any,
    rewrite_sink: SinkOp | None = None,
) -> dict[str, Any]:
    """Return a JSONL-ready copy of ``record``; for aggressive variants,
    side-effect-write the PNG to ``sidecar_dir`` and replace ``image``
    with ``image_path``.

    For non-aggressive records, when ``rewrite_sink`` is provided (Story
    J.g), the ``path`` field is rewritten to the sink's per-record output
    (instance-relative, via the sink's ``path_template``) so consumers see
    the transformed pixels rather than the diverged source.
    """
    if not _is_aggressive_variant(record):
        out = dict(record)
        if rewrite_sink is not None:
            from datarefinery.pipeline.sinks.template import render_template

            out["path"] = render_template(
                rewrite_sink.path_template, record=record, split=split_name
            )
        return out
    img = record.get("image")
    if not isinstance(img, np.ndarray) or img.dtype != np.uint8:
        # No bytes to persist (or wrong dtype) — fall back to passthrough
        # so legacy/non-image plugins aren't accidentally forced through
        # the PNG path.
        return dict(record)
    record_id = str(record["record_id"])
    sidecar_path = sidecar_dir / f"{record_id}.png"
    # Story J.h: ImageFolder stamps `record_id` as `<source>/<class>/<file>`
    # (forward slashes) and the aggressive realizer appends `__v<NNN>`, so the
    # sidecar filename can carry separators that imply nested directories.
    # Create the leaf's parent (not just `sidecar_dir`) so PIL.save does not
    # fail with FileNotFoundError. For flat (manual-API) record_ids the parent
    # is `sidecar_dir` and this is a no-op-equivalent. `record_id` itself is
    # NOT mutated; `image_path` mirrors it verbatim.
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    pil_image_module.fromarray(img).save(sidecar_path, format="PNG", optimize=False)
    out = dict(record)
    out.pop("image", None)
    out["image_path"] = f"{split_name}/images/{record_id}.png"
    return out


def _serializable(record: Record) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in record.items():
        coerced = _coerce(v)
        if coerced is _SKIP:
            continue
        out[k] = coerced
    return out


_SKIP: Any = object()


def _coerce(value: Any) -> Any:
    """Coerce non-JSON-native values to a serializable form, or skip."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value if _coerce(v) is not _SKIP]
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items() if _coerce(v) is not _SKIP}
    if isinstance(value, Path):
        return str(value)
    # numpy arrays, bytes, custom objects: drop from persisted form.
    return _SKIP
