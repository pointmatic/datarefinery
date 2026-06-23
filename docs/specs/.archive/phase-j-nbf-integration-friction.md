# Phase J — NbFoundry integration spike friction list

> **Status:** spike deliverable for Story J.b (Phase J), authored
> 2026-06-11 against DataRefinery v0.20.0 (in-progress; v0.19.0 + the
> v0.20.0 work in progress on `main`). Throwaway artifact — each item
> below is a candidate for a separate Phase J follow-up story (or a
> contract-doc clarification absorbed by Story J.c), to be triaged by
> the developer at the J.b approval gate.

## Spike setup

- **Scratch dir:** `/tmp/dr-nbf-spike/` (synthetic 2-class × 6-image
  ImageFolder, scaffolded recipe, isolated `.cache/`).
- **Notebook:** `/tmp/dr-nbf-spike/datarefinery_demo.py` (Marimo 0.23.9
  script — six cells; library path + CLI subprocess path).
- **Validation:** `marimo export script` confirms the notebook
  parses + serializes cleanly; live in-browser rendering of `rich`
  output requires developer eyeballs (see § "Needs visual confirmation"
  below). Library cells were exercised end-to-end via
  `python /tmp/dr-nbf-spike/lib_exercise.py` and produced expected
  results; CLI cells were exercised by repeating the same subprocess
  invocations the cell would make.

## Categorization

Each item is tagged with one or more of:

- **CONTRACT** — the cross-repo contract doc (Story J.c
  `nbfoundry/vendor-dependency-spec.md`) should pin a behavior; no code
  change required.
- **CODE** — a code change is the right fix.
- **DOC** — a recipe-authoring / README clarification is the right fix.
- **ENV** — environmental issue (not DR's repo); record for posterity,
  do not act on it from DR.

---

## Findings

### F1. `--log-target` is a documented no-op stub. **CODE | CONTRACT**

The story task explicitly highlighted log-target redirection as a
critical NbF surface. The CLI accepts `--log-target` and the
`RuntimeConfig` resolves it from env + flag — but
[`cli/app.py:80`](../../src/datarefinery/cli/app.py#L80) calls it
"reserved no-op stub" and nothing in
[`logging.py`](../../src/datarefinery/logging.py) consumes the value.
The JSON `StreamHandler` is unconditionally bound to `sys.stderr`. So a
notebook user passing `--log-target=/tmp/dr.jsonl` sees the file never
get created, no error, no warning.

**Reproducer:** `python -m datarefinery --log-target=/tmp/dr-log.jsonl
materialize <recipe>` — `/tmp/dr-log.jsonl` is not created and no
warning is emitted.

**Recommendation:** prioritize implementing `--log-target` for Phase J.
The path forward is a small one — `get_logger` already attaches the
`StreamHandler`; consuming `RuntimeConfig.log_target` to swap that for a
file handler (or to `tee` to both) is a localized change. Until it
ships, document the no-op status loudly in the contract doc (J.c)
under "Failure modes NbFoundry SHOULD detect → silent log-target".

### F2. No machine-readable output format. **CODE | CONTRACT**

Every CLI command renders its result as a `rich.Table` written to
stdout (with Unicode box-drawing glyphs, optional ANSI color, terminal-
width-dependent layout, and field truncation at column boundaries —
see F3). There is no `--json` / `--format=json` flag. A notebook cell
parsing CLI output for state (e.g. "did validate pass?", "what's the
recipe hash?", "how many records per split?") has only the exit code
and screen-scraped table cells to work with.

The cleanest workaround NbF can adopt today is "use the library API,
never the CLI subprocess" — but that re-couples the notebook to DR's
Python version + plugin discovery, defeating the CLI-as-stable-API
boundary that NbF would otherwise benefit from.

**Recommendation:** add a top-level `--json` (or `--output=json`)
option that swaps rich rendering for a `json.dump(...)` of the
verb-result dataclass to stdout. Every verb already builds a
structured result (`ValidationReport`, `StatusReport`, `Manifest`,
`InspectionView`); the JSON path is one mode-switch at the renderer.
Until it ships, document this as a Phase J cross-repo gap and have
NbF's contract doc (J.c) instruct consumers to call the library API
for state and the CLI only for "run with isolation" use cases.

### F3. CLI table fields are silently truncated. **CODE | CONTRACT**

`rich.Table` auto-width truncates cell contents with `…` when output
exceeds terminal width (default 80 cols when stdout is non-TTY).
Observed truncations on the spike's scratch recipe:

- Validate: descriptor column shortens
  `stats_from_instance_mutually_exclusive_with_fit_source` →
  `stats_from_instance_mutually_exclusive_w…` and
  `featurization_output_field_loader_collis…`.
- Materialize / status: `recipe_hash` (64 hex) is truncated to
  ~52 chars + `…`. The full hash is unrecoverable from stdout.

A notebook user piping CLI output into a cell can't read the recipe or
input hash back. (The full hashes live in `manifest.json`, which is
the contract-doc-pinned canonical surface — but discoverability is
poor: nothing in the CLI output tells the user "the truncated value is
not authoritative; read `<instance>/manifest.json`".)

**Recommendation:** orthogonal to F2 — once `--json` lands, this stops
mattering for parsing. For human-readable CLI, consider either (a)
suppressing rich truncation on hash columns (force full width) or (b)
appending a footer line like `Full hashes: see <instance>/manifest.json`.

### F4. `--quiet` and `--verbose` are accepted but ignored. **CODE**

[`cli/app.py:113-120`](../../src/datarefinery/cli/app.py#L113-L120)
declares `--quiet` / `--verbose` and stuffs them into the typer context
state, but no command reads `state["quiet"]` or `state["verbose"]`.
The validate table renders identically with or without `--quiet`.

For NbF specifically, `--quiet` is the obvious knob to suppress the
"is this a TTY?" rich rendering and emit one-line confirmations
suitable for log-and-continue. Its current no-op-ness is misleading
(the flag is documented in `--help` as suppressing non-essential
output).

**Recommendation:** either wire the flag through every command's
renderer (preferred — straightforward, no contract surface) or remove
it from the global callback until it can be implemented. Don't ship a
documented flag that does nothing.

### F5. Prefer `python -m datarefinery` over the bare console-script form for subprocess invocations. **CONTRACT**

During the spike the bare `datarefinery` console script failed on this
machine (the shim under `.pyve/envs/root/conda/bin/datarefinery`
pointed at a Python interpreter that had been removed by an env
recreate, surfacing as `bad interpreter: No such file or directory`).
The underlying cause is a Pyve toolchain issue that the Pyve maintainer
has flagged for upstream fix (Pyve v3.0.6 ships the imminent bugfix
class; a follow-up release will land the init-semantics correction
that prevents the env-recreate-leaves-stale-shims shape entirely). So
this is **not a permanent class** of NbF-environment failure — it will
recede as Pyve consumers upgrade — but the **recommendation below
stands regardless**, because `python -m` is resilient to *any*
shim-resolution issue (PATH ordering, pyenv shim staleness, conda
activation race, virtualenv-in-virtualenv shadowing, etc.), not just
this one.

`python -m datarefinery <verb>` invokes the package via
`datarefinery/__main__.py` and sidesteps the entry-point shim entirely.
The CLI behavior is byte-identical between the two invocation forms.

**Recommendation:** **CONTRACT** — the J.c contract doc should
recommend NbF subprocess invocations use `[sys.executable, "-m",
"datarefinery", ...]` rather than `["datarefinery", ...]`. One sentence
in the "CLI invocation" subsection; it shields NbF from shim-
resolution edge cases at zero cost and is robust to whichever Python
environment manager the notebook is running under.

### F6. `discover_plugins` strict-rejects duplicate entry-point distributions. **CODE | DOC**

Both `datarefinery 0.3.0` (legacy distribution name from before the
PyPI rename) and `ml-datarefinery 0.15.0` (current distribution) can
coexist in a single environment — and currently do, on the spike's
main `.venv/`. Both register identical entry points under the
`datarefinery.plugins` group; `discover_plugins` (`plugins/discovery.py:90`)
sees the same plugin name twice and raises
`PluginError("duplicate plugin name: 'image_classification'")`. The
error message names the plugin but **does not name the two
distributions** providing it, leaving the user to grovel
`pip list | grep -i datarefinery` to diagnose.

This is a real NbF-environment failure mode: a user `pip install
ml-datarefinery` on top of an env that already has the legacy
`datarefinery` (or vice-versa) gets a hard CLI/library refusal with a
confusing error.

**Recommendation:** the error message in `_register` should name the
contributing distributions (read `entry.dist.metadata["Name"]` +
version and surface both in the message). Optionally also collapse
identical-`PLUGIN` registrations to a single entry rather than
erroring (the loaded object is the same Python object when both
distributions point at the same module). Updating the contract doc
(J.c) to document this failure mode is a stopgap; the error-message
fix is the long-term answer.

### F7. The CLI scaffolds `schema_version: 1`. **CODE | DOC**

[`scaffolder/init.py`](../../src/datarefinery/scaffolder/init.py) (via
`datarefinery init`) emits recipes pinned to `schema_version: 1`. The
loader migrates them to v2 on read, so it works — but a new NbF user
running `init` and looking at the output may reasonably assume v1 is
"current." This is the I.h "scaffolder v2 grand sweep" item in
[`stories.md § Future`](stories.md), already tracked; recording it here
so the J.c contract doc can name v2 explicitly as the current shape
and point at the migration path.

**Recommendation:** no new story — the Future entry covers it. The
J.c contract doc should reference the v2 shape and the loader-side
auto-migration; J.b output here is to flag that the disconnect is
real-world observable.

### F8. `inspect` doesn't accept a recipe argument — but `inspect --view` is undocumented. **DOC**

`python -m datarefinery inspect <recipe.yaml>` works (it resolves the
recipe to the bound instance via the same `status` mechanism). But
`--view` is exposed in the CLI signature as an optional string with
no documented vocabulary. Calling `inspect` without `--view` produced
the "Records per split" + "Sample records" tables; the spike didn't
discover what other view names exist or what they render. NbF would
need a documented vocabulary to drive notebook-side selectors.

**Recommendation:** the J.c contract doc should enumerate the `--view`
values and the InspectionView fields each populates. (The library
analog is `dr.inspect(view=...)`, which has the same opacity from the
NbF-vendor perspective.)

### F9. Marimo's "single-definition" rule constrains repeated subprocess patterns. **CONTRACT**

Marimo enforces single-definition-per-symbol across cells: re-using
`res = subprocess.run(...)` in two cells raises
`MultipleDefinitionError`. NbF authors of "exercise five CLI verbs in
five cells" notebooks must distinct-name every binding
(`res_validate`, `res_status`, ...). This is a Marimo constraint, not
DR's — but the J.c contract doc should call it out as a notebook-shape
guidance so NbF's documentation matches the constraint.

**Recommendation:** **CONTRACT** — one paragraph in J.c under
"Notebook-output ergonomics" naming the constraint and the
distinct-name convention.

### F10. Rich progress bars in subprocess are silent for fast runs. **CONTRACT**

The materialize verb uses `rich.Progress(... transient=True)`, which
auto-detects non-TTY stdout and (on the spike) emitted nothing visible
for a 0.16-second run on 12 records. For a long-running materialize on
real data, the captured stdout would show progress-line noise mixed
with the final summary table. NbF either wants (a) `--no-progress` to
turn it off cleanly in subprocess contexts, or (b) the library API
(which uses the `progress_callback` parameter and gives NbF total
control over rendering).

**Recommendation:** the J.c contract doc should document the library
`progress_callback` parameter as the right path for notebook progress
UX and direct NbF away from CLI subprocess for the materialize verb
when the recipe is large. A `--no-progress` flag would be a small
additional code change, but the library path is the bigger lever.

### F11. Top-level `materialize()` discards the `DataRefinery` instance + cache-hit signal. **CONTRACT**

The convenience entry point
`from datarefinery import materialize` returns an `Instance` but
constructs and discards an internal `DataRefinery`. So a caller cannot
ask "was that a cache hit?" — the only way to know is to use
`DataRefinery.from_recipe(...).materialize()` and read `dr.last_run.cache_hit`.

This is fine if documented: for NbF, the contract is "use
`DataRefinery.from_recipe(...).materialize()` whenever you care about
cache-hit signaling; the top-level `materialize()` is a one-shot
convenience." J.c's contract doc should pin this.

**Recommendation:** **CONTRACT** — one bullet in the "Library entry
points" subsection.

### F12. Default `cache_root` is `data/` relative to cwd. **CONTRACT**

[`RuntimeConfig`](../../src/datarefinery/core/config.py) defaults to
`cache_root=Path("data")` (relative). A notebook executed from
`~/my-notebooks/` will materialize into `~/my-notebooks/data/instances/...`
unless the user sets `--cache-root` or `DATAREFINERY_CACHE_ROOT`. Not
broken — but surprising for notebook authors who expect a global
default cache like `~/.cache/datarefinery/`.

**Recommendation:** **CONTRACT** — document the default explicitly in
J.c so NbF can prompt notebook users to configure `cache_root` early.
(A code change to use `platformdirs.user_cache_dir(...)` would also be
defensible but is a larger contract shift; flag for separate scoping.)

## Needs visual confirmation (developer eyeballs)

The following could not be verified programmatically in this spike;
they need a live Marimo browser session to confirm:

- **V1.** How do rich-rendered ANSI escape sequences look in a Marimo
  markdown cell? My expectation: they render as literal text (Marimo
  is not an ANSI terminal). If true, this elevates F2 (machine-
  readable output) from "nice-to-have" to "required for the CLI path
  to be ergonomic in notebooks at all."
- **V2.** Do rich's Unicode box-drawing glyphs render correctly under
  Marimo's default font stack? Likely yes (UTF-8 throughout) but worth
  a quick check.
- **V3.** Does `marimo edit /tmp/dr-nbf-spike/datarefinery_demo.py`
  surface the library cells as reactive, or do they re-execute every
  time `dr` changes? The notebook is written assuming Marimo's normal
  dataflow — a quick walkthrough at J.b's gate would confirm the
  shape is right.

## Triage suggestion at the J.b approval gate

| Item | Severity | Path |
| --- | --- | --- |
| F1 log-target no-op | High | New code story in Phase J |
| F2 no `--json` flag | High | New code story in Phase J |
| F4 `--quiet` / `--verbose` no-op | Medium | Patch as part of F2 work or its own story |
| F6 duplicate-plugin error msg | Medium | Small code story; merge with F1 cluster |
| F3 hash-column truncation | Low | Resolves when F2 lands; defer |
| F10 `--no-progress` | Low | Resolves once contract doc points at `progress_callback`; defer |
| F5, F7, F8, F9, F11, F12 | N/A | Absorbed by J.c contract-doc authoring |

The high-severity items (F1, F2, F4, F6) plus the Marimo-eyes
verification (V1) are what should drive J.c's contract doc; without
those settled, J.c would document aspirational ergonomics rather than
real ones.
