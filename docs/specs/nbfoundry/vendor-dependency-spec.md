# DataRefinery ↔ NbFoundry dependency contract

> **Status:** authoritative cross-repo contract (Story J.c, in-progress v0.20.0). Pre-production: this document may evolve as NbFoundry adoption surfaces gaps. Post-production: it becomes a stability contract — changes follow the schema-version-bump + migration ceremony in [`project-essentials.md` § "Cache identity is the reproducibility contract"](../project-essentials.md).
>
> **Authoring basis (2026-06-11).** Stood up against current DataRefinery v0.20.0 source after the Story J.b NbFoundry integration spike. Friction items absorbed from [`phase-j-nbf-integration-friction.md`](../phase-j-nbf-integration-friction.md) are cross-referenced inline as `(F# from J.b spike)`. Items marked **forward-declared** target separate Phase J follow-up stories not yet authored; the inline cross-reference names the friction-list entry that motivates each.
>
> **Round 3 addition 2026-06-12 (Story J.k).** Added § "Disk-loader vs. library-records Featurization asymmetry" under § Library entry points, documenting **F4** from the [J.d MF integration spike](../phase-j-mf-integration-friction.md): a `Featurizations` op whose `output_field` the loader pre-stamps validates on the disk path (check 23 exempts loader-stamped fields) but can hit the unconditional runtime collision guard when records are constructed manually via the library API. Documentation-only — it pins existing behavior and changes no code. (F4 lands here rather than in the MF spec because the library-records path is NbFoundry's home; the MF spec's Round 3 note records the cross-reference.)
>
> **2026-06-13 (Story J.l).** Added § "Top-level `resolve_instance()` convenience" under § Library entry points: the blessed instance locator, a facade over `DataRefinery.status()`, plus the "don't reimplement the cache key" rule (cross-referencing the MF spec's new § "Resolving a materialized instance"). Additive library surface; no code/shape change beyond the new function + top-level re-exports.

## Overview

This document is the **cross-repo contract surface** between DataRefinery (the data-pipeline producer + library + CLI tool) and NbFoundry (the Marimo-based notebook framework that uses DataRefinery as both a library inside cells and a CLI subprocess driven from cells).

Unlike the [ModelFoundry contract](../modelfoundry/vendor-dependency-spec.md), which pins the **materialized-instance shape** (recipe model, manifest, on-disk dataset, report), this contract pins the **interaction surface**:

- The **library entry points** NbFoundry consumers may import into a notebook cell.
- The **CLI commands** NbFoundry consumers may invoke as subprocesses from notebook cells, including exit-code semantics and the messages NbF parses.
- The **notebook-output ergonomics** that determine whether DataRefinery output composes cleanly with Marimo's reactive-cell rendering model.

It does **not** re-document the materialized-instance shape — that remains the MF spec's domain. NbF consumers who need to read a materialized instance bind against the MF spec for those surfaces.

Out of scope here: NbFoundry's notebook-compilation APIs, exercise-block emission, and `learningfoundry` integration (all live in NbFoundry's repo); DataRefinery's internal implementation details (live in [`tech-spec.md`](../tech-spec.md) and [`features.md`](../features.md)).

## Library entry points

Importable from the top-level `datarefinery` package ([`src/datarefinery/__init__.py`](../../../src/datarefinery/__init__.py)):

```python
from datarefinery import (
    DataRefinery,   # the class — load-and-run a recipe
    Instance,       # accessor over a materialized instance directory
    materialize,    # one-shot convenience (no cache-hit signal)
    __version__,    # package version string
)
```

The `__all__` set is closed: only the four names above are guaranteed stable. NbFoundry SHOULD bind against the top-level imports rather than deeper paths (`datarefinery.core.datarefinery.DataRefinery`, etc.); the inner paths are subject to internal refactor.

### `DataRefinery` class — the cache-aware path

```python
class DataRefinery:
    @classmethod
    def from_recipe(
        cls,
        recipe_path: Path,
        config: RuntimeConfig | None = None,
        variant: str | None = None,
        seed: int | None = None,
    ) -> DataRefinery: ...

    # Read-only state
    recipe: Recipe                          # property; variant-overlaid
    plugin: Plugin                          # property
    seed: int                               # property; resolved
    variant: str | None                     # property
    config: RuntimeConfig                   # property
    last_run: RunnerResult | None           # property; None until materialize()

    # Verbs
    def validate(self) -> ValidationReport: ...
    def materialize(
        self,
        *,
        raw_records: Sequence[Mapping[str, Any]] | None = None,
        raw_input_hashes: Mapping[str, str] | None = None,
        stop_after: str | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> Instance: ...
    def status(self) -> StatusReport: ...
    def inspect(
        self,
        instance_path: Path | None = None,
        view: str | None = None,
    ) -> InspectionView: ...
    def report(self, instance_path: Path) -> Instance: ...
    def clean(self, selector: CleanSelector, *, force: bool = False) -> CleanReport: ...
    def export(self, *, sink_names=None, raw_input_hashes=None, raw_records=None) -> ExportResult: ...
    def cache_key(self, raw_input_hashes: Mapping[str, str]) -> CacheKey: ...

    @staticmethod
    def check(config: RuntimeConfig | None = None) -> CheckReport: ...
```

**Construction.** `from_recipe(path)` loads + validates the recipe exactly once (validation report memoized; subsequent `.validate()` calls return it without re-running). Variant overlay is applied *before* validation, so what `.validate()` reports is what `.materialize()` will execute. Passing `config=None` resolves a `RuntimeConfig` with defaults from environment variables.

**`materialize()`.** Inflates the recipe's `Input` sources from disk by default; library callers MAY pass `raw_records` + `raw_input_hashes` to bypass disk loading. Returns a loaded `Instance`. Sets `self.last_run` to the `RunnerResult` (which exposes `.cache_hit: bool`).

**`progress_callback`.** Receives one call per stage entry with the stage name (one of `pipeline.runner.STAGE_NAMES`). NbFoundry SHOULD use this rather than the CLI's `rich` progress bar to drive notebook progress UX — the callback gives the notebook total control over rendering inside a Marimo cell (F10 from J.b spike).

**Cache-hit signaling.** After `dr.materialize()`, read `dr.last_run.cache_hit: bool`. The top-level `materialize()` convenience function discards the `DataRefinery` instance and therefore the cache-hit signal — use it only for one-shot flows where the signal is not needed (F11 from J.b spike).

### `Instance` accessor

```python
@dataclass(frozen=True)
class Instance:
    path: Path
    manifest: Manifest                   # see MF spec for the shape
    recipe: Recipe                       # the canonicalized recipe
    fitted_statistics: FittedStatistics  # lazy reader, see MF spec
    report_path: Path                    # absolute path to report.md
    is_partial: bool                     # mirrors manifest.is_partial

    @classmethod
    def load(cls, path: Path) -> Instance: ...
    def render_report(self, *, plugin: object | None = None) -> None: ...
```

`Instance.load(path)` reads `manifest.json` + `recipe.json`, asserts the recipe canonicalizes to `manifest.recipe_hash`, and constructs a lazy `FittedStatistics` view (no file I/O on construction). Field shapes (`Manifest`, `FittedStatistics`) are pinned by the MF spec.

### Top-level `materialize()` convenience

```python
def materialize(
    recipe_path: Path,
    *,
    config: RuntimeConfig | None = None,
    variant: str | None = None,
    seed: int | None = None,
) -> Instance: ...
```

One-shot loader → validator → runner → instance. **Discards** the intermediate `DataRefinery`, so the cache-hit signal is lost. Use when the notebook cell only needs the materialized `Instance` and doesn't care whether the run hit cache.

### Top-level `resolve_instance()` convenience

```python
def resolve_instance(
    recipe_path: Path | str,
    *,
    cache_root: Path | str | None = None,
    seed: int | None = None,
    variant: str | None = None,
) -> StatusReport: ...
```

Locates the materialized instance for a recipe **without running the pipeline** — a thin facade over `DataRefinery.from_recipe(...).status()` returning the same `StatusReport` (`cache_status` ∈ `hit`/`miss`/`corrupt`, `instance_path`, full `cache_key`, `manifest` on hit). Use it from a notebook cell to answer "is this recipe already materialized, and where?" before deciding whether to call `materialize()`. Both `resolve_instance` and `StatusReport` are importable from the top-level `datarefinery` package. Like the disk loader, it hashes the recipe's declared inputs, so the inputs must be present.

**Do not recompute the instance path / cache key by hand** — see the MF spec § "Resolving a materialized instance" for the rationale (a hand-rolled key silently breaks after any DataRefinery canonical-bytes change). `resolve_instance()` / `status()` is the only supported resolver. *(Story J.l, 2026-06-13.)*

### Disk-loader vs. library-records Featurization asymmetry

A recipe that passes validation through the **disk path** (the loader inflates records from `Input.sources`) can still raise at materialize time when the **same recipe** is driven via the library API with **manually constructed** records — specifically for `Featurizations` whose `output_field` is a field the loader normally pre-stamps.

Validator **check 23** exempts loader-stamped fields (`record_id`, `image`, `path`, `label`, `partition`) from the `output_field`-collision rule, because on the disk path those fields are produced by the loader *before* the Featurization runs, and the op legitimately overwrites / derives them. But the runtime collision guard in [`pipeline/stages/featurizations.py`](../../../src/datarefinery/pipeline/stages/featurizations.py) is unconditional: it raises `MaterializeError` if **any** record already carries `output_field` when the op runs. So a notebook cell that builds records by hand and supplies one already populated with the Featurization's `output_field` will hit the runtime check even though the recipe validates.

**Guidance for NbFoundry notebook authors:** when supplying records manually to the library API, either (a) rely on the loader to stamp the field — i.e. drive materialization from `Input.sources` via `DataRefinery.from_recipe(...).materialize()` rather than hand-built records — or (b) remove the Featurization op (and the pre-populated field) when constructing records yourself. *(F4, pinned in Round 3 — see header; this documents existing behavior, it does not change the collision-check.)*

## CLI commands

The installed console-script is `datarefinery`, but NbFoundry SHOULD invoke the CLI as `[sys.executable, "-m", "datarefinery", ...]` rather than `["datarefinery", ...]`. The `-m` form invokes [`datarefinery/__main__.py`](../../../src/datarefinery/__main__.py) directly and sidesteps console-script shim resolution (PATH ordering, pyenv shim staleness, conda activation race, virtualenv-in-virtualenv shadowing, env-recreate-leaves-stale-shim, etc.). The two forms have byte-identical CLI behavior; the `-m` form is portably resilient (F5 from J.b spike).

### Verb vocabulary

| Verb | Purpose | Returns |
|---|---|---|
| `check` | FR-18 environment soundness probe (no recipe required). | exit 0 / 2 |
| `validate` | FR-2 validation against a recipe. | exit 0 (pass) / 1 (fail) |
| `init` | FR-17 deterministic scaffolder. v1: `image_classification` only. | exit 0 |
| `materialize` | FR-3 end-to-end pipeline run. | exit 0 |
| `status` | FR-19 instance summary or recipe→instance resolution. | exit 0 |
| `report` | FR-15 re-render `report.md` / `drift.json` / visualizations from persisted state. | exit 0 |
| `inspect` | FR-20 read-only views of a materialized instance. | exit 0 |
| `clean` | FR-21 cache cleanup. | exit 0 |
| `export` | Story I.f re-run sinks against an existing instance without re-materializing. | exit 0 |

### Exit-code contract

Pinned in [`cli/_exit_codes.py`](../../../src/datarefinery/cli/_exit_codes.py):

| Code | Meaning |
|---|---|
| 0 | Success. |
| 1 | User/recipe error — `RecipeError`, `ValidationError`, `ContractError`, `MaterializeError`. |
| 2 | System error — `PluginError`, `CacheError`, uncaught. |
| 130 | `KeyboardInterrupt` / SIGINT. |

NbFoundry SHOULD bind against the exit code as the **machine-readable signal**. Treat exit 0 as success, exit 1 as a recipe-level error the notebook user should fix, exit 2 as an environmental error the user SHOULD route to the toolchain owner.

### Global options

Resolved on the typer root callback ([`cli/app.py`](../../../src/datarefinery/cli/app.py)):

| Flag | Env var | Effect |
|---|---|---|
| `--cache-root` | `DATAREFINERY_CACHE_ROOT` | Root for `<cache>/instances/...`. Default: `data/` relative to cwd (F12). |
| `--log-level` | `DATAREFINERY_LOG_LEVEL` | Logger threshold (`DEBUG` / `INFO` / `WARNING` / ...). |
| `--log-target` | `DATAREFINERY_LOG_TARGET` | **Forward-declared (Phase J).** Today a documented no-op stub (F1 from J.b spike); accepts the value silently. NbFoundry MUST NOT depend on this redirecting output until the Phase J follow-up story lands. |
| `--plugin-path` | `DATAREFINERY_PLUGIN_PATH` (PATH-style) | Extra plugin discovery directory; repeatable. |
| `--workers` | `DATAREFINERY_WORKERS` | Process-pool worker count. |
| `--seed` | — | Override the recipe-declared seed (changes cache identity). |
| `--variant` | — | Recipe variant overlay applied before validation. |
| `--no-color` | — | Disable ANSI color in `rich` output. **Wired and honored.** |
| `--quiet` / `-q` | — | **Forward-declared (Phase J).** Accepted into context but no command consults the value today (F4 from J.b spike). |
| `--verbose` / `-v` | — | **Forward-declared (Phase J).** Same status as `--quiet`. |
| `--version` | — | Print package version and exit. |

### Error-message contracts NbF MAY parse

The CLI's catch-all entry point [`main_entry()`](../../../src/datarefinery/cli/app.py) renders an exception by class name in a `rich` `Panel` titled with the class name, to stderr. The pattern is:

```
╭───────────── PluginError ─────────────╮
│ <single-line message from str(exc)>   │
╰───────────────────────────────────────╯
```

NbFoundry MAY parse the panel title (`PluginError`, `ValidationError`, `RecipeError`, `MaterializeError`, `ContractError`, `CacheError`) as the exception class name for routing — these are stable. The message text inside the panel is informational; NbF SHOULD NOT pattern-match on it.

For machine-readable error output beyond the exit code + class name, see § "Forward-compatibility expectations" (`--json` is forward-declared and tracked under Phase J Story TBD per F2 from J.b spike).

### Verb-specific surfaces

- **`init`** — accepts `--input <dir>`, `--output <yaml-path>`, `--plugin {image_classification}`, `--enhance` (requires `[llm]` extra). The scaffolded recipe is written to `--output` with `schema_version: 1` today (F7 from J.b spike — auto-migrated to v3 by the loader; the canonical persisted shape inside materialized instances is always the latest, v3). Stable for v1.
- **`validate`** — positional argument is the recipe YAML. Prints a numbered checks table (FR-2 #1–#25 today; new checks land in subsequent releases). Exit 0 if every check passes (warnings allowed), exit 1 if any fails.
- **`materialize`** — positional argument is the recipe YAML. Accepts `--stage <NAME>` for partial runs; valid stage names are `pipeline.runner.STAGE_NAMES`. Cache hits short-circuit before any temp-dir work.
- **`status`** — positional argument is either a recipe YAML (resolves cache identity from disk) or a materialized instance directory. Exit 0 in all cases including cache miss; corrupt instances print the `corrupt` label but still exit 0.
- **`inspect`** — positional argument is either a recipe YAML or an instance directory. Optional `--view <name>` selects an `InspectionView` sub-field. The `--view` vocabulary is not yet pinned here; NbFoundry consumers who need named views SHOULD use the library surface (`dr.inspect(view=...)`) and read the dataclass fields directly (F8 from J.b spike — Phase J Story TBD to pin the `--view` vocabulary as a CLI contract).

## Notebook-output ergonomics

This section pins the surfaces that govern how DataRefinery output composes with Marimo's reactive-cell model.

### stdout vs. stderr

- **stdout**: human-rendered `rich` output (tables, panels, progress). Goes to the terminal in a normal shell, captured by `subprocess.run(..., capture_output=True)` in a notebook cell. Contains Unicode box-drawing glyphs by default; ANSI color escapes are present unless `--no-color` is passed.
- **stderr**: JSON-line operational logging via `get_logger` ([`logging.py`](../../../src/datarefinery/logging.py)). One JSON object per line: `{"ts", "level", "logger", "stage", "op_id", "message", "extras"?, "exc_info"?}`. NbFoundry MAY tail stderr for structured progress signals without competing with the human-facing stdout rendering.

### `rich` output composition with Marimo

The CLI prints to stdout with terminal-aware `rich.Console`. Two properties matter for Marimo cell composition:

1. **ANSI color escapes** are emitted unless `--no-color` is passed. In a Marimo `mo.md(f"```\n{result.stdout}\n```")` rendering, ANSI escapes appear as literal text (Marimo is not an ANSI renderer). NbF notebook authors SHOULD pass `--no-color` for subprocess invocations whose stdout they intend to display.
2. **Box-drawing glyphs** (`┏━━┓┃ ┃┗━━┛`) are Unicode and render as text in any UTF-8 surface, including Marimo cells. They preserve the column alignment but are not parsable as structured data — downstream parsing should rely on the library API (or, when it lands, the `--json` mode).

### Progress UX

- **Library path** — pass a `progress_callback` to `DataRefinery.materialize(...)`. NbFoundry has total control over notebook progress rendering (Marimo progress widget, custom HTML, etc.).
- **CLI subprocess path** — `materialize` uses `rich.Progress(transient=True)`. In non-TTY contexts (`subprocess.run`) this auto-detects and either emits very little or nothing for fast runs. For long runs, raw progress-line bytes mix into the captured stdout. NbFoundry SHOULD prefer the library path whenever progress UX matters; the CLI subprocess path is the right shape for fire-and-forget runs (F10 from J.b spike).

### Marimo single-definition constraint

Marimo enforces single-definition-per-symbol across cells: re-using a binding name (e.g. `res = subprocess.run(...)`) in two cells raises `marimo._ast.errors.MultipleDefinitionError` at scaffold time. NbF notebook authors who invoke multiple CLI verbs SHOULD use distinct binding names per cell (`res_validate`, `res_status`, ...). This is a Marimo constraint, not DataRefinery's, but it shapes the notebook-author UX (F9 from J.b spike).

### `RuntimeConfig.cache_root` default

`RuntimeConfig` defaults to `cache_root=Path("data")` — a **relative** path. A notebook run from `~/my-notebooks/` produces `~/my-notebooks/data/instances/...`. NbFoundry SHOULD prompt notebook users to set an explicit `cache_root` (via `--cache-root`, `DATAREFINERY_CACHE_ROOT`, or passing `RuntimeConfig(cache_root=...)` into `DataRefinery.from_recipe`) early in the notebook flow so the cache lives in a predictable location (F12 from J.b spike).

## Schema-version coordination policy

NbFoundry SHOULD track DataRefinery's `datarefinery.recipe.loader.SUPPORTED_SCHEMA_VERSIONS` set (importable; v0.22.0+ ships `{1, 2, 3}` with `LATEST_SCHEMA_VERSION = 3`). The loader auto-migrates v1→v2→v3 on read; the persisted `recipe.json` inside a materialized instance is always the latest (v3) shape.

**Schema v2 → v3 (v0.22.0, Story J.n.3) — segmented recipe identity.** Cache identity moved from the flat canonical sha256 to a **segmented** hash; this is a **one-time pre-1.0 cache invalidation** (every instance re-materializes once). The recipe shape on disk is **unchanged** (segmentation is internal — the v2→v3 bootstrap stamps the version only, no field reshape), so NbFoundry — which drives the library/CLI rather than reading recipe internals — needs no binding changes beyond widening its tracked support set to include `3`. Full detail (segmented algorithm, `AudioSource` union) is in the MF spec § Cache-identity contract.

For NbFoundry's use cases — driving the library/CLI rather than reading recipe internals — the schema-version coordination obligation is much lighter than ModelFoundry's:

- Notebook cells that **read recipe fields** (e.g. for documentation rendering) SHOULD bind against v2 names; v1 inputs are auto-migrated before reaching the notebook.
- Notebook cells that **only invoke library/CLI verbs** are unaffected by schema-version changes — the CLI/library surface is independent of recipe-schema versioning.

ModelFoundry's [§ Schema-version coordination policy](../modelfoundry/vendor-dependency-spec.md) documents the recipe-side coordination in full; NbFoundry consumers who need the recipe internals SHOULD bind against the MF spec for that surface.

## Forward-compatibility expectations

- **Library API additions.** New methods on `DataRefinery` and new fields on `Instance` are additive; existing methods/fields remain stable. NbF SHOULD bind against the documented surfaces and ignore unrecognized future additions.
- **CLI verb additions.** New verbs are additive. New global options are additive. NbF SHOULD bind against documented verbs/flags and forward-decline unrecognized ones.
- **Verb-specific flag additions.** Additive within each verb. Documented flags remain stable; new flags surface in `--help` and `vendor-dependency-spec.md` updates.
- **Forward-declared options (today no-ops).** `--log-target`, `--quiet`, `--verbose` are documented above as forward-declared. NbFoundry SHOULD NOT depend on their behavior until the Phase J follow-up stories land. Their flag names are stable; only the behavior is pending.

## Failure modes NbFoundry SHOULD detect

These are the conditions a defensive NbFoundry notebook flow should surface to the user rather than ignore. The exact handling (prompt, hard error, fallback) is NbFoundry's choice.

### Library path

- **`PluginError: duplicate plugin name: '...'`** — the executing Python environment has two distributions providing the same plugin entry point (e.g. legacy `datarefinery` + current `ml-datarefinery` on the same `sys.path`). Today the error names the duplicate plugin but not the contributing distributions (F6 from J.b spike — Phase J follow-up story TBD). NbFoundry SHOULD intercept this error class and prompt the user to `pip list | grep -i datarefinery` and uninstall the legacy distribution.
- **`RecipeError` / `ValidationError`** raised by `from_recipe(...)` — the recipe failed schema or check-level validation. The error message names the specific issue.
- **`MaterializeError`** raised by `materialize(...)` — the pipeline failed mid-run. The error message names the failing stage.
- **`Instance.load` raises `MaterializeError`** when the manifest is missing or the persisted `recipe.json` does not canonicalize to `manifest.recipe_hash` — the instance directory is inconsistent.

### CLI path

- **Exit 2** — system error. NbFoundry SHOULD route these to the user as toolchain issues rather than recipe issues.
- **Exit 1** — user/recipe error. NbFoundry SHOULD route these as notebook-author-actionable (fix the recipe or its inputs).
- **Exit 130** — `KeyboardInterrupt`. NbFoundry SHOULD treat this as user-initiated cancellation.
- **Stale console-script shim** — invoking `["datarefinery", ...]` raises `OSError: [Errno 8] Exec format error` (or similar) when the console-script shim's shebang points at a removed Python interpreter. NbFoundry SHOULD always use the `[sys.executable, "-m", "datarefinery", ...]` form (see § "CLI commands" above) to  sidestep this entire class.

### Common to both

- **`schema_version` higher than NbF's known support range** — same rule as MF's: hard-error on NbF's side rather than coerce. Practical exposure is low for NbF (it does not read recipe internals deeply), but the rule applies if NbF does parse recipe content.

## Versioning and adoption

- DataRefinery ships **forward-declared contracts** at release time: each release's CHANGELOG enumerates contract changes (library API, CLI verbs, output ergonomics, manifest, recipe shape). NbFoundry tracks but does not block DataRefinery releases.
- NbFoundry adopts **on its own schedule**. A notebook that uses DataRefinery via `from datarefinery import ...` and `[sys.executable, "-m", "datarefinery", ...]` runs against whichever installed DataRefinery is on the notebook environment's `sys.path` / `PATH` — no version pin is enforced by DataRefinery.
- **Pre-production (v < 1.0)**: this document may change without a schema-version bump if no recipe/manifest/report bytes change. Documenting an existing surface in this file is not a contract change. The forward-declared items (`--log-target`, `--quiet`, `--verbose`, `--json`, error-message duplicate-distribution naming, CLI `--view` vocabulary) are tracked as Phase J follow-up stories; each lands with a CHANGELOG entry naming the new contract.
- **Post-production (v >= 1.0)**: this document becomes a stability contract. Changes to any contract surface go through the schema-version-bump + migration ceremony.

Cross-references:

- [`docs/specs/concept.md`](../concept.md) — DataRefinery's why.
- [`docs/specs/features.md`](../features.md) — feature requirements (FR-3 PipelineRunner, FR-18 check, FR-19 status, FR-20 inspect).
- [`docs/specs/tech-spec.md`](../tech-spec.md) — library + CLI implementation surfaces.
- [`docs/specs/project-essentials.md`](../project-essentials.md) § "Recipe / manifest / report shape changes need a cross-repo coordination check" — the cross-repo discipline rule.
- [`docs/specs/modelfoundry/vendor-dependency-spec.md`](../modelfoundry/vendor-dependency-spec.md)
  — the sibling contract pinning the materialized-instance shape.
- [`docs/specs/phase-j-nbf-integration-friction.md`](../phase-j-nbf-integration-friction.md)
  — the J.b spike friction list this document is authored against.
