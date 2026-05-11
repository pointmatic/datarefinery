# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-05-11

### Added

- README expanded with quickstart (Story F.a) — opens Phase F:
  - Installation: PyPI install plus a from-source path that documents
    the pyve two-environment workflow (runtime venv + testenv).
  - Quickstart walking through `init → validate → materialize →
    status` against an image_classification folder layout, with the
    expected on-disk cache layout (`recipe.yaml`, `manifest.json`,
    `dataset/`, `fitted_statistics/`, `report/`).
  - Recipe anatomy: an end-to-end YAML example mirroring the
    scaffolder output, plus a section-by-section table covering
    Input, Output, Labels, SampleData, InputContracts, Filters,
    Generation, Splits, Transformations, Augmentations,
    Featurizations, OutputExpectations, Visualizations, and
    variants.
  - CLI verb summary table (`check`, `init`, `validate`,
    `materialize`, `status`, `report`, `inspect`, `clean`) with FR
    cross-references, plus the execution-context flag/env-var table.
  - Plugin model overview citing the v1 set
    (image_classification first-class; tabular and text as stubs)
    and pointing at `plugins/base.py` for the protocol.
  - Library API example covering both the one-shot `materialize`
    convenience and the lower-level `DataRefinery.from_recipe`
    surface; verified against the CIFAR-10-shaped fixture.
  - "v1 scope and non-goals" section sourced from `concept.md`.
  - Cross-links to `docs/specs/concept.md`,
    `docs/specs/features.md`, and `docs/specs/tech-spec.md`.
- Recipe Authoring Guide at `docs/guides/recipe-authoring.md` (Story
  F.b; doc-only, shares the F.a release):
  - Section-by-section walk-through of every recipe surface
    (`Input`, `Output`, `Labels`, `SampleData`, `InputContracts`,
    `Filters`, `Generation`, `Splits`, `Transformations`,
    `Augmentations`, `Featurizations`, `OutputExpectations`,
    `Visualizations`, `variants`).
  - Dedicated treatments of fit-on-train discipline (why
    `fit_source: train` is the only accepted value and where the
    statistics land on disk), variants (cache-identity implications,
    when to overlay vs. fork a recipe), `InputContracts` /
    `OutputExpectations` (assertion-kind table with required keys),
    and the Filters-vs-Splits decision for class imbalance.
  - A complete reference recipe that materializes against the
    CIFAR-10-shaped fixture; the default and `--variant no_augment`
    materializations were both verified end-to-end. Subsidiary
    snippets (Filters with `random_sample` and `filter_by_label`)
    were composed into materializable recipes and verified against
    the same fixture.
  - Cross-linked from `README.md` and `docs/specs/concept.md`.
- Plugin Authoring Guide at `docs/guides/plugin-authoring.md` (Story
  F.c; doc-only, shares the F.a release):
  - `Plugin` protocol reference: the six required attributes
    (`name`, `supported_sections`, `supported_operations`,
    `schema_version`, `operation_factory`, `is_stub`) with a table
    keyed to each, plus the canonical 13-section list asserted by
    the cross-plugin contract suite.
  - `OperationSpec` and `ParameterSpec` walk-through: `parameters`,
    `fit_on_train`, `applicable_splits`, `applicable_sections` — and
    how each interacts with validator checks 5, 6, and 18.
  - Operation-handle shape summary across stages (Filters callables;
    Transformations / Featurizations `fit` + `apply` objects with
    `FittedValues`; Visualizations `render`), each pointing at the
    canonical `pipeline/stages/` Protocol and the
    `image_classification` operation as the reference
    implementation.
  - Discovery and registration: the `datarefinery.plugins`
    entry-point group for installed packages, and `--plugin-path`
    for development; discovery rules (uniqueness, protocol
    attributes, `datarefinery check` listing).
  - Stub vs. real plugin semantics tied to the cross-plugin contract
    test assertions.
  - Hello-plugin walk-through: a minimal `hello` plugin declaring
    one Featurization `echo` op, plus a minimal recipe targeting it.
    Verified end-to-end via `datarefinery --plugin-path
    hello_plugin.py check` (plugin listed `active`) and
    `validate hello-recipe.yaml` (18/18 checks pass) against the
    CIFAR-10-shaped fixture.
  - References to `tabular` and `text` stubs as starting templates,
    plus a versioning/stability note tied to FR-16's
    pre-production-vs.-post-production rules.
  - Cross-linked from `README.md`, `docs/guides/recipe-authoring.md`,
    and `docs/specs/concept.md`.

## [0.5.7] - 2026-05-09

### Added

- Generic plugin contract harness (Story E.h) — closes Phase E:
  - `tests/plugin_contract/conftest.py` uses `pytest_generate_tests`
    to parametrize every test that consumes a `plugin` argument
    across all plugins discovered via the entry-point group, with
    plugin names as test ids. Adding a new plugin opts it into the
    harness automatically — no per-plugin file required.
  - `tests/plugin_contract/test_protocol.py` ships five
    cross-plugin assertions:
    1. `isinstance(plugin, Plugin)` — runtime-protocol satisfaction.
    2. Non-empty, stripped string name.
    3. `supported_sections` is a subset of the canonical 13 recipe
       section names; a plugin that lists a non-canonical section is
       wrong at the contract layer even before any recipe references
       it.
    4. Every `supported_operations` entry round-trips through
       `OperationSpec.model_validate`; each declares at least one
       `applicable_sections`, all of which must be canonical.
    5. `is_stub()` reflects reality — stubs must raise from
       `operation_factory` for at least one declared op; non-stubs
       must construct cleanly for at least one declared op. The
       asymmetry is intentional: a non-stub may ship some
       not-yet-implemented ops alongside real ones, but a plugin that
       claims to be a stub and yet successfully constructs operations
       breaks the materialize-time refusal contract.
  - Existing per-plugin contract files (`test_image_classification.py`,
    `test_tabular.py`, `test_text.py`) still cover plugin-specific
    schema assertions that go beyond the protocol.

### Tests

- 15 new parametrized tests (5 generic assertions × 3 discovered
  plugins).

## [0.5.6] - 2026-05-09

### Added

- Coverage configuration and per-module gates (Story E.g):
  - `[tool.coverage.run]` defaults `pyve test --cov` to the
    `src/datarefinery` package.
  - `[tool.coverage.report]` enables show-missing and excludes
    `pragma: no cover`, `raise NotImplementedError`, and
    `TYPE_CHECKING:` blocks.
  - `[tool.coverage.datarefinery]` (project-private TOML table)
    declares `core_invariant_modules` (the eight modules that gate the
    FR-4 reproducibility contract — `recipe.loader`,
    `recipe.canonical`, `cache.identity`, `cache.atomic`,
    `pipeline.stages.splits`, `pipeline.workers`, `plugins.base`,
    `plugins.discovery`) and `core_invariant_threshold = 95`. Phase G
    CI consumes this table via Python; `pytest-cov` doesn't natively
    support per-module `fail_under`.
  - The project-wide percentage gate is intentionally unset
    pre-production; an inline `# pre-prod: project-wide gate enabled
    at production release` comment marks the spot.

### Tests

- 3 new unit tests in `tests/unit/test_plugins_discovery.py`
  back-filling coverage of `plugins.discovery`:
  - Extra-path module without a top-level `PLUGIN` attr is ignored
    silently.
  - Extra-path module that fails to import surfaces as `PluginError`.
  - Top-level `PLUGIN` attr that doesn't satisfy the Plugin protocol
    raises with a class-named message.
  - These move the discovery module from 88% → 96% coverage. The two
    remaining uncovered lines are the entry-point class-instantiation
    branch and the `spec_from_file_location` defensive None-spec
    branch — both genuinely hard to exercise without full entry-point
    setup.

## [0.5.5] - 2026-05-09

### Added

- Cache-identity pinning gate (Story E.f, FR-4):
  - `tests/unit/test_canonical_hash_pin.py` is a single-test module
    pinning the canonical SHA-256 digest of a representative fixture
    recipe. A failed assertion walks the reviewer through the
    four-step ceremony from `project-essentials.md` "Cache identity
    is the reproducibility contract — invalidations are ceremonious":
    bump `SUPPORTED_SCHEMA_VERSIONS`, ship a migration, announce
    blast radius, update the pin in the same commit. Pre-production
    versus post-production rules are both spelled out so a future
    bump doesn't mis-apply the wrong ceremony level.
  - Module docstring includes a one-liner for legitimately
    regenerating the digest after a deliberate cache-invalidating
    change.

### Changed

- Removed the duplicate canonical-hash pin from
  `tests/unit/test_canonical.py` so the gate is single-source. The
  remaining tests in `test_canonical.py` cover cosmetic-edit
  invariance, value-edit sensitivity, and JSON wellformedness.

## [0.5.4] - 2026-05-08

### Added

- Per-stage failure-mode integration tests (Story E.e):
  - `tests/integration/test_failure_modes.py` parametrizes a forced
    failure across 10 stage labels (`InputContracts`,
    `Filters/pre_split`, `Splits`, `Filters/post_split`, `Generation`,
    `Transformations`, `Featurizations`, `Augmentations`,
    `OutputExpectations`, `Visualizations`). Plugin-op failures are
    injected via a `_FailingPlugin` wrapper around the
    `image_classification` plugin that raises from
    `operation_factory` whenever the named op is requested.
    Stage-driver failures use recipe shapes that trip the runner's
    own raise sites (record_count_min contract, key_assignment with
    unmapped records, non-train augmentation declaration).
  - Each case asserts the runner re-raises, the temp dir survives
    with a `FAILED` JSON marker naming the expected `current_stage`
    label, and the final cache path is never written to.
  - Tests bypass the FR-2 validator and instantiate
    `PipelineRunner` directly so failure recipes that intentionally
    violate FR-2 checks (e.g., the non-train augmentation case used
    to reach the augmentations-stage defensive guard) reach the
    runner unchanged.

## [0.5.3] - 2026-05-08

### Added

- End-to-end determinism integration test (Story E.d):
  - `tests/integration/test_determinism_workers.py` runs the same
    fixture pipeline three times at `--workers 1/2/4` (each into a
    fresh cache root so the second and third runs don't short-circuit
    on cache hit) and asserts the resulting instance directories are
    byte-identical. `manifest.json` is normalized by stripping
    `created_at` and `elapsed_seconds` (intrinsically run-specific),
    and `report.md` is normalized by stripping the two corresponding
    "Created at:" / "Elapsed:" lines that render those manifest
    fields. A second sanity-guard test confirms those two fields
    actually vary across independent runs — without it the
    determinism check could pass vacuously if the fields turned
    stable.
  - Both tests are marked `slow`; `pytest -m 'not slow'` skips them
    so CI can run them on demand.

### Changed

- `pyproject.toml` now declares the `slow` pytest marker so
  `--strict-markers` passes for the new tests and so `pytest -m
  'not slow'` is the documented opt-out.

## [0.5.2] - 2026-05-08

### Added

- Hypothesis property tests for split determinism (Story E.c, FR-7):
  - `tests/unit/test_splits_determinism.py` with two property tests:
    - **Repeat-run determinism** (200 examples). For varied record
      counts (8-120), label sets (2-4 distinct values), ratio shapes
      (two-way + three-way), seeds, and optional stratification, two
      independent `apply_splits(...)` calls produce byte-identical
      partitions.
    - **Cross-worker determinism** (10 examples). Records are
      pre-processed through `pipeline.workers.run_parallel(workers=W)`
      with an identity worker function at `W ∈ {1, 2, 4}`; the result
      is then split with the same seed. All three worker counts must
      produce byte-identical partitions, validating the
      `project-essentials.md` "Determinism contract in
      `pipeline.workers`" rule that worker count must not leak into
      downstream stage output. The example budget is small because
      every example spawns three `ProcessPoolExecutor`s.

## [0.5.1] - 2026-05-08

### Added

- Hypothesis property tests for cache identity (Story E.b, FR-4):
  - `tests/unit/test_cache_identity_properties.py` with two property
    tests, each running for 1000 examples per
    `@settings(max_examples=1000)`:
    - **Cosmetic invariance.** A composite strategy deep-copies the
      baseline recipe dict, recursively shuffles every nested
      mapping's key order via a Hypothesis-drawn seed, re-emits
      through `yaml.safe_dump` with varying `indent` and
      `default_flow_style`, and splices in random blank/comment
      lines. The recipe-portion of `compute_cache_key` must remain
      identical across every generated text variant.
    - **Semantic divergence.** Ten mutator strategies (combined with
      `st.one_of`) that change `recipe.seed`, `Splits.seed`, split
      ratios, `Labels.field`, input source path, or add a `Filters`,
      `InputContracts`, `Visualizations`, or `SampleData` entry, or
      toggle `label_from`. Each must produce a different cache key
      than the baseline; the rare strategy-regenerates-baseline case
      is detected via a canonical-hash equality check and skipped.
  - These complement the example-based fixtures in
    `tests/unit/test_canonical.py` and the canonical-hash pin —
    together they make every reproducibility guarantee in
    `project-essentials.md` "Cache identity is the reproducibility
    contract" a test that fails loudly when broken.

## [0.5.0] - 2026-05-08

### Added

- CIFAR-10-shaped test-fixture synthesizer (Story E.a) — opens Phase E:
  - `tests/fixtures/build_cifar10_shaped.py` exposes
    `build_cifar10_shaped(root, *, num_classes, per_class,
    image_size, seed)` plus default constants. The default config
    produces 10 class folders × 5 PNGs each = 50 8×8 RGB images via a
    seeded `numpy.random.default_rng`, byte-stable across runs.
  - `tests/conftest.py` provides a session-scoped
    `cifar10_shaped_dir` pytest fixture so the synthesis cost (<1s
    locally) is paid once per session instead of per test.
  - Module docstring documents the "do not check in real CIFAR-10
    here" rule with rationale (size, licensing, repo bloat) and
    points contributors at a one-shot local download for tests that
    genuinely need the real dataset.
- Migrated `tests/integration/test_golden_path.py` (Phase D's closing
  integration test) to consume the new session fixture, proving its
  reusability and keeping per-test isolation via `shutil.copytree`.

### Tests

- 6 new self-tests in `tests/unit/test_cifar10_shaped_fixture.py`
  cover the default 50-PNGs/10-class layout, 8×8 RGB image
  dimensions, same-seed byte-identical output, different-seed
  divergence, the <1s build-time budget called out in the story, and
  that the session fixture is consumable by name.

## [0.4.9] - 2026-05-08

### Added

- Phase D golden-path integration test (Story D.j) — closes Phase D:
  - `tests/integration/test_golden_path.py` exercises the documented
    user journey end-to-end through the typer CLI: synthesizes a
    CIFAR-10-shaped fixture (10 classes, 3 PNGs each, 8x8 RGB,
    seeded), runs `datarefinery init`, simulates the "review and
    uncomment the suggested Transformations" step by inserting a
    fit-on-train normalize op, then runs
    `datarefinery validate` → `datarefinery materialize` →
    `datarefinery status` and asserts all four exit 0.
  - Asserts every artifact called out in the story task is present in
    the final instance: `manifest.json`, `recipe.json`, per-split
    JSONL files, `fitted_statistics/norm/{mean,std}.parquet`,
    `report/report.md`, `report/drift.json`, and the two scaffolded
    reporting visualizations (`class_distribution.png`,
    `samples.png`). Final invocation reruns `materialize` and
    asserts `cache=hit` plus no new promotion.

## [0.4.8] - 2026-05-08

### Added

- `datarefinery clean` CLI verb (Story D.i, FR-21):
  - `src/datarefinery/cli/commands/clean_cmd.py` registered on the
    typer app via `app.command("clean", ...)`. Selectors:
    `--by-recipe HASH`, `--by-age DAYS`, `--orphans`, `--all`. The
    library `cache.cleaner.clean(...)` already supported all of these
    via `CleanSelector`; this verb is a thin typer wrapper plus the
    FR-21 confirmation guard.
  - `--all` requires either an interactive TTY confirmation (via
    `typer.confirm`) or `--yes` for non-TTY use (CI, piped
    invocations). Refusing without `--yes` in a non-TTY context
    raises `CacheError` with a documented message rather than
    blocking on a prompt that can never be answered.
  - Refuses with `CacheError` when no selector is given, matching the
    FR-21 "no silent broad delete" rule.
  - Renders a `rich` table summary (cache root, removed count,
    skipped count) plus per-path tables on success.

### Tests

- 7 new CLI smoke tests in `tests/cli/test_clean_cmd.py`: no-selector
  refusal, `--by-recipe` removes only the matching recipe shard,
  `--by-age` removes backdated instances, `--orphans` removes old
  temp dirs in `.tmp/`, `--all` without `--yes` in non-TTY refuses
  (cache untouched), `--all --yes` wipes the cache, and the summary
  table renders.

## [0.4.7] - 2026-05-08

### Added

- `datarefinery inspect` CLI verb (Story D.h, FR-20):
  - `src/datarefinery/core/inspect.py` with `InspectionView` (frozen
    dataclass: `instance_path`, `exploration_views`, optional
    `rendered`, `fitted_op_ids`, `record_counts`, `sample_records`),
    `RenderedView` (in-memory PNG bytes), and
    `build_inspection_view(instance, plugin, *, view,
    peek_per_split)`. The FR-20 partial-instance refusal lives here so
    library and CLI callers are guarded identically.
  - `DataRefinery.inspect(instance_path=None, view=None)` is now a
    real method (was a `NotImplementedError` stub): when called
    without `instance_path`, it resolves the bound recipe to its
    cached instance via `status()` and raises `MaterializeError` on
    cache miss.
  - `src/datarefinery/cli/commands/inspect_cmd.py` registered on the
    typer app via `app.command("inspect", ...)`. Accepts either a
    recipe YAML or an instance directory. `--view NAME` renders the
    named exploration visualization on demand; `--out PATH` writes
    the PNG bytes (and is rejected without `--view`). No-`--view`
    mode prints three `rich` tables: overview (instance,
    exploration views, fitted-stats op ids), records-per-split, and
    a sample-records peek (first three rows per split from the
    persisted JSONL).

### Tests

- 8 new CLI smoke tests in `tests/cli/test_inspect_cmd.py`: list+peek
  mode, `--view --out` PNG round-trip (with PNG signature check),
  `--view` without `--out`, unknown-view error, partial-instance
  refusal (manifest mutated to `is_partial=True` reaches the
  documented refusal path), recipe-path resolution to the cached
  instance, recipe-path cache miss errors, and `--out` without
  `--view` validation.

## [0.4.6] - 2026-05-08

### Added

- `datarefinery report` CLI verb (Story D.g, FR-15.4):
  - `src/datarefinery/cli/commands/report_cmd.py` registered on the
    typer app via `app.command("report", ...)`. Loads the materialized
    instance, discovers the plugin matching `instance.recipe.plugin`,
    and re-renders `report.md`, `drift.json`, and every reporting-mode
    visualization in place. Never reruns the pipeline. Prints the
    paths it touched.
  - `pipeline.inputs.reload_dataset(instance_dir, plugin)` reads the
    persisted per-split JSONL files and re-inflates plugin-specific
    record fields. For `image_classification`, the `image` array is
    reloaded via PIL from each record's `path` field. (Other plugins
    are stubs; reload is not implemented for them in v1.)
  - `reporting.report.re_render_report(instance_dir, recipe, *,
    plugin=None)` now also rewrites `drift.json` (via
    `compute_drift_placeholder` over the reloaded splits) and the
    reporting-mode visualizations (via
    `apply_reporting_visualizations`) when a `plugin` is supplied.
    Without a plugin the function still re-renders `report.md`-only,
    matching the previous behavior — useful for library callers who
    have already validated stat consistency.
  - `Instance.render_report(*, plugin=None)` and
    `DataRefinery.report(instance_path)` forward the plugin through;
    the latter passes its own bound plugin so library callers don't
    have to re-discover.
- The FR-15 "stale fitted-stats" hard error is reachable from two
  places: `Instance.load` already rejects instance dirs whose
  persisted `recipe.json` doesn't canonicalize to `manifest.recipe_hash`
  (Story D.a), and `re_render_report`'s own check guards the
  call when `Instance.load` is bypassed.

### Tests

- 4 new CLI smoke tests in `tests/cli/test_report_cmd.py`: round-trip
  re-render restores `report.md`, `drift.json`, and the
  visualization PNG byte-identically; the verb's announce output
  names every artifact; tampered persisted recipe → `MaterializeError`;
  missing instance dir is a usage error.

## [0.4.5] - 2026-05-08

### Added

- `datarefinery status` CLI verb (Story D.f, FR-19):
  - `src/datarefinery/core/status.py` with `StatusReport` (frozen
    dataclass: `cache_status` ∈ {hit, miss, corrupt}, `cache_key`,
    `instance_path`, optional `manifest`, optional `note`) and
    `resolve_status(cache_root, key)`.
  - `DataRefinery.status()` is now a real method (was a
    `NotImplementedError` stub): hashes the recipe's input sources via
    `pipeline.inputs.hash_inputs`, computes the cache key, and
    inspects `<cache_root>/instances/<key>/manifest.json`.
  - `src/datarefinery/cli/commands/status_cmd.py` registered on the
    typer app via `app.command("status", ...)`. Accepts either an
    instance directory (`Instance.load` path) or a recipe YAML file
    (recipe-path resolution). Hit renders a three-table `rich` summary
    (metadata, records-per-split, optional warnings); miss/corrupt
    render a single status table with the resolved hashes and
    expected instance path. `cache=miss` exits 0 (not an error);
    corrupt instances surface a `datarefinery clean` pointer per the
    FR-19 edge case.

### Tests

- 4 new CLI smoke tests in `tests/cli/test_status_cmd.py`: recipe-path
  hit on a freshly materialized instance, recipe-path miss on an
  unmaterialized recipe (exit 0), instance-path mode, and the FR-19
  corrupt-instance edge case (manifest.json removed → `cache=corrupt`
  + clean pointer).

## [0.4.4] - 2026-05-08

### Added

- `datarefinery materialize` CLI verb (Story D.e, FR-3) — closes the
  init → validate → materialize golden path:
  - `src/datarefinery/cli/commands/materialize_cmd.py` registered on
    the typer app via `app.command("materialize", ...)`. Renders a
    `rich` progress bar (driven by per-stage callbacks from the
    runner) and a three-table summary on completion: top-level
    metadata (cache hit/miss, instance path, hashes, seed, variant,
    elapsed), records-per-split counts, and optional warnings.
  - `--stage NAME` selects a partial run that stops after the named
    stage and leaves the result in the temp directory (no promote)
    with the manifest marked partial. Valid stage names are listed
    in the `--help` output.
- Disk-backed input loader (`src/datarefinery/pipeline/inputs.py`)
  deferred from Stories C.m and D.a:
  - `load_raw_records(recipe, plugin)` inflates `recipe.Input.sources`
    into records and a per-source SHA-256 content-hash dict for cache
    identity. The `image_classification` ImageFolder loader walks
    `<root>/<class>/<file>.{png,jpg,jpeg}` and only attaches a
    `label` field when `Labels.source.kind=="direct"` (so
    derived-label recipes leave the field for the featurization
    stage to populate).
  - `tabular` and `text` plugins refuse with `PluginError` until
    their full implementations land post-v1.
- `PipelineRunner` enhancements:
  - `progress_callback: Callable[[str], None] | None` parameter on
    `.run(...)`; invoked at the start of each stage.
  - `stop_after: str | None` parameter validated against the new
    public `STAGE_NAMES` tuple; partial runs write a manifest with
    the new `completed_through: str | None` field on
    `Manifest`, set `is_partial=True`, and skip atomic promote.
  - `RunnerResult` gained `is_partial: bool` so callers can
    distinguish a partial run from a completed one.
  - `PipelineRunner` accepts an optional `variant` keyword and
    records it in `manifest.variant` (was hard-coded to `None`).
- `DataRefinery.materialize()` upgrades:
  - Optional `raw_records` / `raw_input_hashes` (kept for library
    callers); when omitted the disk loader runs.
  - New `stop_after` and `progress_callback` keywords pass through
    to the runner.
  - New `last_run` property exposes the most recent `RunnerResult`
    (so the CLI can surface cache hit/miss).
- Top-level `materialize(recipe_path, *, config, variant, seed)` now
  performs disk-backed loading internally (was a
  `NotImplementedError` stub pointing at this story).

### Tests

- 5 new CLI smoke tests in `tests/cli/test_materialize_cmd.py`:
  cache-miss → instance produced (manifest, recipe.json, dataset
  jsonl per split, report.md, drift.json), rerun cache-hit on the
  second invocation, partial stage run with persisted partial
  manifest (`is_partial=True`, `completed_through="Splits"`),
  invalid stage name rejected, missing recipe is a usage error.

## [0.4.3] - 2026-05-08

### Added

- `datarefinery init` CLI verb (Story D.d, FR-17):
  - `src/datarefinery/cli/commands/init_cmd.py` registered on the
    typer app via `app.command("init", ...)`. Wraps
    `datarefinery.scaffolder.init.scaffold(...)`. Options: `--input`
    / `-i` (raw-inputs root, must exist as a directory), `--output`
    / `-o` (recipe YAML path; parent directories created on demand
    by the scaffolder), `--plugin` (defaults to
    `image_classification`; non-image categories raise the
    documented v1 refusal), `--enhance` (opt-in optional LLM
    enhancement; missing `[llm]` extra raises `PluginError` with the
    `pip install 'datarefinery[llm]'` install snippet, inherited
    from `scaffolder.llm.enhance`).
  - On success the verb prints a green confirmation plus a
    `datarefinery validate <output>` next-step pointer.

### Tests

- 6 new CLI smoke tests in `tests/cli/test_init_cmd.py` covering
  the basic write, the init→validate round-trip (scaffolded recipe
  passes every FR-2 check), parent-directory creation, the
  `--enhance` missing-extra error path (via propagated `PluginError`),
  the non-image plugin refusal, and the missing-input usage error.

## [0.4.2] - 2026-05-08

### Added

- `datarefinery validate` CLI verb (Story D.c, FR-2):
  - `src/datarefinery/cli/commands/validate_cmd.py` registered on the
    typer app via `app.command("validate", ...)`. Takes a recipe path
    argument, calls `DataRefinery.from_recipe(...).validate()`, and
    renders the 18-entry `ValidationReport` as a `rich` table (id,
    status, descriptor, location, message) with a summary line.
  - Status column is color-coded (green pass, yellow warn, red fail).
  - Honors the shared `--variant` option from the root callback — the
    overlay is applied to the recipe before validation runs.
  - Exits 0 on a clean recipe (warnings allowed); exits 1 on any check
    failure (per the documented user-error exit code).

### Tests

- 5 new CLI smoke tests in `tests/cli/test_validate_cmd.py` covering
  the clean-recipe exit-zero path, the multi-violation exit-one path
  (no short-circuit), full 18-row rendering, missing-file usage error,
  and `--variant` overlay flow-through.

## [0.4.1] - 2026-05-08

### Added

- `datarefinery check` CLI verb (Story D.b, FR-18):
  - `src/datarefinery/core/check.py` with `build_check_report()` and
    frozen `CheckReport`, `PluginInfo`, `DependencyStatus` dataclasses.
    Reports DataRefinery version, Python version, platform, plugin
    entry-point group, extra plugin discovery paths, every discovered
    plugin (name, schema version, stub-vs-active, source module),
    optional `[llm]` extra (`lmentry`), and optional accelerators
    (Metal/MPS, CUDA). Plugin-discovery errors are caught and recorded
    in `failures` so the report remains constructible.
  - `DataRefinery.check(config=None)` is now a static delegator
    returning the same `CheckReport`.
  - Accelerator probe is gated on `importlib.util.find_spec("torch")`
    and only imports torch if installed; otherwise both Metal and CUDA
    are reported missing with the documented "torch not installed"
    detail.
  - `src/datarefinery/cli/commands/__init__.py` (new package) and
    `src/datarefinery/cli/commands/check_cmd.py` render the report as a
    stack of `rich` tables on stdout. The verb is registered on the
    typer app via `app.command("check", ...)`. Exits 0 on a healthy
    environment (with warning rows for missing optional deps), exits 2
    on a soundness failure (e.g., plugin discovery raising
    `PluginError`).

### Tests

- 10 new unit tests in `tests/unit/test_check.py` covering the
  structured-report shape, plugin enumeration, optional-extra and
  accelerator probes (with the torch-not-installed branch documented),
  the `passed` property, frozen-dataclass invariants, plugin-discovery
  failure capture, and `RuntimeConfig.plugin_path` flow-through.
- 6 new CLI smoke tests in `tests/cli/test_check_cmd.py` covering
  exit-zero on a healthy environment, plugin and extras rendering, and
  the exit-2 path when discovery fails.

## [0.4.0] - 2026-05-08

### Added

- Public library entry point (Story D.a) — Phase D opens:
  - `src/datarefinery/core/datarefinery.py` with the `DataRefinery`
    class. Construction (`from_recipe`) loads the recipe, applies any
    requested variant overlay, discovers and binds the declared plugin,
    and runs the FR-2 validator exactly once; the report is memoized
    behind `validate()` so subsequent calls are zero-cost. The class
    exposes `recipe`, `plugin`, `seed`, `variant`, `config`, `validate`,
    `materialize`, `report`, `clean`, and a `cache_key(raw_input_hashes)`
    method. Verbs whose CLI counterparts ship in later stories
    (`status` → D.f, `inspect` → D.h, `check` → D.b) are present as
    `NotImplementedError` stubs so the public class shape is stable.
  - `src/datarefinery/core/instance.py` with `Instance` frozen
    dataclass (`path`, `manifest`, `recipe`, `fitted_statistics`,
    `report_path`, `is_partial`) and `Instance.load(path)`.
    `fitted_statistics` is exposed lazily — construction performs no
    fitted-statistics I/O. `Instance.render_report()` re-renders the
    instance's `report.md` from persisted state without rerunning the
    pipeline (FR-15.4).
  - Top-level `materialize(recipe_path, *, config, variant, seed)`
    convenience matching the tech-spec signature; raises
    `NotImplementedError` pointing at Story D.e (the CLI verb wires the
    disk-backed input loader). Library callers use
    `DataRefinery.from_recipe(...).materialize(raw_records=...,
    raw_input_hashes=...)` until D.e ships.
  - Public re-exports in `datarefinery/__init__.py`: `DataRefinery`,
    `Instance`, `materialize`, `__version__`.
- Per-instance recipe persistence:
  - `<instance>/recipe.json` is now written by `pipeline.runner` as the
    canonicalized recipe used for the run. `Instance.load()` reads it
    back, parses it through `Recipe.model_validate_json`, and verifies
    the canonical hash matches `manifest.recipe_hash` — a tampered or
    inconsistent instance directory raises `MaterializeError`.
  - `cache.layout.recipe_path(instance)` helper.
- `PipelineRunner` accepts an optional `variant` keyword and records it
  in `manifest.variant` so future tooling can attribute an instance to
  its source variant.

### Tests

- 15 new unit tests in `tests/unit/test_datarefinery.py` covering
  public re-exports, validation memoization (the FR-2 validator is
  invoked exactly once per `from_recipe`), seed override, unknown-plugin
  rejection, `cache_key` composition, the materialize → `Instance.load`
  round-trip, recipe-hash mismatch detection, lazy
  `fitted_statistics`, `clean` routing through the configured cache
  root, and `NotImplementedError` stubs for the deferred verbs.

## [0.3.13] - 2026-05-08

### Added

- Deterministic image-classification scaffolder (Story C.o, FR-17) -
  Phase C complete:
  - `src/datarefinery/scaffolder/__init__.py` (package),
    `src/datarefinery/scaffolder/init.py`
    (`scaffold_image_classification(input_path, output_path, *,
    enhance=False)` and the top-level `scaffold(...,
    plugin="image_classification", ...)` dispatcher), and
    `src/datarefinery/scaffolder/llm.py` (lazy `lmentry` import +
    offline detection). The deterministic path performs no network
    I/O and never imports `lmentry`; `enhance=True` is the only
    surface that touches the optional extra.
  - Recipe inspection: walks the ImageFolder layout
    (`<root>/<class>/<file>.{png,jpg,jpeg}`), inspects the first
    image for shape and dtype, sorts class names. Raises
    `RecipeError` for non-directory inputs, missing class
    subdirectories, or missing image files - each error message
    cites the expected layout.
  - Generated recipe: declares `Input` (image_folder source pointing
    at the scanned directory), `Output` (record schema with `image`
    and `label`, plus `path` for downstream traceability and so
    validator check 7 sees it in the field universe), `Labels` (kind
    "derived", derivation "parent_directory_name"), `Splits` (70/15/15
    stratified by `label`, seed 11), a `label_from_path`
    Featurization populating `label`, and reporting Visualizations
    (`class_distribution_histogram`, `sample_grid`). A commented-out
    block of suggested `Transformations` (resize, normalize) is
    appended below the recipe so the user can uncomment and tune.
  - LLM enhancement (`scaffolder.llm.enhance`): missing `lmentry` ->
    `PluginError` pointing at the `[llm]` extra; offline detection
    fails (UDP-level reachability probe via `_is_online`) -> the
    deterministic recipe is emitted with a "LLM enhancement
    skipped: offline" note in the YAML header. Online with `lmentry`
    installed -> v1 placeholder marker note "LLM enhancement
    applied" (full LLM-driven judgment lands post-v1).
  - Non-image refusals: `scaffold(..., plugin="tabular")` and
    `scaffold(..., plugin="text")` raise `PluginError` with the
    documented "init scaffolder not available for this category in
    v1" message per features.md FR-17 edge cases.
  - `tests/unit/test_scaffolder.py` covers: scaffold writes a recipe
    with the expected header + schema_version + plugin; loaded
    recipe validates clean (all 18 checks pass); image dimensions
    inferred from the first image; 70/15/15 stratified split; derived
    label via `label_from_path`; both reporting visualizations
    present; commented-out suggested Transformations in YAML;
    parent-dir creation for output path; tabular/text refusals;
    non-directory and empty-directory error paths; missing-images
    error; LLM-without-lmentry `PluginError`; offline note in YAML;
    online "applied" note; deterministic path doesn't import
    lmentry; end-to-end materialize round-trip via the runner
    (synthetic records matching the scaffolded on-disk layout
    produce a complete instance with both reporting PNGs and full
    record counts); module exposes `scaffold` and
    `scaffold_image_classification` (21 tests).

### Notes

- v1 deviation: the materialize round-trip test synthesizes records
  matching the scaffolded directory layout in-memory because
  disk-based input loading was deferred from C.m. The CLI
  `materialize` verb (Story D.e) will wire scaffolded recipes through
  end-to-end disk loading.

## [0.3.12] - 2026-05-08

### Added

- Reporting: report.md + drift.json (Story C.n, FR-15):
  - `src/datarefinery/reporting/drift.py` defines pydantic
    `DriftSchema` (frozen, `extra="forbid"`) plus `SplitDriftRecord`
    and `FeatureDriftRecord`. `DRIFT_SCHEMA_VERSION_PLACEHOLDER = 0`
    per features.md FR-15 #3 - the schema is unstable until
    production release (v1.0.0) at which point the version bumps to 1.
    `compute_drift_placeholder(splits, *, plugin_name, label_field)`
    builds the v1 placeholder: per-split record counts and (when a
    label field is provided) sorted class distributions. Feature-
    level summaries are intentionally empty in v1; the schema slot is
    reserved for DataMachine consumers. `write_drift`/`read_drift`
    canonical JSON round-trip with sorted keys.
  - `src/datarefinery/reporting/report.py` exposes
    `render_report_md(recipe, manifest, *, fitted_op_ids) -> str`
    producing a deterministic markdown summary: manifest header
    (recipe/input hashes, seed, variant, created_at, elapsed,
    partial-run marker), inputs, splits + total, operations applied
    per section (filters/generation/transformations/featurizations/
    augmentations/visualizations), fitted statistics op_ids, and any
    accumulated warnings. Same inputs -> byte-identical markdown.
  - `re_render_report(instance_dir, recipe)` regenerates `report.md`
    from a materialized instance without rerunning the pipeline
    (FR-15.4). Compares the manifest's `recipe_hash` against the
    canonical hash of the recipe handed in; mismatch raises
    `MaterializeError` per FR-15 edge case "re-rendering against a
    stale fitted-statistics block is rejected".
    `list_fitted_op_ids(fitted_root)` enumerates persisted op_ids
    for the report's fitted-statistics section.
  - `src/datarefinery/pipeline/runner.py` now also writes
    `<instance>/report/report.md` and `<instance>/report/drift.json`
    inside the temp directory before the atomic promote. Fitted
    op_ids accumulated across Transformations and Featurizations
    flow into the report.
  - `tests/unit/test_drift.py` covers placeholder version, frozen +
    extra-forbid model behavior, per-split counts, label-field-driven
    class distribution, missing-label-field skip, sorted split keys,
    unstable-notes, empty feature_summary, JSON round-trip, and
    canonical sort-keys output (13 tests).
  - `tests/unit/test_report.py` covers manifest summary inclusion,
    inputs/splits sections, per-section op listings, fitted op_ids
    listing, "(none)" placeholders, warning rendering, partial-run
    marker, byte-stability for identical inputs, the
    `list_fitted_op_ids` directory helper (missing dir + sorted
    subdirs), `re_render_report` happy path, recipe-hash-mismatch
    hard error, and overwrite-of-stale-content (13 tests).
  - `tests/integration/test_runner.py` adds an end-to-end check that
    the runner writes both `report.md` (with fitted op listed) and
    a parseable `drift.json` whose split records sum to the input
    record count.

### Notes

- The story checklist mentioned adding `reporting/__init__.py`; that
  package init was already created in Story C.k for the visualization
  library API. No change needed beyond noting the package now also
  hosts `report.py` and `drift.py`.

## [0.3.11] - 2026-05-08

### Added

- PipelineRunner conductor (Story C.m, FR-3) - Phase C orchestration:
  - `src/datarefinery/pipeline/manifest.py` defines pydantic
    `Manifest` (frozen, `extra="forbid"`) carrying full
    `recipe_hash`/`input_hash` (SHA-256 hex), `seed`, `variant`,
    `created_at`, `elapsed_seconds`, `is_partial`, `failed_stage`,
    `record_counts`, and `warnings`. `MANIFEST_SCHEMA_VERSION = 1` is
    a separate counter from the recipe schema version per tech-spec.
    `write_manifest`/`read_manifest` round-trip via JSON.
  - `src/datarefinery/pipeline/runner.py` exposes `PipelineRunner(
    recipe, plugin, config, seed)` with `run(temp_dir, *,
    raw_records, raw_input_hashes) -> RunnerResult`. Sequences:
    `InputContracts` -> pre-split `Filters` -> `Splits` -> post-split
    `Filters` -> `Generation` -> `Transformations` -> `Featurizations`
    -> `Augmentations` (policy capture) -> `OutputExpectations` ->
    reporting `Visualizations` -> dataset persistence -> manifest
    write -> `atomic_promote(temp_dir, final_dir)`.
  - Cache-hit short-circuit: if `<final_dir>/manifest.json` exists,
    return without touching the temp dir; the persisted manifest is
    re-read and returned alongside the path.
  - Failure path: any stage exception triggers
    `mark_failed(temp_dir, exc, current_stage)` and re-raises;
    `final_dir` is never touched and no partial manifest is promoted.
  - Warning aggregation: stage warnings (split unassigned, sparse
    classes, empty-class filters, generation non-train splits, etc.)
    are accumulated as `ManifestWarning(stage=..., message=...)` and
    persisted on the manifest.
  - v1 scope notes: raw input loading is the caller's responsibility
    (`run` accepts `raw_records` + per-source `raw_input_hashes`);
    the CLI `materialize` verb (Story D.e) wires disk-based loading.
    Dataset persistence is intentionally minimal - per-split
    JSON-lines under `<instance>/dataset/<split>.jsonl` with each
    record's serializable fields; numpy arrays, bytes, and other
    non-JSON-native values are dropped (image bytes are accessed via
    the source `path` field, not embedded in the materialized
    dataset).
  - `tests/integration/test_runner.py` covers end-to-end
    materialization (manifest + dataset/<split>.jsonl + report
    visualization PNGs), well-formed manifest fields and shape,
    `normalize` fitted-stats persistence (`mean.parquet` and
    `std.parquet`), temp-dir cleanup after promote, instance path
    matches `compute_cache_key` derivation, cache-hit short-circuit
    on second run (returns cached manifest, leaves temp untouched),
    different seed misses cache, visualization-failure injection
    leaves `FAILED` marker with `stage="Visualizations"` and never
    creates the final `manifest.json`, and dataset JSON-lines omits
    numpy `image` arrays while preserving `record_id` and `label`
    (11 tests).

## [0.3.10] - 2026-05-08

### Added

- Deterministic parallel worker pool (Story C.l):
  - `src/datarefinery/pipeline/workers.py` exposes
    `run_parallel(seed, fn, items, workers, *, record_id_field) ->
    Iterator[Record]` and the `per_record_seed(global_seed, record, *,
    record_id_field)` helper. Implements the determinism contract from
    `project-essentials.md`: per-record seed
    `sha256(global_seed.to_bytes(8, "big") + str(record_id).encode()).digest()[:8]`
    decoded as a 64-bit unsigned int, and reorder-by-`record_id`
    (stable across mixed-type ids via a `(type, str)` sort key)
    before yielding. Worker count and process scheduling are
    invisible to downstream stages.
  - Serial fast-path when `workers <= 1` bypasses
    `ProcessPoolExecutor` entirely (still per-record-seeded, still
    reorder-by-record-id). Worker exceptions surface to the caller
    via `Future.result()` in parallel mode and via direct call in
    serial mode. Records missing the `record_id` field raise
    `MaterializeError` rather than silently producing
    nondeterministic output.
  - `tests/unit/test_workers.py` covers the per-record seed formula
    pin (deliberate cache-relevant change marker), seed determinism,
    record/global-seed sensitivity, int/custom-field record ids,
    missing-id error, byte-identical workers=1/2/4 output (the
    headline determinism check, also parametrized), per-record-seed
    invariance across worker counts and matches against the formula,
    reorder-by-record-id in serial and parallel (with order-jumbling
    delays in parallel), mixed-type id handling, empty input,
    workers=0 serial fast-path, exception propagation in both modes,
    same-seed cross-run identity, different-seed produces different
    per-record seeds, and a serial-mode same-PID sanity check
    (23 tests).

## [0.3.9] - 2026-05-08

### Added

- Visualizations: reporting + exploration modes (Story C.k, FR-13):
  - `src/datarefinery/pipeline/stages/visualizations.py` exposes
    `apply_reporting_visualizations(splits, viz_ops, *, plugin,
    output_dir, label_field) -> VisualizationsResult`. The runner
    iterates `mode == "reporting"` ops, calls
    `plugin.operation_factory("Visualizations", op.op).render(...)`,
    and writes PNG bytes to `<output_dir>/<op.name>.png`.
    `exploration`-mode ops are skipped. Failures wrap as
    `MaterializeError` per FR-13 ("reporting visualization that fails
    -> hard error during materialization"); non-bytes returns also
    hard-error.
  - `src/datarefinery/reporting/__init__.py` and
    `src/datarefinery/reporting/visualizations.py` expose
    `render_visualization(splits, op, *, plugin, label_field) ->
    RenderedVisualization` for exploration-mode use (typically called
    by the `inspect` CLI verb in Story D.h). Returns the same handle
    output without persisting; failures propagate unwrapped per the
    "exploring, not materializing" semantics.
  - Visualization handle protocol is `(.render(splits, params, *,
    label_field) -> bytes)` returning PNG bytes.
    `RenderedVisualization` carries `name`, `op`, `png_bytes`, and
    `path` (`None` for exploration mode).
  - `src/datarefinery/plugins/image_classification/operations/visualizations.py`
    implements three viz handles with Pillow alone (no matplotlib in
    deps):
    - `ClassDistributionHistogramOp`: per-class bar chart on a
      400x300 canvas; class iteration is stably ordered for
      seed-deterministic PNG bytes.
    - `SampleGridOp`: tiles the first N records' images into a
      square-ish grid; with `per_class=True`, takes the first N from
      each class (validator check 18 enforces param shape; the op
      requires `Labels.field` only when `per_class=True`).
    - `MeanImagePerClassOp`: per-class mean image (resized to 32x32
      thumbnails) tiled in a row.
  - All three are deterministic by record order: no RNG, stable class
    sort by `(type, repr)`, and Pillow's PNG encoder is byte-stable
    for identical pixel inputs.
  - `image_classification.plugin.operation_factory` now dispatches
    Visualizations ops via `_VISUALIZATION_OPS`; the only remaining
    factory exemptions are `to_grayscale`, `cast_dtype`, and the
    three augmentation ops (which are policy-only in v1 per FR-11).
  - `tests/unit/test_visualizations_stage.py` covers writes-png-per-
    op, skips-exploration-in-reporting-mode, creates-output-directory,
    empty-op-list pass-through, byte determinism for all three ops,
    sensitivity to input changes, per-class sampling, no-records
    blank rendering, missing-`Labels.field` rejection, FR-13
    reporting-failure hard error, non-bytes return hard error,
    exploration-API no-persist + unwrapped error propagation +
    non-bytes TypeError, and pixel-level decoding-and-shape smoke
    checks (20 tests).
  - `tests/plugin_contract/test_image_classification.py` adds a
    Visualizations factory-callable assertion and asserts that
    augmentation ops still raise `NotImplementedError` (policy-only
    per FR-11).

## [0.3.8] - 2026-05-08

### Added

- Augmentations declaration stage (Story C.j, FR-11):
  - `src/datarefinery/pipeline/stages/augmentations.py` exposes
    `collect_augmentation_policies(augmentation_ops) ->
    AugmentationsResult` and the `manifest_block(result)` helper that
    renders the augmentation list as stable canonical JSON for the
    runner's manifest. Each declared `AugmentationOp` becomes a frozen
    `AugmentationPolicy` carrying `name`, `op`, `params`, `splits`,
    and `seed`.
  - v1 does NOT pre-materialize augmented examples (FR-11 #2, #3) -
    the recipe declares augmentation policies that ModelFoundry
    honors on-the-fly during training. This stage's only side effect
    is producing the manifest summary; no image bytes change.
  - Defensive train-only re-check: validator check 5 enforces
    `splits=["train"]` for augmentations; this stage raises
    `MaterializeError` if a non-train split somehow reached it.
  - Image plugin's three augmentation OperationSpecs (`random_crop`,
    `horizontal_flip`, `color_jitter`) declared in C.b remain
    policy-only; no factory wiring (the plugin's
    `operation_factory` still raises `NotImplementedError` for
    Augmentations).
  - `AugmentationPolicy.to_manifest_dict()` and
    `AugmentationsResult.to_manifest_list()` produce
    JSON-serializable dicts with sorted param keys for byte-stable
    manifest output.
  - `tests/unit/test_augmentations_stage.py` covers policy
    collection, params/splits/seed verbatim capture, empty-list
    pass-through, manifest dict shape, sorted param keys, stable JSON
    formatting, full round-trip preservation, `seed=None` round-trip,
    non-train and test-only defensive rejection, empty-splits
    permitted, and frozen-result guarantees (13 tests).
- Story title typo fix in `docs/specs/stories.md` for C.j: was
  `v0.3.28`, corrected to `v0.3.8` to match the bump-version task line.

## [0.3.7] - 2026-05-08

### Added

- Featurizations stage + derived-label machinery (Story C.i, FR-12,
  FR-22):
  - `src/datarefinery/pipeline/stages/featurizations.py` exposes
    `apply_featurizations(splits, ops, *, plugin, fitted_stats,
    label_field) -> FeaturizationsResult`. Operation handle protocol
    is `(.fit_on_train, .fit, .apply)` with kwargs `inputs`,
    `output_field`, `label_field`. The stage decides whether to fit
    via `OperationSpec.fit_on_train`; fitted values are persisted
    once via `FittedStatistics` and applied across every declared
    split (FR-12 #3 mirrors FR-10's discipline). Unknown ops, missing
    `fit_source`, or undeclared `splits`/`fit_source` references
    raise `MaterializeError`.
  - Field-collision hard error per FR-12 edge case: under the
    uniform-schema invariant, the stage checks the first record of
    each target split before applying; an existing key collision
    raises `MaterializeError` (no records mutated).
  - FR-22 derived-label wiring: when `Labels.source.kind == "derived"`,
    the recipe author writes a `FeaturizationOp` whose
    `output_field` matches `Labels.field`. The stage runs that
    featurization like any other; no special-casing needed - the
    same machinery produces derived labels.
  - `src/datarefinery/plugins/image_classification/operations/featurizations.py`
    implements two featurization handles:
    - `LabelFromPathOp` (no fit): derives a label from a record's
      path field. Default `source` is `parent_directory_name` (the
      ImageFolder convention - `cats/foo.jpg` -> `"cats"`); also
      supports `filename` and `stem`. Raises `PluginError` on missing
      input field, empty `inputs`, or unknown `source`.
    - `ImageSizeStatsOp` (no fit): writes the image's spatial
      shape (e.g., `[H, W, C]`) under `output_field`. Supports 2-D
      and 3-D arrays; raises `PluginError` on other ndim.
  - `image_classification.plugin.operation_factory` now dispatches
    `Featurizations` ops via `_FEATURIZATION_OPS`; `to_grayscale`,
    `cast_dtype`, all augmentation ops, and all visualization ops
    still raise `NotImplementedError` (lands in C.j-C.k).
  - `tests/unit/test_featurizations_stage.py` covers
    parent-directory derivation, alternate sources (`filename`),
    unknown source rejection, missing-input-field error, empty-inputs
    error, image-size-stats shape extraction (3-D and 2-D),
    invalid-ndim rejection, multi-record / multi-split determinism,
    field-collision hard error (FR-12 edge case), no-collision-on-
    empty-split, fit-on-train support via a fixture plugin
    (persistence + train-fitted apply across splits + missing-
    fit_source error), unknown-op error, undeclared-split error,
    empty-list pass-through, and input-list non-mutation
    (18 tests).
  - `tests/plugin_contract/test_image_classification.py` adds a
    `Featurizations` factory-callable assertion.

## [0.3.6] - 2026-05-07

### Added

- Transformations stage + FittedStatistics persistence (Story C.h,
  FR-10 / FR-6):
  - `src/datarefinery/pipeline/fitted_stats.py` exposes
    `FittedStatistics(root)` with `put_scalar`/`get_scalar` (storing
    `float`/`int`/`str`/`bool` values in `<root>/<op_id>/scalars.json`
    as a sorted JSON object) and `put_vector`/`get_vector` (storing
    `pyarrow.Table` instances as `<root>/<op_id>/<name>.parquet`).
    Multiple `put_scalar` calls for the same `op_id` accumulate into
    one JSON file; later writes overwrite by name. Reads raise
    `MaterializeError` for missing or malformed inputs (including
    non-object `scalars.json`, non-scalar JSON values, and
    non-`pyarrow.Table` vector inputs). Never opaque pickles
    (FR-6 #3).
  - `src/datarefinery/pipeline/stages/transformations.py` exposes
    `apply_transformations(splits, ops, *, plugin, fitted_stats,
    label_field) -> TransformationsResult`. The handle protocol for
    Transformations operations is `(.fit, .apply)`; the stage decides
    whether to fit using `OperationSpec.fit_on_train`. Fit phase runs
    against the declared `fit_source` split, persists results via the
    supplied `FittedStatistics`, and the same fitted values flow into
    the apply phase across every declared `splits` entry (FR-10 #2).
    `MaterializeError` covers unknown ops, fit-on-train without
    `fit_source`, and `fit_source`/`splits` referencing undeclared
    splits.
  - `FittedValues(scalars, vectors)` is the data carrier between fit
    and apply. Recipe-supplied `mean`/`std` for `normalize` short-
    circuit the per-split fit so authored values flow into the
    persisted output (useful for tabular pipelines; image recipes
    typically omit them).
  - `src/datarefinery/plugins/image_classification/operations/transformations.py`
    implements three transformation handles:
    - `ResizeOp` (no fit): resizes each record's NumPy `image` field
      via Pillow with the recipe-specified `size` and `method`
      (`nearest`/`bilinear`/`bicubic`/`lanczos`); raises `PluginError`
      on invalid params.
    - `NormalizeOp` (fit-on-train): per-channel mean/std fitted on
      the train split; apply does `(x - mean) / std` with a
      zero-variance guard. Honors recipe-pinned mean/std when both
      are supplied.
    - `MeanSubtractOp` (fit-on-train, mean only): per-channel mean
      fitted on train; apply does `x - mean`.
    The remaining declared ops (`to_grayscale`, `cast_dtype`) still
    raise `NotImplementedError` from the factory.
  - `image_classification.plugin.operation_factory` now dispatches
    `Transformations` ops via `_TRANSFORMATION_OPS`.
  - `tests/unit/test_fitted_stats.py` covers scalar/vector round-trip,
    multi-scalar same-file accumulation, sorted-key layout, value
    overwrite, missing-op/missing-name read errors, non-scalar reject,
    malformed/non-object JSON, vector type guard, per-`op_id`
    directory layout, and post-promote independent-instance read
    pattern (16 tests).
  - `tests/unit/test_transformations_stage.py` covers resize-no-fit,
    no-stats-persisted-for-resize, invalid resize params,
    normalize-fits-on-train-only-and-persists, apply-uses-train-stats
    (val/test do not refit), determinism, zero-variance guard,
    recipe-pinned mean/std, mean_subtract persists only mean and
    centers around zero, unknown-op error, fit-on-train-without-
    fit_source error, fit_source/splits-undeclared errors, empty-list
    pass-through, FittedValues default, input non-mutation, and
    pyarrow.Table persisted-stats invariant (19 tests).
  - `tests/plugin_contract/test_image_classification.py` updated to
    assert resize/normalize/mean_subtract handles are returned and
    `to_grayscale`/`cast_dtype` still raise `NotImplementedError`.

## [0.3.5] - 2026-05-07

### Added

- Generation stage + image plugin duplication op (Story C.g, FR-9):
  - `src/datarefinery/pipeline/stages/generation.py` exposes
    `apply_generation(splits, generation_ops, *, plugin,
    output_record_schema, label_field)` returning a frozen
    `GenerationResult` carrying the updated `splits` (fresh lists; the
    caller's inputs are not mutated), `counts_before`/`counts_after`
    per split (consumed by the runner for manifest pre/post counts),
    and any `warnings`. Generation dispatches via
    `plugin.operation_factory("Generation", op.name)` - the model has
    no separate `op` field, so `GenerationOp.name` doubles as the
    lookup key. The canonical Generation operation signature is
    `(records, *, seed, inputs, output_schema, label_field) ->
    list[Record]` returning *new* records to add; the stage
    concatenates onto the split's existing records.
  - Each generated record is validated against `Output.record_schema`;
    any record missing a required Output field raises
    `MaterializeError` with the op name, split, and missing fields
    listed.
  - `applies_at` is honored (default `["train"]` via the model);
    non-train splits emit a per-op warning per features.md FR-9 edge
    case ("atypical but legitimate, flagged in the report"). An
    `applies_at` referencing an undeclared split raises
    `MaterializeError` (validator check 15 normally enforces this;
    the stage fails loudly if invoked without that gate).
  - `src/datarefinery/plugins/image_classification/operations/generation.py`
    implements `duplicate_minority_class`: brings each non-majority
    class up to the majority count by sample-with-replacement using
    `numpy.random.default_rng(seed)`. Class iteration is stably
    ordered so output is seed-deterministic across hash-randomization
    variants. Requires `Labels.field`; raises `PluginError` otherwise.
    v1 simplification: target count is the majority class size (no
    user-tunable target).
  - `image_classification.plugin.operation_factory` now dispatches
    `Generation` ops via `_GENERATION_OPS`; remaining sections still
    raise `NotImplementedError` (lands in C.h-C.k).
  - `tests/unit/test_generation_stage.py` covers minority→majority
    rebalancing, pre/post counts, seed determinism, seed sensitivity,
    no-op when balanced, missing-`label_field` error, default
    train-only `applies_at`, non-train warning, undeclared-split hard
    error, output-schema mismatch hard error (via a fixture plugin
    that drops a field), empty-list pass-through, input-list non-
    mutation, and frozen-result guarantee (13 tests).
  - `tests/plugin_contract/test_image_classification.py` adds an
    assertion that `Generation` ops are callable through the factory.

## [0.3.4] - 2026-05-07

### Added

- Filters stage + first image plugin operations (Story C.f, FR-8):
  - `src/datarefinery/pipeline/stages/filters.py` exposes
    `apply_pre_split_filters(records, filter_ops, *, plugin, label_field)`
    and `apply_post_split_filters(splits, filter_ops, *, plugin,
    label_field)` returning frozen `FilterResult`s with `records`,
    `warnings`, and `removed` count. Filters dispatch through
    `plugin.operation_factory("Filters", op_name)`; the canonical filter
    operation signature is
    `(records, params, *, label_field) -> list[Record]`. Pre-split
    filters honor the default `stages=["pre_split"]`; post-split
    filters apply only to splits listed in `FilterOp.splits`.
  - Empty-class warnings: when a filter pass reduces a class's record
    count from positive to zero, a warning is emitted (FR-8 edge case).
    Per-split warnings include the split name; warnings are skipped
    when no `label_field` is supplied.
  - `src/datarefinery/plugins/image_classification/operations/filters.py`
    implements the image plugin's two filter operations:
    - `filter_by_label(records, params, *, label_field)`: include or
      exclude records by label-set membership; defaults `action` to
      `"include"`; raises `PluginError` if `label_field` is `None` or
      `action` is not `"include"`/`"exclude"`.
    - `random_sample(records, params, *, label_field)`: reproducible
      sampling via `numpy.random.default_rng(seed)`. Requires exactly
      one of `fraction` (in `[0, 1]`) or `n` (non-negative); requires
      integer `seed`. Output preserves original record order so
      downstream stages see a stable subsequence.
  - `image_classification.plugin.operation_factory` now dispatches
    `Filters` ops via `_FILTER_OPS`; remaining sections still raise
    `NotImplementedError` (lands in C.g-C.k).
  - `tests/unit/test_filters_stage.py` covers include/exclude, default
    action, unknown action, missing-`label_field` error, sampling
    reproducibility, seed sensitivity, order-preservation,
    `n > total`, fraction/`n` exclusivity, missing-seed and
    out-of-range fraction errors, pre/post stage dispatch, multi-stage
    runs, in-order multi-filter pipelines, empty-class warnings (with
    and without label field), per-split warning naming, missing-`op`
    predicate error, frozen-result, and empty-list pass-through
    (24 tests).
  - `tests/plugin_contract/test_image_classification.py` updated to
    assert filter ops now return callables while other sections still
    raise `NotImplementedError`.

## [0.3.3] - 2026-05-07

### Added

- Splits stage (Story C.e, FR-7):
  - `src/datarefinery/pipeline/stages/splits.py` exposes
    `apply_splits(records, section, *, seed) -> SplitResult` plus a
    `resolve_seed(section, fallback)` helper for callers to pick the
    section seed over the recipe-level fallback. `SplitResult` is a
    frozen dataclass listing `splits: Mapping[str, list[Record]]`,
    `unassigned: list[Record]`, the pass-through `class_balance` tag,
    and any sparse-class `warnings`.
  - Two splitting modes: ratio-based (cumulative-fraction
    partitioning; sub-1.0 ratio sums leave a recorded `unassigned`
    remainder per features.md FR-7 edge case) and key-based
    (`mapping[str(record[field])]` lookup; unmapped or missing-field
    records raise `MaterializeError` with sample indices).
  - Stratification (`stratify_by`) honored in ratio mode by
    partitioning each class's records by the same ratio shape.
    Sparse-class detection emits a per-class warning when any class
    has fewer records than the number of positive-ratio splits.
    Class iteration is stably ordered by `(type, repr)` so stratified
    output is seed-deterministic across hash-randomization variants.
  - `class_balance` is a tag passed through unchanged - resampling is
    ModelFoundry-side per features.md FR-7 #4; this stage does no
    resampling.
  - Determinism: shuffles use `numpy.random.default_rng(seed)`; same
    seed + same record order produces byte-identical partitions.
  - `tests/unit/test_splits_stage.py` covers ratio partitioning, seed
    determinism, sub-1.0 remainder, partition completeness with awkward
    counts, stratified class distribution, sparse-class warning, no-warn
    when classes are dense, stratified determinism, key-based
    partitioning, unmapped-record and missing-field hard errors,
    empty-target-split behavior, `class_balance` pass-through, no-
    resampling invariant, seed precedence helper, and empty-input
    edge case (18 tests).

## [0.3.2] - 2026-05-07

### Added

- Pipeline contracts: InputContracts and OutputExpectations evaluation
  (Story C.d, FR-23):
  - `src/datarefinery/pipeline/contracts.py` exposes
    `evaluate_input_contracts(records, contracts) -> ContractResult` and
    `evaluate_output_expectations(dataset, expectations) -> ContractResult`.
    Both materialize the iterable once internally so multiple assertions
    traverse the same records without callers re-buffering. The
    `ContractResult` aggregates one `AssertionResult` per declared
    contract and exposes `passed`, `failures`, `warnings`, plus a
    `raise_for_status()` method that raises `ContractError` only on
    error-severity failures (warnings are recorded but never raise).
  - Five assertion kinds: `record_count` (dataset-level `min`/`max`
    bounds), `required_field` (every record contains the field
    non-None), `dtype` (Python type tag with numpy aliases, rejecting
    `bool` for int-family tags), `range` (`min`/`max` per-field), and
    `distributional` (placeholder that always passes in v1; full
    machinery is post-v1 per features.md FR-23 edge cases).
  - The aggregator does not short-circuit; an unknown assertion `kind`
    or a missing required `field` is reported as a failure rather than
    raising.
  - `tests/unit/test_contracts.py` covers each assertion kind's pass
    and fail paths, severity handling (warning vs. error),
    `raise_for_status` behavior, the no-short-circuit aggregator,
    iterator consumption, and frozen-result guarantees (34 tests).

## [0.3.1] - 2026-05-07

### Added

- Tabular and text plugin stubs (Story C.c):
  - `src/datarefinery/plugins/tabular/` and
    `src/datarefinery/plugins/text/` packages, each declaring a section
    list and `OperationSpec` outlines so recipes targeting
    `plugin: tabular` or `plugin: text` validate clean against FR-2
    checks 1-18. Tabular outlines cover Filters
    (`filter_by_value`, `drop_nulls`, `random_sample`), Generation
    (`duplicate_minority_class`), Transformations
    (`standardize` [fit-on-train], `min_max_scale` [fit-on-train],
    `one_hot_encode` [fit-on-train], `cast_dtype`), Featurizations
    (`polynomial_features`), and Visualizations
    (`class_distribution_histogram`, `field_summary_table`). Text
    outlines cover Filters (`filter_by_label`, `filter_by_length`,
    `random_sample`), Generation (`duplicate_minority_class`),
    Transformations (`lowercase`, `strip_punctuation`, `tokenize`,
    `remove_stopwords`), Featurizations (`tfidf` [fit-on-train],
    `token_count`), and Visualizations
    (`class_distribution_histogram`, `token_length_histogram`).
  - Both plugins return `is_stub() -> True`; `operation_factory(...)`
    raises `PluginError("stub plugin; not implemented")` with plugin,
    section, and op name in the message. Full operation
    implementations are post-v1.
  - Registered under the `datarefinery.plugins` entry-point group in
    `pyproject.toml` so `discover_plugins()` returns both stubs.
  - `tests/plugin_contract/test_tabular.py` and
    `tests/plugin_contract/test_text.py` cover runtime-protocol
    satisfaction, metadata, declared section/op set, `OperationSpec`
    validity per operation, fit-on-train placement invariant, the
    `PluginError` factory contract, and entry-point discovery.
  - `tests/integration/test_tabular_stub_smoke.py` exercises a tabular
    recipe through `Recipe.model_validate` + `validator.validate`
    (all 18 checks pass) and confirms `operation_factory` raises
    `PluginError`.

## [0.3.0] - 2026-05-07

### Added

- Image classification plugin skeleton (Story C.b) - Phase C begins:
  - `src/datarefinery/plugins/image_classification/` package with
    `plugin.py` declaring full `OperationSpec` parameter schemas for
    16 operations across Filters (`filter_by_label`, `random_sample`),
    Generation (`duplicate_minority_class`), Transformations
    (`resize`, `normalize` [fit-on-train], `mean_subtract`
    [fit-on-train], `to_grayscale`, `cast_dtype`), Featurizations
    (`label_from_path`, `image_size_stats`), Augmentations
    (`random_crop`, `horizontal_flip`, `color_jitter` - all
    train-only), and Visualizations
    (`class_distribution_histogram`, `sample_grid`,
    `mean_image_per_class`).
  - `operation_factory` raises `NotImplementedError` for now (real
    implementations land in Stories C.f-C.k); `is_stub() -> False`
    because the schemas are real.
  - Registered under the `datarefinery.plugins` entry-point group in
    `pyproject.toml` so `discover_plugins()` returns it without
    requiring `--plugin-path`.
  - `tests/plugin_contract/test_image_classification.py` covers
    runtime-protocol satisfaction, metadata, declared section/op set,
    `OperationSpec` validity per operation, fit-on-train invariant
    (must be in Transformations), augmentation train-only invariant,
    `resize` parameter schema accepting fixture params, the
    `NotImplementedError` factory contract, and that
    `discover_plugins()` returns the plugin via entry points.

## [0.2.10] - 2026-05-07

### Added

- Cache cleaner library API (Story B.i, FR-21) - Phase B complete:
  - `src/datarefinery/cache/cleaner.py` exposes the frozen
    `CleanSelector` dataclass (`by_recipe_hash`, `by_input_hash`,
    `by_seed`, `by_age_days`, `orphans`, `orphan_age_days`, `all`) and
    `clean(cache_root, selector, *, force=False) -> CleanReport`. The
    `by_*` filters compose intersection-style; `orphans=True` adds
    temp dirs older than `orphan_age_days` to the target set;
    `all=True` requires `force=True` and clears every direct child of
    `<cache-root>/instances/`. Recipe and input hash matchers truncate
    callers' full hashes to 16 chars before comparison. Failed
    removals are captured in `CleanReport.skipped` rather than aborting
    the run. The CLI verb wrapping this lands in Phase D.
  - `tests/unit/test_cleaner.py` synthesizes a 4-instance + 2-orphan
    layout and covers each selector, intersection-style composition,
    the 16-char truncation invariant, the `all`-without-`force`
    refusal, the `orphan_age_days` threshold, missing-cache-root
    no-op, and `shutil.rmtree` failure capture in `skipped`.

## [0.2.9] - 2026-05-07

### Added

- Atomic temp-then-promote (Story B.h, FR-5):
  - `src/datarefinery/cache/atomic.py` exposes
    `atomic_promote(temp_dir, final_dir)` (cross-device guard via
    `os.stat(...).st_dev` comparison; `os.replace`-based rename; wraps
    `OSError` and missing-temp into `MaterializeError`) and
    `mark_failed(temp_dir, exc, stage)` (writes a `FAILED` JSON marker
    with stage, exception type/message/traceback, and ISO-8601 UTC
    timestamp; no-ops if `temp_dir` was already promoted/cleaned).
    Cross-device detection is wrapped in a `_device_id` helper so the
    guard is testable without a real multi-filesystem setup.
  - `tests/unit/test_atomic.py` covers success path (temp gone, final
    populated), missing-temp failure, cross-device refusal (with
    monkey-patched `_device_id`), `os.replace` `OSError` wrapping,
    `mark_failed` JSON shape and required fields, no-op on missing
    temp, and an end-to-end `atomic_promote` failure followed by
    `mark_failed` leaving temp + `FAILED` marker without ever touching
    the final cache path.

## [0.2.8] - 2026-05-07

### Added

- Cache layout helpers (Story B.g):
  - `src/datarefinery/cache/layout.py` exposes path helpers
    (`instances_root`, `instance_dir`, `tmp_dir`, `manifest_path`,
    `dataset_dir`, `fitted_stats_dir`, `report_dir`) producing the
    documented `<cache-root>/instances/<recipe16>/<input16>/<seed>/`
    shape (with in-flight runs under `<cache-root>/instances/.tmp/`).
    Final hashes truncate to 16 chars per `CacheKey`.
  - `make_run_id()` returns `<utc_iso_compact>-<8hex>` (e.g.
    `20260507T143022Z-deadbeef`); lex-sortable to the second with an
    8-hex random suffix for collision resistance under concurrent calls.
  - `tests/unit/test_cache_layout.py` covers each helper's path shape,
    `instance_dir` truncation invariant, `make_run_id` format, sortable-
    by-timestamp invariant, and uniqueness under both 2000-id sequential
    bursts and 8-thread concurrent generation.

## [0.2.7] - 2026-05-07

### Added

- Cache identity (Story B.f, FR-4):
  - `src/datarefinery/cache/__init__.py`,
    `src/datarefinery/cache/identity.py`. Frozen `CacheKey` dataclass
    (`recipe_hash`, `input_hash`, `seed`) with `.short` returning the
    first 16 hex characters of `recipe_hash` for cache-directory
    sharding. Full SHA-256 hashes are stored in `manifest.json`
    (per `project-essentials.md` "Cache identity is the
    reproducibility contract").
  - `compute_cache_key(recipe, raw_input_hashes, seed)` SHA-256s
    `to_canonical_bytes(recipe)` for `recipe_hash`, then SHA-256s the
    sorted-by-name concatenation of per-source content hashes
    (`name=<hex>;` pairs) for `input_hash`. Order-independent: dict
    insertion order does not affect `input_hash`.
  - `tests/unit/test_cache_identity.py` covers identity stability,
    sensitivity to recipe / input / seed changes, order-independence,
    name-vs-content-hash collision resistance, recipe-hash-matches-
    canonical-bytes-SHA-256 internal consistency, and hex-format
    invariants.

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
