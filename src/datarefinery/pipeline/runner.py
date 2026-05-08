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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datarefinery import __version__
from datarefinery.cache.atomic import atomic_promote, mark_failed
from datarefinery.cache.identity import compute_cache_key
from datarefinery.cache.layout import (
    dataset_dir,
    fitted_stats_dir,
    instance_dir,
    manifest_path,
    report_dir,
)
from datarefinery.core.config import RuntimeConfig
from datarefinery.pipeline.contracts import (
    evaluate_input_contracts,
    evaluate_output_expectations,
)
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.manifest import (
    Manifest,
    ManifestWarning,
    write_manifest,
)
from datarefinery.pipeline.stages.augmentations import (
    collect_augmentation_policies,
)
from datarefinery.pipeline.stages.featurizations import apply_featurizations
from datarefinery.pipeline.stages.filters import (
    apply_post_split_filters,
    apply_pre_split_filters,
)
from datarefinery.pipeline.stages.generation import apply_generation
from datarefinery.pipeline.stages.splits import apply_splits, resolve_seed
from datarefinery.pipeline.stages.transformations import apply_transformations
from datarefinery.pipeline.stages.visualizations import (
    apply_reporting_visualizations,
)
from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import Recipe
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


@dataclass(frozen=True)
class RunnerResult:
    """Outcome of one pipeline run."""

    instance_dir: Path
    cache_hit: bool
    manifest: Manifest


class PipelineRunner:
    """Sequence every Phase-C stage and produce a materialized instance."""

    def __init__(
        self,
        recipe: Recipe,
        plugin: Plugin,
        config: RuntimeConfig,
        seed: int,
    ) -> None:
        self.recipe = recipe
        self.plugin = plugin
        self.config = config
        self.seed = seed

    def run(
        self,
        temp_dir: Path,
        *,
        raw_records: list[Record],
        raw_input_hashes: Mapping[str, str],
    ) -> RunnerResult:
        """Execute the pipeline against ``raw_records`` into ``temp_dir``.

        Returns a :class:`RunnerResult` indicating whether the run hit
        cache or materialized fresh. On cache hit, ``temp_dir`` is not
        touched.
        """
        cache_key = compute_cache_key(self.recipe, raw_input_hashes, self.seed)
        final_dir = instance_dir(self.config.cache_root, cache_key)

        if manifest_path(final_dir).exists():
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

        try:
            current_stage = "InputContracts"
            ic = evaluate_input_contracts(
                raw_records, self.recipe.InputContracts
            )
            ic.raise_for_status()
            warnings.extend(
                _wrap(current_stage, (w.message for w in ic.warnings))
            )

            current_stage = "Filters/pre_split"
            pre_filter = apply_pre_split_filters(
                raw_records,
                self.recipe.Filters,
                plugin=self.plugin,
                label_field=label_field,
            )
            warnings.extend(_wrap(current_stage, pre_filter.warnings))
            records = pre_filter.records

            current_stage = "Splits"
            splits = apply_splits(
                records,
                self.recipe.Splits,
                seed=resolve_seed(self.recipe.Splits, self.seed),
            )
            warnings.extend(_wrap(current_stage, splits.warnings))
            split_map: dict[str, list[Record]] = dict(splits.splits)
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

            current_stage = "Filters/post_split"
            post_filter = apply_post_split_filters(
                split_map,
                self.recipe.Filters,
                plugin=self.plugin,
                label_field=label_field,
            )
            for split_name, fr in post_filter.items():
                split_map[split_name] = fr.records
                warnings.extend(_wrap(current_stage, fr.warnings))

            current_stage = "Generation"
            gen_result = apply_generation(
                split_map,
                self.recipe.Generation,
                plugin=self.plugin,
                output_record_schema=self.recipe.Output.record_schema,
                label_field=label_field,
            )
            split_map = dict(gen_result.splits)
            warnings.extend(_wrap(current_stage, gen_result.warnings))

            current_stage = "Transformations"
            fitted_stats = FittedStatistics(fitted_stats_dir(temp_dir))
            tx_result = apply_transformations(
                split_map,
                self.recipe.Transformations,
                plugin=self.plugin,
                fitted_stats=fitted_stats,
                label_field=label_field,
            )
            split_map = dict(tx_result.splits)
            fitted_op_ids: list[str] = list(tx_result.fitted_op_ids)

            current_stage = "Featurizations"
            feat_result = apply_featurizations(
                split_map,
                self.recipe.Featurizations,
                plugin=self.plugin,
                fitted_stats=fitted_stats,
                label_field=label_field,
            )
            split_map = dict(feat_result.splits)
            fitted_op_ids.extend(feat_result.fitted_op_ids)

            current_stage = "Augmentations"
            collect_augmentation_policies(self.recipe.Augmentations)
            # Policies are descriptive only in v1 (FR-11); the
            # serialized block is recorded in the manifest's eventual
            # `augmentations` field via the runner's report writer
            # (Story C.n) - here we just defensively re-validate.

            current_stage = "OutputExpectations"
            all_records = [
                r for split in split_map.values() for r in split
            ]
            oe = evaluate_output_expectations(
                all_records, self.recipe.OutputExpectations
            )
            oe.raise_for_status()
            warnings.extend(
                _wrap(current_stage, (w.message for w in oe.warnings))
            )

            current_stage = "Visualizations"
            viz_dir = report_dir(temp_dir) / "visualizations"
            apply_reporting_visualizations(
                split_map,
                self.recipe.Visualizations,
                plugin=self.plugin,
                output_dir=viz_dir,
                label_field=label_field,
            )

            current_stage = "Dataset"
            _write_dataset(dataset_dir(temp_dir), split_map)

            current_stage = "Manifest"
            elapsed = time.monotonic() - start
            manifest = Manifest(
                datarefinery_version=__version__,
                plugin=self.plugin.name,
                plugin_version=str(self.plugin.schema_version),
                recipe_hash=cache_key.recipe_hash,
                input_hash=cache_key.input_hash,
                seed=cache_key.seed,
                variant=None,
                created_at=datetime.now(UTC),
                elapsed_seconds=elapsed,
                record_counts={
                    name: len(records) for name, records in split_map.items()
                },
                warnings=warnings,
            )
            write_manifest(manifest_path(temp_dir), manifest)

            current_stage = "Report"
            report_root = report_dir(temp_dir)
            write_report(
                report_root / REPORT_FILENAME,
                render_report_md(
                    self.recipe, manifest, fitted_op_ids=fitted_op_ids
                ),
            )
            drift = compute_drift_placeholder(
                split_map,
                plugin_name=self.plugin.name,
                label_field=label_field,
            )
            write_drift(report_root / DRIFT_FILENAME, drift)

            atomic_promote(temp_dir, final_dir)
        except Exception as exc:
            mark_failed(temp_dir, exc, current_stage)
            raise

        return RunnerResult(
            instance_dir=final_dir, cache_hit=False, manifest=manifest
        )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _wrap(stage: str, messages: Any) -> list[ManifestWarning]:
    return [ManifestWarning(stage=stage, message=str(m)) for m in messages]


def _read_manifest(final_dir: Path) -> Manifest:
    from datarefinery.pipeline.manifest import read_manifest

    return read_manifest(manifest_path(final_dir))


def _write_dataset(
    dataset_root: Path, splits: Mapping[str, list[Record]]
) -> None:
    """Write per-split JSON-lines summaries.

    Each line is one record with non-JSON-native fields (numpy arrays,
    bytes, Path) coerced to strings or dropped. v1 simplification:
    image bytes are not persisted; downstream tools resolve image
    content via the source ``path`` field.
    """
    dataset_root.mkdir(parents=True, exist_ok=True)
    for split_name, records in splits.items():
        path = dataset_root / f"{split_name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(_serializable(r), sort_keys=True))
                fh.write("\n")


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
