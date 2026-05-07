# stories.md -- DataRefinery (Python 3.12.x)

This document breaks the `DataRefinery` project into an ordered sequence of small, independently completable stories grouped into phases. Each story has a checklist of concrete tasks. Stories are organized by phase and reference modules defined in `tech-spec.md`.

Put **`vX.Y.Z` in the story title only when that story ships the package version bump** for that release. Doc-only or polish stories **omit the version from the title** (they share the release with the preceding code story, or use your project's doc-release policy). **One semver bump per owning story** — extra tasks on the *same* story share that bump; see `project-essentials.md`. Semantic versioning applies to the package. Stories are marked with `[Planned]` initially and changed to `[Done]` when completed.

For a high-level concept (why), see [`concept.md`](concept.md). For requirements and behavior (what), see [`features.md`](features.md). For implementation details (how), see [`tech-spec.md`](tech-spec.md). For project-specific must-know facts, see [`project-essentials.md`](project-essentials.md) (`plan_phase` appends new facts per phase). For the workflow steps tailored to the current mode (cycle steps, approval gates, conventions), see [`docs/project-guide/go.md`](../project-guide/go.md) — re-read it whenever the mode changes or after context compaction.

---

## Phase A: Foundation

Establish the project's structural and operational scaffolding: package layout, build/dev tooling, CLI entry-point wiring, an early end-to-end critical-path spike, the PyPI name reservation, and the cross-cutting primitives (logging, errors, runtime config, plugin discovery) that every later module depends on. Phase A executes in `scaffold_project` mode for A.a and `code_test_first` mode thereafter.

### Story A.a: v0.0.1 Project Scaffolding [Done]

Lay down the repo skeleton: license, manifest, README, changelog, gitignore, src layout, environment file. This story is executed in `scaffold_project` mode, not `code_test_first`. It is marked `[Done]` by `scaffold_project` mode upon completion.

- [x] Add `LICENSE` (Apache-2.0) at repo root.
- [x] Create `pyproject.toml` with hatchling backend, project metadata, runtime deps from tech-spec, optional `[llm]` extra, console script, and entry-point group `datarefinery.plugins`.
- [x] Create `README.md` with project tagline, install snippet, one-line usage example.
- [x] Create `CHANGELOG.md` seeded with `## [0.0.1]` entry.
- [x] Create `.gitignore` covering Python, pyve, build artifacts, `data/`.
- [x] Create `environment.yml` for the pyve micromamba env (Python 3.12.x).
- [x] Create `requirements-dev.txt` listing ruff, mypy, pytest, pytest-cov, hypothesis, types-pyyaml, build.
- [x] Establish `src/datarefinery/` package directory with `__init__.py` exposing `__version__ = "0.0.1"` and a `py.typed` marker file.
- [x] Create `tests/` directory with empty `conftest.py` and `unit/`, `integration/`, `cli/`, `plugin_contract/`, `fixtures/` subdirectories.
- [x] Apply copyright + SPDX header to every new `.py`/`.yml`/shell file per `project-essentials.md`.
- [x] Initialize main venv: `pyve run pip install -e .`.
- [x] Initialize testenv: `pyve testenv init && pyve testenv run pip install -e . && pyve testenv install -r requirements-dev.txt`.
- [x] Configure `ruff` and `mypy --strict` sections in `pyproject.toml`; configure `[tool.pytest.ini_options]` (testpaths, addopts).
- [x] Bump version to v0.0.1
- [x] Update CHANGELOG.md
- [x] Verify: `pyve run python -c "import datarefinery; print(datarefinery.__version__)"` prints `0.0.1`; `pyve testenv run ruff check src tests` and `pyve testenv run mypy src` pass clean.

### Story A.b: v0.0.2 Hello-World CLI [Done]

Smallest runnable CLI artifact proving the entry-point and test runner are wired up.

- [x] Add `src/datarefinery/cli/__init__.py` and `src/datarefinery/cli/app.py` with a typer `app = Typer()` instance.
- [x] Implement `--version` and `--help` at the root command; `--version` reads `datarefinery.__version__`.
- [x] Add `src/datarefinery/__main__.py` so `python -m datarefinery` invokes the CLI.
- [x] Add `tests/cli/test_smoke.py` asserting `datarefinery --version` exits 0 and prints the package version.
- [x] Bump version to v0.0.2
- [x] Update CHANGELOG.md
- [x] Verify: `pyve run datarefinery --version` prints `0.0.2`; `pyve test tests/cli/test_smoke.py` passes.

### Story A.c: End-to-End Stack Spike [Done]

Throwaway script wiring the full critical path together (recipe load → canonical bytes → SHA-256 → temp-dir create → atomic promote → manifest write) before production modules exist. Lives in `scripts/`, not in the package. No version bump (no shipped code).

- [x] Create `scripts/spike_critical_path.py` that:
  - [x] Hard-codes a tiny recipe dict (no plugin yet); serializes via `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
  - [x] Computes a SHA-256 hex digest over the canonical bytes.
  - [x] Creates `./data/instances/.tmp/<run-id>/` directory.
  - [x] Writes a stub `manifest.json` containing the recipe hash, a fake input hash, seed=0, and a UTC timestamp.
  - [x] Calls `os.replace(temp_dir, final_dir)` to promote into `./data/instances/<hash16>/<input16>/0/`.
  - [x] Re-runs and confirms the second run lands on the existing path (idempotent on identical inputs).
- [x] Add a `# spike — do not import from src/` warning at the top of the script.
- [x] Document discoveries (cross-device `os.replace` traps, `pathlib` vs `os` ergonomics, run-id format) in a comment block at the bottom of the file for the implementation stories to reference.
- [x] Verify: running the spike twice produces one promoted instance directory and prints `cache=hit` on the second run.

### Story A.d: PyPI Trusted Publishing & Name Reservation [Deferred]

> **Deferred 2026-05-07.** Neither `datarefinery` nor `data-refinery` is
> available on PyPI; the package name needs to be resolved before this story
> can ship. Version slot is released back to the next shippable story.
> Re-pick this story up after the name decision is made; revisit whether the
> Trusted Publishing flow as designed is still the right shape at that time.

Claim the package name on PyPI before substantive feature work. The publish workflow + minimal `pyproject.toml` + `LICENSE` + minimal `README.md` together cut the reservation upload via OIDC trusted publishing.

- [ ] Configure the PyPI project's Trusted Publishing binding: GitHub repo, workflow filename `publish.yml`, environment `pypi`.
- [ ] Configure the TestPyPI project's Trusted Publishing binding similarly with environment `testpypi`.
- [ ] Add `.github/workflows/publish.yml` with three jobs: build (`python -m build`), publish-to-testpypi (always on tag), publish-to-pypi (tag from `main`, gated by `pypi` environment protection rules).
- [ ] Use `pypa/gh-action-pypi-publish` for both publish steps.
- [ ] Add a "Publishing" section to `README.md` documenting that releases are tag-driven.
- [ ] Verify wheel + sdist build locally: `pyve testenv run python -m build`.
- [ ] Bump version (slot TBD when story is re-picked)
- [ ] Update CHANGELOG.md
- [ ] Verify: tag push from `main` triggers publish workflow; both TestPyPI and PyPI receive the upload; `pip install <package>==<version>` from a clean venv succeeds and `<package> --version` prints the version.

### Story A.e: v0.1.3 Logging Foundation [Done]

JSON line-formatted operational logger separated from `rich` user-facing output (per tech-spec cross-cutting concerns).

- [x] Add `src/datarefinery/logging.py` with `JsonFormatter` (fields: `ts`, `level`, `logger`, `stage`, `op_id`, `message`, plus `extras`).
- [x] Add `get_logger(name: str) -> logging.Logger` helper that attaches a `NullHandler` for library callers.
- [x] Wire CLI startup (in `cli/app.py`) to install a `JsonFormatter` `StreamHandler` writing to stderr by default; honor a future `--log-target` option as a no-op stub for now.
- [x] Unit tests: a logged record produces a single line of valid JSON with all required fields; library import alone does not configure root logging.
- [x] Bump version to v0.1.3
- [x] Update CHANGELOG.md
- [x] Verify: `pyve run python -c "import logging, datarefinery.logging as l; lg=l.get_logger('x'); lg.info('hi', extra={'stage':'s','op_id':'o'})"` emits a single JSON line containing `"stage": "s"`.

### Story A.f: v0.1.4 Error Hierarchy [Done]

Define the exception tree that every later module raises against, plus the CLI exit-code mapping.

- [x] Add `src/datarefinery/core/__init__.py`, `src/datarefinery/core/errors.py` with the hierarchy from tech-spec: `DataRefineryError` → `RecipeError`, `ValidationError`, `PluginError`, `ContractError`, `MaterializeError`, `CacheError`.
- [x] Add `cli/_exit_codes.py` mapping exception type → exit code (0/1/2/130) per tech-spec CLI design.
- [x] Wire `cli/app.py` to catch `DataRefineryError` subclasses, print a structured `rich` error panel, and exit with the mapped code; also catch `KeyboardInterrupt` → exit 130.
- [x] Unit tests: each exception subclass maps to the expected exit code; uncaught exceptions exit 2.
- [x] Bump version to v0.1.4
- [x] Update CHANGELOG.md
- [x] Verify: `pyve test tests/unit/test_errors.py` passes; a deliberate raise of each subclass through the CLI surface yields the documented exit code.

### Story A.g: v0.1.5 RuntimeConfig and Configuration Precedence [Done]

Pydantic `RuntimeConfig` populated from CLI flags and env vars; recipe never reads from this surface (per `project-essentials.md` "Recipe is authoritative").

- [x] Add `src/datarefinery/core/config.py` with `RuntimeConfig` (cache_root, log_level, log_target, plugin_path, workers).
- [x] Add shared CLI options to `cli/app.py`: `--cache-root`, `--log-level`, `--log-target`, `--plugin-path` (repeatable), `--workers`, `--seed`, `--variant`, `--no-color`, `--quiet`, `--verbose`, `--version`.
- [x] Map env vars `DATAREFINERY_CACHE_ROOT`, `DATAREFINERY_LOG_LEVEL`, `DATAREFINERY_LOG_TARGET`, `DATAREFINERY_PLUGIN_PATH` (PATH-style on POSIX), `DATAREFINERY_WORKERS` to the same fields with lower precedence than CLI flags.
- [x] Document in module docstring (one short line) that data-pipeline semantics never read from `RuntimeConfig`; only execution context does.
- [x] Unit tests covering precedence: env-only, CLI-only, both (CLI wins), defaults.
- [x] Bump version to v0.1.5
- [x] Update CHANGELOG.md
- [x] Verify: precedence tests pass; `datarefinery --cache-root /tmp/x --version` does not error.

### Story A.h: v0.1.6 Plugin Protocol and Discovery [Done]

Plugin abstraction landed *before* recipe validator, since validator check 2 + check 18 require the plugin contract.

- [x] Add `src/datarefinery/plugins/__init__.py`, `src/datarefinery/plugins/base.py` with `Plugin` protocol (`name`, `supported_sections`, `supported_operations`, `schema_version`, `operation_factory`, `is_stub`) and `OperationSpec` pydantic model (parameter schema, fit-on-train flag, applicable splits, stage applicability).
- [x] Add `src/datarefinery/plugins/discovery.py` with `discover_plugins(extra_paths)` walking entry-point group `datarefinery.plugins` and `extra_paths`; raise `PluginError` on duplicate names.
- [x] Add a `_test_dummy` plugin (in `tests/fixtures/`, registered ad-hoc via `extra_paths`) that satisfies the protocol and is used by discovery tests.
- [x] Unit tests: discovery returns the test plugin via `extra_paths`; duplicate-name raises `PluginError`; `OperationSpec` parameter validation rejects extra fields.
- [x] Bump version to v0.1.6
- [x] Update CHANGELOG.md
- [x] Verify: `pyve test tests/unit/test_plugins_discovery.py` passes.

---

## Phase B: Recipe & Cache Core Services

The reproducibility contract is built here: recipe → pydantic model → canonical bytes → SHA-256 → cache layout → atomic promotion. Every stage of Phase C depends on these primitives. Cache identity is the most consequential surface in the project; per `project-essentials.md` post-production it is invalidation-ceremonious, but in this phase we are establishing the canonical algorithm itself.

### Story B.a: v0.2.0 Recipe Pydantic Models [Done]

Pydantic v2 models for `Recipe` and every section, frozen and `extra="forbid"` so unknown keys produce loud failures.

- [x] Add `src/datarefinery/recipe/__init__.py`, `src/datarefinery/recipe/models.py`.
- [x] Define `Recipe` plus per-section models per tech-spec table: `InputSection`, `OutputSection`, `LabelsSection`, `SampleDataSection`, `Contract`, `Expectation`, `FilterOp`, `GenerationOp`, `SplitsSection`, `TransformationOp`, `AugmentationOp`, `FeaturizationOp`, `VisualizationOp`.
- [x] All models use `model_config = ConfigDict(extra="forbid", frozen=True)`.
- [x] Per-section models have minimum viable fields wired (full plugin-specific param shapes are validated by `OperationSpec` later).
- [x] Unit tests: round-trip a small recipe dict through `Recipe.model_validate(...)` and `model_dump()`; unknown keys raise; missing required sections raise.
- [x] Bump version to v0.2.0
- [x] Update CHANGELOG.md
- [x] Verify: `pyve test tests/unit/test_recipe_models.py` passes.

### Story B.b: v0.2.1 Recipe Loader and Schema-Version Gate (FR-1) [Done]

YAML → dict → `Recipe`, with the schema-version gate as the first thing that runs.

- [x] Add `src/datarefinery/recipe/loader.py` with `SUPPORTED_SCHEMA_VERSIONS = frozenset({1})` and `load(path) -> Recipe`.
- [x] Use `yaml.safe_load`; wrap `yaml.YAMLError` into `RecipeError` with line/column.
- [x] Refuse missing/unrecognized `schema_version` with `RecipeError` listing supported versions and the migration-path pointer (placeholder for now).
- [x] Stub `recipe.loader.migrations: dict[tuple[int, int], Callable]` (empty for v1; reserved for post-production).
- [x] Unit tests: each FR-1 edge case (missing version, unrecognized version, malformed YAML, unknown top-level key warning).
- [x] Bump version to v0.2.1
- [x] Update CHANGELOG.md
- [x] Verify: loader-edge-case tests all pass with the documented error text.

### Story B.c: v0.2.2 Canonical Bytes (FR-4) [Done]

The canonical-form algorithm. **This is the cache reproducibility contract** — see `project-essentials.md` "Cache identity is the reproducibility contract — invalidations are ceremonious." Every pydantic field default is part of the canonical bytes.

- [x] Add `src/datarefinery/recipe/canonical.py` with `to_canonical_bytes(recipe: Recipe) -> bytes` implementing `model_dump(mode="json")` → `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` → UTF-8 encode.
- [x] Unit tests: byte-identical output for whitespace-only YAML edits, comment-only edits, key-reordered YAML; different output for any value change.
- [x] Add a fixture recipe and a pinned hex digest constant; unit test asserts the digest matches (the canonical-hash pinning test that gates accidental default changes).
- [x] Bump version to v0.2.2
- [x] Update CHANGELOG.md
- [x] Verify: cosmetic-edit invariance tests pass; the pinned canonical-hash test passes.

### Story B.d: v0.2.3 Variant Overlay (FR-14) [Done]

Variants applied **before** canonicalization so cache identity reflects the selected variant.

- [x] Add `src/datarefinery/recipe/variants.py` with `apply_variant(recipe, variant_name)`.
- [x] Variant overlays merge per-section (allow `Augmentations: []` to clear; allow scalar replacements).
- [x] Unit tests: each variant produces a different `to_canonical_bytes` output; default (no variant) leaves recipe unchanged; unknown variant name raises `RecipeError`.
- [x] Bump version to v0.2.3
- [x] Update CHANGELOG.md
- [x] Verify: variant-cache-identity tests pass.

### Story B.e.1: v0.2.4 Recipe Validator framework + checks 1–6 (FR-2 part 1) [Done]

Land the validator framework that the rest of FR-2 builds on, plus the first six checks (schema/plugin recognition, section validity, operation declarations, augmentation discipline, fit-on-train discipline). `validate(...)` never short-circuits — it runs every registered check.

- [x] Add `src/datarefinery/recipe/validator.py` with the framework: `CheckStatus = Literal["pass", "fail", "warn"]`; `CheckResult` dataclass (`check_id: int`, `descriptor: str`, `status`, `location: str | None`, `message: str`); `ValidationReport` dataclass listing every result with `passed`, `failures`, `warnings` properties; `validate(recipe, plugin) -> ValidationReport` aggregator that runs every registered check and never short-circuits.
- [x] Implement checks 1–6 as `check_01_schema_version_recognized`, `check_02_plugin_name_discoverable`, `check_03_section_names_valid_for_plugin`, `check_04_operations_declare_stages_and_splits`, `check_05_augmentations_train_only`, `check_06_fit_on_train_uses_train_split`.
- [x] Per-check failure fixtures + unit tests asserting the right check fires for each violation.
- [x] Unit tests: a fully valid recipe passes all six checks; a recipe violating multiple checks (within 1–6) reports every failure (no short-circuit).
- [x] Bump version to v0.2.4
- [x] Update CHANGELOG.md
- [x] Verify: `pyve test tests/unit/test_validator.py` passes; checks 1–6 fire as documented.

### Story B.e.2: v0.2.5 Recipe Validator: checks 7–13 (FR-2 part 2) [Done]

Field references, splits structure, class-imbalance strategy, visualization mode, variants targets, Labels resolvability.

- [x] Implement checks 7–13 as `check_07_operations_reference_declared_fields`, `check_08_splits_partition_correctly`, `check_09_stratification_keys_exist`, `check_10_class_imbalance_strategy_in_one_place`, `check_11_visualization_mode_declared`, `check_12_variants_reference_declared_sections`, `check_13_labels_resolvable`.
- [x] Per-check failure fixtures + unit tests asserting the right check fires for each violation.
- [x] Unit test: a recipe violating multiple of checks 1–13 reports every failure (no short-circuit).
- [x] Bump version to v0.2.5
- [x] Update CHANGELOG.md
- [x] Verify: checks 7–13 fire as documented.

### Story B.e.3: v0.2.6 Recipe Validator: checks 14–18 (FR-2 part 3) [Planned]

Generation→Output schema consistency, defined-split references, SampleData subset, contracts/expectations field existence, plugin-OperationSpec parameter validation. Check 18 cross-checks each operation's `params` against the declaring plugin's `OperationSpec` from Story A.h.

- [ ] Implement checks 14–18 as `check_14_generation_output_schema_consistent`, `check_15_split_references_defined`, `check_16_sample_data_strict_subset`, `check_17_contract_fields_exist_at_stage`, `check_18_plugin_operation_params_validate`.
- [ ] Per-check failure fixtures + unit tests asserting the right check fires for each violation.
- [ ] Unit tests: a fully valid recipe passes all 18 checks; a multi-violation recipe spanning checks 1–18 reports every failure (no short-circuit).
- [ ] Bump version to v0.2.6
- [ ] Update CHANGELOG.md
- [ ] Verify: full FR-2 check suite (1–18) fires as documented.

### Story B.f: v0.2.7 Cache Identity (FR-4) [Planned]

`CacheKey` and `compute_cache_key` combining recipe canonical hash + input hash + seed.

- [ ] Add `src/datarefinery/cache/__init__.py`, `src/datarefinery/cache/identity.py`.
- [ ] Implement `CacheKey` frozen dataclass (`recipe_hash: str`, `input_hash: str`, `seed: int`) with `.short` returning `recipe_hash[:16]`.
- [ ] Implement `compute_cache_key(recipe, raw_inputs, seed)`: SHA-256 over canonical bytes; SHA-256 over sorted-by-name concatenation of per-source content hashes; combined with seed.
- [ ] Unit tests: byte-identical recipe + inputs + seed → identical key; any change → different key; sources sorted by declared name (order-independent).
- [ ] Bump version to v0.2.7
- [ ] Update CHANGELOG.md
- [ ] Verify: cache-identity tests pass.

### Story B.g: v0.2.8 Cache Layout Helpers [Planned]

`CachePaths` helpers under `<cache-root>` matching the layout in tech-spec.

- [ ] Add `src/datarefinery/cache/layout.py` with helpers: `instance_dir(cache_root, key)`, `tmp_dir(cache_root, run_id)`, `manifest_path(instance_dir)`, `report_dir(instance_dir)`, `dataset_dir(...)`, `fitted_stats_dir(...)`.
- [ ] Implement `make_run_id() -> str` returning `<utc_iso_compact>-<8hex>`.
- [ ] Unit tests: layout helpers produce the documented path shape; `make_run_id` outputs are sortable and unique under concurrent calls.
- [ ] Bump version to v0.2.8
- [ ] Update CHANGELOG.md
- [ ] Verify: layout-helper tests pass.

### Story B.h: v0.2.9 Atomic Temp-then-Promote (FR-5) [Planned]

`os.replace`-based promotion with cross-device guard and `FAILED` marker on failure.

- [ ] Add `src/datarefinery/cache/atomic.py` with `atomic_promote(temp_dir, final_dir)` and `mark_failed(temp_dir, exc, stage)`.
- [ ] `atomic_promote` validates `os.stat().st_dev` of `temp_dir.parent` and `final_dir.parent` match; raises `MaterializeError` on mismatch with the documented "same-filesystem" message.
- [ ] `mark_failed` writes `FAILED` JSON marker (stage, exc_type, message, traceback).
- [ ] Unit tests: success path promotes and removes temp; failure path leaves temp + `FAILED` marker; cross-device case is exercised on a tmpfs/loopback (skip on platforms where multi-device tmp isn't easy).
- [ ] Bump version to v0.2.9
- [ ] Update CHANGELOG.md
- [ ] Verify: atomic-promote tests pass; injected-failure test leaves the expected `FAILED` artifact.

### Story B.i: v0.2.10 Cache Cleaner (FR-21) [Planned]

`clean` selectors: by-recipe, by-age, orphans, all. Library API only in this story; CLI verb lands in Phase D.

- [ ] Add `src/datarefinery/cache/cleaner.py` with `CleanSelector` and `clean(cache_root, selector, *, force=False) -> CleanReport`.
- [ ] Selectors: `by_recipe_hash`, `by_input_hash`, `by_seed`, `by_age_days` (mtime threshold), `orphans` (temp dirs older than threshold), `all` (requires `force=True`).
- [ ] Unit tests covering each selector against a synthesized cache layout fixture; `all` without `force` raises; orphan threshold respected.
- [ ] Bump version to v0.2.10
- [ ] Update CHANGELOG.md
- [ ] Verify: `pyve test tests/unit/test_cleaner.py` passes.

---

## Phase C: Pipeline & Orchestration

This is where DataRefinery actually does work: stages execute against a plugin's operations, fitted statistics persist, parallel workers preserve determinism, and the pipeline runner sequences everything inside an atomic temp-then-promote materialization. Phase C opens with a spike because it introduces the plugin/operation integration boundary.

### Story C.a: Plugin-Driven Operation Execution Spike [Planned]

Throwaway script in `scripts/` that exercises one real operation through the plugin protocol end-to-end (load tiny image fixture → invoke a single resize operation via plugin factory → write output). Validates the plugin abstraction against a real op before committing the full set. No version bump.

- [ ] Create `scripts/spike_plugin_op.py` that:
  - [ ] Builds a minimal in-memory `Plugin` instance with one resize operation.
  - [ ] Loads three Pillow-decoded PNGs.
  - [ ] Invokes the plugin's `operation_factory("Transformations", "resize")` and applies it.
  - [ ] Writes outputs to `./scratch/spike/` and prints shape/dtype.
- [ ] Document any abstraction friction discovered (signatures, lifecycle, error handling) at the bottom of the script for C.b/C.h to consume.
- [ ] Verify: spike script runs end-to-end and produces three resized PNGs.

### Story C.b: v0.3.0 Image Plugin Skeleton [Planned]

`image_classification` plugin module with the section list, operation registry, and parameter schemas — but no operation logic yet. Lets the validator's check 18 light up immediately and gives later stage stories a concrete plugin to register against.

- [ ] Add `src/datarefinery/plugins/image_classification/__init__.py`, `src/datarefinery/plugins/image_classification/plugin.py`, `src/datarefinery/plugins/image_classification/operations/__init__.py`.
- [ ] Declare `name`, `supported_sections`, `supported_operations` (resize, normalize, augment, label_from_path, sample, …) with full `OperationSpec` parameter schemas.
- [ ] Register the plugin under entry-point group `datarefinery.plugins` in `pyproject.toml`.
- [ ] `operation_factory(...)` raises `NotImplementedError` for now; `is_stub() -> False`.
- [ ] Plugin contract test (`tests/plugin_contract/test_image_classification.py`) asserts declared sections and operation schemas validate against fixture parameter dicts.
- [ ] Bump version to v0.3.0
- [ ] Update CHANGELOG.md
- [ ] Verify: `discover_plugins()` returns the image plugin; the plugin contract test passes.

### Story C.c: v0.3.1 Plugin Stubs: Tabular and Text [Planned]

Validate-clean, materialize-fail stubs. Confirms the plugin abstraction doesn't bake in image assumptions.

- [ ] Add `src/datarefinery/plugins/tabular/plugin.py` and `src/datarefinery/plugins/text/plugin.py` declaring sections + operation outlines per tech-spec.
- [ ] `is_stub() -> True`; `operation_factory(...)` raises `PluginError("stub plugin; not implemented")`.
- [ ] Register under entry-point group `datarefinery.plugins` in `pyproject.toml`.
- [ ] Plugin contract tests for both stubs assert section lists and operation outlines.
- [ ] Smoke test: a recipe declaring `plugin: tabular` validates clean but raises `PluginError` at materialize time with the documented message.
- [ ] Bump version to v0.3.1
- [ ] Update CHANGELOG.md
- [ ] Verify: stub plugin contract tests pass; tabular validate-clean / materialize-fail smoke test passes.

### Story C.d: v0.3.2 Pipeline Contracts: InputContracts and OutputExpectations (FR-23) [Planned]

Assertion evaluation for declared contracts and expectations.

- [ ] Add `src/datarefinery/pipeline/__init__.py`, `src/datarefinery/pipeline/contracts.py`.
- [ ] Implement `evaluate_input_contracts(records, contracts) -> ContractResult` and `evaluate_output_expectations(dataset, expectations) -> ContractResult`.
- [ ] Failures raise `ContractError`; severities `error` and `warning` honored.
- [ ] Unit tests: each assertion type (record-count bounds, required field, dtype, range, distributional placeholder) passes/fails as documented.
- [ ] Bump version to v0.3.2
- [ ] Update CHANGELOG.md
- [ ] Verify: contract evaluation tests pass.

### Story C.e: v0.3.3 Splits Stage (FR-7) [Planned]

Train/val/test partitioning with stratification, key-based assignment, and class-balance strategies.

- [ ] Add `src/datarefinery/pipeline/stages/__init__.py`, `src/datarefinery/pipeline/stages/splits.py`.
- [ ] Implement ratio-based and key-based splits via scikit-learn splitters; stratification honored; class-balance strategy tags applied without resampling at this layer (resampling is ModelFoundry-side).
- [ ] Unsplit-remainder recorded; stratification with sparse classes warns; key-based with unmapped records raises `MaterializeError`.
- [ ] Unit tests: deterministic partitioning given seed; stratification distribution; sparse-class warning; unmapped-records hard error.
- [ ] Bump version to v0.3.3
- [ ] Update CHANGELOG.md
- [ ] Verify: split-determinism unit tests pass for fixed seed.

### Story C.f: v0.3.4 Filters Stage (FR-8) [Planned]

Pre-split (default) and post-split filter operations, with sampling seeded.

- [ ] Add `src/datarefinery/pipeline/stages/filters.py`.
- [ ] Implement predicate-based filters and seeded sampling filters; `applies_at` per recipe.
- [ ] Wire image plugin's filter ops (e.g., `filter_by_label`, `random_sample`).
- [ ] Edge cases: empty-class warning; unseeded sampler caught by validator (already covered in B.e).
- [ ] Unit tests: predicate filtering preserves expected records; sampling is reproducible given seed.
- [ ] Bump version to v0.3.4
- [ ] Update CHANGELOG.md
- [ ] Verify: filter unit tests pass.

### Story C.g: v0.3.5 Generation Stage (FR-9) [Planned]

Record-count-changing operations (oversampling, synthesized records). Image plugin SMOTE-equivalent or duplication for v1.

- [ ] Add `src/datarefinery/pipeline/stages/generation.py`.
- [ ] Implement generation runner respecting `applies_at` (default train-only post-split).
- [ ] Generated records validated against `Output` schema; mismatches raise `MaterializeError`.
- [ ] Manifest captures pre/post counts.
- [ ] Unit tests: generation increases record count deterministically; output-schema mismatch hard-errors.
- [ ] Bump version to v0.3.5
- [ ] Update CHANGELOG.md
- [ ] Verify: generation unit tests pass.

### Story C.h: v0.3.6 Transformations + Fitted Statistics (FR-10, FR-6) [Planned]

Deterministic transformations including fit-on-train statistics persistence.

- [ ] Add `src/datarefinery/pipeline/stages/transformations.py` and `src/datarefinery/pipeline/fitted_stats.py`.
- [ ] Implement `FittedStatistics` per tech-spec (`put_scalar`, `put_vector`, `get_scalar`, `get_vector`); scalars in `scalars.json` per `op_id`; vectors as `<name>.parquet`.
- [ ] Transformations honor `fit_source` (train-only fitting, persistence, then apply across declared splits).
- [ ] Image plugin transformations (resize, normalize, mean-subtract, etc.) implemented.
- [ ] Unit tests: fit-on-train idempotent given fixed inputs; round-trip serdes; transformation is deterministic given fitted stats.
- [ ] Bump version to v0.3.6
- [ ] Update CHANGELOG.md
- [ ] Verify: transformation + fitted-stats round-trip tests pass.

### Story C.i: v0.3.7 Featurizations + Derived Labels (FR-12, FR-22) [Planned]

Same machinery for featurizations and derived labels (e.g., label from filename pattern).

- [ ] Add `src/datarefinery/pipeline/stages/featurizations.py`.
- [ ] Implement deterministic featurization runner referencing declared inputs (including filenames/metadata).
- [ ] Wire `Labels` derivation through the featurization runner per FR-22.
- [ ] Image plugin featurizations (`label_from_path`, basic stats featurizers) implemented.
- [ ] Edge case: name collision with existing field → hard error.
- [ ] Unit tests: derived label resolved from `parent_directory_name`; collision hard-errors.
- [ ] Bump version to v0.3.7
- [ ] Update CHANGELOG.md
- [ ] Verify: featurization + derived-label unit tests pass.

### Story C.j: v0.3.28 Augmentations Declaration (FR-11) [Planned]

Augmentation policies are recorded in the manifest and surfaced in the report; v1 does not pre-materialize augmented examples.

- [ ] Add `src/datarefinery/pipeline/stages/augmentations.py`.
- [ ] Validate that declared augmentations apply only to train (validator check 5 already enforces; this story consumes it).
- [ ] Manifest captures augmentation policy summary (op name, params, seed) for each declared augmentation.
- [ ] Image plugin augmentation specs (random_crop, horizontal_flip, color_jitter) declared as policy-only ops.
- [ ] Unit tests: augmentation policy round-trips through manifest; non-train declaration is rejected before this stage runs.
- [ ] Bump version to v0.3.8
- [ ] Update CHANGELOG.md
- [ ] Verify: augmentation policy tests pass.

### Story C.k: v0.3.9 Visualizations: Exploration and Reporting (FR-13) [Planned]

Reporting visualizations rendered into the instance; exploration visualizations rendered on demand.

- [ ] Add `src/datarefinery/pipeline/stages/visualizations.py` and `src/datarefinery/reporting/visualizations.py`.
- [ ] Reporting-mode renderer writes to `report/visualizations/` during materialize; exploration-mode renderer is a library API for `inspect`.
- [ ] Image plugin visualizations: class-distribution histogram, sample grid, mean-image-per-class.
- [ ] Edge case: reporting-mode failure raises `MaterializeError` (per FR-13).
- [ ] Unit tests: reporting-mode renders deterministic PNG bytes for fixed input; exploration-mode returns objects without persisting.
- [ ] Bump version to v0.3.9
- [ ] Update CHANGELOG.md
- [ ] Verify: visualization unit tests pass.

### Story C.l: v0.3.10 Pipeline Workers: Deterministic Parallelism [Planned]

Opt-in `ProcessPoolExecutor` with the per-record seeding + reorder-by-record-id contract from `project-essentials.md` "Determinism contract in `pipeline.workers`."

- [ ] Add `src/datarefinery/pipeline/workers.py` with `run_parallel(seed, fn, items, workers) -> Iterator[Record]`.
- [ ] Per-record seed = `sha256(seed.to_bytes(8, 'big') + record_id_bytes).digest()[:8]` decoded as 64-bit int.
- [ ] Collect futures; sort outputs by `record_id` before yielding (no `as_completed` streaming across stage boundaries).
- [ ] Serial fast-path when `workers == 1`.
- [ ] Unit tests: same input + same seed produces byte-identical output for `workers=1`, `workers=2`, `workers=4`; per-record seed independent of worker count and scheduling.
- [ ] Bump version to v0.3.10
- [ ] Update CHANGELOG.md
- [ ] Verify: worker determinism unit tests pass under all three worker counts.

### Story C.m: v0.3.11 PipelineRunner: Stage Sequencing (FR-3) [Planned]

The conductor: validate → cache check → temp dir → stages 1–11 → manifest → atomic promote.

- [ ] Add `src/datarefinery/pipeline/runner.py` with `PipelineRunner(recipe, plugin, config, seed)` and `.run(temp_dir)`.
- [ ] Sequence stages in recipe-declared order with the default sequence from tech-spec (Input → InputContracts → Filters → Splits → Generation → Transformations → Featurizations → (Augmentations declared) → OutputExpectations → reporting Visualizations → manifest).
- [ ] Cache hit short-circuit: if `<final_dir>/manifest.json` exists, return without temp work.
- [ ] On stage failure: `mark_failed(temp_dir, exc, stage)` then re-raise.
- [ ] On success: write `manifest.json` then `atomic_promote(temp_dir, final_dir)`.
- [ ] Integration test: end-to-end run on the fixture image dataset produces a complete instance directory; rerun with same inputs produces `cache=hit` (no work).
- [ ] Bump version to v0.3.11
- [ ] Update CHANGELOG.md
- [ ] Verify: integration runner test passes; failure-injection at one stage leaves `FAILED` marker and never touches the final cache path.

### Story C.n: v0.3.12 Reporting: report.md and drift.json (FR-15) [Planned]

Render the human-readable report and the structured drift placeholder consumed by DataMachine.

- [ ] Add `src/datarefinery/reporting/__init__.py`, `src/datarefinery/reporting/report.py`, `src/datarefinery/reporting/drift.py`.
- [ ] `report.md` summarizes recipe, inputs, splits, operations applied, fitted-statistics summary, key counts, warnings.
- [ ] `drift.json` schema matches `DriftSchema` in tech-spec (`schema_version=0` placeholder; documented as unstable until production release; typed JSON shape).
- [ ] `Instance.render_report()` re-renders without rerunning the pipeline (FR-15.4).
- [ ] Unit tests: `report.md` content stable for fixture instance; `drift.json` validates against pydantic `DriftSchema`.
- [ ] Bump version to v0.3.12
- [ ] Update CHANGELOG.md
- [ ] Verify: report and drift-schema tests pass.

### Story C.o: v0.3.13 Scaffolder: Deterministic init for image_classification (FR-17) [Planned]

`init` produces a working starter recipe from raw image inputs, offline. Optional `lmentry` enhancement layer is lazy-imported.

- [ ] Add `src/datarefinery/scaffolder/__init__.py`, `src/datarefinery/scaffolder/init.py`, `src/datarefinery/scaffolder/llm.py`.
- [ ] `scaffold_image_classification(input_path, output_path, *, enhance=False)`: inspects image directory tree (file types, dimensions, dtype, class folders), emits a starter recipe with `Input`/`Output`/`Labels`/`Splits` populated, common `Transformations` stubbed (commented out).
- [ ] `enhance=True` lazy-imports `lmentry`; missing extra raises `PluginError` pointing at `[llm]`; offline detection emits a recipe with an "enhancement skipped" comment.
- [ ] Tabular/text invocations raise the documented "init scaffolder not available for this category in v1" error.
- [ ] Unit tests: scaffolded recipe parses through `recipe.loader`, validates clean, materializes successfully on a CIFAR-shaped fixture.
- [ ] Bump version to v0.3.13
- [ ] Update CHANGELOG.md
- [ ] Verify: scaffolded recipe round-trip materializes; non-image scaffold attempt raises documented error.

---

## Phase D: CLI & Library API

Co-equal surfaces. Each CLI verb is a thin typer wrapper around a method on `DataRefinery` or a module-level function. Every verb gets a smoke test in Phase E; this phase lands the verbs themselves.

### Story D.a: v0.4.0 DataRefinery Class and Instance Loader [Planned]

Library entry point that owns the loaded recipe and exposes verb methods.

- [ ] Add `src/datarefinery/core/datarefinery.py` with `DataRefinery` class (per tech-spec signature: `from_recipe`, `validate`, `materialize`, `status`, `inspect`, `report`, `clean`, `check`, `recipe`, `cache_key`).
- [ ] Add `src/datarefinery/core/instance.py` with `Instance` frozen dataclass (`path`, `manifest`, `recipe`, `fitted_statistics`, `report_path`, `is_partial`) and `Instance.load(path)`.
- [ ] Top-level `materialize(recipe_path, *, config, variant, seed) -> Instance` convenience.
- [ ] Public API re-exports in `datarefinery/__init__.py`: `DataRefinery`, `Instance`, `materialize`, `__version__`.
- [ ] Unit tests: `DataRefinery.from_recipe(...)` runs validation once; `Instance.load(...)` parses manifest and exposes fitted-statistics lazily.
- [ ] Bump version to v0.4.0
- [ ] Update CHANGELOG.md
- [ ] Verify: library API round-trip tests pass.

### Story D.b: v0.4.1 CLI verb: check (FR-18) [Planned]

- [ ] Add `src/datarefinery/cli/commands/__init__.py`, `src/datarefinery/cli/commands/check_cmd.py`.
- [ ] Reports Python version, package version, plugin discovery (names + paths), optional acceleration availability (Metal / CUDA), optional extras (`lmentry`).
- [ ] Returns 0 with warnings on missing optional deps; returns 2 on missing required.
- [ ] Unit + smoke test: `datarefinery check` exits 0 on a healthy environment.
- [ ] Bump version to v0.4.1
- [ ] Update CHANGELOG.md
- [ ] Verify: `pyve run datarefinery check` exits 0 and lists installed plugins.

### Story D.c: v0.4.2 CLI verb: validate (FR-2) [Planned]

- [ ] Add `src/datarefinery/cli/commands/validate_cmd.py` invoking `DataRefinery.validate()`.
- [ ] CLI renders a `rich` table per check (id, status, location, message); exits 1 on any failure.
- [ ] Smoke test: a clean fixture recipe exits 0; a recipe violating each check exits 1 with all 18 entries reported.
- [ ] Bump version to v0.4.2
- [ ] Update CHANGELOG.md
- [ ] Verify: CLI smoke tests for validate pass.

### Story D.d: v0.4.3 CLI verb: init (FR-17) [Planned]

- [ ] Add `src/datarefinery/cli/commands/init_cmd.py` with `--enhance` flag and `--input`, `--output` paths.
- [ ] Errors when `--enhance` requested without `[llm]` extra; documents the install snippet in the error.
- [ ] Smoke test: `datarefinery init --input <fixture> --output recipe.yaml` produces a valid recipe.
- [ ] Bump version to v0.4.3
- [ ] Update CHANGELOG.md
- [ ] Verify: init smoke test passes; produced recipe is parsed clean by `validate`.

### Story D.e: v0.4.4 CLI verb: materialize (FR-3) [Planned]

- [ ] Add `src/datarefinery/cli/commands/materialize_cmd.py` invoking `DataRefinery.materialize()`.
- [ ] CLI shows `rich` per-stage progress bars; final summary includes cache hit/miss, instance path, elapsed seconds, key counts.
- [ ] Verb-specific options: `--stage NAME` (partial run; result not promoted; manifest marked partial).
- [ ] Smoke test: `datarefinery materialize` end-to-end on fixture; rerun shows `cache=hit`.
- [ ] Bump version to v0.4.4
- [ ] Update CHANGELOG.md
- [ ] Verify: materialize smoke test passes; second run hits cache.

### Story D.f: v0.4.5 CLI verb: status (FR-19) [Planned]

- [ ] Add `src/datarefinery/cli/commands/status_cmd.py` invoking `DataRefinery.status()`.
- [ ] Accepts either an instance path or a recipe path (resolves cache key to find instance).
- [ ] Renders `rich` table: hashes, seed, plugin, schema version, variant, created_at, record counts per split, warnings.
- [ ] Smoke test: status against fresh instance shows expected fields; against missing cache reports `cache=miss` (exit 0).
- [ ] Bump version to v0.4.5
- [ ] Update CHANGELOG.md
- [ ] Verify: status smoke test passes.

### Story D.g: v0.4.6 CLI verb: report (FR-15 re-render) [Planned]

- [ ] Add `src/datarefinery/cli/commands/report_cmd.py` invoking `Instance.render_report()`.
- [ ] Re-renders `report.md`, `drift.json`, and reporting visualizations from existing fitted statistics + manifest; never reruns the pipeline.
- [ ] Edge case: stale fitted-stats vs manifest hashes → `MaterializeError` with the documented inconsistency message.
- [ ] Smoke test: `datarefinery report` against fixture instance updates the report files in place.
- [ ] Bump version to v0.4.6
- [ ] Update CHANGELOG.md
- [ ] Verify: report smoke test passes.

### Story D.h: v0.4.7 CLI verb: inspect (FR-20) [Planned]

- [ ] Add `src/datarefinery/cli/commands/inspect_cmd.py` invoking `DataRefinery.inspect()`.
- [ ] `--view NAME` renders a named exploration visualization; `--out PATH` writes to file (image/HTML).
- [ ] Default (no `--view`) lists exploration visualizations and structured peek of fitted statistics + sample records.
- [ ] Refuses to operate on a partial (FAILED) instance with the documented pointer.
- [ ] Smoke test: list and render at least one exploration visualization on fixture instance.
- [ ] Bump version to v0.4.7
- [ ] Update CHANGELOG.md
- [ ] Verify: inspect smoke test passes.

### Story D.i: v0.4.8 CLI verb: clean (FR-21) [Planned]

- [ ] Add `src/datarefinery/cli/commands/clean_cmd.py` invoking `DataRefinery.clean()`.
- [ ] Selectors: `--by-recipe HASH`, `--by-age DAYS`, `--orphans`, `--all`. `--all` requires interactive confirmation; `--yes` allows non-TTY use.
- [ ] Smoke test: each selector against a fixture cache.
- [ ] Bump version to v0.4.8
- [ ] Update CHANGELOG.md
- [ ] Verify: clean smoke tests pass.

### Story D.j: v0.4.9 Integration: `init → validate → materialize` Golden Path [Planned]

End-to-end CLI integration test exercising the documented user journey.

- [ ] Integration test: from a CIFAR-10-shaped fixture directory, run `datarefinery init` → `datarefinery validate` → `datarefinery materialize` → `datarefinery status`; assert all four exit 0 and the final instance is complete (manifest, dataset, fitted_statistics, report all present).
- [ ] Bump version to v0.4.9
- [ ] Update CHANGELOG.md
- [ ] Verify: golden-path integration test passes from a fresh tempdir.

---

## Phase E: Testing & Quality

Phase A–D shipped tests alongside features. Phase E is where we backfill the *contracts* — property-based tests for cache invariants, the determinism integration check, the canonical-hash pinning test, exhaustive failure-mode coverage, and coverage thresholds. The goal is to make every reproducibility guarantee in `concept.md` a test that fails loudly when broken.

### Story E.a: v0.5.0 Test Fixture: CIFAR-10-Shaped Synthesizer [Planned]

A reusable fixture builder that synthesizes a tiny CIFAR-10-shaped dataset at test time (no large binaries committed).

- [ ] Add `tests/fixtures/build_cifar10_shaped.py` synthesizing ~50 images via NumPy RNG (seeded); writes 10 class folders × 5 PNGs via Pillow.
- [ ] Wrap as a pytest fixture (`tests/conftest.py`) producing a tempdir per test session.
- [ ] Add a documented "do not check in real CIFAR-10 here" comment.
- [ ] Bump version to v0.5.0
- [ ] Update CHANGELOG.md
- [ ] Verify: fixture builds in <1s and produces 50 PNGs in 10 class folders.

### Story E.b: v0.5.1 Hypothesis: Cache-Identity Invariance and Sensitivity [Planned]

Property-based proof that cosmetic edits never invalidate the cache and semantic edits always do.

- [ ] Add `tests/unit/test_cache_identity_properties.py`.
- [ ] Hypothesis strategy generating YAML edits restricted to whitespace, comments, key-order permutations, quote-style swaps; assert `compute_cache_key` is invariant.
- [ ] Hypothesis strategy generating semantic edits (changed scalars, added/removed list items, added/removed sections); assert `compute_cache_key` differs.
- [ ] Bump version to v0.5.1
- [ ] Update CHANGELOG.md
- [ ] Verify: both property tests pass on a 1000-example run.

### Story E.c: v0.5.2 Hypothesis: Split Determinism [Planned]

For a fixed seed, repeated splitting of a generated record list must yield identical partitions across runs and across worker counts.

- [ ] Add `tests/unit/test_splits_determinism.py` with Hypothesis strategies for record-count, ratio shapes, stratification keys.
- [ ] Assert: same seed → same partitions across two runs; same seed → same partitions across `workers=1/2/4` (uses `pipeline.workers.run_parallel` from C.l).
- [ ] Bump version to v0.5.2
- [ ] Update CHANGELOG.md
- [ ] Verify: split-determinism property test passes.

### Story E.d: v0.5.3 Determinism Integration Test (workers=1, 2, 4) [Planned]

End-to-end check that the full pipeline produces byte-identical instances regardless of worker count.

- [ ] Add `tests/integration/test_determinism_workers.py`.
- [ ] Run the same fixture pipeline three times with `workers=1`, `workers=2`, `workers=4`; diff the resulting instance directories (excluding `created_at` and `elapsed_seconds`); assert byte-identical.
- [ ] Mark slow; documented in `pyproject.toml` so CI runs it on demand if needed.
- [ ] Bump version to v0.5.3
- [ ] Update CHANGELOG.md
- [ ] Verify: determinism integration test passes locally.

### Story E.e: v0.5.4 Failure-Mode Tests at Every Stage [Planned]

Forced failure injected at each pipeline stage leaves a `FAILED`-marked temp directory and never touches the final cache.

- [ ] Add `tests/integration/test_failure_modes.py`.
- [ ] Parametrize across: input contract failure, filter failure, split failure, generation failure, transformation failure, featurization failure, augmentation declaration failure, output expectation failure, reporting visualization failure.
- [ ] Inject failures via plugin operation that raises; assert temp dir + `FAILED` marker + final cache untouched.
- [ ] Bump version to v0.5.4
- [ ] Update CHANGELOG.md
- [ ] Verify: every parametrized failure-mode case passes.

### Story E.f: v0.5.5 Cache Identity Pinning Test [Planned]

The "consciously sign off on cache invalidation" test from `project-essentials.md`.

- [ ] Add `tests/unit/test_canonical_hash_pin.py`.
- [ ] Pins the canonical-hash hex digest of a representative fixture recipe.
- [ ] Failure message references `project-essentials.md` "Cache identity is the reproducibility contract — invalidations are ceremonious" and the post-production schema-version-bump ceremony.
- [ ] Bump version to v0.5.5
- [ ] Update CHANGELOG.md
- [ ] Verify: pinning test passes; deliberately changing a pydantic default in a sandbox breaks it with the documented message.

### Story E.g: v0.5.6 Coverage Thresholds and Per-Module Gates [Planned]

Wire `pytest-cov` per tech-spec coverage strategy.

- [ ] Configure `pyproject.toml` `[tool.coverage]` with per-module thresholds for the core-invariant set: `recipe.loader`, `recipe.canonical`, `cache.identity`, `cache.atomic`, `pipeline.stages.splits`, `pipeline.workers`, `plugins.base`, `plugins.discovery` (≥95%).
- [ ] No project-wide percentage gate yet (pre-production); add a `# pre-prod: project-wide gate enabled at production release` comment.
- [ ] CI lint/test workflow (lands in Phase G) wires `--cov-fail-under` for core invariants only.
- [ ] Bump version to v0.5.6
- [ ] Update CHANGELOG.md
- [ ] Verify: `pyve test --cov` reports ≥95% on each named core module.

### Story E.h: v0.5.7 Plugin Contract Test Framework [Planned]

Generic plugin contract harness ensuring every registered plugin (real or stub) declares what it claims.

- [ ] Add `tests/plugin_contract/conftest.py` parametrizing across all discovered plugins.
- [ ] Each plugin asserts: declared `supported_sections` is a subset of recipe section names; every entry in `supported_operations` has a valid `OperationSpec`; `is_stub()` reflects whether `operation_factory` raises.
- [ ] Bump version to v0.5.7
- [ ] Update CHANGELOG.md
- [ ] Verify: contract harness passes for image_classification, tabular, text plugins.

---

## Phase F: Documentation & Release

Pre-production v1 polish. README expanded with quickstart and recipe authoring; recipe + plugin authoring guides; final `v1.0.0` cut as the production-release marker (which flips post-production rules per `features.md`).

### Story F.a: README Expanded with Quickstart [Planned]

Promote the package to a non-trivial first-impression README. Minor bump (0.1.0) reflects the leap from "scaffolding present" to "documented usable tool."

- [ ] Expand `README.md` with: install (PyPI + dev paths), quickstart (`init` → `validate` → `materialize` on CIFAR-shaped data), recipe-anatomy section, CLI verb summary table, plugin model overview, link to features.md/tech-spec.md.
- [ ] Add a recipe example for `image_classification` end-to-end.
- [ ] Add a "v1 scope and non-goals" section sourced from concept.md.
- [ ] Update CHANGELOG.md
- [ ] Verify: README renders cleanly on GitHub; quickstart commands succeed against the fixture.

### Story F.b: Recipe Authoring Guide [Planned]

Doc-only; shares F.a's release.

- [ ] Add `docs/guides/recipe-authoring.md`: section-by-section walk-through, fit-on-train discipline, variants, contracts/expectations, when to use Filters vs Splits for class imbalance.
- [ ] Cross-link from README and concept.md.
- [ ] Verify: every code snippet in the guide is materializable against the fixture.

### Story F.c: Plugin Authoring Guide [Planned]

Doc-only; shares F.a's release.

- [ ] Add `docs/guides/plugin-authoring.md`: how to declare a plugin, `OperationSpec` schema, fit-on-train flag, applicable splits, registration via entry-point group.
- [ ] Reference the tabular/text stubs as starting templates.
- [ ] Verify: a hand-written hello-plugin following the guide is discovered and validates a minimal recipe.

### Story F.d: v1.0.0 Production Release [Planned]

The declared production-release event. Per `features.md` and `project-essentials.md`, this flips multiple rules to post-production: schema versions become immutable, the cache layout becomes versioned, the drift schema is frozen, and cache-invalidating changes become ceremonious.

- [ ] Final pass on `features.md` "Acceptance Criteria" — every numbered item demonstrably met.
- [ ] Freeze `DriftSchema` (bump `schema_version` from 0 to 1; remove the "unstable until production release" notes from drift.py and tech-spec).
- [ ] Add `recipe.loader.migrations` registry header documentation: "post-production: every cache-invalidating change requires a migration entry here."
- [ ] Add release notes section in `CHANGELOG.md` titled "**Production Release — Post-production rules are now in effect.**" naming the rule changes.
- [ ] Tag `v1.0.0`; publish workflow uploads to PyPI.
- [ ] Bump version to v1.0.0
- [ ] Update CHANGELOG.md
- [ ] Verify: tagged release lands on PyPI; `pip install datarefinery==1.0.0` from a clean venv succeeds; `datarefinery check` reports environment soundness; `init → validate → materialize` golden path passes on the installed wheel.

---

## Phase G: CI/CD & Automation

Continuous-integration workflow (lint + type + test on every PR), coverage badge, and post-production release-automation polish. The publish workflow already shipped in A.d so the PyPI name was reserved early; Phase G adds the rest.

### Story G.a: v1.0.1 GitHub Actions: Lint + Type + Test [Planned]

CI runs `ruff`, `mypy --strict`, and `pytest` on every PR and on `main`.

- [ ] Add `.github/workflows/ci.yml` running on pull_request and push to `main`.
- [ ] Matrix: Python 3.12 on ubuntu-latest and macos-latest.
- [ ] Steps: checkout, setup-python, install dev requirements, `pyve testenv run ruff check src tests`, `pyve testenv run ruff format --check src tests`, `pyve testenv run mypy src tests`, `pyve test --cov --cov-fail-under` (core-invariant gates from E.g).
- [ ] Required-status-check on `main` for all matrix legs.
- [ ] Bump version to v1.1.0
- [ ] Update CHANGELOG.md
- [ ] Verify: a deliberate lint violation in a PR fails CI on both OS legs.

### Story G.b: v1.0.2 Coverage Badge (Codecov) [Planned]

- [ ] Add Codecov upload step to `ci.yml` using `codecov/codecov-action`.
- [ ] Configure `.codecov.yml` with target ≥85% post-production (per features.md) and per-module ≥95% on core invariants.
- [ ] Add Codecov badge to `README.md`.
- [ ] Bump version to v1.1.1
- [ ] Update CHANGELOG.md
- [ ] Verify: a PR shows a Codecov status check and the README badge updates after merge to `main`.

### Story G.c: v1.0.3 Release Automation Polish [Planned]

- [ ] Add a GitHub Action that on tag push extracts the corresponding `CHANGELOG.md` section and creates a GitHub Release with that body.
- [ ] Add tag protection rule: only maintainers can push `v*` tags.
- [ ] Document the release procedure in `docs/guides/releasing.md` (bump → CHANGELOG → tag → workflow → verify).
- [ ] Bump version to v1.1.2
- [ ] Update CHANGELOG.md
- [ ] Verify: a new tag push produces a GitHub Release with the changelog body and a successful PyPI upload.

---

## Future

<!--
This section captures items intentionally deferred from the active phases above:
- Stories not yet planned in detail
- Phases beyond the current scope
- Project-level out-of-scope items
The `archive_stories` mode preserves this section verbatim when archiving stories.md.
-->

- **Image plugin tasks beyond classification** (detection, segmentation) — accommodated by the plugin interface, no v1 implementation per concept.md/features.md.
- **Tabular plugin: full operation implementations** — v1 ships a stub only; full implementation is post-v1.
- **Text plugin: full operation implementations** — v1 ships a stub only; full implementation is post-v1.
- **Recipe inheritance and multi-file composition** — variants suffice for v1; deferred per concept.md non-goals.
- **Resume-from-stage during materialization** — atomic temp-then-promote is the v1 failure model; resume support is post-v1.
- **`init` for non-image categories** — deterministic scaffolder is image-only in v1.
- **Inter-run concurrency: file-lock-based protocol** — pre-production serializes externally; the post-production protocol designed-for in cache layout is implemented post-v1.
- **Cache layout migration tooling (`clean --upgrade`)** — post-production cache-layout versioning + migration guide; v1 documents pre-prod invalidation semantics only.
- **Hard performance targets and benchmarking suite** — v1 is reactive; stories set targets when representative workloads expose problems.
- **Native Windows first-class support** — WSL2 is the recommended Windows path in v1.
- **Plugin sandboxing** — plugins run in-process, unsandboxed in v1; sandboxing is a post-v1 trust-boundary upgrade.
