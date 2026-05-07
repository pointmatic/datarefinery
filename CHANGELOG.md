# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.6] - 2026-05-07

### Added

- Recipe validator checks 14-18 (Story B.e.3, FR-2 part 3) - FR-2 complete:
  - `check_14_generation_output_schema_consistent` cross-checks each
    `GenerationOp.output_schema` against `Output.record_schema` for
    field name presence and dtype/shape match.
  - `check_15_split_references_defined` verifies every per-op
    `splits` and `Generation.applies_at` reference a name declared in
    `Splits.ratios` or `Splits.key_assignment.mapping` values.
  - `check_16_sample_data_strict_subset` enforces that
    `SampleData.selector` declares exactly one of `n` or `fraction`,
    `n >= 1`, and `0 < fraction < 1` (strict subset).
  - `check_17_contract_fields_exist_at_stage` requires `field`
    references in `InputContracts` and `OutputExpectations` to exist
    in the field universe (`Output.record_schema` ∪ `Labels.field`);
    dataset-level assertions with `field=None` pass through.
  - `check_18_plugin_operation_params_validate` looks up each
    Transformation/Augmentation/Featurization/Visualization's `op`
    against `plugin.supported_operations`; flags unknown operations,
    missing required parameters, and unexpected (extra) parameters.
    Type-checking parameter values is deferred to the runner.
  - `tests/unit/test_validator.py` adds 21 new tests including
    per-check failure fixtures, pass cases, and a multi-violation
    cross-check that simultaneously fires 17 distinct checks
    (everything except check 11, which the model already enforces
    at parse time).

## [0.2.5] - 2026-05-07

### Added

- Recipe validator checks 7-13 (Story B.e.2, FR-2 part 2):
  - `check_07_operations_reference_declared_fields` validates
    `FeaturizationOp.inputs` against the field universe
    (`Output.record_schema` keys ∪ `Labels.field` ∪ upstream
    Featurization `output_field`s). Field references inside opaque
    operation params (Filters/Transformations/Augmentations) are
    deferred to check 18.
  - `check_08_splits_partition_correctly` requires exactly one of
    `ratios` or `key_assignment`, non-negative ratios that sum to
    `<= 1.0` (sub-one is allowed; remainder is unsplit), and a
    non-empty `key_assignment.mapping`.
  - `check_09_stratification_keys_exist` checks
    `Splits.stratify_by` against the same field universe (including
    Featurization outputs).
  - `check_10_class_imbalance_strategy_in_one_place` (heuristic v1)
    flags simultaneous handling in `Splits.class_balance` and any
    `FilterOp.predicate` containing a `class_balance` key.
  - `check_11_visualization_mode_declared` is tautological for valid
    recipes (the model already constrains mode to
    `Literal["exploration", "reporting"]`); kept for FR-2
    completeness.
  - `check_12_variants_reference_declared_sections` rejects variant
    overlay keys that aren't valid Recipe section/scalar names.
  - `check_13_labels_resolvable` requires `Labels.field` to be in
    `Output.record_schema`.
  - `tests/unit/test_validator.py` adds 21 new tests covering
    per-check failure fixtures, pass cases, and a multi-violation
    cross-check spanning 6 simultaneous failures across checks 1-13.
  - Checks 14-18 land in B.e.3 (v0.2.6).

## [0.2.4] - 2026-05-07

### Added

- Recipe validator framework + checks 1-6 (Story B.e.1, FR-2 part 1):
  - `src/datarefinery/recipe/validator.py` exposes `CheckStatus`,
    `CheckResult` (frozen dataclass: `check_id`, `descriptor`, `status`,
    `location`, `message`), `ValidationReport` (with `passed`,
    `failures`, `warnings` properties), `validate(recipe, plugin)`
    aggregator that runs every registered check and never short-circuits
    (a check that raises is captured as a fail rather than aborting),
    and the first six checks: `check_01_schema_version_recognized`,
    `check_02_plugin_name_discoverable`,
    `check_03_section_names_valid_for_plugin`,
    `check_04_operations_declare_stages_and_splits`,
    `check_05_augmentations_train_only`,
    `check_06_fit_on_train_uses_train_split` (consults the plugin's
    `OperationSpec.fit_on_train`).
  - `tests/unit/test_validator.py` covers the valid-recipe-passes-all
    case, no-short-circuit aggregation, exception-as-failure capture,
    and per-check failure fixtures for each of checks 1-6 (with
    pre-split / post-split filter splits, train-only augmentations, and
    fit-on-train fit_source discipline edge cases).
  - Checks 7-13 land in B.e.2 (v0.2.5); checks 14-18 land in
    B.e.3 (v0.2.6).

## [0.2.3] - 2026-05-07

### Added

- Variant overlay (Story B.d, FR-14):
  - `src/datarefinery/recipe/variants.py` exposes
    `apply_variant(recipe, variant_name)` which replaces target sections
    wholesale (e.g., `Augmentations: []` clears, `seed: 99` replaces the
    scalar). The returned `Recipe` always has `variants={}` so cache
    identity reflects only the applied semantics — adding or editing
    unused variants does not invalidate cached instances of other
    variants.
  - Unknown variant name raises `RecipeError` listing the declared
    variants. An overlay that produces an invalid recipe surfaces the
    pydantic message wrapped in `RecipeError`.
  - `tests/unit/test_variants.py` covers `None` clears variants,
    section-clear via empty list, scalar replacement, unknown-variant
    failure, declared-variants listed in the message, distinct
    canonical bytes per variant, neutrality to unused variants,
    invalid-overlay handling, and input-recipe immutability.

## [0.2.2] - 2026-05-07

### Added

- Canonical bytes — recipe-side cache reproducibility contract (Story B.c, FR-4):
  - `src/datarefinery/recipe/canonical.py` exposes
    `to_canonical_bytes(recipe)` implementing
    `Recipe.model_dump(mode="json")` →
    `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` →
    UTF-8 encode.
  - `tests/unit/test_canonical.py` covers cosmetic-edit invariance
    (whitespace-only, comment-only, key-reordered YAML), value-edit
    sensitivity (changed scalar, added section), valid-UTF-8-JSON
    output with no whitespace separators, and byte stability across
    repeated calls.
  - **Canonical hash pin:** `_PINNED_DIGEST` records the SHA-256 of
    the baseline fixture's canonical bytes. Bumping this constant is
    a deliberate cache-invalidation event and must follow the
    ceremony in `project-essentials.md` "Cache identity is the
    reproducibility contract".

## [0.2.1] - 2026-05-07

### Added

- Recipe loader with FR-1 schema-version gate (Story B.b):
  - `src/datarefinery/recipe/loader.py` exposes
    `SUPPORTED_SCHEMA_VERSIONS = frozenset({1})`, an empty post-production
    `migrations: dict[(int, int), Callable]` registry, a
    `KNOWN_TOP_LEVEL_KEYS` constant, and `load(path) -> Recipe`. The gate
    runs before model validation; malformed YAML produces a `RecipeError`
    annotated with the offending line/column, and unknown top-level keys
    emit a forward-compatibility `UserWarning` before the inevitable
    `extra="forbid"` validation hard-error.
  - `tests/unit/test_recipe_loader.py` covers happy path, missing
    `schema_version`, unrecognized version (with supported-list +
    FR-1 pointer), non-integer and boolean schema versions, malformed
    YAML with line/column, non-mapping root, the unknown-top-level-key
    warning followed by hard error, and the constant/migrations stubs.

## [0.2.0] - 2026-05-07

### Added

- Recipe pydantic models (Story B.a) — Phase B begins:
  - `src/datarefinery/recipe/models.py` defines `Recipe` plus per-section
    models (`InputSection`, `InputSource`, `OutputSection`, `FieldSpec`,
    `LabelsSection`, `LabelSource`, `SampleDataSection`, `SampleSelector`,
    `Contract`, `Expectation`, `FilterOp`, `GenerationOp`,
    `SplitsSection`, `KeyAssignment`, `TransformationOp`,
    `AugmentationOp`, `FeaturizationOp`, `VisualizationOp`). All models
    inherit from a shared frozen base with `extra="forbid"`. Plugin-
    specific operation parameters are typed as opaque mappings here;
    cross-checking against `OperationSpec` lands in Story B.e.
  - `tests/unit/test_recipe_models.py` covers minimal-recipe validation,
    `model_dump` round-trip, unknown top-level keys, unknown per-section
    keys, missing required sections (`Input`/`Output`/`Labels`/`Splits`)
    and required top-level fields (`schema_version`/`plugin`),
    instance-frozen guarantee, the `mode` Literal on `VisualizationOp`,
    and `SplitsSection` with key-assignment only.

## [0.1.6] - 2026-05-07

### Added

- Plugin protocol and discovery (Story A.h):
  - `src/datarefinery/plugins/base.py` defines a runtime-checkable
    `Plugin` protocol (`name`, `supported_sections`,
    `supported_operations`, `schema_version`, `operation_factory`,
    `is_stub`) plus frozen pydantic `OperationSpec` (parameters,
    `fit_on_train`, `applicable_splits`, `applicable_sections`) and
    `ParameterSpec`. Both models reject extra fields.
  - `src/datarefinery/plugins/discovery.py` exposes
    `discover_plugins(extra_paths=None)` which walks the
    `datarefinery.plugins` entry-point group plus developer extra
    paths (directories or single `.py` files), looking for a
    top-level `PLUGIN` attribute. Duplicate names raise
    `PluginError`; missing paths and unloadable modules raise
    `PluginError` with the file path included.
  - `tests/fixtures/dummy_plugin.py` and `dummy_plugin_dup.py`
    provide a `_test_dummy` plugin and a duplicate-name partner for
    the discovery test suite.
  - `tests/unit/test_plugins_discovery.py` covers extra-paths file
    and directory discovery, duplicate-name failure, missing-path
    failure, `OperationSpec`/`ParameterSpec` extra-field rejection,
    defaults, frozenness, and round-trip parameters.

## [0.1.5] - 2026-05-07

### Added

- Runtime configuration and shared CLI options (Story A.g):
  - `src/datarefinery/core/config.py` defines a frozen pydantic
    `RuntimeConfig` with `cache_root`, `log_level`, `log_target`,
    `plugin_path`, `workers` and a `resolve()` classmethod implementing
    the documented CLI > env > default precedence (env mapping
    overridable for testing). `DATAREFINERY_PLUGIN_PATH` is split on
    `os.pathsep` (POSIX `:`).
  - `cli/app.py` adds shared options at the root callback:
    `--cache-root`, `--log-level`, `--log-target`,
    `--plugin-path` (repeatable), `--workers`, `--seed`, `--variant`,
    `--no-color`, `--quiet`, `--verbose`. The callback builds a
    `RuntimeConfig` and stashes it on the typer `Context` for downstream
    commands.
  - `tests/unit/test_config.py` covers env-only, CLI-only, both
    (CLI wins), partial overrides, empty-string env, PATH-style splitting,
    `frozen=True`, and `extra="forbid"`.

## [0.1.4] - 2026-05-07

### Added

- Error hierarchy and CLI exit-code mapping (Story A.f):
  - `src/datarefinery/core/errors.py` defines `DataRefineryError` plus
    `RecipeError`, `ValidationError`, `PluginError`, `ContractError`,
    `MaterializeError`, `CacheError`.
  - `src/datarefinery/cli/_exit_codes.py` exposes `EXIT_OK`, `EXIT_USER`,
    `EXIT_SYSTEM`, `EXIT_INTERRUPT` and `exit_code_for(exc)` mapping per
    tech-spec (user 1 / system 2 / SIGINT 130).
  - `cli/app.py` adds `main_entry()` that runs the typer app with
    `standalone_mode=False`, catches `DataRefineryError` and
    `KeyboardInterrupt`, renders a `rich` error panel on stderr, and exits
    with the mapped code; uncaught exceptions exit 2.
  - Console script (`pyproject.toml`) and `__main__.py` now route through
    `main_entry`.

### Tests

- `tests/unit/test_errors.py` — exhaustive subclass and exit-code mapping.
- `tests/cli/test_exit_codes.py` — subprocess tests asserting each error
  class produces the documented exit code through `main_entry`, plus
  `KeyboardInterrupt → 130`, uncaught `RuntimeError → 2`, and that
  `--help` / `--version` still exit 0.

## [0.1.3] - 2026-05-07

### Added

- Logging foundation (Story A.e):
  - `src/datarefinery/logging.py` exposes `JsonFormatter` (single-line JSON
    with `ts`, `level`, `logger`, `stage`, `op_id`, `message`, plus an
    `extras` bucket for non-reserved record attributes) and `get_logger`
    helper that idempotently attaches a `NullHandler` and a
    `JsonFormatter` `StreamHandler(stderr)` to the `datarefinery` package
    logger. Importing the module does not touch root logging.
  - CLI startup in `cli/app.py` now initializes the package logger via
    `get_logger("cli")`. `--log-target` is accepted as a reserved no-op
    stub; full routing lands in Story A.g.
  - `tests/unit/test_logging.py` covers single-line JSON shape, required
    fields, `extras` round-trip, and the no-root-handler invariant.

## [0.0.2] - 2026-05-06

### Added

- Hello-world Typer CLI (Story A.b):
  - `src/datarefinery/cli/app.py` exposes a `Typer` app with `--version` and `--help`; `--version` reads `datarefinery.__version__`.
  - `src/datarefinery/__main__.py` so `python -m datarefinery` invokes the CLI.
  - `tests/cli/test_smoke.py` smoke tests asserting `--version` and `--help` exit 0 and surface the package version.

## [0.0.1] - 2026-05-06

### Added

- Initial project scaffolding (Story A.a):
  - Apache-2.0 `LICENSE`.
  - `pyproject.toml` with hatchling backend, runtime dependencies, optional `[llm]` extra, console script, plugin entry-point group, and ruff / mypy / pytest configuration.
  - `requirements-dev.txt` listing the dev tool pinset for the pyve testenv.
  - `src/datarefinery/` package with `__version__` and PEP 561 `py.typed` marker.
  - `tests/` skeleton (`conftest.py` plus `unit/`, `integration/`, `cli/`, `plugin_contract/`, `fixtures/` subdirectories).
  - `README.md` with project tagline, install snippet, and one-line usage example.
  - `.gitignore` covering Python, pyve, build artifacts, and `data/`.
  - `environment.yml` for the pyve micromamba environment (Python 3.12.x).
