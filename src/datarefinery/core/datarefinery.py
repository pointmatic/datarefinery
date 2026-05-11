# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Library entry point: ``DataRefinery``.

Construction loads + validates the recipe once. Verb methods share that
state and dispatch to the relevant Phase-B/C primitive (loader,
validator, runner, cleaner, reporting). CLI commands wrap these methods
in thin typer surfaces (Phase D follow-on stories).

Several verb methods stub for future stories: ``check`` (D.b),
``status`` (D.f), ``inspect`` (D.h). They are present so the public
class shape is stable and downstream callers can program against the
final API; their bodies raise ``NotImplementedError`` until the owning
story lands them.

``cache_key`` is exposed as a method (not a property) because input
hashes are required to produce a full :class:`CacheKey`; raw-input
loading lives in the materialize CLI verb (D.e), so D.a leaves
caller-supplied input hashes as the explicit contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from datarefinery.cache.cleaner import CleanReport, CleanSelector, clean
from datarefinery.cache.identity import CacheKey, compute_cache_key
from datarefinery.cache.layout import make_run_id, tmp_dir
from datarefinery.core.check import CheckReport, build_check_report
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import PluginError
from datarefinery.core.inspect import InspectionView, build_inspection_view
from datarefinery.core.instance import Instance
from datarefinery.core.status import StatusReport, resolve_status
from datarefinery.pipeline.inputs import hash_inputs, load_raw_records
from datarefinery.pipeline.runner import PipelineRunner, RunnerResult
from datarefinery.plugins.base import Plugin
from datarefinery.plugins.discovery import discover_plugins
from datarefinery.recipe.loader import load as load_recipe
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import ValidationReport
from datarefinery.recipe.validator import validate as validate_recipe
from datarefinery.recipe.variants import apply_variant

Record = Mapping[str, Any]


class DataRefinery:
    """Loaded-recipe container exposing every CLI verb as a method."""

    def __init__(
        self,
        recipe: Recipe,
        plugin: Plugin,
        config: RuntimeConfig,
        seed: int,
        *,
        variant: str | None,
        validation_report: ValidationReport,
    ) -> None:
        self._recipe = recipe
        self._plugin = plugin
        self._config = config
        self._seed = seed
        self._variant = variant
        self._validation_report = validation_report
        self._last_run: RunnerResult | None = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_recipe(
        cls,
        recipe_path: Path,
        config: RuntimeConfig | None = None,
        variant: str | None = None,
        seed: int | None = None,
    ) -> DataRefinery:
        """Load + validate a recipe and return a ready-to-run instance.

        Validation runs exactly once during construction; the report is
        memoized and returned by :meth:`validate`. Variant overlay
        (FR-14) is applied *before* validation so what we validate is
        what :meth:`materialize` will execute.
        """
        config = config if config is not None else RuntimeConfig()
        recipe = load_recipe(Path(recipe_path))
        recipe = apply_variant(recipe, variant)

        plugin = _discover_plugin(recipe.plugin, config.plugin_path)
        report = validate_recipe(recipe, plugin)

        resolved_seed = seed if seed is not None else recipe.seed

        return cls(
            recipe=recipe,
            plugin=plugin,
            config=config,
            seed=resolved_seed,
            variant=variant,
            validation_report=report,
        )

    # ------------------------------------------------------------------
    # Read-only state
    # ------------------------------------------------------------------

    @property
    def recipe(self) -> Recipe:
        """The variant-overlaid, validated recipe."""
        return self._recipe

    @property
    def plugin(self) -> Plugin:
        """The plugin instance backing :attr:`recipe.plugin`."""
        return self._plugin

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def variant(self) -> str | None:
        return self._variant

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    def cache_key(self, raw_input_hashes: Mapping[str, str]) -> CacheKey:
        """Compute the cache identity for this recipe + inputs + seed.

        ``raw_input_hashes`` maps each input source name to a SHA-256
        hex digest of its content. CLI input loading (Story D.e) is
        responsible for producing these; library callers compute them
        themselves.
        """
        return compute_cache_key(self._recipe, raw_input_hashes, self._seed)

    # ------------------------------------------------------------------
    # Verbs
    # ------------------------------------------------------------------

    def validate(self) -> ValidationReport:
        """Return the memoized validation report from construction."""
        return self._validation_report

    def materialize(
        self,
        *,
        raw_records: Sequence[Record] | None = None,
        raw_input_hashes: Mapping[str, str] | None = None,
        stop_after: str | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> Instance:
        """Run the pipeline end-to-end and return the loaded instance.

        With no inputs supplied the pipeline-input loader inflates the
        recipe's ``Input`` sources from disk (currently the
        image_classification ``image_folder`` loader; tabular and text
        plugins refuse). Library callers may pass ``raw_records`` /
        ``raw_input_hashes`` explicitly to bypass disk loading.

        ``stop_after`` selects a partial run by stage name (one of
        :data:`pipeline.runner.STAGE_NAMES`); the result is left in the
        temp directory unpromoted, with ``manifest.is_partial=True``.
        ``progress_callback`` is invoked at the start of each stage.
        """
        if (raw_records is None) != (raw_input_hashes is None):
            raise ValueError(
                "DataRefinery.materialize: pass both raw_records and "
                "raw_input_hashes, or neither (to load from disk)"
            )
        records: list[Record]
        hashes: dict[str, str]
        if raw_records is None:
            loaded, hashes = load_raw_records(self._recipe, self._plugin)
            records = list(loaded)
        else:
            assert raw_input_hashes is not None
            records = [dict(r) for r in raw_records]
            hashes = dict(raw_input_hashes)

        runner = PipelineRunner(
            recipe=self._recipe,
            plugin=self._plugin,
            config=self._config,
            seed=self._seed,
            variant=self._variant,
        )
        result: RunnerResult = runner.run(
            tmp_dir(self._config.cache_root, make_run_id()),
            raw_records=records,
            raw_input_hashes=hashes,
            stop_after=stop_after,
            progress_callback=progress_callback,
        )
        self._last_run = result
        return Instance.load(result.instance_dir)

    @property
    def last_run(self) -> RunnerResult | None:
        """The most recent :class:`RunnerResult`, or ``None`` if not yet run."""
        return self._last_run

    def report(self, instance_path: Path) -> Instance:
        """Re-render the report for a previously materialized instance.

        Rewrites ``report.md``, ``drift.json``, and the reporting-mode
        visualizations from persisted state without rerunning the
        pipeline. The plugin bound to this :class:`DataRefinery` is
        passed through so visualization op factories and dataset
        re-inflation work without the caller wiring them up.
        """
        instance = Instance.load(Path(instance_path))
        instance.render_report(plugin=self._plugin)
        return instance

    def clean(self, selector: CleanSelector, *, force: bool = False) -> CleanReport:
        """Remove cache entries matching ``selector`` (FR-21)."""
        return clean(self._config.cache_root, selector, force=force)

    def status(self) -> StatusReport:
        """Resolve cache identity from disk inputs and report instance state (FR-19).

        Hashes the recipe's input sources via the same path the
        materialize verb uses, computes the cache key, and inspects
        ``<cache_root>/instances/<key>/manifest.json``. Cache miss
        returns a ``StatusReport`` with ``cache_status="miss"``; it is
        not an error.
        """
        hashes = hash_inputs(self._recipe, self._plugin)
        key = compute_cache_key(self._recipe, hashes, self._seed)
        return resolve_status(self._config.cache_root, key)

    def inspect(
        self,
        instance_path: Path | None = None,
        view: str | None = None,
    ) -> InspectionView:
        """Read-only views over a materialized instance (FR-20).

        ``instance_path`` may be omitted; in that case the loaded
        recipe + cache config resolve to the bound instance via the
        same path :meth:`status` uses. A cache miss raises
        :class:`MaterializeError` (inspect requires a materialized
        instance).
        """
        if instance_path is None:
            report = self.status()
            if report.cache_status != "hit":
                from datarefinery.core.errors import MaterializeError

                raise MaterializeError(
                    f"inspect: no materialized instance for this recipe "
                    f"(cache_status={report.cache_status}). Run "
                    f"`datarefinery materialize <recipe>` first."
                )
            instance_path = report.instance_path

        instance = Instance.load(Path(instance_path))
        return build_inspection_view(instance, self._plugin, view=view)

    @staticmethod
    def check(config: RuntimeConfig | None = None) -> CheckReport:
        """Probe runtime soundness (FR-18) and return a structured report.

        Static because environment soundness does not require a loaded
        recipe. The CLI verb in `datarefinery.cli.commands.check_cmd`
        wraps this and renders the result as a `rich` table.
        """
        return build_check_report(config)


def materialize(
    recipe_path: Path,
    *,
    config: RuntimeConfig | None = None,
    variant: str | None = None,
    seed: int | None = None,
) -> Instance:
    """One-shot top-level convenience matching the tech-spec signature.

    Loads the recipe, applies the requested variant, runs FR-2
    validation, inflates the recipe's input sources from disk, and
    materializes the pipeline. Library callers who want to provide
    pre-loaded records bypass this and call
    ``DataRefinery.from_recipe(...).materialize(raw_records=...,
    raw_input_hashes=...)`` directly.
    """
    return DataRefinery.from_recipe(
        Path(recipe_path), config=config, variant=variant, seed=seed
    ).materialize()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _discover_plugin(name: str, extra_paths: tuple[Path, ...]) -> Plugin:
    plugins = discover_plugins(extra_paths=extra_paths or None)
    if name not in plugins:
        raise PluginError(
            f"recipe references plugin {name!r} but discovery only found {sorted(plugins)!r}"
        )
    return plugins[name]
