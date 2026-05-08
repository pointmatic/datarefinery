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

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from datarefinery.cache.cleaner import CleanReport, CleanSelector, clean
from datarefinery.cache.identity import CacheKey, compute_cache_key
from datarefinery.cache.layout import make_run_id, tmp_dir
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import PluginError
from datarefinery.core.instance import Instance
from datarefinery.pipeline.runner import PipelineRunner
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
        raw_records: Sequence[Record],
        raw_input_hashes: Mapping[str, str],
    ) -> Instance:
        """Run the pipeline end-to-end and return the loaded instance.

        Raw-input loading is the caller's responsibility in v1 — the
        materialize CLI verb (Story D.e) wires disk-backed loaders.
        Library callers can synthesize records in-memory or call
        domain-specific loaders directly.
        """
        runner = PipelineRunner(
            recipe=self._recipe,
            plugin=self._plugin,
            config=self._config,
            seed=self._seed,
            variant=self._variant,
        )
        result = runner.run(
            tmp_dir(self._config.cache_root, make_run_id()),
            raw_records=list(raw_records),
            raw_input_hashes=raw_input_hashes,
        )
        return Instance.load(result.instance_dir)

    def report(self, instance_path: Path) -> Instance:
        """Re-render the report for a previously materialized instance."""
        instance = Instance.load(Path(instance_path))
        instance.render_report()
        return instance

    def clean(
        self, selector: CleanSelector, *, force: bool = False
    ) -> CleanReport:
        """Remove cache entries matching ``selector`` (FR-21)."""
        return clean(self._config.cache_root, selector, force=force)

    def status(self, instance_path: Path | None = None) -> Any:
        """Summarize an instance (FR-19). Implementation lands in D.f."""
        del instance_path
        raise NotImplementedError(
            "DataRefinery.status() lands in Story D.f (CLI verb: status)"
        )

    def inspect(self, view: str | None = None) -> Any:
        """Read-only views (FR-20). Implementation lands in D.h."""
        del view
        raise NotImplementedError(
            "DataRefinery.inspect() lands in Story D.h (CLI verb: inspect)"
        )

    @staticmethod
    def check(config: RuntimeConfig | None = None) -> Any:
        """Environment soundness report (FR-18). Implementation lands in D.b."""
        del config
        raise NotImplementedError(
            "DataRefinery.check() lands in Story D.b (CLI verb: check)"
        )


def materialize(
    recipe_path: Path,
    *,
    config: RuntimeConfig | None = None,
    variant: str | None = None,
    seed: int | None = None,
) -> Instance:
    """One-shot top-level convenience matching the tech-spec signature.

    Disk-backed input loading lands with the materialize CLI verb in
    Story D.e; until then this convenience raises ``NotImplementedError``
    pointing at the explicit
    :meth:`DataRefinery.materialize` method, which accepts
    caller-supplied ``raw_records`` + ``raw_input_hashes``.
    """
    del recipe_path, config, variant, seed
    raise NotImplementedError(
        "Top-level materialize() requires disk-backed input loading, "
        "which lands in Story D.e (CLI verb: materialize). Use "
        "DataRefinery.from_recipe(...).materialize(raw_records=..., "
        "raw_input_hashes=...) in the meantime."
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _discover_plugin(name: str, extra_paths: tuple[Path, ...]) -> Plugin:
    plugins = discover_plugins(extra_paths=extra_paths or None)
    if name not in plugins:
        raise PluginError(
            f"recipe references plugin {name!r} but discovery only "
            f"found {sorted(plugins)!r}"
        )
    return plugins[name]
