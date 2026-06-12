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

### Story J.g: Consumer-applied transformations boundary — `path` rewrite + validator guard [Planned]

**Disposition: feature addition + validator check + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Closes the silent `path`-vs-transformed-pixels divergence surfaced during the [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) 2026-06-11 ratification round 2.

In v0.19.0, `path` is set once at input loading and never rewritten by Transformations or Sinks. A non-aggressive recipe declaring `resize` (or any pixel-altering op) produces JSONL whose `path` points at source pixels while the in-memory transformed image is dropped at serialization — consumers reading `path` get pre-transform geometry, silently. The CIFAR-10 reference flow has no geometry transforms and avoids the gap, but it's load-bearing for generalization.

**Approach.** Require a sink for lazy-mode recipes containing pixel-altering Transformations; DR rewrites each record's `path` field to point at the sink's per-record output. Interim validator check refuses the silent-divergence case so it cannot be authored in the first place.

**Tasks:**

- [ ] Identify the closed set of pixel-altering Transformation ops in the `image_classification` plugin (today: `resize`; plus any future ops). Document the criterion explicitly: an op is pixel-altering if its `apply` changes the image array's bytes in a consumer-visible way that is NOT recoverable from persisted fitted statistics. `normalize` / `mean_subtract` are NOT pixel-altering by this criterion — they are stat-based and consumer-applied.
- [ ] Add validator **check N** (new number; integration suite count assertion updates): lazy-mode recipe + `Transformations` containing a pixel-altering op + no `Sinks` declaration → refuse with a message naming the offending op and the required sink declaration.
- [ ] Implement path-rewrite mechanism: when a recipe declares a sink AND has pixel-altering Transformations, DR rewrites each record's `path` field at JSONL emission to point at the sink's per-record output (using the sink's resolved `path_template`).
- [ ] Unit tests: pixel-altering + no sink → validator refusal; pixel-altering + sink → JSONL records carry rewritten `path` matching the sink's per-record output; non-pixel-altering (`normalize`-only) → `path` unchanged (regression guard).
- [ ] Integration test: end-to-end recipe with `resize` + sink → consumer reads `path`, decodes the sidecar PNG, gets byte-identical pixels to the in-memory transformed array recorded by the determinism test.
- [ ] **Cross-repo coordination.** Update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md): ratify the forward-declared § "Consumer-applied transformations vs. baked transformations" — remove the "Phase J Story J.g" forward-declaration; document the closed pixel-altering-op set and the path-rewrite mechanism as the stable contract.
- [ ] DOC: update [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) § Sinks to describe the sink-as-pixel-source pattern.
- [ ] CHANGELOG entry under the in-progress v0.20.0 section: cross-repo contract change. Additive (no `schema_version` bump needed); document the pre-J.g silent-divergence case as a fixed bug.
- [ ] CI parity: `pyve test`, `pyve testenv run mypy src tests`, `pyve testenv run ruff check src/ tests/`, `pyve testenv run ruff format --check src/ tests/`.

**Out of Scope:**

- Aggressive-mode behavior. Unchanged — already correct via `image_path`.
- A separate path-rewrite mechanism that doesn't go through `Sinks`. Sinks are the existing "write transformed pixels to disk" surface; using them keeps one mechanism for the write half (sink → bytes) and one for the JSONL-binding half (path rewrite → consumer-visible source). Adding a parallel mechanism would multiply the surfaces where loose/tight coupling questions could re-surface, mirroring the precedent in [`project-essentials.md`](project-essentials.md) § "Sibling-instance dependencies are loose-coupled in v1".
- Pixel-altering ops appearing in `Augmentations` (lazy mode). Lazy-mode augmentations are policy-only by design (consumer realizes); they're not in scope here.
- A path-rewrite for `mean_subtract` / `normalize`. These are consumer-applied by design (see vendor-dependency-spec § "Normalization is applied by the consumer"); their bytes-on-disk semantics are unchanged.

---

### Story J.h: ImageFolder + aggressive Augmentations — sidecar PNG path crash [Planned]

**Disposition: bugfix + validator + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Surfaced 2026-06-12 during the [J.d MF integration spike](phase-j-mf-integration-friction.md) (F1).

End-to-end materialization of a recipe declaring `Input.type: image_folder` + `Augmentations: [{materialization: aggressive, ...}]` fails with `FileNotFoundError` at the dataset-write stage. The image_classification ImageFolder loader stamps `record_id` as `"<source-name>/<class>/<filename>"` (with forward slashes); the runner's [`_prepare_record_for_persistence`](../../src/datarefinery/pipeline/runner.py) computes the sidecar PNG path as `sidecar_dir / f"{record_id}.png"`, which produces nested directories without `mkdir(parents=True)`. PIL `Image.save` then fails to open the file for writing. The reproducer is in the J.d friction-list F1 section.

**Why the test suite missed it.** The Story H.r.2 aggressive-mode integration tests ([`test_runner.py:519`](../../tests/integration/test_runner.py#L519)) use the library API with manually constructed flat record_ids (`rec_0001`), sidestepping both the slashes and the nested-dir problem. The disk-loader path has never been exercised end-to-end with aggressive variants in the test suite — this story closes that gap.

**Tasks:**

- [ ] Reproduce the crash with a failing integration test materializing an `image_folder` recipe + aggressive `horizontal_flip` end-to-end (no library shortcut to manually-constructed records). Test lives in `tests/integration/`.
- [ ] Fix in [`_prepare_record_for_persistence`](../../src/datarefinery/pipeline/runner.py): sanitize the per-variant sidecar filename so loader-stamped `record_id` slashes do not create nested directories. Decide between (a) `mkdir(parents=True, exist_ok=True)` on `sidecar_path.parent` to preserve the nested layout, or (b) replacing `/` (and other path separators) with a safe character (e.g. `__`) so the filename stays flat. Decision criterion: byte-stable across loader/manual paths, no record_id mutation in the JSONL.
- [ ] Update the JSONL `image_path` field to match the chosen sanitized form so consumers resolve correctly. Update [`test_runner.py:519`](../../tests/integration/test_runner.py#L519) family expectations if the sanitization changes the relative path shape; the deterministic-bytes integration test (`test_aggressive_materialize_is_deterministic_across_runs`) must stay green.
- [ ] Cross-repo coordination: update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Sidecar PNG encoding" / § "Aggressive-mode variants" to pin the sanitization rule (so MF consumers know how `image_path` resolves when source `record_id` contains separators). Additive — no `schema_version` bump on canonical-bytes grounds, but the on-disk PNG path layout changes for ImageFolder recipes with aggressive variants → pre-prod re-materialize event for any such recipe.
- [ ] CHANGELOG entry under the in-progress v0.20.0 section flagging the on-disk-layout change for `image_folder` + aggressive recipes.
- [ ] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`.

**Out of Scope:**

- Library-API manual-records path. The existing flat-record_id pattern continues to work unchanged; this story is the disk-loader path's gap.
- Non-image plugins. Tabular and text plugins ship as stubs and don't exercise aggressive realizers in v1.
- A general "record_id is filesystem-safe" invariant across DataRefinery. Scope is the sidecar PNG persistence path. Other code that consumes `record_id` (JSONL keying, cache identity, log messages) is unaffected.

---

### Story J.i: Pixel-altering Transformations + aggressive Augmentations — validator refusal [Planned]

**Disposition: validator check + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Surfaced 2026-06-12 during the [J.d MF integration spike](phase-j-mf-integration-friction.md) (F2). **Natural fold-in with Story J.g** — both stories enumerate the same closed set of pixel-altering Transformation ops.

A recipe declaring `Transformations: [{op: normalize, ...}]` alongside `Augmentations: [{materialization: aggressive, ...}]` crashes mid-pipeline with `TypeError: Cannot handle this data type: (1, 1, 3), <f8` in the realizer. Runner stage order is `... → Transformations → Featurizations → Augmentations → ...`, so the realizer sees float64 z-scores from normalize and PIL `Image.fromarray` rejects them. The crash applies to every pixel-altering aggressive augmentation (`horizontal_flip`, `random_crop`, `color_jitter`, `random_erasing`) chained after any dtype-changing Transformations op (`normalize`, `mean_subtract`).

**Approach.** Add a new FR-2 check that refuses the combination at validate time. The same closed pixel-altering-op set Story J.g is scoping for the lazy-mode `path` rewrite applies here — the two stories share the enumeration. Coordinate task order with J.g so the enumeration lands once.

**Tasks:**

- [ ] Reuse the closed pixel-altering Transformation-op set from Story J.g (today: `resize` is geometry-altering; this story adds `normalize`, `mean_subtract` as dtype-altering — both classes break the aggressive realizers' uint8 assumption). Either share an enum/constant or document the coordination explicitly in both check docstrings.
- [ ] Add validator **check N** (new number; integration-suite count assertion updates): recipe with a pixel-altering / dtype-altering Transformation op + any aggressive `AugmentationOp` targeting the same split → refuse with a message naming the offending op pair and the split.
- [ ] Reproduce the crash with a failing test, then confirm the new validator check refuses the recipe before the run starts.
- [ ] Cross-repo coordination: update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Aggressive-mode variants" / § "Materialization modes" to call out the incompatibility, referencing the new check ID.
- [ ] DOC: update [`recipe-authoring.md`](../guides/recipe-authoring.md) § Augmentations to document the constraint.
- [ ] CHANGELOG entry under the in-progress v0.20.0 section: new validator check; previously-author-able recipes that hit the crash now fail fast at validate time (existing instances are unaffected — they don't materialize today either).
- [ ] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`.

**Out of Scope:**

- Realizer changes to accept float-typed input. Considered and rejected: cast-back would be lossy (loses normalize z-scores) and break the recipe-as-truth contract.
- Stage-order reversal (Augmentations before Transformations). Out of scope — would invert the "fit on train, apply everywhere" discipline for normalize because fit would run on augmented records.
- Lazy-mode augmentations. Lazy-mode is policy-only by design; the realizer runs in the consumer.
- Per-split scope. The check refuses any same-split combo; partial-split combos (e.g. normalize on train+val, aggressive only on train) still get caught by the train-split overlap.

---

### Story J.j: `drift.json.recipe_hash` — align spec promise with code [Planned]

**Disposition: bugfix + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Surfaced 2026-06-12 during the [J.d MF integration spike](phase-j-mf-integration-friction.md) (F7).

The [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Failure modes ModelFoundry SHOULD detect" promises `drift.json.recipe_hash` as the consumer-visible field MF reads to detect stale fitted statistics ("`drift.json`'s `recipe_hash` field aligns with `manifest.recipe_hash`; mismatch is ipso facto a stale instance"). On current v0.20.0 instances, `drift.json` has no `recipe_hash` key — its top-level fields are `feature_summary`, `notes`, `plugin`, `schema_version`, `splits`. Consumers must cross-read `manifest.json` to do the check the spec advertises.

This is a documented promise that doesn't currently exist in code. The right fix is to add the field — small, additive, and aligns spec with reality.

**Tasks:**

- [ ] Reproduce the gap with a failing test: assert `drift.json` top-level keys include `recipe_hash` and that the value matches `manifest.recipe_hash` for any fresh instance.
- [ ] Add `recipe_hash` to `drift.json` at the runner's [`compute_drift_placeholder`](../../src/datarefinery/pipeline/runner.py) emission site. Mirror the existing field's emission discipline: copy from `cache_key.recipe_hash` (full 64-hex), not the truncated 16-char shard.
- [ ] Confirm the field perturbs no canonical bytes (it lives in `report/drift.json`, not the recipe) — the canonical-hash pinning fixture stays green.
- [ ] Unit test: `compute_drift_placeholder` emits `recipe_hash`. Integration test: round-trip a fresh instance, assert `drift.recipe_hash == manifest.recipe_hash` byte-for-byte.
- [ ] Cross-repo coordination: update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Report subsections" to enumerate `drift.json.recipe_hash` as a stable field; the existing § "Failure modes" parenthetical referencing this field is now load-bearing.
- [ ] DOC: no recipe-authoring change (drift.json is consumer-facing, not authorable).
- [ ] CHANGELOG entry under the in-progress v0.20.0 section: additive `drift.json` field; no `schema_version` bump; align spec promise with code.
- [ ] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`.

**Out of Scope:**

- Other drift.json fields beyond `recipe_hash`. The MF spec's `drift.json` shape stays "pre-prod unstable" per the existing caveat; this story closes exactly one promise.
- A separate stale-instance verb / CLI surface. The MF consumer-side check is the canonical path; DR doesn't need a new verb for it.
- Backfilling `recipe_hash` into already-materialized v0.19.0 instances. Pre-prod re-materialization is the migration path; explicit in the CHANGELOG.

---

### Story J.k: Vendor-dependency-spec ratification round — absorb J.d friction items F3/F4/F5/F6/F8 [Planned]

**Disposition: documentation + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Bundles the five contract-doc clarifications surfaced during the [J.d MF integration spike](phase-j-mf-integration-friction.md) — F3 (medium) + F4/F5/F6/F8 (low). Mirrors the "Round 2 additions 2026-06-11" pattern already in the [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) header.

Each friction item is a small spec edit; bundling them avoids over-decomposition into five tiny stories that share one file and a single coordinated PR. F4 touches both the MF and NbF vendor-dep specs (the asymmetry it documents surfaces in the library-records path, which is NbF's home); F3/F5/F6/F8 are MF-spec-only.

**Tasks:**

- [ ] **F3 — host portability of lazy-mode `path`.** Extend [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Source-resolution path" with an explicit "Host portability" subsection: the `path` field is host-bound; consumers operating across hosts SHOULD either (a) require a `Sinks` block writing per-record images so `path` is rewritten under the instance directory (the Story J.g `path`-rewrite mechanism is the long-term fix for the pixel-altering subset), or (b) ship the source ImageFolder alongside the instance. Cross-reference J.g for the pixel-altering subset.
- [ ] **F4 — disk-loader / library-records Featurization asymmetry.** Add a short subsection under [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) § "Library entry points" (the natural home — that subsection already documents the library-records path) flagging the asymmetry: a `Featurizations` op with `output_field` that the loader pre-stamps succeeds through the disk path (the validator-23 collision guard exempts loader-stamped fields), but the same recipe driven via the library API with manually constructed records arriving with that field already populated will hit the runtime collision check in [`featurizations.py`](../../src/datarefinery/pipeline/stages/featurizations.py). Recommend "rely on the loader to stamp the field, or remove the Featurization op when supplying records manually."
- [ ] **F5 — `schema_version` field-name overload.** Extend [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Schema-version coordination policy" with an explicit disambiguation: `manifest.schema_version` (manifest format version, currently `1`; see `pipeline.manifest.MANIFEST_SCHEMA_VERSION`) and `recipe.schema_version` (recipe schema version, currently `2`; see `recipe.loader.SUPPORTED_SCHEMA_VERSIONS`) are **independent counters with different rules**. Consumers binding against the recipe-schema coordination logic must read `recipe.schema_version`, not `manifest.schema_version`.
- [ ] **F6 — every recipe section persists in `recipe.json`.** Add one paragraph in [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Recipe-side contract": all top-level recipe sections are present in `recipe.json` whether or not the author declared them; absent / empty sections appear as the section type's default (`[]` for list sections, `null` for optional object sections, empty `{}` where applicable). Consumers SHOULD treat empty / null sections as "not declared". Cross-reference [`project-essentials.md`](project-essentials.md) § "Cache identity is the reproducibility contract" for the canonical-bytes mechanism.
- [ ] **F8 — implicit consumer-side runtime deps.** Add one sentence to [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Overview" naming the consumer-side runtime deps a downstream tool needs to read DataRefinery artifacts beyond pure stdlib: `numpy` (image bytes; record arrays), `Pillow` (PNG decode for aggressive variants and any image-bytes reads), `pyarrow` (parquet decode for fitted statistics).
- [ ] **Header ratification note.** Update the MF spec status block at the top, adding a "Round 3 additions 2026-06-12" entry summarizing F3/F5/F6/F8 absorption (mirroring the existing Round 2 entry); update the NbF spec status block similarly for F4. Both notes name Story J.k as the authoring round and reference the J.d friction list.
- [ ] **Lock-down statement.** Each F-item gets a brief "pinned in Round 3" note inline at the absorption site so future readers can trace the provenance back to the J.d friction list without grovelling commit history.
- [ ] CHANGELOG entry under the in-progress v0.20.0 section: cross-repo contract clarification round absorbing five J.d friction items; documentation-only (no canonical-bytes perturbation, no manifest/recipe shape change).
- [ ] CI parity: `pyve test`, `pyve env run mypy src tests`, `pyve env run ruff check src/ tests/`, `pyve env run ruff format --check src/ tests/`. (Doc-only — tests/lint stay green by construction; CI parity verification is the standard end-of-story discipline.)

**Out of Scope:**

- Code changes. F3/F4/F5/F6/F8 are all contract-doc clarifications by design. F4's NbF-spec note documents an existing asymmetry; it does not propose changing the collision-check behavior. The F3 "host portability" framing references J.g's `path`-rewrite mechanism but does not duplicate J.g's scope.
- Forward-declared item rewording. The forward-declared `manifest.label_classes` (J.f) and `Consumer-applied transformations` section (J.g) in the MF spec stay as-is — they're absorbed by their owning stories when those land, not here.
- `nbfoundry/vendor-dependency-spec.md` forward-declared items from J.b (F1 log-target, F2 `--json`, F4 `--quiet`/`--verbose`, F6 duplicate-plugin error). Those are NbF-spec forward declarations awaiting their own code stories; this ratification round closes only the J.d-side editorial gaps.

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
- **Default-change discipline tooling for cache-identity stability** — expand the canonical-hash pinning test suite to cover multiple fixture recipes with different default-coverage profiles, so any change to a pydantic field default (anywhere in the recipe model graph) trips at least one pin and forces the developer to either revert or bump `schema_version`. Add an optional pre-commit / CI hook that diffs pydantic field defaults against `main` and requires a `schema_version` bump or an explicit "non-semantic default change" acknowledgement in the commit message. End-state invariant: cache invalidations are always deliberate (acknowledged at change time, announced in release notes); never silent. Plan as production-readiness work.
- **`stats_from_instance.variant: <name>` selector** — let a consumer recipe pin a specific sibling-variant's fitted statistics (e.g., normalize stats fit under a specific experimental overlay). The Phase I G19 fix closes the no-variant case; the variant-selector form is a follow-up. Added during Phase I planning (Story I.h).
- **Real `to_grayscale` Transformation op** — Phase I removed the declared-but-unimplemented `to_grayscale` OperationSpec entry to keep the surface honest. A real implementation with a `method: average | luminance | …` parameter set is deferred until a recipe surfaces a concrete need. Added during Phase I planning (Story I.h).
- **Plugin-pluggable validator-check reserved-set hook** — let plugins declare `Plugin.loader_stamped_fields(recipe) -> set[str]` so validator check 23 (Featurization `output_field` collision) can be applied to non-stub plugins when their loaders ship. Today the reserved-set is hardcoded for `image_classification`; tabular and text stubs don't stamp fields and don't need the hook yet. Originally noted in Story I.c's prevention notes; added during Phase I planning (Story I.h).
- **Per-stage report subsections** — extend the snapshot-based stage-aware viz dispatch (Story I.v / G7) so the rendered `report.md` carries one heading per snapshotted stage. The v1 deliverable is one report section with per-viz `stage:` annotations; richer structure is a UX polish follow-up. Added during Phase I planning (Story I.h).
- **Scaffolder v2 grand sweep** — refresh the bundled `init` scaffolder ([`scaffolder/init.py`](../../src/datarefinery/scaffolder/init.py)) to actively showcase v2 affordances in the scaffolded recipe (`seed_derive_from: master` on every seeded op, tag-driven `applies_to` example, `replace_input_records: true` demo, `value_in_set` instead of bare enum lists, etc.). Phase I's Bundle 4 ships the *minimal* scaffolder update (emit valid v2-shape recipes); the grand-sweep redesign of the scaffolded recipe as a teaching artifact is a follow-up. Added during Phase I planning (Story I.h).
- **Real `distributional` assertion kind** — replace the v1 placeholder with a real evaluator (KS test, JS divergence, or similar). The current placeholder always passes; downstream drift tools (DataMachine) implement their own checks. Added during Phase I planning (Story I.h).
- **DR-side `class_balance` resampling** — physically resample (oversample minority records into the cached train split, or emit per-record `class_weight`) at the Splits stage rather than passing the strategy through as an MF-binding hint. Phase I chose MF-side resampling (Story I.s / G10); revisit if downstream evidence accumulates that the materialized instance needs to be framework-agnostic and self-contained. Added during Phase I planning (Story I.h).
- **Broad consumer-context rewrite of internal specs** — sanitize the deeper consumer-perspective surface in [`phase-i-dependency-gaps-v0.16.0.md`](phase-i-dependency-gaps-v0.16.0.md) and [`phase-i-intermediate-artifact-persistence-spec.md`](phase-i-intermediate-artifact-persistence-spec.md): replace "Recipe A" / "Recipe B" with generic role names, drop or rephrase Module N / Phase B / Phase D / Task 2 references, replace consumer recipe filenames (`cifar10-base.yaml`, `cifar10c-eval.yaml`) and consumer-side phase-plan links with generic placeholders, generalize consumer-specific record counts and tag names. Story I.h scrubbed only the hard-blacklisted course identifiers (see developer auto-memory) for in-course blast-radius reduction; this Future story is the deliberate rewrite once the course is complete. Git history will continue to carry the original consumer surface regardless. Added during Story I.h execution.
