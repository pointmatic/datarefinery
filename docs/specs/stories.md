# stories.md -- datarefinery (python)

This document breaks the `datarefinery` project into an ordered sequence of small, independently completable stories grouped into phases. Each story has a checklist of concrete tasks. Stories are organized by phase and reference modules defined in `tech-spec.md`.

Put **`vX.Y.Z` in the story title only when that story ships the package version bump** for that release. Doc-only or polish stories **omit the version from the title** (they share the release with the preceding code story, or use your project’s doc-release policy). **One semver bump per owning story** — extra tasks on the *same* story share that bump; see `project-essentials.md`. Semantic versioning applies to the package. Stories are marked with `[Planned]` initially and changed to `[Done]` when completed.

For a high-level concept (why), see [`concept.md`](concept.md). For requirements and behavior (what), see [`features.md`](features.md). For implementation details (how), see [`tech-spec.md`](tech-spec.md). For project-specific must-know facts, see [`project-essentials.md`](project-essentials.md) (`plan_phase` appends new facts per phase). For the workflow steps tailored to the current mode (cycle steps, approval gates, conventions), see [`docs/project-guide/go.md`](../project-guide/go.md) — re-read it whenever the mode changes or after context compaction.

---

## Version Cadence

Standard semantic versioning, with these conventions:

- **Every story belongs to a phase.** Bugfix stories included. No orphan stories.
- **Per-story bumping** (when a story owns its own release):
  - Bugfix or trivial change → **patch** (`vX.Y.Z+1`)
  - Feature or improvement → **minor** (`vX.Y+1.0`)
  - Breaking change → **major** (`vX+1.0.0`). Post-1.0 only, and only via the `plan_production_phase` mode, which negotiates with the developer about whether the breakage is substantively user-facing or technically-but-trivially breaking (example: a log-format change is technically breaking, but if logs aren't a core consumer capability, the developer may judge it minor or even patch).
- **Phase-bundling option:** a phase can run unversioned during work and ship a single release/tag at end-of-phase. Stories within the phase carry no version in their title; the phase's last story owns the bump (magnitude determined by the highest-impact change in the bundle).
- **No out-of-order implementation.** Story order in this file is the order of execution. If work order needs to change, **reorganize/renumber here first** — don't skip ahead and create version-number gaps.
- **Pre-1.0:** standard semver applies; version starts at `v0.1.0` (Story A.a).
- **Post-1.0:** every phase must go through `plan_production_phase` (the lighter `plan_phase` is pre-1.0 only). Major bumps only happen through that mode's negotiation step.

This is the authoritative cadence rule. **Do not extrapolate the bump magnitude from `pyproject.toml`'s current version** — re-read this section whenever you're about to assign a version to a story.

---

## Phase J: ModelFoundry + NbFoundry Integration

Phase J wires DataRefinery into its two downstream consumers — **ModelFoundry** (deep contract consumer of the recipe model, manifest, dataset on-disk layout, and report) and **NbFoundry** (notebook-side consumer using DataRefinery as a library + CLI inside Marimo cells). DataRefinery is a **vendor** to both consumers.

Phase J is a **catch-all** by design: it seeds the known gaps below and expects most additional stories to accrete reactively as real integration work surfaces friction. Stories phase-bundle a single end-of-phase release (target v0.20.0); no per-story version bumps.

Full plan: [`phase-j-modelfoundry-nbfoundry-integration-plan.md`](phase-j-modelfoundry-nbfoundry-integration-plan.md). Authoring context: [`phase-j-context-prompt.md`](phase-j-context-prompt.md).

---

### Story J.a: SampleData runtime — P-postpipeline + M-sidecar [Done]

**Disposition: feature addition.** Part of Phase J phase-bundle release (target v0.20.0). Closes FR-J-1.

Carries forward the [Story I.r.0 spike](.archive/stories-v0.16.2.md) recommendation: subset the materialized dataset per-split *after* the pipeline runs, emit a `sample/` sidecar alongside the full `dataset/`. `SampleSelector.kind` and `splits` are already in the model (Story I.r); this story implements the runtime that honors them.

First task is a 15-minute re-confirm that P-postpipeline + M-sidecar is still the right call against current evidence — if the spike's framing has aged out, open a small re-spike (Story J.a.1) before continuing.

**Tasks:**

- [x] Re-confirm P-postpipeline + M-sidecar against current consumer-spec evidence. If unchanged, proceed; if it has aged out, open J.a.1 spike. Confirmed unchanged: MF binds against `dataset/<split>.jsonl` (vendor-dependency-spec.md), NbF has no `SampleData` reference yet, Phase J plan independently restates the same shape; `per_class` placement constraint (needs final labels) still rules out P-input.
- [x] Add new pipeline stage [`src/datarefinery/pipeline/stages/sample_data.py`](../../src/datarefinery/pipeline/stages/sample_data.py), sequenced after splits. Inputs: per-split record iterables + resolved `SampleDataSection`. Outputs: per-split sampled record iterables + a `SampleResult`.
- [x] Implement `kind: uniform` — random subset of `n` (or `fraction`) records per selected split, seeded reproducibly via `pipeline.workers.per_record_seed`-style derivation. Per-record-seed ranking ⇒ invariant to input ordering / worker count / scheduling.
- [x] Implement `kind: per_class` — stratified subset of `n` records per class label per selected split; reads `Labels.field` on the final per-record dict. Reject (at runtime) recipes whose final records lack the label field — error names the split and missing-field count.
- [x] Implement `splits` honoring — sample only the listed splits; default to all defined splits when unset.
- [x] Emit `sample/<split>.jsonl` (and per-record PNG sidecars under `sample/<split>/images/` where the source records carry sidecar images) inside the atomic temp-then-promote unit alongside `dataset/`, `fitted_statistics/`, `report/`. New layout helper [`cache.layout.sample_dir`](../../src/datarefinery/cache/layout.py).
- [x] Add `class SampleManifestEntry` and `Manifest.sample: SampleManifestEntry | None = None` in [`src/datarefinery/pipeline/manifest.py`](../../src/datarefinery/pipeline/manifest.py): `{ "selector": <echo>, "record_counts": { "<split>": <int>, … } }`. Full-manifest site emits when recipe declares `SampleData:`; partial-manifest site leaves the field at its default `None` (a partial run that stops mid-pipeline cannot reach the post-pipeline stage).
- [x] Update validator **check 16** wording: "subset of the declared input" → "subset of the prepared dataset" (placement decision flips the spec wording). Docstring on `check_16_sample_data_strict_subset` now names the post-pipeline runtime ([`recipe/validator.py`](../../src/datarefinery/recipe/validator.py)). Selector-coherence enforcement unchanged.
- [x] Unit tests in [`tests/unit/test_sample_data_stage.py`](../../tests/unit/test_sample_data_stage.py): `uniform` + `per_class` runtime; `splits` honoring; reproducibility (same seed → identical, different seed → different, input-order invariance); manifest round-trip (with and without `sample`); missing-label-field runtime refusal; seed-precedence resolver. 19 tests, all pass.
- [x] Integration test in [`tests/integration/test_sample_data.py`](../../tests/integration/test_sample_data.py): end-to-end fixture recipe with `SampleData:` declared — `dataset/` unchanged, `sample/train.jsonl` contains the expected per-class counts, `manifest.sample` is well-formed, no-SampleData recipes leave `sample` as `None` and skip the `sample/` directory, sample JSONL is byte-identical across runs.
- [x] DOC: updated [`docs/guides/recipe-authoring.md` § SampleData](../guides/recipe-authoring.md) — replaced the "Runtime status (v0.18.0): not yet honored" callout with the v0.20.0 behavioral spec (uniform/per_class semantics, splits honoring, determinism, manifest entry, cross-repo pointer).
- [x] DOC: updated [`docs/specs/features.md`](features.md) FR-2 check #16 wording to "subset of the prepared dataset" + named the FR-J-1 runtime.
- [x] DOC: updated [`docs/specs/tech-spec.md`](tech-spec.md) § instance directory tree — added `sample/` block with per-split JSONL + sidecar PNG layout.
- [x] **Cross-repo coordination.** Updated [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md): added `manifest.sample` row + `manifest.sample` shape subsection + `sample/` on-disk-layout block + division-of-responsibility note (`dataset/` stays authoritative for training; `sample/` is quick-look). Additive — no `schema_version` bump (canonical recipe bytes unchanged; this is a materialization-behavior change, pre-prod re-materialize event for any recipe declaring `SampleData:`).
- [x] CHANGELOG entry under the in-progress v0.20.0 section flagging the materialization-bytes change for recipes with `SampleData:` and the FR-2 check 16 wording flip.
- [x] CI parity: `pyve test` (1269 unit + 67 integration), `pyve testenv run mypy src tests` (202 files clean), `pyve testenv run ruff check src/ tests/`, `pyve testenv run ruff format --check src/ tests/` — all green.

**Out of Scope:**

- M-replace artifact semantics (the sample replaces the materialized instance). Considered and rejected in the I.r.0 spike.
- Cross-split sampling (e.g., `n` records across all splits combined). Stays per-split.
- `stats_from_instance.variant: <name>` selector — separate Future story.

---

### Story J.b: Integration spike — NbFoundry [Done]

**Disposition: integration spike** (throwaway; deliverable is a documented friction list, not production code). Part of Phase J phase-bundle release. Closes FR-J-4.

Write a Marimo notebook that uses DataRefinery via library calls AND CLI subprocess invocations. Exercise common patterns (load → validate → materialize → inspect a materialized instance). The friction list feeds Story J.c's contract-doc authoring.

**Execute before J.c** so the contract doc reflects real ergonomics rather than aspirational ones.

**Tasks:**

- [x] Time-box (target: one working session). Scaffold a minimal Marimo notebook in a scratch directory. Scaffolded under `/tmp/dr-nbf-spike/` (synthetic 2-class × 6-image ImageFolder + `datarefinery init`-generated recipe + isolated `.cache/`); notebook authored at `/tmp/dr-nbf-spike/datarefinery_demo.py` (Marimo 0.23.9; six cells covering library + CLI subprocess paths). `marimo export script` confirms the notebook parses + serializes cleanly.
- [x] Exercise the **library path**: `from datarefinery import DataRefinery`, `.from_recipe`, `.materialize()`, instance result accessors. Note what gets imported, what works, what's missing. Confirmed `DataRefinery`, `Instance`, `materialize`, `__version__` all reachable from the top-level package; `from_recipe → validate → materialize → status → inspect` round-trips cleanly; cache-hit signaling works via `dr.last_run.cache_hit`. Two friction items surfaced: F11 (top-level `materialize()` discards cache-hit signal), F12 (default cache_root is `data/` relative to cwd).
- [x] Exercise the **CLI path**: invoke `datarefinery validate`, `materialize`, `status` as subprocesses from notebook cells. Note exit codes, stdout/stderr behavior, whether `rich` tables render usefully inside Marimo, whether progress bars need suppression. Confirmed `python -m datarefinery <verb>` invocations succeed end-to-end; exit codes match documented `_exit_codes.py` mapping; stdout is `rich`-formatted tables with optional ANSI color, no `--json` alternative. Six friction items surfaced: F1 (log-target no-op), F2 (no machine-readable output), F3 (hash-column truncation), F4 (`--quiet`/`--verbose` no-ops), F5 (console-script shim broken; `python -m` form recommended), F6 (duplicate-plugin error msg doesn't name distributions), F10 (subprocess progress-bar UX).
- [x] Capture a **friction list** in [`docs/specs/phase-j-nbf-integration-friction.md`](phase-j-nbf-integration-friction.md): same shape as J.d — what was expected, what happened, what fix it implies. Pay particular attention to log-target redirection, progress-bar noise, and error-message machine-readability. Twelve items (F1–F12) captured with severity, category (CODE / CONTRACT / DOC / ENV), and triage suggestion. Three "needs eyeballs" items (V1–V3) flagged for live Marimo session.
- [x] Present the friction list at the approval gate; the developer decides which items inform J.c's contract doc and which become separate Phase J stories. Triage matrix at the bottom of the friction doc recommends F1/F2/F4/F6 become new code stories in Phase J; F3/F10 defer (resolve when F2 lands); F5/F7/F8/F9/F11/F12 absorb into J.c's contract-doc authoring.

**Out of Scope:**

- Production NbFoundry integration code. The spike is investigation, not implementation.
- Authoring [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) — that is Story J.c, which executes after this spike.

---

### Story J.c: NbFoundry vendor-dependency-spec stand-up [Done]

**Disposition: documentation + cross-repo contract.** Part of Phase J phase-bundle release. Closes FR-J-2.

NbFoundry has no equivalent of [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md), yet it binds against DataRefinery's library entry points, CLI surface, and notebook-display output formats. Stand up [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) as a separate doc (per phase-plan decision: separate docs are easier to manage than a unified consumer-contract doc).

**Best executed after Story J.b** (NbFoundry integration spike) so spike findings feed the contract-doc authoring rather than the other way around.

**Tasks:**

- [x] Create [`docs/specs/nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) mirroring the structure of the MF doc — status block + Overview drawing the interaction-binding (NbF) vs. shape-binding (MF) split.
- [x] Document the **library entry points** NbFoundry consumers may import — `DataRefinery`, `DataRefinery.from_recipe`, `.materialize()`, instance result accessors. Pin signatures and return types. Three subsections: `DataRefinery` class (full method signature block), `Instance` accessor, top-level `materialize()` convenience. F11 from the J.b friction list absorbed (cache-hit signaling: use `DataRefinery.from_recipe(...).materialize()` for cache-aware flows; top-level `materialize()` discards the signal).
- [x] Document the **CLI commands** NbFoundry consumers may invoke from notebook cells — verb names, flag names, exit codes, error-message contracts (specifically the messages NbF parses). Sections: verb vocabulary table, exit-code contract table mirroring [`cli/_exit_codes.py`](../../src/datarefinery/cli/_exit_codes.py), global options table, error-message panel-title contract. F5 absorbed (recommend `[sys.executable, "-m", "datarefinery", ...]`); F8 absorbed (`--view` vocabulary forward-declared, recommend library `dr.inspect(view=...)`).
- [x] Document the **notebook-output ergonomics** — `--log-target`, progress-bar suppression flags, stdout/stderr expectations, `rich`-rendering behavior inside Marimo cells. Subsections: stdout vs. stderr separation discipline, `rich` output composition with Marimo (ANSI/Unicode), progress UX (library `progress_callback` preferred over CLI subprocess), Marimo single-definition constraint (F9), default `cache_root` (F12). F1 absorbed (`--log-target` no-op flagged as forward-declared); F10 absorbed (progress-bar guidance).
- [x] Document **schema-version coordination** (mirror MF doc § Schema-version coordination policy) and **forward-compatibility expectations** (unknown ops, unknown manifest keys). NbF's obligation is much lighter than MF's — NbF mostly drives the library/CLI rather than reading recipe internals; cross-references the MF spec for the recipe-side coordination.
- [x] Document **failure modes NbFoundry SHOULD detect** — schema-version mismatch, missing manifest fields, plugin missing. Three subsections (library path, CLI path, common). F6 absorbed (duplicate-plugin error class today names the plugin but not the contributing distributions; flagged as Phase J follow-up).
- [x] Document the **versioning and adoption** policy (pre-prod / post-prod stability promises; same shape as MF doc). Forward-declared items enumerated explicitly so adopters know what is pending: `--log-target`, `--quiet`/`--verbose`, `--json`, duplicate-distribution naming, CLI `--view` vocabulary.
- [x] Cross-reference from [`docs/specs/concept.md`](concept.md), [`docs/specs/features.md`](features.md), and [`docs/specs/project-essentials.md`](project-essentials.md) § "Recipe / manifest / report shape changes need a cross-repo coordination check" — extend the "three surfaces" entry to name both consumer-spec docs. concept.md § Target Users now names NbF as an indirect beneficiary with a pointer to the new spec. features.md adds a § FR-3 cross-repo contract note and bumps four `modelfoundry/dependency-spec.md` references to the current `modelfoundry/vendor-dependency-spec.md` filename. project-essentials.md § cross-repo coordination expanded from "three surfaces" to **five surfaces** (three shape-binding + two interaction-binding), with two new refusal examples (don't rename `DataRefinery.materialize` to `run`; don't remap an existing exit code), and updated to reference both consumer-spec docs.

**Out of Scope:**

- Implementing any new library API or CLI verb for NbFoundry's benefit. If the spike surfaces concrete gaps, those become separate Phase J stories.
- NbFoundry-side adoption work. Owned by the NbFoundry repo.

---

### Story J.d: Integration spike — ModelFoundry [Done]

**Disposition: integration spike** (throwaway; deliverable is a documented friction list, not production code). Part of Phase J phase-bundle release. Closes FR-J-3.

Take a fresh v0.19.0 DataRefinery materialized instance, consume it from a minimal ModelFoundry harness, exercise the documented contract surfaces, capture friction. The friction list feeds the next cluster of Phase J stories (contract-doc fixes, ergonomic library/CLI fixes, small additive manifest fields).

**Tasks:**

- [x] Time-box (target: one working session). Pick a representative recipe (existing fixture or scaffolded `init` output). Scratch dir at `/tmp/dr-mf-spike/` with synthetic 3-class × 8-image ImageFolder. Two recipes authored: an aggressive-augmentation recipe (`recipe.yaml`, `horizontal_flip` + `materialization: aggressive` + `expansion: 2`) for sidecar-PNG resolution, and a normalize recipe (`recipe_norm.yaml`) for fitted-statistics persistence. Both validate against current v0.20.0 source.
- [x] Materialize a fresh instance with v0.19.0 DataRefinery (current `main` = v0.20.0 in-progress; FR-J-1 SampleData runtime + manifest.sample field shipped J.a, so v0.20.0 was the right version to spike against). Two friction discoveries gated this task — F1 (ImageFolder + aggressive sidecar path crashes) and F2 (normalize + aggressive realizer crashes) — both worked around by materializing via the library API with manually constructed flat-record_id records. Both captured as **high-severity code stories candidate** in the friction list.
- [x] From a minimal MF harness (real or mocked), exercise: recipe-model reads against schema_v2 names; `manifest.json` reads of every field MF binds against per [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md); dataset `<split>.jsonl` reads + sidecar PNG resolution for an aggressive-mode variant; `report.md` + `drift.json` reads. Harness at `/tmp/dr-mf-spike/mf_harness.py` — pure stdlib + numpy + Pillow + pyarrow, **no `from datarefinery import`**. All five sections (manifest, recipe-side, dataset+sidecar, report, cache-identity) exercised; **9 positive confirmations** (every documented contract surface works) and **8 friction items** (F1–F8) recorded.
- [x] Capture a **friction list** in [`docs/specs/phase-j-mf-integration-friction.md`](phase-j-mf-integration-friction.md): each item names what was expected, what happened, and what fix (or contract-doc clarification) it implies. Categorize: contract-doc errors, missing fields, ergonomic snags, schema_v2 surprises. Authored with severity, category (CODE / CONTRACT / VALIDATOR / DOC), reproducer, and per-item triage suggestion. Distinguishes "what worked" (recorded explicitly so the next ratification round can move surfaces from documented → verified) from "friction".
- [x] Present the friction list at the approval gate; the developer decides which items become follow-up Phase J stories and which are no-ops. Triage matrix at the bottom of the friction doc identifies F1 and F2 as the two **high-severity code stories** (real crash bugs that escaped the test suite because integration tests sidestepped the failure modes); F7 as a **medium** one-line code fix aligning spec promise with reality; F3–F6 + F8 as **CONTRACT-doc clarifications** foldable into the next [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) ratification pass.

**Out of Scope:**

- Production ModelFoundry adapter code. The spike is investigation, not implementation.
- Fixing the friction items in-band. Each one becomes a separate Phase J story (or is dropped at the gate).

---

### Story J.e: schema_version 2 consumer-side adoption check [Done]

**Disposition: cross-repo verification.** Part of Phase J phase-bundle release. Closes FR-J-5.

v0.19.0 ships `schema_version 2` with a loader-side v1→v2 migration. Verify both consumers handle v1 recipes (migrated by the loader) and v2 recipes (native shape) cleanly. May collapse into J.d / J.b if those spikes organically exercise both versions.

**Tasks:**

- [x] Confirm `datarefinery.recipe.loader.SUPPORTED_SCHEMA_VERSIONS == {1, 2}` and the v1→v2 migration produces a v2-shape recipe (`recipe.json` reflects v2 canonical bytes). Confirmed: `SUPPORTED_SCHEMA_VERSIONS == frozenset({1, 2})`, `LATEST_SCHEMA_VERSION == 2`; the composed v1→v2 migration in [`recipe.migrations`](../../src/datarefinery/recipe/migrations.py) (`filters_reshape_v1_to_v2 → generation_reshape_v1_to_v2 → assertion_naming_v1_to_v2`) produces v2 canonical bytes.
- [x] During J.d, feed both a v1 fixture recipe and a v2 fixture recipe through the MF harness — confirm both work end-to-end. Authored `/tmp/dr-mf-spike/recipe_v1.yaml` (v1-shape: `kind: dtype` + `kind: record_count`) and `recipe_v2.yaml` (v2-shape: `kind: dtype_equals` + `kind: record_count_in_range`). Both validate clean (25/25 checks); both materialize. **Byte-identical persisted `recipe.json` (same SHA-256) and identical `manifest.recipe_hash` across v1-input and v2-input.** Verified by the same MF harness exercising every documented bind surface against both materialized instances.
- [x] During J.b, do the same in the Marimo notebook — confirm both versions materialize and the resulting instance is readable. **Coverage-by-construction**: the v1→v2 migration runs inside `DataRefinery.from_recipe` upstream of caller shape, so a Marimo notebook cell sees the same migrated bytes the MF harness does. No NbF-specific code path can break v1/v2 transparency. Documented in the [J.d friction list](phase-j-mf-integration-friction.md) § "Schema-v1 ↔ schema-v2 input transparency".
- [x] Document any consumer-side surprises (e.g., MF binds against a v1 field name internally) as additions to the J.d / J.b friction lists; coordinate fixes via the relevant `vendor-dependency-spec.md`. **No new code-level friction surfaced** — both consumer paths see identical canonical bytes. The verification empirically confirmed friction item F5 from the J.d friction list (the `schema_version` field-name overload between `manifest.schema_version=1` and `recipe.schema_version=2` is real on a fresh instance; Story J.k pins the disambiguation in the MF spec). A new "Schema-v1 ↔ schema-v2 input transparency" subsection appended to the [J.d friction list](phase-j-mf-integration-friction.md) records the positive confirmations so the next MF/NbF vendor-dep-spec ratification round can move "v1→v2 loader transparency" from "documented" to "verified by Story J.e spike".

**Out of Scope:**

- Adding new schema versions. v2 is the current shape; v3 is a future ceremony.
- Schema_v2 changes to the recipe model itself. The phase-bundle is verification, not further reshape.

---

### Story J.f: `manifest.label_classes` — canonical class-set enumeration [Done]

**Disposition: feature addition + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Closes the class-enumeration gap surfaced during the [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) 2026-06-11 ratification round 2.

Today the manifest carries no canonical class set. Every consumer that needs label→logit-index mapping, confusion-matrix axes, or per-class column naming scans JSONL itself and picks a sort convention out-of-band. Two consumers (or two flows in one consumer) can silently disagree on ordering, producing misaligned predictions ↔ confusion matrix ↔ class-weight vectors. Centralize the list in the manifest so ordering becomes the producer's commitment.

**Tasks:**

- [x] Add `Manifest.label_classes: list[Any] | None = None` field in [`src/datarefinery/pipeline/manifest.py`](../../src/datarefinery/pipeline/manifest.py).
- [x] Compute at materialize time in [`pipeline/runner.py`](../../src/datarefinery/pipeline/runner.py): scan all labeled records across all defined splits (skip unlabeled records per FR-22), take the distinct union, sort ascending using Python `sorted(...)` semantics. Empty when no labeled records exist → field is `None`. Implemented as `_compute_label_classes(split_map, *, label_field, unlabeled_splits) -> list[Any] | None` module-level helper.
- [x] Emit at both the full and partial manifest-build sites (mirror the `class_balance` and `sample` emission discipline). Full-run site at the end of `run()`; partial-run site at `_partial_finish()` so `--stage` partial runs still emit `label_classes` reflecting whatever labeled records were observed up to the stop point.
- [x] Unit tests: balanced multi-class, sparse class (present only in test), single-class, fully-unlabeled (`None`), `str` and `int` label dtypes. Confirm the manifest-side computation matches a JSONL-derived scan over all splits. 12 tests in [`tests/unit/test_label_classes.py`](../../tests/unit/test_label_classes.py): balanced, sparse-only-in-test, singleton class, int dtype, str dtype, fully-unlabeled, mixed-with-missing-label, unlabeled-split skipping, empty split_map, all-splits-unlabeled, plus two manifest round-trip tests.
- [x] Integration test: round-trip a fixture recipe and assert the manifest's `label_classes` matches the JSONL-derived set on a recipe with disjoint train/val/test class coverage. 2 tests in [`tests/integration/test_label_classes.py`](../../tests/integration/test_label_classes.py): disjoint A/B (train) + C (val) + D (test) coverage via `key_assignment`, with consumer-side JSONL-scan-and-sort verification matching the producer commitment byte-for-byte; plus a fully-unlabeled records pathological case.
- [x] Cache-identity guard: confirm the new field perturbs no canonical bytes (it lives in manifest, not recipe) — pinning fixture stays green. Verified: `tests/unit/test_canonical_hash_pin.py::test_canonical_hash_is_pinned` passes with no change required.
- [x] **Cross-repo coordination.** Update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md): ratify the forward-declared `manifest.label_classes` shape subsection — remove the "forward-declared" / "pre-J.f" caveats; mark the field as live in the current release. Field-row updated, shape subsection re-headered (`Shipped Phase J Story J.f, v0.20.0` replaces `Forward-declared`), pre-J.f consumer-guidance reframed as an **adoption-migration** note for pre-v0.20.0 instances (consumers still scan-and-sort when reading older instances; the algorithm matches the producer's exactly). The "set vs counts" division added as an explicit producer-commitment-scope bullet so future readers don't conflate the new field with per-class counts (consumer-derived).
- [x] DOC: update [`docs/specs/tech-spec.md`](tech-spec.md) manifest section to enumerate the new field. Added `sinks_skipped`, `class_balance`, `sample`, and `label_classes` lines to the `class Manifest` block alongside the existing fields (the prior listing was stale).
- [x] CHANGELOG entry under the in-progress v0.20.0 section: additive manifest field, no `schema_version` bump (no canonical-bytes perturbation), consumer-bind addition. New `Added` bullet under `[0.20.0] - in progress` enumerating the computation + scope (set, not counts) + adoption migration; new `Cross-repo coordination` bullet documenting the MF spec ratification of the `manifest.label_classes` row + shape subsection.
- [x] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`. 1283 unit tests + 69 integration tests pass; mypy 204 files clean; ruff check + ruff format clean.

**Out of Scope:**

- Per-class frequency / count emission in the manifest. Consumer-derived from JSONL is fine; the canonical class list is what matters for ordering. See `manifest.class_balance` shape § "Per-class counts" for the documented division.
- Multi-label / multi-class-per-record extensions. v1 image_classification is single-label; multi-label is a Future feature.

---

### Story J.g: Consumer-applied transformations boundary — `path` rewrite + validator guard [Done]

**Disposition: feature addition + validator check + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Closes the silent `path`-vs-transformed-pixels divergence surfaced during the [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) 2026-06-11 ratification round 2.

In v0.19.0, `path` is set once at input loading and never rewritten by Transformations or Sinks. A non-aggressive recipe declaring `resize` (or any pixel-altering op) produces JSONL whose `path` points at source pixels while the in-memory transformed image is dropped at serialization — consumers reading `path` get pre-transform geometry, silently. The CIFAR-10 reference flow has no geometry transforms and avoids the gap, but it's load-bearing for generalization.

**Approach.** Require a sink for lazy-mode recipes containing pixel-altering Transformations; DR rewrites each record's `path` field to point at the sink's per-record output. Interim validator check refuses the silent-divergence case so it cannot be authored in the first place.

**Tasks:**

- [x] Identify the closed set of pixel-altering Transformation ops in the `image_classification` plugin (today: `resize`; plus any future ops). Document the criterion explicitly: an op is pixel-altering if its `apply` changes the image array's bytes in a consumer-visible way that is NOT recoverable from persisted fitted statistics. `normalize` / `mean_subtract` are NOT pixel-altering by this criterion — they are stat-based and consumer-applied. **Done as a declarative plugin flag** `OperationSpec.pixel_altering` ([`plugins/base.py`](../../src/datarefinery/plugins/base.py)), set `True` on `resize` ([`plugins/image_classification/plugin.py`](../../src/datarefinery/plugins/image_classification/plugin.py)); `normalize` / `mean_subtract` / `cast` keep the default `False`. Story J.i reuses the same flag mechanism for its dtype-altering set — no hardcoded recipe-layer constant, no plugin-name gate (check passes trivially for stub plugins with no pixel-altering ops).
- [x] Add validator **check N** (new number; integration suite count assertion updates): lazy-mode recipe + `Transformations` containing a pixel-altering op + no `Sinks` declaration → refuse with a message naming the offending op and the required sink declaration. **Check 26** `pixel_altering_transform_requires_sink` ([`recipe/validator.py`](../../src/datarefinery/recipe/validator.py)): refuses when a pixel-altering Transformation applies to any lazily-serialized split with no qualifying image sink (`png_per_record` + `field: image` + post-transform stage) covering it; message names the offending op(s) and the uncovered splits. Splits realized as aggressive variants are exempt. Suite now runs **26** checks (updated `test_validator.py` + four integration count assertions).
- [x] Implement path-rewrite mechanism: when a recipe declares a sink AND has pixel-altering Transformations, DR rewrites each record's `path` field at JSONL emission to point at the sink's per-record output (using the sink's resolved `path_template`). Shared logic in [`pipeline/path_rewrite.py`](../../src/datarefinery/pipeline/path_rewrite.py) (`path_rewrite_plan`, `uncovered_pixel_altering_splits`, `qualifying_image_sinks`); runner threads the plan into [`_write_dataset` / `_prepare_record_for_persistence`](../../src/datarefinery/pipeline/runner.py) for non-aggressive records. Rewritten `path` is **instance-relative** (resolved via `render_template`); first qualifying sink in recipe order wins per split; applies to the `sample/` sidecar JSONL too.
- [x] Unit tests: pixel-altering + no sink → validator refusal; pixel-altering + sink → JSONL records carry rewritten `path` matching the sink's per-record output; non-pixel-altering (`normalize`-only) → `path` unchanged (regression guard). [`test_pixel_altering_flag.py`](../../tests/unit/test_pixel_altering_flag.py) (5), [`test_path_rewrite.py`](../../tests/unit/test_path_rewrite.py) (12: classification, coverage-gap, aggressive-exemption, rewrite-plan), [`test_runner_path_rewrite.py`](../../tests/unit/test_runner_path_rewrite.py) (3: rewritten / unplanned-split / no-plan), check-26 cases in [`test_validator.py`](../../tests/unit/test_validator.py) (5).
- [x] Integration test: end-to-end recipe with `resize` + sink → consumer reads `path`, decodes the sidecar PNG, gets byte-identical pixels to the in-memory transformed array recorded by the determinism test. [`tests/integration/test_consumer_transform_boundary.py`](../../tests/integration/test_consumer_transform_boundary.py): non-uniform gradient images, `path` rewritten across all three splits, decoded PNG byte-identical to the PIL-resize reference, plus cross-run determinism of the rewritten JSONL.
- [x] **Cross-repo coordination.** Update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md): ratify the forward-declared § "Consumer-applied transformations vs. baked transformations" — remove the "Phase J Story J.g" forward-declaration; document the closed pixel-altering-op set and the path-rewrite mechanism as the stable contract. Status block gains a "J.g ratified 2026-06-12" entry; the "Unresolved boundary" subsection is rewritten as "resolved" (closed op set, check 26, instance-relative path-rewrite); the Sinks-baked bullet updated; consumer guidance now states `path` is instance-relative for pixel-altering recipes.
- [x] DOC: update [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) § Sinks to describe the sink-as-pixel-source pattern. New "Sink as pixel source" subsection with worked `resize` + sink YAML, the check-26 requirement, and the `normalize`/`cast`/aggressive exemptions; the "where to put the sink" tip notes the J.g exception that wants `post_Transformations`.
- [x] CHANGELOG entry under the in-progress v0.20.0 section: cross-repo contract change. Additive (no `schema_version` bump needed); document the pre-J.g silent-divergence case as a fixed bug. Added bullet (flag + check 26 + path-rewrite), Materialization-bytes note (instance-relative `path` → pre-prod re-materialize event), Cross-repo coordination note (MF spec ratification).
- [x] CI parity: `pyve test`, `pyve testenv run mypy src tests`, `pyve testenv run ruff check src/ tests/`, `pyve testenv run ruff format --check src/ tests/`. 1310 tests pass (unit + integration); mypy clean (209 files); ruff check + format clean. (Note: the Pyve v3 testenv has a stale binary shebang from the v2→v3 layout migration; mypy/ruff were invoked via `.pyve/envs/testenv/venv/bin/python -m …` — a Pyve migration artifact to flag upstream, not a DR-side issue.)

**Out of Scope:**

- Aggressive-mode behavior. Unchanged — already correct via `image_path`.
- A separate path-rewrite mechanism that doesn't go through `Sinks`. Sinks are the existing "write transformed pixels to disk" surface; using them keeps one mechanism for the write half (sink → bytes) and one for the JSONL-binding half (path rewrite → consumer-visible source). Adding a parallel mechanism would multiply the surfaces where loose/tight coupling questions could re-surface, mirroring the precedent in [`project-essentials.md`](project-essentials.md) § "Sibling-instance dependencies are loose-coupled in v1".
- Pixel-altering ops appearing in `Augmentations` (lazy mode). Lazy-mode augmentations are policy-only by design (consumer realizes); they're not in scope here.
- A path-rewrite for `mean_subtract` / `normalize`. These are consumer-applied by design (see vendor-dependency-spec § "Normalization is applied by the consumer"); their bytes-on-disk semantics are unchanged.

---

### Story J.h: ImageFolder + aggressive Augmentations — sidecar PNG path crash [Done]

**Disposition: bugfix + validator + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Surfaced 2026-06-12 during the [J.d MF integration spike](phase-j-mf-integration-friction.md) (F1).

End-to-end materialization of a recipe declaring `Input.type: image_folder` + `Augmentations: [{materialization: aggressive, ...}]` fails with `FileNotFoundError` at the dataset-write stage. The image_classification ImageFolder loader stamps `record_id` as `"<source-name>/<class>/<filename>"` (with forward slashes); the runner's [`_prepare_record_for_persistence`](../../src/datarefinery/pipeline/runner.py) computes the sidecar PNG path as `sidecar_dir / f"{record_id}.png"`, which produces nested directories without `mkdir(parents=True)`. PIL `Image.save` then fails to open the file for writing. The reproducer is in the J.d friction-list F1 section.

**Why the test suite missed it.** The Story H.r.2 aggressive-mode integration tests ([`test_runner.py:519`](../../tests/integration/test_runner.py#L519)) use the library API with manually constructed flat record_ids (`rec_0001`), sidestepping both the slashes and the nested-dir problem. The disk-loader path has never been exercised end-to-end with aggressive variants in the test suite — this story closes that gap.

**Tasks:**

- [x] Reproduce the crash with a failing integration test materializing an `image_folder` recipe + aggressive `horizontal_flip` end-to-end (no library shortcut to manually-constructed records). Test lives in `tests/integration/`. [`tests/integration/test_imagefolder_aggressive.py`](../../tests/integration/test_imagefolder_aggressive.py): writes a real 2-class ImageFolder to disk, loads via `pipeline.inputs.load_raw_records`, materializes; pre-fix it raised `FileNotFoundError` on `dataset/train/images/imgs/c0/img_0001.png__v000.png` (nested parent not created).
- [x] Fix in [`_prepare_record_for_persistence`](../../src/datarefinery/pipeline/runner.py): sanitize the per-variant sidecar filename so loader-stamped `record_id` slashes do not create nested directories. Decide between (a) `mkdir(parents=True, exist_ok=True)` on `sidecar_path.parent` to preserve the nested layout, or (b) replacing `/` (and other path separators) with a safe character (e.g. `__`) so the filename stays flat. Decision criterion: byte-stable across loader/manual paths, no record_id mutation in the JSONL. **Chose (a)** — `sidecar_path.parent.mkdir(parents=True, exist_ok=True)`. Rationale: zero collision risk (ImageFolder ids are unique full relative paths; flattening could alias e.g. `a_/b` and `a/_b`), no `record_id` or `image_path` munging (both mirror the id verbatim), and a no-op for flat manual-API ids (parent == `sidecar_dir`).
- [x] Update the JSONL `image_path` field to match the chosen sanitized form so consumers resolve correctly. Update [`test_runner.py:519`](../../tests/integration/test_runner.py#L519) family expectations if the sanitization changes the relative path shape; the deterministic-bytes integration test (`test_aggressive_materialize_is_deterministic_across_runs`) must stay green. **No change needed** — option (a) keeps `image_path = "<split>/images/<record_id>.png"` verbatim, so the flat-record_id `test_runner.py:519` family is unaffected; ran the full aggressive family + the determinism test — all green.
- [x] Cross-repo coordination: update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Sidecar PNG encoding" / § "Aggressive-mode variants" to pin the sanitization rule (so MF consumers know how `image_path` resolves when source `record_id` contains separators). Additive — no `schema_version` bump on canonical-bytes grounds, but the on-disk PNG path layout changes for ImageFolder recipes with aggressive variants → pre-prod re-materialize event for any such recipe. § "Aggressive-mode variants" `image_path` row now states it is exactly `"<split>/images/<record_id>.png"` and may be **nested** when `record_id` carries `/`, with a join-as-relative-POSIX-path consumer obligation; § "Record-multiplication shape" notes DR does not sanitize `record_id` and the writer creates the implied nested dirs.
- [x] CHANGELOG entry under the in-progress v0.20.0 section flagging the on-disk-layout change for `image_folder` + aggressive recipes. New `Fixed` subsection (the crash + fix), plus Materialization-bytes note (nested sidecar subtree, pre-prod re-materialize event) and Cross-repo coordination note (the `image_path` resolution rule).
- [x] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`. 1311 tests pass; mypy clean (210 files); ruff check + format clean. (Testenv rebuilt under Pyve v3 — the `pyve env run …` forms now work natively after the v3-migration stale-shebang repair.)

**Out of Scope:**

- Library-API manual-records path. The existing flat-record_id pattern continues to work unchanged; this story is the disk-loader path's gap.
- Non-image plugins. Tabular and text plugins ship as stubs and don't exercise aggressive realizers in v1.
- A general "record_id is filesystem-safe" invariant across DataRefinery. Scope is the sidecar PNG persistence path. Other code that consumes `record_id` (JSONL keying, cache identity, log messages) is unaffected.

---

### Story J.i: Pixel-altering Transformations + aggressive Augmentations — validator refusal [Done]

**Disposition: validator check + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Surfaced 2026-06-12 during the [J.d MF integration spike](phase-j-mf-integration-friction.md) (F2). **Natural fold-in with Story J.g** — both stories enumerate the same closed set of pixel-altering Transformation ops.

A recipe declaring `Transformations: [{op: normalize, ...}]` alongside `Augmentations: [{materialization: aggressive, ...}]` crashes mid-pipeline with `TypeError: Cannot handle this data type: (1, 1, 3), <f8` in the realizer. Runner stage order is `... → Transformations → Featurizations → Augmentations → ...`, so the realizer sees float64 z-scores from normalize and PIL `Image.fromarray` rejects them. The crash applies to every pixel-altering aggressive augmentation (`horizontal_flip`, `random_crop`, `color_jitter`, `random_erasing`) chained after any dtype-changing Transformations op (`normalize`, `mean_subtract`).

**Approach.** Add a new FR-2 check that refuses the combination at validate time. The same closed pixel-altering-op set Story J.g is scoping for the lazy-mode `path` rewrite applies here — the two stories share the enumeration. Coordinate task order with J.g so the enumeration lands once.

**Tasks:**

- [x] Reuse the closed pixel-altering Transformation-op set from Story J.g (today: `resize` is geometry-altering; this story adds `normalize`, `mean_subtract` as dtype-altering — both classes break the aggressive realizers' uint8 assumption). Either share an enum/constant or document the coordination explicitly in both check docstrings. **Coordination decision:** added a sibling `OperationSpec.dtype_altering` flag ([`plugins/base.py`](../../src/datarefinery/plugins/base.py)) alongside J.g's `pixel_altering`; marked `normalize` / `mean_subtract` ([`plugins/image_classification/plugin.py`](../../src/datarefinery/plugins/image_classification/plugin.py)). **Correction to the framing:** `resize` is pixel-altering but **uint8-preserving**, so it does NOT break the aggressive realizer (verified against the `horizontal_flip` realizer's `PIL.Image.fromarray` call) — `resize` + aggressive materializes fine. Only dtype-altering (non-uint8 output) ops crash, so the check keys off `dtype_altering`, not `pixel_altering`. The two flags are independent and documented as such in both check docstrings (26 ↔ 27).
- [x] Add validator **check N** (new number; integration-suite count assertion updates): recipe with a pixel-altering / dtype-altering Transformation op + any aggressive `AugmentationOp` targeting the same split → refuse with a message naming the offending op pair and the split. **Check 27** `dtype_altering_transform_incompatible_with_aggressive` ([`recipe/validator.py`](../../src/datarefinery/recipe/validator.py)): refuses a `dtype_altering` Transformation sharing any split with an aggressive Augmentation; message names the op pair + overlap split. `resize` is intentionally NOT refused (see correction above). Suite now runs **27** checks (updated `test_validator.py` + four integration count assertions 26→27).
- [x] Reproduce the crash with a failing test, then confirm the new validator check refuses the recipe before the run starts. [`tests/integration/test_dtype_altering_aggressive_guard.py`](../../tests/integration/test_dtype_altering_aggressive_guard.py): `test_normalize_plus_aggressive_crashes_unguarded` runs the recipe through `PipelineRunner` and asserts the raw mid-pipeline crash; `test_validate_refuses_before_run` asserts check 27 flags the same recipe at validate time. Plus 6 check-27 unit cases in [`test_validator.py`](../../tests/unit/test_validator.py) (normalize / mean_subtract refusal, resize-allowed, lazy-aug-allowed, normalize-only-allowed, partial-split-overlap-refused) and 4 dtype-flag cases in [`test_pixel_altering_flag.py`](../../tests/unit/test_pixel_altering_flag.py).
- [x] Cross-repo coordination: update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Aggressive-mode variants" / § "Materialization modes" to call out the incompatibility, referencing the new check ID. Added an "Incompatibility" paragraph under § "Materialization modes" pinning the uint8 realizer requirement, the `dtype_altering` classification, check 27, and the explicit `resize`-is-allowed clarification.
- [x] DOC: update [`recipe-authoring.md`](../guides/recipe-authoring.md) § Augmentations to document the constraint. New "Constraint: aggressive mode requires uint8 image bytes" paragraph with the keep-normalization-consumer-side / use-lazy-mode remedies and the `resize`-is-fine note.
- [x] CHANGELOG entry under the in-progress v0.20.0 section: new validator check; previously-author-able recipes that hit the crash now fail fast at validate time (existing instances are unaffected — they don't materialize today either). New `Added` bullet (flag + check 27, with the resize clarification) + Cross-repo coordination note.
- [x] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`. 1323 tests pass; mypy clean (211 files); ruff check + format clean.

**Out of Scope:**

- Realizer changes to accept float-typed input. Considered and rejected: cast-back would be lossy (loses normalize z-scores) and break the recipe-as-truth contract.
- Stage-order reversal (Augmentations before Transformations). Out of scope — would invert the "fit on train, apply everywhere" discipline for normalize because fit would run on augmented records.
- Lazy-mode augmentations. Lazy-mode is policy-only by design; the realizer runs in the consumer.
- Per-split scope. The check refuses any same-split combo; partial-split combos (e.g. normalize on train+val, aggressive only on train) still get caught by the train-split overlap.

---

### Story J.j: `drift.json.recipe_hash` — align spec promise with code [Done]

**Disposition: bugfix + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Surfaced 2026-06-12 during the [J.d MF integration spike](phase-j-mf-integration-friction.md) (F7).

The [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Failure modes ModelFoundry SHOULD detect" promises `drift.json.recipe_hash` as the consumer-visible field MF reads to detect stale fitted statistics ("`drift.json`'s `recipe_hash` field aligns with `manifest.recipe_hash`; mismatch is ipso facto a stale instance"). On current v0.20.0 instances, `drift.json` has no `recipe_hash` key — its top-level fields are `feature_summary`, `notes`, `plugin`, `schema_version`, `splits`. Consumers must cross-read `manifest.json` to do the check the spec advertises.

This is a documented promise that doesn't currently exist in code. The right fix is to add the field — small, additive, and aligns spec with reality.

**Tasks:**

- [x] Reproduce the gap with a failing test: assert `drift.json` top-level keys include `recipe_hash` and that the value matches `manifest.recipe_hash` for any fresh instance. [`tests/integration/test_drift_recipe_hash.py`](../../tests/integration/test_drift_recipe_hash.py) (red pre-fix: no `recipe_hash` key) + unit cases in [`test_drift.py`](../../tests/unit/test_drift.py). The pre-existing `test_drift_json_is_canonical_sorted` key-set pin was updated to include the new top-level key.
- [x] Add `recipe_hash` to `drift.json` at the runner's [`compute_drift_placeholder`](../../src/datarefinery/pipeline/runner.py) emission site. Mirror the existing field's emission discipline: copy from `cache_key.recipe_hash` (full 64-hex), not the truncated 16-char shard. Added `DriftSchema.recipe_hash: str | None = None` ([`reporting/drift.py`](../../src/datarefinery/reporting/drift.py)) + a `recipe_hash` keyword on `compute_drift_placeholder`; runner passes `cache_key.recipe_hash`; `re_render_report` ([`reporting/report.py`](../../src/datarefinery/reporting/report.py)) passes `manifest.recipe_hash` so re-rendered drift stays consistent. `str | None` (default `None`) keeps reads of pre-J.j instances and the many existing test callers working.
- [x] Confirm the field perturbs no canonical bytes (it lives in `report/drift.json`, not the recipe) — the canonical-hash pinning fixture stays green. Verified: `tests/unit/test_canonical_hash_pin.py` passes unchanged.
- [x] Unit test: `compute_drift_placeholder` emits `recipe_hash`. Integration test: round-trip a fresh instance, assert `drift.recipe_hash == manifest.recipe_hash` byte-for-byte. 3 unit cases (emit, backward-read default `None`, write/read round-trip) + the integration test asserting equality with `manifest.recipe_hash` and full 64-hex length.
- [x] Cross-repo coordination: update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Report subsections" to enumerate `drift.json.recipe_hash` as a stable field; the existing § "Failure modes" parenthetical referencing this field is now load-bearing. § "Report subsections" `drift.json` bullet now names `recipe_hash` as the one stable field within the otherwise-unstable schema (equal to `manifest.recipe_hash`, pre-J.j fallback noted); § "Failure modes" parenthetical updated to state it is emitted as of J.j with the pre-J.j fallback.
- [x] DOC: no recipe-authoring change (drift.json is consumer-facing, not authorable). Confirmed — no edit.
- [x] CHANGELOG entry under the in-progress v0.20.0 section: additive `drift.json` field; no `schema_version` bump; align spec promise with code. New `Added` bullet + Cross-repo coordination note.
- [x] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`. 1327 tests pass; mypy clean (212 files); ruff check + format clean.

**Out of Scope:**

- Other drift.json fields beyond `recipe_hash`. The MF spec's `drift.json` shape stays "pre-prod unstable" per the existing caveat; this story closes exactly one promise.
- A separate stale-instance verb / CLI surface. The MF consumer-side check is the canonical path; DR doesn't need a new verb for it.
- Backfilling `recipe_hash` into already-materialized v0.19.0 instances. Pre-prod re-materialization is the migration path; explicit in the CHANGELOG.

---

### Story J.k: Vendor-dependency-spec ratification round — absorb J.d friction items F3/F4/F5/F6/F8 [Done]

**Disposition: documentation + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Bundles the five contract-doc clarifications surfaced during the [J.d MF integration spike](phase-j-mf-integration-friction.md) — F3 (medium) + F4/F5/F6/F8 (low). Mirrors the "Round 2 additions 2026-06-11" pattern already in the [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) header.

Each friction item is a small spec edit; bundling them avoids over-decomposition into five tiny stories that share one file and a single coordinated PR. F4 touches both the MF and NbF vendor-dep specs (the asymmetry it documents surfaces in the library-records path, which is NbF's home); F3/F5/F6/F8 are MF-spec-only.

**Tasks:**

- [x] **F3 — host portability of lazy-mode `path`.** Extend [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Source-resolution path" with an explicit "Host portability" subsection: the `path` field is host-bound; consumers operating across hosts SHOULD either (a) require a `Sinks` block writing per-record images so `path` is rewritten under the instance directory (the Story J.g `path`-rewrite mechanism is the long-term fix for the pixel-altering subset), or (b) ship the source ImageFolder alongside the instance. Cross-reference J.g for the pixel-altering subset. Added a **Host portability** bold paragraph with the (a)/(b) workarounds and the J.g cross-reference; inline `(F3, pinned in Round 3)` marker.
- [x] **F4 — disk-loader / library-records Featurization asymmetry.** Add a short subsection under [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) § "Library entry points" (the natural home — that subsection already documents the library-records path) flagging the asymmetry: a `Featurizations` op with `output_field` that the loader pre-stamps succeeds through the disk path (the validator-23 collision guard exempts loader-stamped fields), but the same recipe driven via the library API with manually constructed records arriving with that field already populated will hit the runtime collision check in [`featurizations.py`](../../src/datarefinery/pipeline/stages/featurizations.py). Recommend "rely on the loader to stamp the field, or remove the Featurization op when supplying records manually." Added a new `### Disk-loader vs. library-records Featurization asymmetry` subsection in the NbF spec; verified the runtime guard is unconditional at [`featurizations.py:128`](../../src/datarefinery/pipeline/stages/featurizations.py#L128) (`if recs and op.output_field in recs[0]: raise MaterializeError`).
- [x] **F5 — `schema_version` field-name overload.** Extend [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Schema-version coordination policy" with an explicit disambiguation: `manifest.schema_version` (manifest format version, currently `1`; see `pipeline.manifest.MANIFEST_SCHEMA_VERSION`) and `recipe.schema_version` (recipe schema version, currently `2`; see `recipe.loader.SUPPORTED_SCHEMA_VERSIONS`) are **independent counters with different rules**. Consumers binding against the recipe-schema coordination logic must read `recipe.schema_version`, not `manifest.schema_version`. Added a two-row disambiguation table + the off-by-one warning; values verified against source (`MANIFEST_SCHEMA_VERSION = 1`, `LATEST_SCHEMA_VERSION = 2`).
- [x] **F6 — every recipe section persists in `recipe.json`.** Add one paragraph in [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Recipe-side contract": all top-level recipe sections are present in `recipe.json` whether or not the author declared them; absent / empty sections appear as the section type's default (`[]` for list sections, `null` for optional object sections, empty `{}` where applicable). Consumers SHOULD treat empty / null sections as "not declared". Cross-reference [`project-essentials.md`](project-essentials.md) § "Cache identity is the reproducibility contract" for the canonical-bytes mechanism. Added the paragraph enumerating list-section / optional-object defaults with the project-essentials cross-reference.
- [x] **F8 — implicit consumer-side runtime deps.** Add one sentence to [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Overview" naming the consumer-side runtime deps a downstream tool needs to read DataRefinery artifacts beyond pure stdlib: `numpy` (image bytes; record arrays), `Pillow` (PNG decode for aggressive variants and any image-bytes reads), `pyarrow` (parquet decode for fitted statistics). Added a **Consumer-side runtime dependencies** paragraph to § Overview, noting metadata-only consumers need none of the three.
- [x] **Header ratification note.** Update the MF spec status block at the top, adding a "Round 3 additions 2026-06-12" entry summarizing F3/F5/F6/F8 absorption (mirroring the existing Round 2 entry); update the NbF spec status block similarly for F4. Both notes name Story J.k as the authoring round and reference the J.d friction list. MF "Round 3 additions 2026-06-12 (Story J.k)" entry summarizes F8/F6/F3/F5; NbF "Round 3 addition 2026-06-12 (Story J.k)" entry covers F4; both reference the J.d friction list.
- [x] **Lock-down statement.** Each F-item gets a brief "pinned in Round 3" note inline at the absorption site so future readers can trace the provenance back to the J.d friction list without grovelling commit history. Every absorption site carries an inline `*(Fn, pinned in Round 3 — see header.)*` marker.
- [x] CHANGELOG entry under the in-progress v0.20.0 section: cross-repo contract clarification round absorbing five J.d friction items; documentation-only (no canonical-bytes perturbation, no manifest/recipe shape change). New Cross-repo coordination bullet enumerating F8/F6/F3/F5 (MF) + F4 (NbF).
- [x] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`. (Doc-only — tests/lint stay green by construction; CI parity verification is the standard end-of-story discipline.) 1327 tests pass; mypy clean (212 files); ruff check + format clean.

**Out of Scope:**

- Code changes. F3/F4/F5/F6/F8 are all contract-doc clarifications by design. F4's NbF-spec note documents an existing asymmetry; it does not propose changing the collision-check behavior. The F3 "host portability" framing references J.g's `path`-rewrite mechanism but does not duplicate J.g's scope.
- Forward-declared item rewording. The forward-declared `manifest.label_classes` (J.f) and `Consumer-applied transformations` section (J.g) in the MF spec stay as-is — they're absorbed by their owning stories when those land, not here.
- `nbfoundry/vendor-dependency-spec.md` forward-declared items from J.b (F1 log-target, F2 `--json`, F4 `--quiet`/`--verbose`, F6 duplicate-plugin error). Those are NbF-spec forward declarations awaiting their own code stories; this ratification round closes only the J.d-side editorial gaps.

---

### Story J.l: v0.20.0 `resolve_instance` convenience + cache-identity resolution contract [Done]

**Disposition: feature addition (library ergonomics) + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Surfaced 2026-06-13: ModelFoundry **reimplemented** the DataRefinery instance-ID (cache-key) computation rather than calling the producer's resolver — exactly the brittleness the reproducibility contract exists to prevent (any canonical-bytes change silently breaks a consumer's hand-rolled key math).

`DataRefinery.from_recipe(...).status()` already is the authoritative resolver (`hash_inputs → compute_cache_key → resolve_status → StatusReport`). The gap is **ergonomics + discoverability**: locating an instance requires constructing a full handle, and a consumer scanning the top-level `datarefinery` namespace finds `materialize()` but no obvious "where is my instance?" entry point — so they roll their own. Close the gap with a top-level facade, and harden the contract doc so reimplementation is explicitly out-of-contract.

**Approach.** Add `datarefinery.resolve_instance(...)` as a thin top-level convenience — an alias composing `from_recipe(...).status()`, returning the same `StatusReport`. Symmetric with the existing top-level `materialize()` facade (one-line wrapper over `from_recipe(...).materialize()`); **one resolution implementation, two ergonomic entry points** — no logic duplication, no second result shape. Re-export the result type so consumers type against it without spelunking submodules. Then add a "Resolving a materialized instance" section to the MF contract that names the blessed resolver and forbids cache-key reimplementation.

**Tasks:**

- [x] Add `resolve_instance(recipe_path, *, cache_root=None, seed=None, variant=None) -> StatusReport` in [`core/datarefinery.py`](../../src/datarefinery/core/datarefinery.py), delegating to `DataRefinery.from_recipe(recipe_path, config, variant, seed).status()`. `cache_root: Path | str | None` builds a `RuntimeConfig(cache_root=...)` (default `RuntimeConfig()` when `None`). Docstring notes a custom `plugin_path` requires the full handle (resolve_instance is the common-case facade). Docstring also carries the "consumers MUST NOT recompute the cache key" rule.
- [x] Re-export `resolve_instance`, `StatusReport`, and `resolve_status` from [`datarefinery/__init__.py`](../../src/datarefinery/__init__.py) so the resolution surface is reachable as `from datarefinery import resolve_instance, StatusReport`. `__all__` updated.
- [x] Unit tests: `resolve_instance` returns a `StatusReport`; miss case (deterministic `instance_path`, `cache_status="miss"`, populated `cache_key`); `seed` / `variant` flow through to the resolved key; `cache_root=None` uses the default; result is byte-equal to `from_recipe(...).status()` (delegation equivalence); top-level importability. Top-level importability + `__all__` membership in [`test_resolve_instance_exports.py`](../../tests/unit/test_resolve_instance_exports.py) (3); miss/hit/delegation/seed/variant/str-path coercion in [`test_resolve_instance.py`](../../tests/integration/test_resolve_instance.py) (7) — delegation equivalence asserts `resolve_instance(...) == from_recipe(...).status()`.
- [x] Integration test: materialize an instance, then `resolve_instance(...)` returns `cache_status="hit"` with `instance_path` equal to the materialized dir and a parsed `manifest` whose `recipe_hash` matches; a never-materialized recipe resolves to `miss`. Both covered in `test_resolve_instance.py`.
- [x] **Cross-repo coordination.** Add a "Resolving a materialized instance" section to [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md): name `datarefinery.resolve_instance(...)` / `DataRefinery.status()` as the **one** supported way to locate an instance; document the `StatusReport` shape + `hit`/`miss`/`corrupt` contract; **explicitly forbid** consumers recomputing the cache key / instance path themselves, with the rationale (canonical-bytes changes silently break a reimplementation — the 2026-06-13 MF bug). Add a brief `resolve_instance` entry to [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) § "Library entry points" (its natural home). Header ratification notes in both specs. New MF § "Resolving a materialized instance" (placed right after § Cache-identity contract — the section that documents the key math, i.e. the reimplementation temptation); new NbF § "Top-level `resolve_instance()` convenience"; dated 2026-06-13 (Story J.l) header notes in both.
- [x] CHANGELOG entry under the in-progress v0.20.0 section: additive library API + cross-repo contract hardening; no `schema_version` bump (no recipe/manifest/on-disk shape change). Added bullet + Cross-repo coordination bullet.
- [x] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`. 1337 tests pass; mypy clean (214 files); ruff check + format clean. (Note: the Pyve v3 testenv had been re-created empty since the prior story — reprovisioned via `pyve env run testenv -- pip install -e ".[corruptions]"` + `pyve env install testenv -r requirements-dev.txt`, a recurring v3 churn to flag upstream.)
- [x] Bump version to v0.20.0

**Out of Scope:**

- Machine-readable CLI `status --json` (J.b friction F2) — a separate, larger story. `resolve_instance` is the **library** facade; the CLI JSON surface is its own future work.
- Resolving without the recipe's inputs present. Cache identity includes the input hash, so resolution hashes the declared inputs (same as `status()`/`materialize()`); a host without the inputs cannot resolve from scratch and must be handed the path (or read the manifest of an existing instance).
- A new `CacheKey`-from-recipe public helper beyond what `StatusReport.cache_key` already exposes. The facade returns the full key; no separate key-only API is added.
- Changing `status()` semantics. `resolve_instance` delegates to it unchanged; validation still runs (a recipe that can't load/validate can't have a valid instance anyway).

---

### Story J.m: v0.21.0 Hatchling dynamic version — single source of truth for the package version [Done]

**Disposition: build/release hygiene (bugfix).** Standalone post-bundle story owning its own **v0.21.0** bump — the Phase J v0.20.0 phase-bundle has shipped (tag `v0.20.0` exists; Story J.l owned that bump), so this is new work with its own release rather than part of the bundle. Surfaced 2026-06-16.

The package version is declared in two hand-maintained places that have drifted: [`pyproject.toml`](../../pyproject.toml) `[project].version = "0.20.0"` (static) and [`src/datarefinery/__init__.py`](../../src/datarefinery/__init__.py) `__version__ = "0.19.0"` (stale). The drift originated in Story J.l, whose "Bump version to v0.20.0" task updated `pyproject.toml` but not `__init__.py`. It is consumer-visible: [`cli/app.py`](../../src/datarefinery/cli/app.py) resolves `--version` via `from datarefinery import __version__`, so `datarefinery --version` reports **0.19.0** while the built wheel's package metadata reports **0.20.0** — "which version is this?" has two answers.

The project already builds with Hatchling (`build-backend = "hatchling.build"`); the fix is to adopt Hatchling's dynamic-version source so the literal lives in exactly one place. (A build-system improvement, hence a minor bump rather than a patch number-fix.)

**Approach.** Make [`src/datarefinery/__init__.py`](../../src/datarefinery/__init__.py) `__version__` the **single source of truth**. `pyproject.toml` declares `dynamic = ["version"]` and points `[tool.hatch.version]` at the `__init__.py` literal, which Hatchling extracts at build time. `cli/app.py` is unchanged (keeps importing `__version__`, so `--version` works in editable / source-checkout / uninstalled contexts with no runtime metadata lookup). The `importlib.metadata` direction was considered and rejected (see Out of Scope).

**Tasks:**

- [x] In [`pyproject.toml`](../../pyproject.toml): remove the static `version = "0.20.0"` from `[project]`, add `dynamic = ["version"]` to `[project]`, and add a `[tool.hatch.version]` table with `path = "src/datarefinery/__init__.py"`. Hatchling's default (regex) version source reads the `__version__ = "..."` assignment from that file. Done — `[project].version` replaced with `dynamic = ["version"]`; `[tool.hatch.version] path = "src/datarefinery/__init__.py"` added with a single-source comment above the wheel-target block.
- [x] Bump the now-canonical literal in [`src/datarefinery/__init__.py`](../../src/datarefinery/__init__.py) to `__version__ = "0.21.0"`. This is the single bump this story owns. Done.
- [x] Audit and update tooling that read the now-removed static `[project].version`. The release workflow [`.github/workflows/publish.yml`](../../.github/workflows/publish.yml) "Verify … version matches tag" step read `pyproject.toml["project"]["version"]` and `KeyError`ed on the dynamic field — re-pointed it at the single source (`sed`-extract `__version__` from `src/datarefinery/__init__.py`) and renamed the step. Repo-wide grep confirms `publish.yml` was the only other static-version reader (`ci.yml`'s `tomllib` read is the coverage config, not the version). Surfaced when the `v0.21.0` tag push failed the publish job at this step (pre-PyPI-upload, so no release was affected); the corrected extraction was simulated locally against the tag (`0.21.0` == `0.21.0`).
- [x] Verify the build reads it: build a wheel via the project's build path (`python -m build`) and confirm its `METADATA` `Version:` field equals `0.21.0` (and `hatch version` reports `0.21.0` if `hatch` is available). No second edit site exists. Verified via the editable reinstall (`pyve env run testenv -- pip install -e ".[corruptions]"`), which builds through the same Hatchling backend: produced `ml_datarefinery-0.21.0-py3-none-any.whl` (version sourced from `__init__.py` — the only source) and uninstalled the prior `0.19.0` editable metadata. `build`/`hatch` aren't in the runtime testenv, so the pip editable build is the build-time proof.
- [x] Verify the consumer surface: `datarefinery --version` reports `0.21.0`, and — after a fresh install — `importlib.metadata.version("ml-datarefinery") == datarefinery.__version__`. Verified post-reprovision: `datarefinery --version` → `0.21.0`; `importlib.metadata.version("ml-datarefinery") == datarefinery.__version__ == "0.21.0"`. (Pre-reprovision the testenv carried stale editable metadata `0.19.0` — the exact drift class this story closes.)
- [x] Add a drift-regression guard so this cannot silently recur: a unit test ([`tests/unit/test_version_single_source.py`](../../tests/unit/test_version_single_source.py)) asserting (a) `pyproject.toml` declares `version` as dynamic and carries no static `[project].version` literal (the structural single-source invariant), and (b) the installed package metadata version equals `datarefinery.__version__`. Note the editable-install caveat inline: (b) requires the env to reflect current source (CI installs fresh; a stale local editable install must be reprovisioned via `pyve` first). Done — 4 tests: version literal well-formed; pyproject declares `version` dynamic + no static literal; `[tool.hatch.version].path` points at `__init__.py`; installed metadata == source `__version__` (skips if the dist is absent, with the editable-stale caveat in the assertion message + a comment).
- [x] CHANGELOG: open a new `## [0.21.0]` section above `[0.20.0]`; entry under it noting the single-source-of-truth fix and that `datarefinery --version` now matches package metadata (it previously reported the stale `0.19.0`). No `schema_version` / canonical-bytes impact (build-config + version-string change only). Done — new `## [0.21.0] - 2026-06-16` § with a `Fixed` entry; the `[0.20.0] - in progress` section is left untouched (out of scope).
- [x] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/` — all green. `pyve test` 1341 passed (1337 + 4 new); mypy clean (215 files); ruff check + ruff format clean.

**Out of Scope:**

- The `importlib.metadata` direction (pyproject canonical, `__init__` derives the version at runtime). Considered and rejected: it requires the package to be installed before its own `__version__` is importable and adds a metadata lookup on import; keeping the literal in source keeps `--version` working in any context and matches the Hatchling idiom.
- Reconciling the `[0.20.0] - in progress` CHANGELOG header against the existing `v0.20.0` tag, and any Phase J phase-bundle closure bookkeeping. Separate release-hygiene item; this story does not retro-edit the v0.20.0 section beyond adding the new v0.21.0 section above it.
- Release-automation / auto-bump tooling (`hatch version minor`, a bump pre-commit hook, tag-from-version CI). The single-source change makes such tooling possible later; building it is its own story.
- Distribution / import-name changes. The distribution stays `ml-datarefinery`; the import name and CLI stay `datarefinery` (per Story H.e). Untouched here.

---

## Subphase J-1: Audio Classification

A consumer is planning to use DataRefinery for audio classification. This phase is focused on implementing the requirements in `docs/specs/audio-classification-requirements.md`.

> **▶ RESUMED (2026-06-22).** The segmented-recipe-identity rearchitecture (Story J.x spike → Recipe Architecture bundle J.n.1–J.n.9) shipped at **v0.22.0**, so Subphase J-1 resumed on the new segmented foundation. J.o–J.q are `[Done]`; J.r is the next `[Planned]` story. J.n Finding A (`target_sample_rate` would invalidate every image cache) was closed structurally by J.n.3's `AudioSource` discriminated variant + `plugin:audio` segment.
>
> CI-parity steps below use the Pyve v3 `pyve env run …` form (the pre-v3 `pyve testenv run …` form is retained only in already-completed stories' historical records).

---

### Story J.n: Spike — Audio-classification plugin design (Q1–Q4 verification) [Done]

**Disposition: investigation spike** (throwaway; deliverable is the documented decision, not code). Part of Phase J phase-bundle release. No version bump.

**Trigger.** Subphase J-1 introduces a new modality plugin that touches the Stage model, Splits/Generation ordering, fit-on-train discipline, and the cross-repo `source_record_id` contract. Four open questions from [`audio-classification-requirements.md`](audio-classification-requirements.md) § Open Questions need to be settled before the R-stories execute. The developer-approved working recommendations are Q1 Generation (windowing as a record-count-changing op), Q2 per-recipe canonical sample rate (default 16000 Hz), Q3 DR-owns-grouping-key only (consumer owns the aggregation math), Q4 audio-domain augmentations deferred to Future. This spike's job is to **verify each recommendation against current DataRefinery source** and produce a frozen design memo that J.o–J.w execute against.

**Why a spike rather than a design memo.** The Q1 choice (windowing as Generation) cascades through Splits ordering, manifest `record_counts` semantics, and `source_record_id` field reuse from FR-11 aggressive variants. If any of those assumptions doesn't hold against current code, the cascade breaks differently and J.q–J.r must reshape. Better to find out at spike time than during execution.

**Tasks:**

- [x] **Verify Q1 — Generation as the windowing placement.** Read [`src/datarefinery/pipeline/runner.py`](../../src/datarefinery/pipeline/runner.py) (and the stage-ordering definition) to confirm Generation runs **after** Splits. Confirm `manifest.record_counts` reflects post-Generation expansion (read the FR-11 aggressive-mode precedent in [`tests/integration/test_runner.py`](../../tests/integration/test_runner.py)). Document file:line citations. **Verified** (memo § Q1): `STAGE_NAMES` orders `Splits`(runner.py:109) before `Generation`(runner.py:111); `record_counts` computed post-Generation (runner.py:525). Clip→window split-integrity falls out of stage order for free.
- [x] **Verify Q1 corollary — `source_record_id` mechanism precedent.** Trace how FR-11 aggressive variants derive `source_record_id` and variant `record_id` (`f"{source_record_id}__v{variant_index:03d}"`). Decide: do audio window records reuse `source_record_id` or introduce a sibling field name? Recommended default: **reuse `source_record_id`** + add `window_index: int` (parallel to `variant_index`). Confirm against the vendor-dependency-spec's JSONL records section. **Verified** (memo § Q1 corollary): `_realizer.py:49-59,113-115`. Reuse `source_record_id` is unambiguous (no aggressive audio augs in v1 → a record is never both window+variant); add `window_index`; derive `__w{window_index:04d}`.
- [x] **Verify Q2 — per-recipe canonical sample rate participates in canonical bytes.** Read [`src/datarefinery/recipe/models.py`](../../src/datarefinery/recipe/models.py) to see how plugin-specific input-source params are wired into the canonical-bytes path. Confirm that a new `target_sample_rate: int` field on the audio input source would participate in cache identity automatically. **Verified with a placement refinement — see memo Finding A.** It participates (canonical.py:20-40 dumps the whole graph), BUT `InputSource` is shared across modalities (models.py:86) and `model_dump` emits all fields, so adding it there invalidates *every image recipe's* cache. Resolution: a discriminated `AudioSource` variant carries the field so image canonical bytes stay put. J.p adjusted.
- [x] **Verify Q3 — DR's `source_record_id` is already the documented consumer-bind for grouping.** Read [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § JSONL records. Document whether the field name can be carried verbatim from FR-11's documentation or whether the audio variant needs its own subsection. **Verified** (memo § Q3): field name carries, but semantics differ (window-of-clip vs. variant-of-image) → audio needs its own "Audio window records" subsection under § JSONL records. That is J.u's scope. "DR owns key; consumer owns aggregation" boundary is consistent with current posture.
- [x] **Verify Q4 — deferring audio-domain augmentations is consistent.** Trace R1–R7 to confirm no requirement transitively pulls in augmentation behavior; confirm the existing `Augmentations` contract would absorb future audio augmentations (SpecAugment-style time/freq masking) without a contract change. **Verified** (memo § Q4): R1–R7 map onto non-Augmentation stages; the modality-agnostic `AugmentationOp` (models.py:356) would absorb future SpecAugment ops with no contract change. Defer cleanly; no v1 surface.
- [x] **Verify R5 normalize feasibility — reuse or new op?** Read [`src/datarefinery/plugins/image_classification/operations/transformations.py`](../../src/datarefinery/plugins/image_classification/operations/transformations.py) `NormalizeOp` + `_per_channel_mean_std`. The existing impl computes `stack.mean(axis=axes_to_reduce)` where `axes_to_reduce = tuple(range(stack.ndim - 1))` — i.e., reduces across all axes except the last. Confirm whether this generalizes to per-mel-bin (where the "last axis" is the mel-bin axis in a `(time_frames, n_mels)` feature) or whether a new `audio_normalize` op is warranted. Recommended default: **reuse if the verify holds**, else split into `audio_normalize`. **Verified — verify does NOT hold; see memo Finding B.** Existing op keeps the *last* axis (transformations.py:226-240); librosa-native `(n_mels, n_frames)` has mel as axis 0, so reuse yields per-*frame* not per-*mel-bin* stats. Per J.n's own fallback → split into `audio_normalize` (B1), extracting a shared mean/std helper to bound duplication. J.t adjusted.
- [x] **Verify R4 spectral primitive — log-mel only for v1.** R4 lists "log-mel spectrogram, or MFCC." Recommended default for v1: **log-mel only**; MFCC moves to Future. Confirm against the requirements spec. **Verified** (memo § R4): nothing in R1–R8 or the acceptance criteria requires MFCC; log-mel only for v1, MFCC → Future. Feature orientation frozen as `(n_mels, n_frames)`.
- [x] **Decide decode library — librosa vs. soundfile vs. torchaudio.** Tradeoffs: librosa (featureful + numpy-coupled; pulls scipy/soundfile transitively), soundfile (thin libsndfile wrapper), torchaudio (framework-coupled, complicates pluggability). Recommended default: **librosa for both decode and featurization** (simplest one-dependency path). Confirm against project-essentials' Pyve env-management constraints. **Decided** (memo § Decode library): librosa for decode+featurize, behind an **`[audio]` optional extra** (mirrors `[corruptions]`/`[llm]` in pyproject.toml) to keep the base install lean; imported lazily inside op `apply` so plugin discovery/contract-tests don't require it.
- [x] **Write the design memo** at `docs/specs/phase-j-subphase-1-audio-design-memo.md` capturing each verified answer with file:line citations, and a "frozen design" section enumerating: stage placements (Generation: `window`; Featurization: `log_mel_spectrogram`; Transformations: `normalize`), field names (`source_record_id`, `window_index`, `feature`, `target_sample_rate`), decode library choice, and the per-mel-bin normalization axis decision. Written at [`phase-j-subphase-1-audio-design-memo.md`](phase-j-subphase-1-audio-design-memo.md): § 1 verifications (cited), § 2 Findings A/B, § 3 frozen-design table, § 4 downstream-story adjustments, § 5 conclusion.
- [x] Present the memo at the approval gate; the developer's confirmation freezes the design for J.o–J.w execution. **No code, no test, no version bump.** Presented; design frozen **pending developer sign-off on Findings A and B** at this gate.

**Out of Scope:**

- Implementing any audio op or scaffolding. Spike is investigation only.
- Renegotiating Q1–Q4 conclusions unless verification surfaces a blocker. Recommendations are accepted; the spike's job is to verify, not re-debate.
- Performance / latency analysis of decode-library candidates. Functional fit is the criterion.

---

### Story Bundle: Recipe Architecture Improvements

See [phase-j-recipe-architecture-spike.md](phase-j-recipe-architecture-spike.md).

---

### Story J.n.1: Design-decision memo — resolve open Qs Q1–Q8 [Done]

**Disposition: investigation spike** (throwaway; deliverable is the resolved-decisions memo, not code). Part of the Recipe Architecture bundle. No version bump.

The [spike memo](phase-j-recipe-architecture-spike.md) § 9 enumerates 7 substantive open design questions plus the Q8 vertical-axis decision. Settle them in a frozen tech spec at `docs/specs/phase-j-recipe-architecture-design.md` before implementation begins. Mirrors the I.r.0 / J.n spike pattern: spike findings produce a memo, the memo's resolved decisions land in a second memo, then implementation executes against the second memo without re-debating.

**Tasks:**

- [x] **Q1 — Plugin-surface representation.** **Decided** ([design § Q1](phase-j-recipe-architecture-design.md)): **section-granular segment-typed sub-models** (`core`/`plugin`/`overlays`/`extensions`) + **narrow discriminated union** on `InputSource.type` (`ImageSource | AudioSource`) for typed plugin source-fields; reject the disruptive nested-`plugin:` sub-doc. **Pivotal finding:** byte-isolation for Finding A comes from Q7 sparse hashing, *not* field relocation — segmentation's job is per-plugin versioning/validation/pin boundaries. Straddle rule: base source fields → `core`; discriminated-subclass extras (`target_sample_rate`) → `plugin:<name>`. (Highest-stakes decision.)
- [x] **Q2 — Overlay composition & identity.** **Decided** ([§ Q2](phase-j-recipe-architecture-design.md)): generalize today's variant to an **ordered multi-overlay list, last-writer-wins override**, open override-bags validated post-merge; **hash the resolved recipe** (definitions stripped, as today — [variants.py:44](../../src/datarefinery/recipe/variants.py#L44)); `manifest.variant` → `manifest.overlays: list[str]`. Verified the isolation property already exists; gap was only composability + naming.
- [x] **Q3 — `join_stable` shape.** **Decided** ([§ Q3](phase-j-recipe-architecture-design.md)): **ordered concatenation of per-segment SHA-256 digests** (`b"\x1f".join`), one fixed `EMPTY_MARKER` constant; **not Merkle** (~4–9 segments). Prefix-capable by construction (stage prefix = hash of a digest-list prefix) — keeps Q8 adoptable without redesign.
- [x] **Q4 — Versioning umbrella.** **Decided** ([§ Q4](phase-j-recipe-architecture-design.md)): **per-segment versions, no global umbrella**; structural era-detection (flat `schema_version` vs. segment-version block); migration keyed `(segment, from, to) → (dict→dict)`; one special flat→segmented bootstrap migration (the J.n.3 one-time event) that also injects old defaults explicitly (Q7).
- [x] **Q5 — Extensions namespace syntax.** **Decided** ([§ Q5](phase-j-recipe-architecture-design.md)): a single top-level **`extensions: {<namespace>: {<key>: <value>}}`** block (not `x-*`); `extra="forbid"` relaxes only inside; plugins declare `extension_keys()`, validator refuses undeclared keys; empty block contributes nothing (additive landing).
- [x] **Q6 — Validator adaptation.** **Decided** ([§ Q6](phase-j-recipe-architecture-design.md)): check_23 reserved set → plugin-provided **`loader_stamped_fields(recipe)`** hook; checks 19/20/21 → plugin-owned `validate_plugin_segment`. **Collapse** the Future "plugin-pluggable validator reserved-set hook" entry into the bundle (tracked under J.n.7).
- [x] **Q7 — No-implicit-defaults rollout mechanics.** **Decided** ([§ Q7](phase-j-recipe-architecture-design.md)): **drop `ParameterSpec.default`**; default-value params → `required` (scaffolder emits via plugin-provided `recommended_params`), mode-selecting (`normalize.mean`/`std`) kept; bootstrap migration injects old defaults explicitly so existing recipes stay valid; default-reintroduction CI guard. Verified ~28 defaults; scaffolder already value-emitting. Collapses the Future "default-change discipline tooling" entry.
- [x] **Q8 — Vertical stage-reuse decision.** **Decided** ([§ Q8](phase-j-recipe-architecture-design.md)): **decline for this bundle** (DR's flat gradient; rely on existing `export`/`report`/partial-run); `join_stable` stays prefix-capable (Q3) so a minimal cut is adoptable later without redesign. J.n.7 stage-boundary pin tests skipped.
- [x] Write the design memo at `docs/specs/phase-j-recipe-architecture-design.md` with explicit Q1–Q8 answers + file:line citations for any verification work. Present at the approval gate; the developer's confirmation freezes the design for J.n.2–J.n.7. Written; verification facts gathered + cited; presented at this gate.
- [x] **Cross-tool family coordination.** Per spike memo § 10, pass the resolved-decisions memo to ModelFoundry — they adopt the horizontal mechanism + no-implicit-defaults wholesale. Coordinate any divergence cross-repo before locking the design. **Developer-owned** (cross-repo, not executable from here): the design § "Cross-tool family coordination" enumerates the five points MF must mirror/diverge-on (Q3 join form, Q4 per-segment versioning, Q5 extensions grammar, Q7 no-defaults, Q1 horizontal segment set). **Confirmed at the J.n.1 gate (2026-06-13):** DR-side Q1–Q8 frozen; cross-repo reconciliation proceeds in ModelFoundry's `plan_phase` before its J.n.3-equivalent invalidation lands.

**Out of Scope:**

- Implementing the rearchitecture. This memo is settle-decisions only.
- Re-litigating the spike memo § 3 resolved stance (no-implicit-defaults, required-vs-optional rule, pre-1.0 zero support window) — those are settled. Q1–Q8 are the open dimensions.

---

### Story J.n.2: Segment-aware canonical hasher + per-segment versioning infrastructure [Done]

**Disposition: feature addition (infrastructure).** Part of the Recipe Architecture bundle.

Implement the segment-aware canonical-bytes machinery per the J.n.1 design memo: `join_stable(segments) → bytes`, per-segment hashing, empty-segment markers, per-segment version constants. Built alongside the existing flat-model `model_dump` canonical bytes (shadow mode) so the J.n.3 + J.n.4 mass invalidation can flip atomically rather than incrementally.

**Tasks:**

- [x] Implement `join_stable` per J.n.1 Q3 (concatenated digests or Merkle); ensure it supports cumulative-prefix composition (the deferred Q8 vertical-axis hook). Concatenated digests (`b"\x1f".join`) in new [`recipe/segments.py`](../../src/datarefinery/recipe/segments.py); `prefix_hash(digests, upto)` provides the vertical hook.
- [x] Define empty-segment markers; pin-test that an empty segment contributes a fixed nothing to the join. `EMPTY_MARKER` = domain-separated 32-byte constant; `segment_digest(empty)` returns it; pin-tested ({}/None/[]/"" → marker; extensions={} ≡ extensions=None).
- [x] Add per-segment version constants (e.g., `CORE_SCHEMA_VERSION`, `PLUGIN_IMAGE_SCHEMA_VERSION`, `PLUGIN_AUDIO_SCHEMA_VERSION`, `OVERLAYS_SCHEMA_VERSION`, `EXTENSIONS_SCHEMA_VERSION`). All five added (=1).
- [x] Add migration registry skeleton keyed per J.n.1 Q4 (`(segment, from, to) → migration_fn`). `SEGMENT_MIGRATIONS: dict[tuple[str,int,int], Callable[[dict],dict]] = {}` (empty; J.n.7 populates).
- [x] Provide a **dormant** shadow path: the segmented hasher exists alongside the authoritative flat `model_dump` hasher but does not yet drive the cache key. **Corrected per confirmed Q3** (the uniform-wrapping combiner makes the segmented hash *intentionally* ≠ the flat hash — that delta is J.n.3's one-time invalidation, not an error): shadow mode does NOT assert flat == segmented. It computes the segmented hash on a degenerate single-`core` wrapping of the flat recipe (no field distribution — J.n.3 owns that) and asserts **determinism** + that **the flat hasher remains authoritative** (cache key unchanged when shadow is on). J.n.3 flips authority to segmented and performs the real field distribution — the atomic flip. Implemented: `shadow_segments_from_flat` / `shadow_recipe_hash`; `RuntimeConfig.shadow_segmented_identity: bool = False`; runner computes + DEBUG-logs the shadow hash when on, authoritative flat key untouched.
- [x] Unit tests for `join_stable` determinism, empty-segment isolation, prefix-composition behavior, and shadow determinism / authoritative-key-unchanged on a sweep of fixture recipes. 16 unit tests in [`test_segments.py`](../../tests/unit/test_segments.py) + 1 integration test in [`test_shadow_segmented_identity.py`](../../tests/integration/test_shadow_segmented_identity.py) (shadow-on vs shadow-off → identical authoritative `recipe_hash` + instance path).
- [x] DOC: document the new internal API in [`tech-spec.md`](tech-spec.md) § Cache identity. Added `recipe.segments` subsection + a "being superseded" note on the flat-canonical subtlety.
- [x] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`. 1358 tests pass; mypy clean (218 files); ruff check + format clean.

**Out of Scope:**

- Moving any actual recipe field into a segment (J.n.3 owns).
- Per-segment migration logic + pin tests (J.n.7 owns the registry population + comprehensive pin-test discipline).

---

### Story J.n.3: Recipe model refactor into segments + plugin-surface representation closes Finding A [Done]

**Disposition: feature addition (mass refactor) + one-time pre-1.0 cache invalidation.** Part of the Recipe Architecture bundle. Closes spike memo Finding A.

Refactor `Recipe` from a flat pydantic model into a segmented one: `core`, `plugin`, `overlays`, `extensions`. Audio's `target_sample_rate` lands in the `plugin:audio` segment only — image recipes' canonical bytes are byte-identical before/after the refactor (modulo the one-time segment-combiner change). Per J.n.1 Q1, the plugin surface uses discriminated unions OR a nested sub-doc (whichever was chosen).

**This is the one-time pre-1.0 cache-invalidation event.** Every existing recipe re-materializes once. Acceptable now, prohibitive post-1.0 per spike memo § 8.

**Implementation decisions (developer-confirmed at the J.n.3 gate).**

- **Option 1 — internal partition, flat author-facing recipe** (vs. the rejected Option 3 author-facing nesting). Segmentation drives hashing / per-segment versioning / validation dispatch / pin boundaries; it is **not** an author-facing reshape. The recipe stays flat on disk. Decisive reasons: Option 1 keeps a future nested *authoring* mode reachable for free (the hash is over segment *content*, authoring-shape-independent) while Option 3 burns the pre-1.0 window on a reshape that isn't required for Finding A; and nesting would imply a stage hierarchy DR deliberately doesn't have (Q8 declined). The anti-footgun Option 3 would have given structurally is recovered by a **CI guard** that every `Recipe` field is assigned exactly one segment (`RECIPE_FIELD_SEGMENTS`). The author-readability UX of nesting is orthogonal — solvable with a validator/visualizer/wizard tool, not the identity model.
- **`schema_version` 2 → 3.** The combiner change is a canonical-form algorithm change, which `project-essentials.md` requires to ride a bump. v3 = the segmented-canonical era; the `(2, 3)` bootstrap is **version-stamp-only** (no field redistribution — Option 1; no default injection — that is Q7 / J.n.4). On-disk per-segment version block deferred to J.n.7 (per-segment version constants stay code-side in `segments.py`; the `(segment, from, to)` registry skeleton stays wired but empty).
- **Plugin source representation = open discriminated union.** `InputSource` is the open base (free-str `type` preserved); `AudioSource(InputSource)` adds `target_sample_rate`, selected **presence-based** (not on `type`, whose audio vocabulary is J.o's to define). `SerializeAsAny` so the subclass serializes its own fields; the base's `extra="forbid"` structurally enforces Finding A.

**Tasks:**

- [x] Refactor [`src/datarefinery/recipe/models.py`](../../src/datarefinery/recipe/models.py): split `Recipe` into segment-typed sub-models per J.n.1 Q1 + Q2 decisions. **Done as an internal partition** (Option 1) — `RECIPE_FIELD_SEGMENTS` + `segments_of` in [`recipe/segments.py`](../../src/datarefinery/recipe/segments.py) rather than nesting the author-facing model; `Recipe` stays flat. CI guard pins exact field→segment coverage.
- [x] Implement the chosen plugin-surface representation (discriminated unions or nested sub-doc); migrate every plugin-specific field into the active plugin's segment. **Open discriminated union** `InputSource | AudioSource` (presence-based selection, `SerializeAsAny`); `target_sample_rate` is the audio-only field, version-governed by `plugin:audio` (straddle rule).
- [x] Wire the runner / loader / validator / cache identity to use the segmented canonical bytes from J.n.2 (turn off shadow mode; segmented becomes the only path). `recipe_identity_hash` is authoritative; routed through `cache/identity.py`, `reporting/report.py`, `core/instance.py`, `cache/sibling_stats.py`. Shadow path retired (config flag, runner block, `shadow_*` fns, shadow tests removed).
- [x] Audio-specific verification: `target_sample_rate` and any other audio-only fields live in `plugin:audio` only; pin-test that they do NOT appear in image recipes' canonical bytes (the direct resolution of J.n Finding A). `tests/unit/test_recipe_segmentation.py` + `tests/integration/test_segmented_identity.py`.
- [x] Migration logic v1 → vN (where N is the new segmented version) keyed by `(segment, from, to)` per J.n.2's registry. The loader applies migrations on read; the cached `recipe.json` reflects the new segmented shape. `v2_to_v3` whole-recipe bootstrap (design Q4); loader `SUPPORTED={1,2,3}`, `LATEST=3`. Per-`(segment, from, to)` registry stays wired-but-empty for J.n.7; recipe stays flat (version-stamp-only) per Option 1.
- [x] Update all fixture recipes to the new segmented shape. **N/A under Option 1** — recipes stay flat; the only fixture-facing changes are the re-pinned canonical hash and `schema_version` 2→3 assertions (loader migrates authored v1/v2 fixtures).
- [x] Integration test: image-fixture pin test shows hash UNCHANGED across an audio-plugin-surface change. Audio-fixture pin test shows hash CHANGED only for audio-segment changes. `tests/integration/test_segmented_identity.py` (pinned image + audio identities; both directions).
- [x] DOC: update [`tech-spec.md`](tech-spec.md) § Data Models to describe the segmented recipe shape. Updated § `recipe.segments` (authoritative) + § Data Models (`AudioSource` union, flat-stays).
- [x] CHANGELOG entry under the in-progress v0.22.0 section: one-time pre-1.0 cache invalidation; document recompute cost and rationale. Added under [Unreleased] (Recipe Architecture bundle / v0.22.0; J.n.9 owns the release section).
- [x] **Cross-repo coordination.** Update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § Recipe-side contract + § Cache-identity contract; mirror in [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md). Full sweep of cross-repo docs lives in J.n.8; this story carries the local diffs that directly correspond to the refactor.
- [x] CI parity. 1377 tests pass; mypy clean (219 files); ruff check + format clean.

**Out of Scope:**

- No-implicit-defaults rollout (J.n.4 owns).
- Overlay reconsideration as first-class composable dimension (J.n.5 owns).
- Extensions namespace (J.n.6 owns).
- Full per-segment pin-test suite (J.n.7 owns); initial pin tests for Finding A + flat→segmented parity land here.

---

### Story J.n.4: No-implicit-defaults rollout [Done]

**Disposition: feature addition (mass refactor + orthogonal mass change) + one-time pre-1.0 cache invalidation.** Part of the Recipe Architecture bundle.

Adopt the spike memo § 3 resolved stance #1: kill code-supplied defaults. The interpreting code supplies no behavior-affecting value; the scaffolder (`init`) emits recommended values explicitly into the recipe text, so they are in canonical bytes, audit-visible, and versioned. Mode-selecting optionality (where absence is itself meaningful — `normalize.mean: None ⇒ "fit from train"`, `log_mel_spectrogram.f_max: None ⇒ "Nyquist"`) is KEPT, but the "absent ⇒ behavior" mapping becomes part of the versioned plugin-segment contract.

**This is orthogonal to but coordinated with J.n.3** — both ship in the same pre-1.0 mass-invalidation window to keep the user-visible blast radius a single re-materialization event, not two.

**Implementation decisions (developer-confirmed at the J.n.4 gate).**

- **Break + re-author, no migration injection** (developer-chosen over Q7's "bootstrap injects old defaults"). Per spike § 3's pre-1.0 zero-support-window, a recipe omitting a now-required param fails validation with a clear "missing required param" message (check 18); fixtures/examples are updated to carry values explicitly. Keeps the loader plugin-agnostic (no frozen op-default table, no loader↔plugin coupling). The combined J.n.3+J.n.4 invalidation stays a single window (bundle releases once at J.n.9).
- **Strict removal at both layers.** `ParameterSpec.default` field removed entirely (extra="forbid" turns any reintroduced `default=` into a construction error); code-supplied defaults removed at *both* the op-implementation `.get(key, fallback)` sites and the runtime param-model `Field(default=…)`. Required params are enforced at validate time (check 18) *and* at the param model (so an unvalidated path errors rather than silently substitutes).
- **`recommended_params(section, op) -> dict` is the new home** for the removed recommended values (added to the `Plugin` protocol + `_REQUIRED_PLUGIN_ATTRS`; the scaffolder's curated starter values stay inline — they intentionally override op recommendations, e.g. `sample_grid.per_class: true`). This is also the substrate for the author-assist tooling discussed at the J.n.3 gate.

**Tasks:**

- [x] Audit every `ParameterSpec(default=…)` in [`src/datarefinery/plugins/base.py`](../../src/datarefinery/plugins/base.py) and per-plugin op definitions; classify each as default-value (eliminate) or mode-selecting (keep). ~25 default-value params across image (~21) / text (3) / tabular (2) → required; only `normalize.mean`/`std` kept mode-selecting (already `required=False`, no default).
- [x] Drop `default=` from every default-value-optionality param. Removed the `default` field from `ParameterSpec` and every call site; removed the matching `.get(...)` op-impl defaults and runtime `Field(default=…)`.
- [x] Re-express `required` per J.n.1 Q7. Default-value params flipped to `required=True`.
- [x] Update the scaffolder ([`scaffolder/init.py`](../../src/datarefinery/scaffolder/init.py)) to emit recommended values explicitly into every scaffolded recipe section. Already value-emitting; verified by a new test (every required param of every scaffolded op appears verbatim). `recommended_params` added as the plugin-owned value home.
- [x] Update every fixture recipe AND every example recipe under [`docs/guides/`](../guides/) to carry values explicitly. No YAML fixtures (recipes built programmatically); `recipe-authoring.md` examples updated (categorical_encode Mode 1 `ordering`; filter_by_label prose). ~70 unit/integration tests updated to pass the now-required params explicitly.
- [x] Unit test: scaffolder output validates AND materializes AND every value appears verbatim. Validates + verbatim in `test_scaffolder.py`; materialize end-to-end covered by the existing `test_golden_path_init_validate_materialize_status` (init→validate→materialize on the scaffolded recipe).
- [x] Pin test: a `default=` re-introduction anywhere in any `ParameterSpec` fails CI. [`tests/unit/test_no_implicit_defaults.py`](../../tests/unit/test_no_implicit_defaults.py) (field-absence + construction-rejection + no-op-declares-a-default + recommended_params pins).
- [x] DOC: update [`recipe-authoring.md`](../guides/recipe-authoring.md). New "No implicit defaults" section + corrected op prose/examples.
- [x] DOC: update [`plugin-authoring.md`](../guides/plugin-authoring.md). Required-vs-mode-selecting rule, `recommended_params` in the protocol table + hello-plugin example, seven-attribute conformance.
- [x] CHANGELOG entry. Added under the [Unreleased] Recipe Architecture bundle section (same v0.22.0 window as J.n.3).
- [x] CI parity. 1384 tests pass; mypy clean (220 files); ruff check + format clean.

**Out of Scope:**

- Per-segment migration registry / broader pin tests (J.n.7 owns; the default-reintroduction guard is included here as a regression test).
- Tooling to detect historical `ParameterSpec` default changes — the Future "default-change discipline tooling" entry collapses into J.n.4 + J.n.7.

---

### Story J.n.5: Overlays mechanism — `variants` as first-class composable overlays [Done]

**Disposition: feature addition.** Part of the Recipe Architecture bundle.

Per spike memo § 4 and J.n.1 Q2: reconsider `variants` (FR-14) as first-class orthogonal overlays with independent identity. Today variants collapse into the base before hashing; under the new model each overlay hashes independently, their composition is order-stable, and recipes with no overlays carry an empty `overlays` segment contributing nothing to canonical bytes (pin-tested in J.n.7).

**Implementation notes.**

- **Verified the isolation property already held** (J.n.1 Q2): unused/other overlay definitions are stripped before hashing, so the genuine gap was only *composability* (single-select → ordered-multi) and *naming*. So this story is a **rename + generalize**, not new identity machinery.
- **`variants` → `overlays`** (recipe section, `recipe/variants.py` → `recipe/overlays.py`, `apply_variant(name)` → `apply_overlays(names)`), selection generalized to the repeatable `--overlay` (ordered, last-writer-wins per section). Library: `from_recipe(overlays=…)`, `resolve_instance(overlays=…)`, `materialize(overlays=…)`, `DataRefinery.overlays` property.
- **Hash-neutral rename folded into the J.n.3 `v2_to_v3` bootstrap** (no v4): overlay definitions are stripped before hashing, so `variants:`→`overlays:` doesn't move the resolved hash — it rides the single v0.22.0 invalidation window. (Confirmed: the J.n.3 canonical-hash pin is unchanged.)
- **`manifest.variant: str | None` → `manifest.overlays: list[str]`; MANIFEST_SCHEMA_VERSION 1 → 2.** Pre-1.0 break: old (v1) manifests don't parse against the v2 model, but the bundle's cache invalidation re-materializes every instance, so no v1 manifest survives — consistent with the J.n.4 break-and-re-author stance; no manifest migration shipped.

**Tasks:**

- [x] Refactor `variants` into the segmented `overlays` representation per J.n.1 Q2 decisions (ordering/conflict rules; open override-bag). `recipe/overlays.py` `apply_overlays(recipe, names)` — ordered, last-writer-wins per section.
- [x] Update loader / runner / validator to apply overlays in declared order with independent per-overlay identity. Loader `KNOWN_TOP_LEVEL_KEYS`, `segments.py` partition, runner/manifest, validator check 12 (`overlays_reference_declared_sections`), CLI `--overlay`, `core/datarefinery.py` facade + module functions, `sibling_stats`, `export`.
- [x] Migration for existing variant-using recipes: the migrated recipe's canonical bytes match the old variant-using recipe's bytes. `v2_to_v3` renames `variants`→`overlays` (hash-neutral; single window).
- [x] Pin test: a recipe with no overlays hashes identically before/after. Proven by the unchanged J.n.3 canonical-hash pin + `test_no_overlays_selected_hashes_like_no_overlays_defined` (additivity) in [`test_overlays.py`](../../tests/unit/test_overlays.py).
- [x] Unit tests: overlay composition ordering; conflict resolution (last-writer-wins, order-dependent identity); independent identity per overlay. [`test_overlays.py`](../../tests/unit/test_overlays.py) (14 tests).
- [x] Integration test: a multi-overlay recipe materializes deterministically; the report's overlay echo names every applied overlay. [`test_overlays_materialize.py`](../../tests/integration/test_overlays_materialize.py).
- [x] DOC: update [`recipe-authoring.md`](../guides/recipe-authoring.md) § Variants → Overlays; document composition rules. Also updated `tech-spec.md` (`recipe.overlays`, Manifest v2).
- [x] **Cross-repo coordination.** [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) (`manifest.overlays`, manifest schema → v2, schema-version coordination) + [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) (library/CLI overlay signatures). Full sweep is J.n.8.
- [x] CHANGELOG entry. Added under the [Unreleased] Recipe Architecture bundle section.
- [x] CI parity. 1391 tests pass; mypy clean (221 files); ruff check + format clean.

**Out of Scope:**

- Net-new overlay capabilities beyond what `variants` provides today — this is a refactor + isolation story, not a feature expansion. Net-new overlay types are post-bundle.

---

### Story J.n.6: Extensions namespace + plugin extension-key declaration [Done]

**Disposition: feature addition.** Part of the Recipe Architecture bundle.

Per spike memo § 4 and J.n.1 Q5: introduce the sanctioned `extensions:` namespace (or `x-*` keys, per Q5) where `extra="forbid"` is relaxed inside the namespace only. Plugin/hook code reads extension parameters; the namespace enters identity only when non-empty (empty for everyone at landing time → no existing cache breaks).

**Strict scope per spike memo § 6.** Extensions carry **parameters** (data read by installed plugin code). Recipe-activated arbitrary code is explicitly OUT — that's a separate trust-boundary effort if ever pursued. The recipe stays a declarative artifact.

**Tasks:**

- [x] Add the `extensions:` block (or `x-*` keys) per J.n.1 Q5 syntax decision; relax `extra="forbid"` inside the namespace only. Per Q5: single top-level `extensions: dict[str, dict[str, Any]]` block ([models.py](../../src/datarefinery/recipe/models.py)); the inner namespace mapping is a free `dict[str, Any]`, so arbitrary keys are accepted *inside* a namespace while every other recipe surface stays strict (`_Frozen` `extra="forbid"`). Loader `KNOWN_TOP_LEVEL_KEYS` += `extensions` (no spurious unknown-key warning).
- [x] Plugin extension-key declaration mechanism: plugins enumerate which extension keys they consume; the validator validates that every extension key in a recipe is declared by an installed plugin. Undeclared keys → refuse with a clear message naming the unknown key. New `Plugin.extension_keys() -> dict[str, set[str]]` (namespace → consumed keys) on the protocol ([base.py](../../src/datarefinery/plugins/base.py)) + all three built-ins (return `{}`) + `discovery._REQUIRED_PLUGIN_ATTRS`. New validator **check 28** ([validator.py](../../src/datarefinery/recipe/validator.py)) refuses any undeclared namespace or key against the recipe's bound plugin, naming the offender; empty `extensions` passes trivially without consulting the plugin.
- [x] Identity: `extensions` segment contributes nothing when empty (pin-tested in J.n.7). `RECIPE_FIELD_SEGMENTS["extensions"] = "extensions"` ([segments.py](../../src/datarefinery/recipe/segments.py)); `segments_of` folds the bare namespace mapping, empty → `EMPTY_MARKER`. Verified additive: the pinned image-recipe identity in `test_segmented_identity.py` is unchanged.
- [x] Unit + integration tests: empty extensions (cache identity unchanged from a no-extensions baseline); declared extension keys validate; undeclared keys refuse; relaxed `extra="forbid"` inside the namespace; strict elsewhere. [`tests/unit/test_extensions_namespace.py`](../../tests/unit/test_extensions_namespace.py) (11 tests: model relaxation/strictness, plugin declaration, check-28 pass/fail/multi-offender) + identity additivity tests appended to [`test_recipe_segmentation.py`](../../tests/unit/test_recipe_segmentation.py) (5) + [`tests/integration/test_extensions_namespace.py`](../../tests/integration/test_extensions_namespace.py) (5: loader round-trip, identity additivity end-to-end, declared-pass via discovered plugin, real-plugin refusal).
- [x] DOC: update [`recipe-authoring.md`](../guides/recipe-authoring.md) with the extensions namespace, including the spike memo § 6 trust-boundary callout: extensions are declarative parameters only; recipe-activated code is a separate effort. Added `## Extensions` section + top-level-keys table row.
- [x] DOC: update [`plugin-authoring.md`](../guides/plugin-authoring.md) to explain plugin extension-key declaration. Added `## Declaring consumed extension keys` section + protocol-table row + `extension_keys` in the protocol sketch and Hello walk-through.
- [x] CHANGELOG entry: additive (no canonical-bytes perturbation for existing recipes — empty namespace marker contributes nothing). Added under the Phase J bundle.
- [x] CI parity. `pyve test` (1410 pass), `mypy src tests` (clean, 223 files), `ruff check` + `ruff format --check` (clean). Check-count assertions bumped 27→28 in `test_validator.py`, `test_tabular_stub_smoke.py`, and three CLI-output integration tests; `extension_keys` added to all test fake plugins now typed against `Plugin`.

**Out of Scope:**

- Recipe-activated arbitrary code / hook execution — explicitly out per spike memo § 6 trust boundary.
- "Promotion" tooling to move an extension into core/plugin scope — manual today; tooling is post-bundle.

---

### Story J.n.7: Per-segment migration registry + per-segment canonical-hash pin tests [Done]

**Disposition: feature addition + enforcement infrastructure.** Part of the Recipe Architecture bundle. **Subsumes** the existing [`stories.md § Future`](stories.md) "Default-change discipline tooling for cache-identity stability" entry — remove that Future entry as part of this story.

Replace the single global `schema_version` with per-segment versions and per-segment migrations. Pin-test every segment in isolation so isolation is enforced, not asserted. Per spike memo § 7.

**Tasks:**

- [x] Populate the migration registry from J.n.2's skeleton: `(segment, from, to) → migration_fn`. Migrations run during the loader's read path; the cached `recipe.json` always reflects the latest segmented shape. **Per the confirmed [versioning-model decision](phase-j-recipe-architecture-design.md) (2026-06-22 gate):** flat `schema_version` stays the on-disk era marker (Option 1 — no on-disk segment-version block, so per-segment versioning adds **no** new invalidation). [`segments.py`](../../src/datarefinery/recipe/segments.py) gains `SEGMENT_VERSION_KEYS`, `SCHEMA_ERA_SEGMENT_VERSIONS` (structural era-detection table), `current_segment_versions()`, `segment_versions_for_era()`, and `apply_segment_migrations(flat, from, to)` — which partitions the flat dict, replays `SEGMENT_MIGRATIONS[(segment, v, v+1)]` per segment (plugin-family-gated for Finding A), and re-flattens. Wired into [`loader.load`](../../src/datarefinery/recipe/loader.py) after the flat chain. **Exact pass-through in the steady state** (every segment at the current era → no perturbation); registry empty today (no segment has bumped). A missing migration for a version gap is a hard load error.
- [x] Per-segment canonical-hash pin tests: image core/plugin, audio core/plugin, empty-overlays/extensions → `EMPTY_MARKER`. Each segment digest is pinned independently in [`tests/unit/test_segment_pin_hashes.py`](../../tests/unit/test_segment_pin_hashes.py); an unexpected move of any single segment's digest is a blocking CI failure forcing a conscious per-segment bump + migration. Cross-plugin isolation enforced (Finding A at segment granularity: an audio-surface change leaves both image segment digests byte-identical, and vice-versa); unused-overlay additivity pinned (definitions stripped by `apply_overlays(None)` → identity + every segment digest unchanged); extensions additivity pinned (perturbs only the `extensions` digest).
- [x] Pin test for the no-implicit-defaults rollout (J.n.4): default-reintroduction anywhere in any `ParameterSpec` fails CI. **Already satisfied** by [`tests/unit/test_no_implicit_defaults.py`](../../tests/unit/test_no_implicit_defaults.py) (`test_parameter_spec_has_no_default_field`, `test_parameter_spec_rejects_a_default_kwarg`, `test_no_registered_op_declares_a_parameter_default` sweep over all installed plugins) — verified covers this task; no new test needed.
- [x] (Optional, per J.n.1 Q8) Stage-boundary pin tests — **skipped: Q8 declined for this bundle** (DR's flat gradient). `prefix_hash` keeps the vertical axis adoptable later with no combiner redesign.
- [x] DOC: update [`tech-spec.md`](tech-spec.md) § Cache Identity to describe per-segment versions + migration registry + pin-test discipline. Added the "Per-segment versions + migrations" + "Pin-test discipline" paragraphs under `recipe.segments`.
- [x] Remove the [`stories.md § Future`](stories.md) "Default-change discipline tooling for cache-identity stability" entry (subsumed by the per-segment pin tests + no-defaults guard). Removed; this story is the subsuming work.
- [~] If J.n.1 Q6 decided so: collapse the Future "plugin-pluggable validator reserved-set hook" entry into this story; otherwise leave as-is. **Flagged for developer at the gate (see below):** Q6 decided to collapse the *decision* into the bundle, but the *implementation* (`Plugin.loader_stamped_fields` / `validate_plugin_segment`) is not in J.n.7's task checklist and was not built here. Left the Future entry intact rather than misrepresent it as done — recommend a follow-up story or an explicit J.n.7 scope expansion.
- [x] CHANGELOG entry. Added under the Phase J bundle.
- [x] CI parity. `pyve test` (1430 pass), `mypy src tests` (clean, 225 files), `ruff check` + `ruff format --check` (clean).

**Out of Scope:**

- Cross-repo doc updates beyond the local tech-spec changes (J.n.8 owns the cross-repo sweep).

---

### Story J.n.8: Cross-repo coordination — vendor-dependency-spec + project-essentials updates [Done]

**Disposition: cross-repo contract authoring.** Part of the Recipe Architecture bundle.

Per spike memo § 10: the horizontal segmented-identity mechanism + no-implicit-defaults discipline are the **cross-tool-family standard**. ModelFoundry adopts wholesale (NbFoundry mirrors per its CLI/library binding). Update both vendor-dependency-specs and `project-essentials.md` to reflect the new architecture and pin it as the shared family standard with the same governance status as the existing cross-repo contracts.

**Tasks:**

- [x] Update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md):
  - § Cache-identity contract: segmented model already landed in J.n.3; **added** a "Per-segment versioning + migration registry (Story J.n.7)" subsection citing the spike memo as the cross-tool-family architectural rationale. **Deviation from task wording:** did **not** delete the "Schema v1 → v2" subsection — it documents real consumer-binding field reshapes (FilterOp/GenerationOp/assertion names), not identity, so it is not "superseded by segmented identity"; deleting it would strand the consumers this story exists to protect. Reframed around segmented identity instead. Flagged at the gate.
  - § Recipe-side contract: **added** a "Segment-scoped recipe shape" subsection with a field→segment table (core / plugin / overlays / extensions) + the `extensions` namespace (J.n.6) + no-implicit-defaults (J.n.4) notes.
  - § Schema-version coordination policy: **added** a "Per-segment coordination" paragraph — flat `recipe.schema_version` stays the consumer-facing counter (no on-disk segment-version block); consumers MAY read `current_segment_versions()` for granularity but bind to the flat counter.
- [x] Update [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) parallel sections: expanded the "Schema v2 → v3" entry with per-segment versioning + extensions + no-implicit-defaults bullets (binding-neutral for NbF; only matters to cells that *read* recipe internals), pointing to the MF spec for full detail.
- [x] Update [`project-essentials.md`](project-essentials.md) § "Cache identity is the reproducibility contract" — replaced the flat `model_dump` / "every pydantic field default is in canonical bytes" framing with segmented identity + per-segment versioning; rewrote the warning to scope it to structural/algorithm/output-byte changes and note no-implicit-defaults removed the op-param silent-default layer.
- [x] Add new [`project-essentials.md`](project-essentials.md) entry: **"No implicit defaults — the interpreting code supplies no behavior-affecting value."** Required-vs-mode-selecting rule; recommended values → scaffolder; cross-tool-family standard; zero pre-1.0 support window; Why / How-to-apply per template + a refuse-this-tempting-move example.
- [x] Extend [`project-essentials.md`](project-essentials.md) § "Recipe / manifest / report shape changes need a cross-repo coordination check" — surface #1 (Recipe model) now names the four segments (`core`, `plugin:<name>`, `overlays`, `extensions`) as separately-bumping contract surfaces, with the Finding-A / additive-extensions / flat-on-disk caveats.
- [~] **ModelFoundry coordination.** Confirm MF's wholesale adoption of horizontal mechanism + no-implicit-defaults per spike memo § 10. **Developer-owned** (cross-repo, not executable from this repo) — mirrors the J.n.1 cross-tool-family coordination task. The DR-side specs now pin the standard; MF/NbF adopt in their own repos. Vertical axis stays MF-owned (DR may adopt a minimal cut later per J.n.1 Q8).
- [x] CHANGELOG entry: cross-repo contract change; segmented identity + per-segment versioning + no-implicit-defaults adopted as cross-tool-family standard.
- [x] CI parity (doc-only; no code change). `pyve test` (1430 pass), `mypy` clean, `ruff check`/`format` clean — confirmed unchanged (docs don't affect them).

**Out of Scope:**

- Net-new contract surfaces beyond what segmented identity introduces.
- ModelFoundry-side / NbFoundry-side implementation of their adoption — owned by their repos.

---

### Story J.n.9: v0.22.0 release — Phase-J Recipe Architecture bundle close [Done]

**Disposition: release bundle.** Part of the Recipe Architecture bundle (closing story).

Phase-bundle release closing the rearchitecture work. Bumps the package version to v0.22.0, writes the CHANGELOG release entry with prominent blast-radius announcement (one-time pre-1.0 mass cache invalidation), and presents the final state at the approval gate. **After this lands, Subphase J-1 audio (J.o–J.w) resumes against the segmented foundation.**

**Tasks:**

- [x] Bump [`src/datarefinery/__init__.py`](../../src/datarefinery/__init__.py) `__version__` to `"0.22.0"`. Hatchling reads this as the single source of truth — no `pyproject.toml [project].version` edit per memory `[[project_version_single_source]]`. Editable install reprovisioned (`pyve env run pip install -e .`) so installed metadata matches; `datarefinery --version` → `0.22.0`; `test_version_single_source.py` green.
- [x] CHANGELOG entry under `## [0.22.0]`: `[Unreleased]` converted to `## [0.22.0] - 2026-06-22 — Phase J Recipe Architecture bundle`. Leads with the **⚠️ one-time pre-1.0 mass cache-invalidation** blockquote (recompute cost + rationale, cites spike/design memo § 8), then Breaking / Added / Changed / Cross-repo coordination / Removed / Notes summary sections, with the existing per-story bullets retained under "Per-story detail".
  - **Removed framing corrected:** worded as removing the *global-umbrella versioning model* — the flat `recipe.schema_version` **remains on disk** as the era marker (per the J.n.7 versioning-model decision), not gone. The Future "plugin-pluggable validator reserved-set hook" entry is **explicitly NOT** removed (J.n.1 Q6 folded the decision in, but J.n.7 did not implement it — tracked follow-up).
- [x] Cross-repo coordination final check: [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md), [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md), and [`project-essentials.md`](project-essentials.md) confirmed current per J.n.8 (no further edits needed).
- [x] Run the full local-verification suite per memory `[[feedback_local_verification_mirrors_ci]]`: `pyve test` (1430 pass), `mypy src tests` (clean, 225 files), `ruff check src/ tests/` + `ruff format --check src/ tests/` (clean), **and the per-module core-invariant coverage gate** (`coverage report --include=<module> --fail-under=95` for each of the 8 gated modules — all pass). **CI follow-up:** the gate first failed on `plugins/base.py` (93% < 95) — the new `extension_keys` multi-line protocol stub added a second uncovered bare-`...` statement (the J.n.6 `extension_keys` + J.n.4 `recommended_params` stubs). Fixed in [`pyproject.toml`](../../pyproject.toml) by excluding `^\s*\.\.\.$` stub bodies in `[tool.coverage.report].exclude_lines` (durable — protects J.o's forthcoming `loader_stamped_fields` protocol stub too). Memory `[[feedback_local_verification_mirrors_ci]]` updated to include the coverage gate (it was the missing local step).
- [x] Present at the approval gate. After approval, Subphase J-1 audio resumes.

**Out of Scope:**

- Vertical stage-reuse implementation — per J.n.1 Q8, either deferred entirely or scoped to a post-bundle story for the minimal expensive-boundary cut.
- Audio plugin work (J.o–J.w) — paused through this release; resumes after.
- Tagging / pushing the release — developer-initiated.

---

### Story J.o: `audio_classification` plugin scaffold + protocol conformance [Done]

**Disposition: feature addition (plugin seam).** Part of Phase J phase-bundle release. Closes R8.

Stand up the bare `audio_classification` plugin so the existing plugin-discovery, validator, and contract-test machinery has a registered seam to build against. The plugin starts with `supported_operations = []` and `is_stub() → False` (real plugin, just empty). Subsequent stories J.p–J.t fill in operations.

**Tasks:**

- [x] Add [`plugins/audio_classification/__init__.py`](../../src/datarefinery/plugins/audio_classification/__init__.py) + [`plugin.py`](../../src/datarefinery/plugins/audio_classification/plugin.py): `name = "audio_classification"`, `supported_sections` = full standard set (per design memo § 4 — includes the frozen audio stages Generation/Featurizations/Transformations + the mandatory Input/Output/Labels/Splits; "inheriting the rest costs nothing"), `supported_operations = {}`, `is_stub() → False`, `operation_factory` raises `PluginError` naming section/op. Plus `recommended_params`/`extension_keys` (return `{}`) so it satisfies the J.n.4/J.n.6 protocol additions.
- [x] Register the plugin via the `datarefinery.plugins` entry-point group in [`pyproject.toml`](../../pyproject.toml); editable reinstall (`pyve env run pip install -e .`) so discovery finds it.
- [x] Add `loader_stamped_fields(recipe)` hook stub — returns `set()` in the scaffold; J.p–J.t populate it as field-stamping ops land. **Scoped narrowly per J.n.1 Q6:** only the audio plugin's stub is in J.o; wiring the hook into validator check 23 across all plugins remains the separate Q6 follow-up.
- [x] Unit / contract test: [`tests/plugin_contract/test_audio_classification.py`](../../tests/plugin_contract/test_audio_classification.py) — loads via discovery, correct name, `is_stub() → False`, empty op list, `operation_factory` raises, `recommended_params`/`extension_keys`/`loader_stamped_fields` empty.
- [x] Plugin-contract/materialize test: minimal `plugin: audio_classification` recipe validates cleanly (all 28 checks) **and** materializes an empty-op instance ([`tests/integration/test_audio_scaffold.py`](../../tests/integration/test_audio_scaffold.py)). **Scope note:** audio input/decode is J.p, so the seam test injects records via the runner's `raw_records=` path (the same pattern other runner integration tests use) rather than reading an audio source from disk — the point is the zero-op pipeline seam, not audio I/O. Also relaxed the generic `test_protocol.py::test_is_stub_reflects_factory_behavior` to permit a non-stub plugin with an intentionally-empty op set (the new scaffold case).
- [x] DOC: [`plugin-authoring.md`](../guides/plugin-authoring.md) intro updated — `audio_classification` listed as the second real plugin, validating the plugin-interface honesty goal from `concept.md`/`features.md`.
- [x] CI parity: `pyve test` (1446 pass), `mypy src tests` (clean, 229 files), `ruff check` + `ruff format --check` (clean), per-module core-invariant coverage gate (all 8 ≥ 95%; new audio package at 100%). Fixed en-dash (RUF00x) + list-invariance (`list[Mapping]`) + E501 issues surfaced by the full gate.

**Out of Scope:**

- Any audio op implementation (J.p–J.t own).
- Updating `tabular` / `text` stubs — separate Future stories.

---

### Story J.p: Audio input sources + decode (R1 + R2) [Done]

**Disposition: feature addition.** Part of Phase J phase-bundle release. Closes R1 + R2.

Implement the two audio input source kinds (parallel to `image_folder` and `image_flat` with `label_from`) and the decode operation that produces a canonical in-pipeline representation: `(record_id, sample_array, sample_rate, path)`. Decode honors a recipe-declared canonical sample rate (Q2 settled in J.n; default `16000 Hz`).

**Tasks:**

- [x] Implement `audio_folder` source kind in [`plugins/audio_classification/inputs.py`](../../src/datarefinery/plugins/audio_classification/inputs.py): class-subdir form; labels from immediate-parent dir name; `record_id = "<source>/<class>/<file>"` matching the `image_folder` pattern.
- [x] Implement `audio_flat` source kind with `label_from` — both `by_id` (join on file stem) and `by_row_order`; reuses the image loader's `_build_label_index`.
- [x] Support `unlabeled: true` partitions for both source kinds — `audio_flat` + `unlabeled` attaches no label; `audio_folder` + `unlabeled` is refused (declare `audio_flat`), mirroring the image rule. Label-dependent stages already refuse on unlabeled splits (check 21, plugin-agnostic).
- [x] Implement decode (loader-side per memo § 3, **not** a recipe op): librosa reads + resamples to the source's `target_sample_rate`, emits `{record_id, sample_array, sample_rate, path[, label]}` (mono float32). Lazy librosa import → module importable without the extra; `PluginError` if invoked without it.
- [~] ~~Add `target_sample_rate: int = 16000`~~ — **superseded.** J.n.3 already shipped `AudioSource.target_sample_rate: int = Field(gt=0)` (required), and the union selection is presence-based, so a default would break selection and reintroduce an implicit default against J.n.4. **Confirmed at the gate (2026-06-22): keep required** — no model change. Audio authors write the canonical rate explicitly; the loader refuses a non-`AudioSource` reaching it.
- [x] Add `librosa` (+ transitive `soundfile`) as the **`[audio]` optional extra** (memo decision — keeps the default install lean), not a base dependency. mypy override added for the stub-less libs; CI install line → `".[corruptions,audio]"`.
- [x] Unit tests: decode determinism (byte-identical array), resampling, cross-source-rate canonicalization to one target, `unlabeled` handling, `audio_flat` `by_id`/`by_row_order`, non-`AudioSource` refusal, `hash_audio_sources` ([`tests/plugins/audio_classification/test_audio_inputs.py`](../../tests/plugins/audio_classification/test_audio_inputs.py), 8). `importorskip` so they skip without `[audio]`.
- [x] Integration test: 3-clip mixed-rate `audio_folder` fixture through `load_raw_records` → `(count=3, sample_rate=16000, mono ~1600-sample shapes)` + content-hash stability ([`tests/integration/test_audio_inputs.py`](../../tests/integration/test_audio_inputs.py)).
- [x] DOC: [`recipe-authoring.md`](../guides/recipe-authoring.md) § Input → new "Audio sources" subsection.
- [x] CHANGELOG entry under a new `## [Unreleased]` "Subphase J-1 — Audio classification" section (v0.22.0 already shipped; the audio bundle ships at J.w).
- [x] CI parity: `pyve test` (1456 pass; audio tests run locally with librosa installed), `mypy src tests` (clean, 233 files), `ruff check`/`format` (clean), core-invariant coverage gate (all 8 ≥ 95%; new audio inputs module 90%).

**Out of Scope:**

- Any windowing or featurization (J.q+).
- Multi-channel (stereo) audio — v1 is mono-focused; stereo to Future if a consumer needs it.
- Audio augmentations (Future).

---

### Story J.q: Windowing as a Generation op (R3) [Done]

**Disposition: feature addition.** Part of Phase J phase-bundle release. Closes R3.

Implement the windowing op that turns a variable-length decoded clip into N fixed-length window records, with author-declared window length and hop. Window records carry `source_record_id` (the parent clip's id) so R7 aggregation can group them. Trailing-remainder policy (pad vs. drop) is author-declared and deterministic. Window-`record_id` derivation follows the J.n design memo (recommended: `f"{source_record_id}__w{window_index:04d}"`, mirroring H.r.2 aggressive variants' `__v{i:03d}`; 4-digit width chosen to accommodate typical clip→window counts up to ~10k).

**Tasks:**

- [x] Implement `window` op in [`plugins/audio_classification/operations/generation.py`](../../src/datarefinery/plugins/audio_classification/operations/generation.py): standard Generation-op signature; `WindowParams` (pydantic, frozen, `extra=forbid`) with the one-of length forms + required `hop_samples`/`remainder`; emits `{record_id: "<parent>__w0042", source_record_id, window_index, sample_array, sample_rate, path, label …inherited}`. A window begins at every `hop_samples` offset; trailing partial → zero-padded (`pad_zero`) or skipped (`drop`).
- [x] Register the op in `supported_operations` (`OperationSpec`, Generation, `fit_on_train: False`, params schema) + `recommended_params` (`{window_length_seconds: 1.0, hop_samples: 8000, remainder: "drop"}`); `operation_factory` dispatches `Generation/window`.
- [x] Unit tests ([`tests/plugins/audio_classification/test_window_op.py`](../../tests/plugins/audio_classification/test_window_op.py), 11): count math under `pad_zero`/`drop`, `source_record_id`/`window_index`/record-id format, inheritance, seconds-form resolution, determinism (byte-identical), multi-clip independence, short-clip, missing-`sample_array` error, one-of-length + non-positive validation. **Determinism note:** windowing is non-stochastic (a pure function of the clip + params), so worker-count invariance holds by construction — asserted via the byte-identical test rather than a workers=1/2/4 audio-materialize run.
- [x] Integration test ([`tests/integration/test_audio_windowing.py`](../../tests/integration/test_audio_windowing.py)): 3-clip varied-length `audio_folder` fixture (0.3s/0.2s/0.5s) → full pipeline → `sum(manifest.record_counts) == 10` (post-windowing expansion from 3 clips).
- [x] **Cross-repo coordination.** [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § JSONL records → new "Audio window records" subsection: window fields + the `__v` (variant) vs `__w` (window) distinction, `source_record_id` as the clip↔window grouping key now serving two mechanisms. Pre-prod doc addition, no `schema_version` bump.
- [x] DOC: [`recipe-authoring.md`](../guides/recipe-authoring.md) § Generation → `window` subsection (length one-of, remainder, grouping, determinism, splits-before-windowing).
- [x] CHANGELOG entry under the Subphase J-1 `[Unreleased]` section.
- [x] CI parity: `pyve test` (1468 pass), `mypy src tests` (clean, 237 files), `ruff check`/`format` (clean), core-invariant coverage gate (all 8 ≥ 95%; window op module 96%). Updated J.o's `test_operation_set_is_empty_in_the_scaffold` (op set no longer empty).

**Out of Scope:**

- Clip-level label propagation discipline (J.r).
- Featurization (J.s).
- Stochastic window selection (Future; the v1 op is fully deterministic per record).

---

### Story J.r: Clip-level label semantics + Splits-before-Generation order (R6) [Done]

**Disposition: feature addition + validator check.** Part of Phase J phase-bundle release. Closes R6.

Make clip-level labels propagate to all windows of a clip and enforce that all windows of one clip stay in a single split. Per the J.n design memo (Q1), this is achieved by running Splits at clip-level (before windowing) so each split is a set of clip-IDs, and windowing fans them out within their assigned split. Add a validator check that defensively refuses any recipe configuration where windowing would otherwise cross splits (guards against future ordering bugs).

**Tasks:**

- [x] Confirm the runner enforces Splits → Generation order via an integration-test guard so the ordering can't regress (build on the J.n memo's verification). `test_splits_runs_before_generation_in_stage_order` in [`tests/integration/test_audio_clip_split_integrity.py`](../../tests/integration/test_audio_clip_split_integrity.py) pins `STAGE_NAMES.index("Splits") < STAGE_NAMES.index("Generation")` — the structural invariant the whole R6 guarantee rests on (runner.py:109).
- [x] Implement label propagation: when the window op derives child records, the parent's `label` field is inherited verbatim, along with any other label-bearing fields per the recipe's `Labels.field` declaration. **Already correct from J.q** — the `window` op builds each child as `dict(record)`, so every clip-level field (including the label under any `Labels.field` name) is inherited verbatim. Locked with a regression guard `test_window_propagates_clip_level_label_verbatim_to_every_window` (non-default `category` label field) in [`test_window_op.py`](../../tests/plugins/audio_classification/test_window_op.py).
- [x] Add validator **check 29** (`splits_operate_at_clip_level`; integration suite count assertion updates 28→29): when a record-fanning Generation op (`replace_input_records=True`) is present and `Splits.stratify_by` is set, refuse if `stratify_by` names a fan-out-introduced field (`source_record_id` / `window_index` — module constant `_FANOUT_CHILD_FIELDS`), naming the offending field + the fanning op(s). Complements check 9 (declared-somewhere) without overlapping it — declaring `window_index` in `Output.record_schema` satisfies 9 but check 29 still refuses stratifying on it. [`recipe/validator.py`](../../src/datarefinery/recipe/validator.py).
- [x] Unit tests: label propagation across windows; window→parent grouping integrity; validator refuses a leak-prone configuration. 5 check-29 cases in [`test_validator.py`](../../tests/unit/test_validator.py) (refuse window_index / source_record_id; pass on clip-level label / no-fanning-op / no-stratify_by) + the window-op label-propagation guard.
- [x] Integration test: a multi-clip fixture with stratified Splits → assert every clip's windows land in exactly one split (no clip's `source_record_id` appears in two splits). `test_every_clips_windows_land_in_exactly_one_split` (8 clips × 2 classes, `stratify_by: label`) asserts pairwise-disjoint per-split `source_record_id` sets, full clip coverage, label inheritance, and the 32-window expansion ([`test_audio_clip_split_integrity.py`](../../tests/integration/test_audio_clip_split_integrity.py)).
- [x] DOC: [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) § Splits + clip-level labels callout. New § Splits → *Clip-level labels (audio) and split integrity* subsection (propagation, split-integrity, check-29-vs-check-9 distinction, ✅/❌ stratify_by example); § Generation → `window` "Splits-before-windowing" bullet updated to reference check 29.
- [x] CHANGELOG entry. New bullet under the Subphase J-1 `[Unreleased]` section (label propagation + check 29 + the 29-check count).
- [x] CI parity. `pyve test` (1476 pass), `pyve env run mypy src tests` (clean, 238 files), `pyve env run ruff check src/ tests/` + `ruff format --check` (clean).

**Out of Scope:**

- Noisy-label / label-confidence handling — explicitly out of scope per R6 spec ("belongs to the modeling repo").
- Multi-label-per-clip extensions.

---

### Story J.s: Spectral featurization op — `log_mel_spectrogram` (R4) [Done]

**Disposition: feature addition.** Part of Phase J phase-bundle release. Closes R4 (log-mel only; MFCC stays in Future per J.n).

Implement the Featurization-stage operation that converts a fixed-length window into a log-mel spectrogram via librosa. The op accepts a window record's sample array and adds a `feature` field (a 2D numpy array of shape `(n_mels, n_frames)`) plus metadata. One feature output per input window — no record-count change at the Featurization stage.

**Tasks:**

- [x] Implement `log_mel_spectrogram` op in [`plugins/audio_classification/operations/featurizations.py`](../../src/datarefinery/plugins/audio_classification/operations/featurizations.py): Featurization op handle (`fit_on_train=False`, no-fit `fit` + `apply`) reading `inputs[0]` (the sample array field) and writing the log-mel array under `output_field`, shape **`(n_mels, n_frames)`** (librosa-native, mel on axis 0); preserves all existing fields. **No-implicit-defaults adjustment** (story text predated J.n.4): the listed param "defaults" become **required** params on a frozen `LogMelParams` model (`extra=forbid`); `f_max` stays **mode-selecting** optional (`None ⇒ Nyquist`, like `normalize.mean`). librosa imported lazily inside `apply` → module importable without the `[audio]` extra; `PluginError` if invoked without it.
- [x] Register the op in `supported_operations` with `OperationSpec` (Featurizations section; `fit_on_train: False`; required vs. mode-selecting `ParameterSpec`s) + `operation_factory` dispatch (`_FEATURIZATION_OPS`) + `recommended_params` (`n_fft`/`hop_length`/`n_mels`/`f_min`/`power`; `f_max` omitted as mode-selecting) ([`plugin.py`](../../src/datarefinery/plugins/audio_classification/plugin.py)). Updated the two J.o contract tests that asserted the op had-not-landed (now assert the handle dispatches + recommended_params populated; the "raises" case repointed at the still-unlanded `audio_normalize`).
- [x] Unit tests: shape across input lengths + `n_mels`; determinism (byte-identical arrays); param validation (reject non-positive `n_fft`/`n_mels`/`hop_length`/`power`, unknown key); `hop_length > n_fft` allowed; `f_max: None ⇒ Nyquist`; field preservation + `output_field` honoring; no-op fit ([`test_log_mel_op.py`](../../tests/plugins/audio_classification/test_log_mel_op.py), 12).
- [x] Integration test ([`tests/integration/test_audio_featurization.py`](../../tests/integration/test_audio_featurization.py)): (a) full decode→window→featurize materialize → `manifest.record_counts` unchanged across the Featurization stage (one-output-per-input, 10 windows in = 10 out); (b) stage-level featurization through the real plugin + real librosa asserting `feature` shape `(n_mels, n_frames)` and byte-identical features across a re-run. **Worker-count invariance** holds by construction (pure function, no RNG) — asserted via the byte-identical re-run rather than a workers=1/2/4 run, mirroring the J.q windowing-determinism rationale.
- [x] **Cross-repo coordination.** Extended [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § Audio window records with an **Audio `feature` field** paragraph: shape `(n_mels, n_frames)` + librosa-native mel-axis orientation as the contract; documents accurately that — like `sample_array` — `feature` is an array-valued in-pipeline field **not** serialized into the dataset JSONL (it feeds the fit-on-train `audio_normalize` op in J.t, whose stats *are* persisted). Pre-prod doc-evolution addition, no `schema_version` bump.
- [x] DOC: [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) § Featurizations → new **Audio-classification Featurizations** subsection (`log_mel_spectrogram` YAML, required-vs-mode-selecting params, determinism, `[audio]`-extra gating, in-pipeline-not-JSONL note).
- [x] CHANGELOG entry under the Subphase J-1 `[Unreleased]` section.
- [x] CI parity. `pyve test` (1491 pass), `pyve env run mypy src tests` (clean), `pyve env run ruff check src/ tests/` + `ruff format --check` (clean).

**Out of Scope:**

- `mfcc` op — Future per J.n recommendation.
- Other spectral representations (CQT, chroma, etc.) — Future.
- Augmentations on featurized output (SpecAugment) — Future.

---

### Story J.t: Fit-on-train feature normalization for audio + `stats_from_instance` parity (R5) [Done]

**Disposition: feature addition (or extension of existing op, depending on J.n outcome).** Part of Phase J phase-bundle release. Closes R5.

Bring fit-on-train normalization to audio spectral features. Per the J.n design memo, normalization operates per-mel-bin (vector of `n_mels` means and `n_mels` stds), fit only on the training split, persisted to `fitted_statistics/<op_id>/` in the existing structured form (JSON scalars + parquet vectors). Confirm the `stats_from_instance` sibling-import path works unchanged for audio normalization (FR-ARCH-1 loose-coupling invariant per project-essentials).

**Stage-placement correction (developer-confirmed at the J.t gate, 2026-06-22).** The J.n memo froze `audio_normalize` at the **Transformations** stage. Implementation revealed this is broken: the runner executes `Transformations` *before* `Featurizations` ([runner.py:355 vs :381](../../src/datarefinery/pipeline/runner.py#L355)), so a Transformations-stage op cannot see the `feature` that `log_mel_spectrogram` (Featurizations) produces — empirically `KeyError: 'feature'`. Since fit-on-train scaling of a *derived* feature is a cross-modality staple (tabular column scaling, text embedding normalization will hit the same wall), the developer chose **Option A**: implement `audio_normalize` as a **fit-on-train Featurization** (the only stage that runs after derivation *and* supports fit-on-train + stats persistence + `stats_from_instance`), convention `log_mel_spectrogram` → `mel`, `audio_normalize` reads `mel` → writes `feature`. Memorialized as a staple capability in [`features.md`](features.md) FR-12 #5 and [`tech-spec.md`](tech-spec.md) § `pipeline.runner`. Amends J.s's documented `output_field` convention (`feature` → `mel`); J.s op code is unchanged (it writes whatever `output_field` the recipe declares). A dedicated post-Featurization transform stage was noted as a possible future `plan_phase` evolution, not adopted now.

**Tasks:**

- [x] ~~Per J.n decision (a)/(b)~~ → **Option (b) `audio_normalize`, as a fit-on-train Featurization** (not a Transformation — see stage-placement correction above). Implemented in [`operations/featurizations.py`](../../src/datarefinery/plugins/audio_classification/operations/featurizations.py) (`AudioNormalizeOp`); reduces over (examples × frames) keeping the mel axis (axis 0) → length-`n_mels` mean/std. Honors recipe-pinned `mean`/`std` (mode-selecting). Registered in `supported_operations` (Featurizations, `fit_on_train=True`) + `_FEATURIZATION_OPS` dispatch.
- [x] **Shared-helper extraction** (memo Finding B1 implementation note): extracted the mean/std fit + parquet wrap/unwrap + `std == 0 → 1.0` zero-variance guard into [`plugins/normalize_stats.py`](../../src/datarefinery/plugins/normalize_stats.py), parameterized by the statistics axis (`reduce_axes_for` + `zscore(..., axis=)`). Image `NormalizeOp` refactored to call it (channel-last); `audio_normalize` calls it (mel-axis-0). Image normalize/mean_subtract tests stay green (byte-identical) — regression-verified.
- [x] Verify `stats_from_instance` path: read-through works for audio (no copy into consumer's `fitted_statistics/`) — integration test `test_stats_from_instance_reads_through_without_refit_or_copy` (fake sibling instance + consumer op importing its mean/std).
- [x] Verify zero-variance guard semantics carry over: per-mel-bin zero-variance channels → `std == 0 → 1.0` at apply, persisted `std` unmodified — unit test `test_zero_variance_bin_guard`.
- [x] Unit tests ([`test_audio_normalize_op.py`](../../tests/plugins/audio_classification/test_audio_normalize_op.py), 7): per-mel-bin fit; fit→apply zero-mean/unit-std; field preservation; zero-variance guard; fit determinism; recipe-pinned mean/std; fit-on-train flag.
- [x] Integration test ([`tests/integration/test_audio_normalize.py`](../../tests/integration/test_audio_normalize.py), 3): full decode→window→log_mel(`mel`)→audio_normalize(`feature`) materialize persists per-mel-bin `mean`/`std` parquet of length `n_mels`; val normalized with **train**-fitted stats byte-identically across a re-run; `stats_from_instance` read-through.
- [x] **Cross-repo coordination.** Extended [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md): updated § Audio spectral features (`mel`/`feature` two-op chain), broadened § Fitted statistics intro to include fit-on-train Featurizations, added § `audio_normalize` statistics (per-mel-bin axis vs. RGB-channel-axis table).
- [x] DOC: [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) § Featurizations — added `audio_normalize` to the Audio subsection with the two-op `mel`→`feature` chain + why-it's-a-Featurization rationale.
- [x] DOC (memorialize staple capability, developer-requested): [`features.md`](features.md) FR-12 behavior #5; [`tech-spec.md`](tech-spec.md) § `pipeline.runner` stage-order rationale. Evaluated [`concept.md`](concept.md) — no change needed (the placement is a feature/implementation concern already covered at the right altitude by the existing "normalization into recipe sections" goal + "plugin-interface honesty" value criterion).
- [x] CHANGELOG entry (J.t bullet + J.s `output_field` convention amendment).
- [x] CI parity. `pyve test` (1501 pass), `pyve env run mypy src tests` (clean, 244 files), `pyve env run ruff check src/ tests/` + `ruff format --check` (clean).

**Out of Scope:**

- Per-frame normalization (Future).
- Multi-channel normalization for stereo audio (Future).
- A dedicated post-Featurization transform stage (noted as a possible future `plan_phase` evolution; the Featurization-as-scaler convention covers v1).

---

### Story J.u: `source_record_id` contract surface + cross-repo coordination (R7) [Done]

**Disposition: cross-repo contract authoring.** Part of Phase J phase-bundle release. Closes R7.

Pin `source_record_id` as the consumer-bind grouping key for audio window aggregation. Update both [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) and [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) (created in J.c) to document the field for audio records and reaffirm the "DR owns the grouping key; consumer owns the aggregation math" boundary (Q3 settled in J.n).

**Tasks:**

- [x] Document `source_record_id` and `window_index` in [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § Audio window records. **Already stood up by J.q** (the `__v`/`__w` distinction table + field semantics); J.u sharpened it rather than adding a duplicate subsection — see the aggregation-contract task below.
- [x] Document the aggregation contract: added a bold **Aggregation contract (R7 — DR owns the key, the consumer owns the math)** paragraph to § Audio window records — the producer guarantee (every window's `source_record_id` is the verbatim parent-clip `record_id`; all windows of a clip share one key and land in one split per R6/J.r) + the consumer obligation (group by it, apply mean/max/logit-average/vote) + the explicit "DR emits no aggregation policy and ships no aggregation op".
- [x] Add a Failure-modes-MF-SHOULD-detect entry: new **Dangling audio window grouping key** bullet ("window's `source_record_id` resolves to no clip → corrupt instance, refuse to consume") in § Failure modes ModelFoundry SHOULD detect.
- [x] Add a parallel "Audio window records" section to [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md): new § Audio window records under Notebook-output ergonomics — per-clip rollup vs. per-window table renderings, consumer-owned grouping, and the arrays-absent-from-JSONL note; cross-references the MF spec for the full contract.
- [x] Extend [`project-essentials.md`](project-essentials.md) § "Recipe / manifest / report shape changes need a cross-repo coordination check": named the **per-record dataset-JSONL field set** as a shape-binding surface, enumerating the image aggressive-variant fields (`source_record_id`/`variant_index`/`image_path`) and audio window fields (`source_record_id`/`window_index`) as grouping keys consumers bind against.
- [x] DOC: brief [`concept.md`](concept.md) cross-link — § Plugin-interface honesty value criterion now notes `audio_classification` (Phase J Subphase J-1) as the second *fully real* (non-stub) plugin landing on the existing category-agnostic abstractions, with pointers to both vendor specs.
- [x] CHANGELOG entry (cross-repo contract additions). New J.u bullet under the Subphase J-1 `[Unreleased]` section.
- [x] CI parity (doc-only; no code change). `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/` + `ruff format --check` — all green (no source touched).

**Out of Scope:**

- The aggregation math itself (MF / NbF own).
- A `clip_record_count` manifest field — derivable from `record_counts` and `source_record_id` distinct count; not requested by R7.

---

### Story J.v: End-to-end audio integration fixture + acceptance gate [Planned]

**Disposition: integration test.** Part of Phase J phase-bundle release. Closes acceptance criteria 1–9 from [`audio-classification-requirements.md`](audio-classification-requirements.md) § Acceptance criteria.

Author a tiny but realistic audio fixture dataset (9 clips across 3 classes, varied durations, mixed source sample rates, one unlabeled partition) and a recipe exercising every R1–R7 capability. Run `init → validate → materialize` end-to-end and assert each of the 9 acceptance criteria. This is the integration gate that catches inter-story gaps before phase-bundle release.

**Tasks:**

- [ ] Add `tests/fixtures/audio/` with 9 short synthetic audio files (sine sweeps and simple tones — deterministic synthesis; no real recordings, keeps the repo lean and avoids licensing questions).
- [ ] Author `tests/fixtures/recipes/audio_classification_v1.yaml` exercising audio_folder + `label_from` + decode + window (Generation) + log_mel_spectrogram (Featurization) + normalize (fit-on-train) + Splits.
- [ ] Add `tests/integration/test_audio_classification.py` covering:
  - AC1: init → validate → materialize succeeds with no workarounds.
  - AC2: byte-identical re-run (excluding `created_at` / `elapsed_seconds`).
  - AC3: cosmetic edit → cache hit; semantic edit (window_length change) → cache miss.
  - AC4: window determinism across worker counts (`workers=1, 2, 4`).
  - AC5: featurization is one-output-per-input (record count unchanged at the Featurization stage).
  - AC6: `stats_from_instance` round-trip with a sibling eval recipe.
  - AC7: stratified splits → every window's `source_record_id` lands in exactly one split.
  - AC8: plugin-contract test green.
  - AC9: failure path (deliberately broken decode params) → FAILED-marked temp directory; no partial cached instance.
- [ ] Document any surprises encountered as a friction-list note (either an addendum to an existing phase-J friction doc or a new `phase-j-subphase-1-audio-friction.md`); follow-up fixes become J.w-adjacent or post-phase stories at developer discretion.
- [ ] CHANGELOG entry.
- [ ] CI parity.

**Out of Scope:**

- Performance benchmarking (Future).
- Real-audio-dataset fixtures (Future; behind a licensing decision).

---

### Story J.w: vX.Y.0 release — Subphase J-1 phase-bundle close [Planned]

**Disposition: release bundle.** Part of Phase J phase-bundle release. The last story in Subphase J-1 (and in Phase J, unless further accretion lands first).

Phase-bundle release closing Subphase J-1. Bumps the package version, writes the CHANGELOG release entry, and presents the final phase-state at the approval gate.

**Tasks:**

- [ ] Bump `src/datarefinery/__init__.py` `__version__` to the next minor (per the Version Cadence rule: "highest-impact change in the bundle"; a new modality plugin is **minor**). Hatchling reads this as the single source of truth — no `pyproject.toml [project].version` edit.
- [ ] CHANGELOG entry: enumerate the new `audio_classification` plugin and the R1–R8 closures; cross-repo contract additions from J.q + J.s + J.t + J.u; new dependency on `librosa`; CHANGELOG note that the second real plugin validates the plugin-interface honesty goal.
- [ ] Cross-repo coordination final check: confirm [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) and [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) are both current with the audio additions.
- [ ] Run the full local-verification suite: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`.
- [ ] Present at the approval gate.

**Out of Scope:**

- Any scope not already in Phase J at this point — new asks become Phase K candidates rather than piling into the release.
- Tagging / pushing the release — developer-initiated.

---

### Story J.x: Spike — Segmented recipe identity / scoped cache invalidation [Done]

**Disposition: design spike** (exploratory; deliverable is the design memo + a `plan_phase` recommendation, not code). Phase J catch-all item — surfaced by the J-1 audio integration (J.n Finding A) and generalized by the developer into a recipe-model architecture question. No version bump.

The flat `recipe.model_dump(mode="json")` canonical form couples cache identity to model-class shape rather than pipeline behavior, so any field added anywhere invalidates every recipe of every modality (the J.n Finding A blast radius), `extra="forbid"` leaves no room to prototype a parameter before committing it to the schema, and a single global `schema_version` makes every shape change a whole-world event. The developer proposed decomposing the recipe into general / plugin-variant / orthogonal-overlay / extensions layers; this spike synthesizes that into one mechanism — **segmented canonical bytes** — and recommends executing it pre-1.0 (before more plugin/modality surface accretes onto the flat model) via `plan_phase`.

**Tasks:**

- [x] Verify the root cause against source: total `model_dump` ([canonical.py:20-40](../../src/datarefinery/recipe/canonical.py#L20-L40)); shared `InputSource` ([models.py:86](../../src/datarefinery/recipe/models.py#L86)); `extra="forbid"` ([models.py:24](../../src/datarefinery/recipe/models.py#L24)); single global `schema_version` ([loader.py](../../src/datarefinery/recipe/loader.py)); op-level `params` as the existing scoped-identity precedent.
- [x] Write the design memo at [`phase-j-recipe-architecture-spike.md`](phase-j-recipe-architecture-spike.md): problem, the segmented-bytes synthesis (core / plugin / overlays / extensions), design principles + the scoped-invalidation reframe, per-segment versioning, the declarative-extensions vs. recipe-activated-code trust boundary, per-segment pin-test enforcement, pre-1.0 rollout, open questions for plan_phase, and the relationship to in-flight audio work.
- [x] Mark Subphase J-1 (J.o–J.w) PAUSED pending the rearchitecture; J.n Finding A's `AudioSource` recast as the plugin-surface segment in miniature (stepping stone, possibly reshaped by plan_phase's representation choice).
- [x] Present at the approval gate with the recommendation to run `plan_phase`. **No code, no tests, no version bump.**
- [x] Fold the design-discussion conclusions into the memo (§ 3 "Resolved stance", recommended-not-frozen): **no implicit defaults** (interpreting code supplies no value; scaffolder emits recommended values explicitly into the recipe); **`required` vs. `optional` = the bump-vs-free rule**; **content-addressed ⇒ support window is a re-derivability horizon**, with the **pre-1.0 window = zero by default** policy. § 9 open-questions trimmed of the now-resolved forks.
- [x] Cross-pollinate from the reciprocal [ModelFoundry spike](modelfoundry/phase-i-recipe-architecture-spike.md): pulled upstream the **vertical stage-reuse axis + the "internal materialization-cache optimization vs. unchanged external identity" reframe** (§ 4 new subsection — acknowledged but **deferred**; DR's flatter compute gradient makes it secondary, with DR's existing `viz_snapshots`/`export`/`report`/`stop_after` credited as embryonic precedent); **`join_stable` future-proofed** for cumulative-prefix composition (§ 4, § 9.8); **cross-tool-family governance** (§ 10 — the horizontal mechanism + no-implicit-defaults are now the shared family standard MF adopted wholesale; the vertical axis is MF's own); conditional stage-isolation pin test (§ 7). Declined to pull MF's 1,000-GPU-hour urgency / full stage-artifact-store overhaul (disproportionate to DR's gradient).

**Out of Scope:**

- Implementing segmented canonical bytes / any model change. That is the `plan_phase`-drafted phase (Phase K candidate), not this spike.
- Recipe-activated arbitrary code (hooks/callbacks the recipe points at). Flagged as a separate trust-boundary effort; this memo keeps the recipe declarative.
- Creating the new phase heading/bundle — `plan_phase`'s exclusive job.

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
- **Image-classification plugin: additional capabilities deferred from Phase H sub-bundle** — see [`phase-h-datarefinery-feature-recommendation.md`](phase-h-datarefinery-feature-recommendation.md) for full specifications:
  - FR-ARCH-1 tight coupling — sibling `recipe_hash` participating in the current recipe's cache identity, so re-materializing upstream auto-invalidates downstream. The Phase H sub-bundle shipped FR-TRANS-1 with loose coupling; tight coupling is the follow-up needed for multi-team or longitudinal workflows.
  - Generic record-tagging primitive — factor FR-FILTER-1's bespoke `label` / `exclude_already_labeled` params into a shared mechanism multiple filter ops can use.
- **`stats_from_instance.variant: <name>` selector** — let a consumer recipe pin a specific sibling-variant's fitted statistics (e.g., normalize stats fit under a specific experimental overlay). The Phase I G19 fix closes the no-variant case; the variant-selector form is a follow-up. Added during Phase I planning (Story I.h).
- **Real `to_grayscale` Transformation op** — Phase I removed the declared-but-unimplemented `to_grayscale` OperationSpec entry to keep the surface honest. A real implementation with a `method: average | luminance | …` parameter set is deferred until a recipe surfaces a concrete need. Added during Phase I planning (Story I.h).
- **Plugin-pluggable validator-check reserved-set hook** — let plugins declare `Plugin.loader_stamped_fields(recipe) -> set[str]` so validator check 23 (Featurization `output_field` collision) can be applied to non-stub plugins when their loaders ship. Today the reserved-set is hardcoded for `image_classification`; tabular and text stubs don't stamp fields and don't need the hook yet. Originally noted in Story I.c's prevention notes; added during Phase I planning (Story I.h).
- **Per-stage report subsections** — extend the snapshot-based stage-aware viz dispatch (Story I.v / G7) so the rendered `report.md` carries one heading per snapshotted stage. The v1 deliverable is one report section with per-viz `stage:` annotations; richer structure is a UX polish follow-up. Added during Phase I planning (Story I.h).
- **Scaffolder v2 grand sweep** — refresh the bundled `init` scaffolder ([`scaffolder/init.py`](../../src/datarefinery/scaffolder/init.py)) to actively showcase v2 affordances in the scaffolded recipe (`seed_derive_from: master` on every seeded op, tag-driven `applies_to` example, `replace_input_records: true` demo, `value_in_set` instead of bare enum lists, etc.). Phase I's Bundle 4 ships the *minimal* scaffolder update (emit valid v2-shape recipes); the grand-sweep redesign of the scaffolded recipe as a teaching artifact is a follow-up. Added during Phase I planning (Story I.h).
- **Real `distributional` assertion kind** — replace the v1 placeholder with a real evaluator (KS test, JS divergence, or similar). The current placeholder always passes; downstream drift tools (DataMachine) implement their own checks. Added during Phase I planning (Story I.h).
- **DR-side `class_balance` resampling** — physically resample (oversample minority records into the cached train split, or emit per-record `class_weight`) at the Splits stage rather than passing the strategy through as an MF-binding hint. Phase I chose MF-side resampling (Story I.s / G10); revisit if downstream evidence accumulates that the materialized instance needs to be framework-agnostic and self-contained. Added during Phase I planning (Story I.h).
- **Broad consumer-context rewrite of internal specs** — sanitize the deeper consumer-perspective surface in [`phase-i-dependency-gaps-v0.16.0.md`](phase-i-dependency-gaps-v0.16.0.md) and [`phase-i-intermediate-artifact-persistence-spec.md`](phase-i-intermediate-artifact-persistence-spec.md): replace "Recipe A" / "Recipe B" with generic role names, drop or rephrase Module N / Phase B / Phase D / Task 2 references, replace consumer recipe filenames (`cifar10-base.yaml`, `cifar10c-eval.yaml`) and consumer-side phase-plan links with generic placeholders, generalize consumer-specific record counts and tag names. Story I.h scrubbed only the hard-blacklisted course identifiers (see developer auto-memory) for in-course blast-radius reduction; this Future story is the deliberate rewrite once the course is complete. Git history will continue to carry the original consumer surface regardless. Added during Story I.h execution.
