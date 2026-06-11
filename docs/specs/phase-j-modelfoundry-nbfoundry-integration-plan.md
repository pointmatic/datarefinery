# Phase J plan — ModelFoundry + NbFoundry integration

> **Type:** combined gap analysis + mini-features + mini-tech-spec for
> Phase J, generated via `plan_phase` (pre-1.0).
> **Predecessor:** Phase I (v0.19.0 — schema_version 2, twelve gap closures).
> **Authoring source:** [`phase-j-context-prompt.md`](phase-j-context-prompt.md)
> (Story I.z), refreshed 2026-05-30 at Phase I close.

## Theme

Phase J is the **integration phase**: wiring DataRefinery into its two
downstream consumers — **ModelFoundry** (deep contract consumer of the
recipe model, manifest, dataset on-disk layout, and report) and
**NbFoundry** (notebook-side consumer using DataRefinery as a library +
CLI inside Marimo cells). DataRefinery is a **vendor** to both
consumers; see [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md)
for the existing MF-side contract.

Phase J is a **catch-all** by design: seed it with the known gaps below,
expect most stories to accrete reactively as real integration work
surfaces friction.

## Gap analysis — what exists vs. what's needed

**What exists at the start of Phase J (post-v0.19.0):**

- ModelFoundry-binding contract surface — [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md):
  recipe-model contract (`Augmentations` and the rest of schema_v2),
  on-disk dataset layout, manifest fields (incl. `class_balance` from
  I.s, `sinks` from I.d), report subsections (`report.md`, `drift.json`,
  visualizations), cache-identity contract, schema-version coordination
  policy, forward-compat expectations.
- Recipe schema **v2** (Phase I bundle 4: FilterOp reshape, GenerationOp
  reshape, assertion-kind naming), v1→v2 loader migration in
  `recipe.migrations.v1_to_v2`.
- Sample-data **schema** (`SampleSelector.kind` ∈ {uniform, per_class},
  `splits`) wired into validation + cache identity (Story I.r).
- `class_balance` MF-binding hint emitted on `SplitResult.class_balance`
  and `manifest.class_balance` (Story I.s / G10).
- Image-classification plugin only; tabular and text are stubs
  (`is_stub() → True`).

**Gaps Phase J must close (priority order):**

1. **SampleData runtime not wired** (highest-priority seed).
   `SampleData` validates and shapes cache identity but produces no
   subset at materialize time. Story **I.r.0** (Done in v0.18.0)
   documented the open product decisions and recommended
   **P-postpipeline + M-sidecar** (subset per-split post-pipeline; emit
   a `sample/` sidecar alongside the full materialized dataset). Phase J
   carries that recommendation into a runtime implementation story.

2. **No NbFoundry vendor-dependency contract.** ModelFoundry has
   [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md);
   NbFoundry has nothing equivalent. Library entry points, CLI surface,
   and output formats are de-facto contracts the moment NbFoundry binds
   against them. Phase J stands up
   [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md)
   as a separate doc (per developer decision: separate docs are easier
   to manage than a unified consumer-contract doc — the two consumers
   bind to substantially different surfaces).

3. **No real integration evidence** for either consumer yet. The MF
   vendor-dependency-spec was authored against the DR-side
   implementation, not validated against an actual MF run. Phase J
   includes one integration spike per consumer to surface real friction.

4. **`schema_version 2` adoption** unverified at consumers. v1→v2 ships
   in v0.19.0; MF/NbF consumer-side handling needs to be validated
   end-to-end (loader picks up v1 recipes correctly; consumer code reads
   the v2 names).

5. **NbFoundry CLI-in-notebook usage patterns undocumented.** The
   NbFoundry concept calls for DataRefinery to be usable inside Marimo
   notebooks as both a library and a CLI. The output ergonomics (rich
   tables, progress bars, log target redirection) need to work cleanly
   when invoked from a notebook subprocess or cell. Surface this as a
   concrete usage doc.

## Feature requirements (mini features.md)

**FR-J-1 — SampleData runtime (P-postpipeline + M-sidecar).**

- Subset the materialized dataset per-split *after* the pipeline runs.
- Honor `SampleSelector.kind`:
  - `uniform`: random subset of `n` (or `fraction`) records per
    selected split, seeded reproducibly.
  - `per_class`: stratified subset — `n` records per class label per
    selected split (reads `Labels.field` on the final per-record dict).
- Honor `SampleSelector.splits` (when set) — sample only the listed
  splits; default to all splits when unset.
- Emit a **sidecar** `sample/` directory alongside `dataset/` in the
  instance: same JSONL-per-split layout (`sample/train.jsonl`,
  `sample/val.jsonl`, …) plus referenced PNG sidecars where applicable.
- Emit a `manifest.sample` field: `{ "selector": { … echo … },
  "record_counts": { "<split>": <int>, … } }`. `null`/absent when no
  `SampleData` section is declared.
- Update FR-2 check #16 to read "subset of the prepared dataset" (was:
  "subset of the declared input") — the placement decision flips the
  spec wording.
- Cross-repo coordination: add `manifest.sample` row + `sample/` layout
  subsection to `modelfoundry/vendor-dependency-spec.md`.

**FR-J-2 — NbFoundry vendor-dependency contract.**

- Stand up [`nbfoundry/vendor-dependency-spec.md`](nbfoundry/vendor-dependency-spec.md)
  mirroring the MF doc's structure but scoped to NbFoundry's actual
  binding surface:
  - **Library entry points** consumers may import — `DataRefinery`,
    `DataRefinery.from_recipe`, `.materialize()`, instance result
    accessors (TBD; pinned during the spike).
  - **CLI commands** consumers may invoke from notebook cells — verbs,
    flag names, exit codes, error-message contracts (for the messages
    consumers parse).
  - **Output ergonomics** — `--log-target`, `--no-progress` (or
    equivalent) for clean notebook display; what stdout/stderr look
    like; whether `rich` tables render inside Marimo.
  - **Versioning and adoption** clauses (same shape as MF doc).

**FR-J-3 — Integration spike (ModelFoundry).**

- Throwaway exercise: take a fresh v0.19.0 DR materialized instance,
  consume it from a minimal ModelFoundry harness, exercise the documented
  contract surfaces (recipe-model reads, manifest reads, dataset reads,
  report reads). Deliverable is a **documented friction list** —
  surprises, missing pieces, contract-doc errors — which feeds the next
  cluster of Phase J stories.

**FR-J-4 — Integration spike (NbFoundry).**

- Throwaway exercise: write a Marimo notebook that uses DataRefinery via
  library calls AND CLI subprocess invocations. Exercise common patterns
  (load → validate → materialize → inspect). Deliverable is a
  **documented friction list** — what works smoothly, what doesn't —
  which feeds FR-J-2's contract-doc authoring and any concrete library/CLI
  fixes.

**FR-J-5 — schema_version 2 consumer-side adoption check.**

- Verify MF and NbF can read v1 recipes (loader migrates) and v2
  recipes (native shape). Pin the consumer-side support sets against
  `datarefinery.recipe.loader.SUPPORTED_SCHEMA_VERSIONS`. Surface any
  consumer bug as a coordinated fix.

## Technical changes (mini tech-spec.md)

**New modules / files:**

- New pipeline stage for SampleData runtime — likely
  `src/datarefinery/pipeline/stages/sample_data.py`, sequenced after the
  final per-split stage. Inputs: per-split record iterables + the
  resolved `SampleDataSection`. Outputs: per-split sampled record
  iterables + a `SampleResult` carrying record counts and selector echo.
- New on-disk subtree under each instance:
  `<instance>/sample/<split>.jsonl` and (where applicable)
  `<instance>/sample/<split>/images/<record_id>.png` (or pointer to
  source PNG; settle in the story).
- New manifest field: `Manifest.sample: SampleManifestEntry | None` in
  `src/datarefinery/pipeline/manifest.py`.
- New consumer-spec file:
  `docs/specs/nbfoundry/vendor-dependency-spec.md`.

**Modified modules:**

- `src/datarefinery/recipe/models.py`: no model change (`SampleSelector`
  is already complete from Story I.r); possibly add a `SampleResult`
  helper alongside `SplitResult`.
- `src/datarefinery/pipeline/runner.py`: invoke the new sample-data
  stage after splits and feed its result into manifest emission.
- `src/datarefinery/pipeline/manifest.py`: add `class SampleManifestEntry`
  and the `sample:` field on `Manifest`.
- `src/datarefinery/recipe/validators.py` (check 16): update wording
  from "subset of the input" → "subset of the prepared dataset" if the
  P-postpipeline decision holds; otherwise no validator change.
- `docs/guides/recipe-authoring.md` § SampleData: replace the
  "Runtime status (v0.18.0)" callout with the v1-shape behavioral spec.
- `docs/specs/features.md` FR-2 check #16: update the wording (above).
- `docs/specs/tech-spec.md` § instance directory tree: add
  `sample/` block.
- `docs/specs/modelfoundry/vendor-dependency-spec.md` § manifest:
  add `manifest.sample` row + shape subsection; § on-disk layout: add
  `sample/` block.

**Cache-identity impact:**

- FR-J-1 changes materialized output bytes for any recipe that declares
  `SampleData:` (the new sidecar appears). Pre-prod re-materialize event
  for those recipes only — call out in CHANGELOG, no `schema_version`
  bump needed (the canonical bytes don't change; the materialization
  semantics do, and pre-prod invalidation is acceptable per
  project-essentials).

**Cross-repo coordination discipline (carries into every story):**

- Three surfaces leave DataRefinery and bind consumers: **recipe model**,
  **manifest schema**, **report subsections**. Any change to these is a
  cross-repo contract change — read and update the relevant
  vendor-dependency-spec(s) in the same change, decide whether a
  `schema_version` bump is required.

## Seed stories (the catch-all expects accretion)

Listed in execution order; Phase J phase-bundles a single end-of-phase
release (no per-story bumps).

- **J.a — SampleData runtime (P-postpipeline + M-sidecar).** Closes
  FR-J-1; carries forward the I.r.0 spike recommendation. The first
  task is to confirm the placement + sidecar decision is still right
  against current evidence (or open a quick re-spike if not).
- **J.b — NbFoundry vendor-dependency-spec stand-up.** Closes FR-J-2.
  Author the doc from the MF template + the NbF concept/features/tech-spec
  + (ideally) the J.d spike's friction list.
- **J.c — Integration spike: ModelFoundry.** Closes FR-J-3.
  Time-boxed; deliverable is a friction-list doc.
- **J.d — Integration spike: NbFoundry.** Closes FR-J-4.
  Time-boxed; deliverable is a friction-list doc that informs J.b.
- **J.e — schema_version 2 consumer-side adoption check.** Closes
  FR-J-5. Pairs with J.c / J.d; may collapse into them if the spikes
  organically exercise v1 + v2.

**Expected accretion path:** J.f, J.g, … land as J.c and J.d surface
concrete friction (contract-doc fixes, ergonomic library/CLI fixes,
small additive manifest fields, etc.). Phase J closes with a phase-bundle
version-bump story that ships all accreted work as a single minor
release.

**Ordering note.** Best executed as **J.d → J.b** and **J.c → contract
fixes (if any)** so spike findings feed the contract-doc work rather
than the other way around. J.a is independent and can run in parallel
or first.

## Out of scope (deferred to Future)

Each item below was considered for Phase J and intentionally left in
[`stories.md § Future`](stories.md). Walk through these at the approval
gate — confirm each is genuinely deferrable.

1. **Real `distributional` assertion kind.** Placeholder always passes;
   downstream drift tools (DataMachine) implement their own checks.
   Stays in Future until a consumer files a concrete need.
2. **Per-stage report subsections.** `report.md` stays single-section;
   stage-aware viz dispatch is internal. Stays in Future.
3. **Real `tabular` plugin.** Stub today; ModelFoundry / NbFoundry can
   ship without it. Stays in Future.
4. **Real `text` plugin.** Same as tabular. Stays in Future.
5. **Broad consumer-context rewrite of internal specs.** Sanitize
   "Recipe A/B" / "Module N" / consumer recipe filenames in the Phase I
   gap doc + intermediate-artifact spec. Stays in Future per Story I.h.
6. **Scaffolder v2 grand sweep.** Bundled `init` scaffolder refresh
   to showcase v2 affordances. Stays in Future per Story I.h.
7. **Default-change discipline tooling.** Canonical-hash pinning
   expansion + pre-commit/CI hook for default-change detection. Stays
   in Future (production-readiness work).
8. **DR-side `class_balance` resampling.** MF-side resampling shipped
   in I.s; DR-side path stays in Future per the entry there.
9. **FR-ARCH-1 tight coupling.** Sibling `recipe_hash` participating in
   consumer cache identity. Stays in Future.
10. **Generic record-tagging primitive.** Factor FR-FILTER-1's
    `label`/`exclude_already_labeled` into a shared mechanism. Stays in
    Future.
11. **Real `to_grayscale` Transformation op.** Removed in Phase I; real
    implementation stays in Future until a recipe surfaces concrete
    need.
12. **`stats_from_instance.variant: <name>` selector.** Stays in Future
    per the entry there.
13. **Plugin-pluggable validator-check reserved-set hook.** Stays in
    Future.
14. **ModelFoundry-side and NbFoundry-side implementation work.** Owned
    by those repos; Phase J only changes the DataRefinery side and the
    cross-repo contract docs.

## Version cadence

Phase J phase-bundles a single minor release at end of phase (most
likely v0.20.0). The phase-bundle bump magnitude is the highest-impact
change in the bundle — FR-J-1 (new manifest field + new on-disk
sidecar layout) is additive and pre-prod, so **minor** is the working
target. If a Phase J story surfaces a breaking change, surface it at
the approval gate before merging — pre-1.0 means re-evaluating the
bundle magnitude rather than auto-promoting to major.
