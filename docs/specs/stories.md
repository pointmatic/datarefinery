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

### Story J.b: NbFoundry vendor-dependency-spec stand-up [Planned]

**Disposition: documentation + cross-repo contract.** Part of Phase J phase-bundle release. Closes FR-J-2.

NbFoundry has no equivalent of [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md), yet it binds against DataRefinery's library entry points, CLI surface, and notebook-display output formats. Stand up [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) as a separate doc (per phase-plan decision: separate docs are easier to manage than a unified consumer-contract doc).

**Best executed after Story J.d** (NbFoundry integration spike) so spike findings feed the contract-doc authoring rather than the other way around.

**Tasks:**

- [ ] Create [`docs/specs/nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) mirroring the structure of the MF doc.
- [ ] Document the **library entry points** NbFoundry consumers may import — `DataRefinery`, `DataRefinery.from_recipe`, `.materialize()`, instance result accessors. Pin signatures and return types.
- [ ] Document the **CLI commands** NbFoundry consumers may invoke from notebook cells — verb names, flag names, exit codes, error-message contracts (specifically the messages NbF parses).
- [ ] Document the **notebook-output ergonomics** — `--log-target`, progress-bar suppression flags, stdout/stderr expectations, `rich`-rendering behavior inside Marimo cells.
- [ ] Document **schema-version coordination** (mirror MF doc § Schema-version coordination policy) and **forward-compatibility expectations** (unknown ops, unknown manifest keys).
- [ ] Document **failure modes NbFoundry SHOULD detect** — schema-version mismatch, missing manifest fields, plugin missing.
- [ ] Document the **versioning and adoption** policy (pre-prod / post-prod stability promises; same shape as MF doc).
- [ ] Cross-reference from [`docs/specs/concept.md`](concept.md), [`docs/specs/features.md`](features.md), and [`docs/specs/project-essentials.md`](project-essentials.md) § "Recipe / manifest / report shape changes need a cross-repo coordination check" — extend the "three surfaces" entry to name both consumer-spec docs.

**Out of Scope:**

- Implementing any new library API or CLI verb for NbFoundry's benefit. If the spike surfaces concrete gaps, those become separate Phase J stories.
- NbFoundry-side adoption work. Owned by the NbFoundry repo.

---

### Story J.c: Integration spike — ModelFoundry [Planned]

**Disposition: integration spike** (throwaway; deliverable is a documented friction list, not production code). Part of Phase J phase-bundle release. Closes FR-J-3.

Take a fresh v0.19.0 DataRefinery materialized instance, consume it from a minimal ModelFoundry harness, exercise the documented contract surfaces, capture friction. The friction list feeds the next cluster of Phase J stories (contract-doc fixes, ergonomic library/CLI fixes, small additive manifest fields).

**Tasks:**

- [ ] Time-box (target: one working session). Pick a representative recipe (existing fixture or scaffolded `init` output).
- [ ] Materialize a fresh instance with v0.19.0 DataRefinery.
- [ ] From a minimal MF harness (real or mocked), exercise: recipe-model reads against schema_v2 names; `manifest.json` reads of every field MF binds against per [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md); dataset `<split>.jsonl` reads + sidecar PNG resolution for an aggressive-mode variant; `report.md` + `drift.json` reads.
- [ ] Capture a **friction list** in `docs/specs/phase-j-mf-integration-friction.md`: each item names what was expected, what happened, and what fix (or contract-doc clarification) it implies. Categorize: contract-doc errors, missing fields, ergonomic snags, schema_v2 surprises.
- [ ] Present the friction list at the approval gate; the developer decides which items become follow-up Phase J stories and which are no-ops.

**Out of Scope:**

- Production ModelFoundry adapter code. The spike is investigation, not implementation.
- Fixing the friction items in-band. Each one becomes a separate Phase J story (or is dropped at the gate).

---

### Story J.d: Integration spike — NbFoundry [Planned]

**Disposition: integration spike** (throwaway; deliverable is a documented friction list, not production code). Part of Phase J phase-bundle release. Closes FR-J-4.

Write a Marimo notebook that uses DataRefinery via library calls AND CLI subprocess invocations. Exercise common patterns (load → validate → materialize → inspect a materialized instance). The friction list feeds Story J.b's contract-doc authoring.

**Execute before J.b** so the contract doc reflects real ergonomics rather than aspirational ones.

**Tasks:**

- [ ] Time-box (target: one working session). Scaffold a minimal Marimo notebook in a scratch directory.
- [ ] Exercise the **library path**: `from datarefinery import DataRefinery`, `.from_recipe`, `.materialize()`, instance result accessors. Note what gets imported, what works, what's missing.
- [ ] Exercise the **CLI path**: invoke `datarefinery validate`, `materialize`, `status` as subprocesses from notebook cells. Note exit codes, stdout/stderr behavior, whether `rich` tables render usefully inside Marimo, whether progress bars need suppression.
- [ ] Capture a **friction list** in `docs/specs/phase-j-nbf-integration-friction.md`: same shape as J.c — what was expected, what happened, what fix it implies. Pay particular attention to log-target redirection, progress-bar noise, and error-message machine-readability.
- [ ] Present the friction list at the approval gate; the developer decides which items inform J.b's contract doc and which become separate Phase J stories.

**Out of Scope:**

- Production NbFoundry integration code. The spike is investigation, not implementation.
- Authoring [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md) — that is Story J.b, which executes after this spike.

---

### Story J.e: schema_version 2 consumer-side adoption check [Planned]

**Disposition: cross-repo verification.** Part of Phase J phase-bundle release. Closes FR-J-5.

v0.19.0 ships `schema_version 2` with a loader-side v1→v2 migration. Verify both consumers handle v1 recipes (migrated by the loader) and v2 recipes (native shape) cleanly. May collapse into J.c / J.d if those spikes organically exercise both versions.

**Tasks:**

- [ ] Confirm `datarefinery.recipe.loader.SUPPORTED_SCHEMA_VERSIONS == {1, 2}` and the v1→v2 migration produces a v2-shape recipe (`recipe.json` reflects v2 canonical bytes).
- [ ] During J.c, feed both a v1 fixture recipe and a v2 fixture recipe through the MF harness — confirm both work end-to-end.
- [ ] During J.d, do the same in the Marimo notebook — confirm both versions materialize and the resulting instance is readable.
- [ ] Document any consumer-side surprises (e.g., MF binds against a v1 field name internally) as additions to the J.c / J.d friction lists; coordinate fixes via the relevant `vendor-dependency-spec.md`.

**Out of Scope:**

- Adding new schema versions. v2 is the current shape; v3 is a future ceremony.
- Schema_v2 changes to the recipe model itself. The phase-bundle is verification, not further reshape.

---

### Story J.f: `manifest.label_classes` — canonical class-set enumeration [Planned]

**Disposition: feature addition + cross-repo contract.** Part of Phase J phase-bundle release (target v0.20.0). Closes the class-enumeration gap surfaced during the [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) 2026-06-11 ratification round 2.

Today the manifest carries no canonical class set. Every consumer that needs label→logit-index mapping, confusion-matrix axes, or per-class column naming scans JSONL itself and picks a sort convention out-of-band. Two consumers (or two flows in one consumer) can silently disagree on ordering, producing misaligned predictions ↔ confusion matrix ↔ class-weight vectors. Centralize the list in the manifest so ordering becomes the producer's commitment.

**Tasks:**

- [ ] Add `Manifest.label_classes: list[Any] | None = None` field in [`src/datarefinery/pipeline/manifest.py`](../../src/datarefinery/pipeline/manifest.py).
- [ ] Compute at materialize time in [`pipeline/runner.py`](../../src/datarefinery/pipeline/runner.py): scan all labeled records across all defined splits (skip unlabeled records per FR-22), take the distinct union, sort ascending using Python `sorted(...)` semantics. Empty when no labeled records exist → field is `None`.
- [ ] Emit at both the full and partial manifest-build sites (mirror the `class_balance` and `sample` emission discipline).
- [ ] Unit tests: balanced multi-class, sparse class (present only in test), single-class, fully-unlabeled (`None`), `str` and `int` label dtypes. Confirm the manifest-side computation matches a JSONL-derived scan over all splits.
- [ ] Integration test: round-trip a fixture recipe and assert the manifest's `label_classes` matches the JSONL-derived set on a recipe with disjoint train/val/test class coverage.
- [ ] Cache-identity guard: confirm the new field perturbs no canonical bytes (it lives in manifest, not recipe) — pinning fixture stays green.
- [ ] **Cross-repo coordination.** Update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md): ratify the forward-declared `manifest.label_classes` shape subsection — remove the "forward-declared" / "pre-J.f" caveats; mark the field as live in the current release.
- [ ] DOC: update [`docs/specs/tech-spec.md`](tech-spec.md) manifest section to enumerate the new field.
- [ ] CHANGELOG entry under the in-progress v0.20.0 section: additive manifest field, no `schema_version` bump (no canonical-bytes perturbation), consumer-bind addition.
- [ ] CI parity: `pyve test`, `pyve testenv run mypy src tests`, `pyve testenv run ruff check src/ tests/`, `pyve testenv run ruff format --check src/ tests/`.

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
