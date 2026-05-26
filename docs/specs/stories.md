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

## Phase I: Bug Fixes and Feature Gaps in v0.16.0

Phase I collects investigation and fix work surfaced by the d802 consumer's cross-check against DataRefinery v0.16.0 (see [`docs/specs/dependency-gaps-v0.16.0.md`](dependency-gaps-v0.16.0.md), entries G1–G17 + DOC). Each gap entered Phase I as a candidate bug; debug-mode investigation determines whether each is a defect (closes here with a code fix) or a feature/architectural gap (a `[Planned]` story is captured here and handed off to `plan_phase` when the developer scopes the work).

### Story I.a: G5 investigation — reclassify as G7 (no code fix) [Done]

**Disposition: documentation-only.** No version bump (no code change).

Debug-mode investigation of [`dependency-gaps-v0.16.0.md` § G5](dependency-gaps-v0.16.0.md) (`augmented_sample_grid` raises `TypeError` on post-normalize float images) determined that G5 is **not a defect**. It is the surface symptom of G7 (visualization stage dispatch — all reporting visualizations run at `post_pipeline` only). The architectural fact is that `augmented_sample_grid` is semantically defined on pixel arrays; z-score values aren't pixels; the viz crashes because it has no way to observe the pre-normalize representation. That capability is G7.

Three candidate code fixes were considered and rejected:

1. **Convert `TypeError` → actionable `RecipeError` at the viz layer.** Error-message quality only; the recipe still cannot use the viz post-normalize. Pure polish.
2. **Make realizers float-tolerant.** Suppresses the crash, but the viz's `_tile` clip-casts z-score values ~[-2, 2] to uint8 [0, 255], producing mostly-black tiles. Silently wrong is worse than crashing.
3. **Stage-aware viz dispatch (= G7).** The honest fix; out of scope for a debug cycle, captured as Story I.b below.

This story produces no code change. Its deliverable is the reclassification in the gap doc and the planned-story handoff to G7.

**Tasks:**

- [x] Reproduce the bug with a failing test (`tests/plugins/image_classification/test_visualizations_augmented_sample_grid.py`); confirmed the documented `TypeError: Cannot handle this data type: (1, 1, 3), <f8` symptom from PIL.Image.fromarray. Test reverted — would pin the wrong contract going forward.
- [x] Audit the four lazy-mode augmentation realizers for float-input behavior: `horizontal_flip` and `color_jitter` crash on float arrays (PIL-backed); `random_crop` and `random_erasing` are pure-numpy and don't crash but the downstream `_tile` would clip-cast z-score values to a meaningless tile.
- [x] Document the investigation outcome in [`docs/specs/dependency-gaps-v0.16.0.md` § G5](dependency-gaps-v0.16.0.md): status block, severity reclassified to "Subsumed by G7," fix path "implement G7."
- [x] Update the dependency-gaps priority summary table: G5 row severity → "Subsumed by G7."
- [x] Update the dependency-gaps recipe-side workarounds table: G5 row → "(No G5-only recipe edit; when G7 lands, restore the viz with `stage: pre_transformations`)."
- [x] Capture Story I.b `[Planned]` in this file for G7 — the genuine fix path.

**Prevention scan (no code changes needed for I.a, but captured for the G7 implementer):**

- The lazy-mode augmentation realizer dtype-handling matrix (above) is the audit surface G7's implementer should inspect first. Two realizers crash on floats; two are silent-but-wrong. Either way, stage-aware dispatch is the right fix; per-realizer dtype-coercion is the wrong fix.
- The viz `_tile` clip-cast at [`augmented_sample_grid.py:144-145`](../../src/datarefinery/plugins/image_classification/visualizations/augmented_sample_grid.py#L144-L145) is dead code once G7 lands and viz operates on uint8 inputs. Remove it as part of G7 unless a defensible cross-stage compatibility argument surfaces.

**Out of Scope**

- Implementing G7 itself. That's Story I.b (`[Planned]`).
- Implementing options 1 or 2 above as a polish-only intermediate fix. Both were rejected during investigation; shipping polish doesn't move the consumer closer to the working viz they want.
- Reclassifying other G entries (G6, G8, etc.) in the same pass. Each gets its own debug cycle.

### Story I.b: G7 — Stage-aware visualization dispatch `[Planned]`

**Disposition: planned, not started.** Awaiting `plan_phase` scope or developer assignment. Captured here so the architectural commitment is recorded in the project's source of truth (`stories.md`), not just in the gap doc.

Per [`dependency-gaps-v0.16.0.md` § G7](dependency-gaps-v0.16.0.md): all reporting-mode visualizations today run at `post_pipeline` only. The `VisualizationOp.stage` field is read by the model but not honored by the runtime — `apply_reporting_visualizations` ([`pipeline/stages/visualizations.py:97`](../../src/datarefinery/pipeline/stages/visualizations.py)) receives only the final post-pipeline splits. The bundled scaffolder writes `stage: post_pipeline` ([`scaffolder/init.py:193`](../../src/datarefinery/scaffolder/init.py)), confirming the de-facto contract.

This story implements stage-aware dispatch: each declared `VisualizationOp.stage` selects which intermediate-stage split snapshot the viz renders against. With it, `augmented_sample_grid` runs at `stage: pre_transformations` and reads uint8 records (resolving G5 as a side effect); `sample_grid` can declare pre/post-normalize variants for the Module 2 learner-facing comparison.

**Why this matters.** Two consumer flows are blocked today:

- G5 (`augmented_sample_grid` post-normalize) — see Story I.a.
- The d802 phase plan's `sample_grid_pre_normalize` vs. `sample_grid_post_normalize` pedagogical comparison ([`docs/specs/dependency-gaps-v0.16.0.md` § G7](dependency-gaps-v0.16.0.md)).

**Design sketch** (per gap doc; final design decided at story-start, not pinned here):

The localized option is **stage snapshots**. Each pipeline stage that materially changes records snapshots a reference to its outputs; `apply_reporting_visualizations` receives a `Mapping[str, Mapping[str, list[Record]]]` keyed by stage name then split name; each `VisualizationOp.stage` selects which snapshot. Less invasive than per-stage viz dispatch (which would require every stage to know about viz). `STAGE_NAMES` in [`pipeline/runner.py:96`](../../src/datarefinery/pipeline/runner.py#L96) already enumerates valid stages.

**Tasks (illustrative — refine at story-start):**

- [ ] Constrain `VisualizationOp.stage` from `str` to `Literal[<valid stage names>]` so unknown-stage typos fail at validate time rather than producing silent fall-through behavior. Add a validator check that the named stage produced output records at materialize time (i.e., not bypassed by an empty pipeline branch).
- [ ] Extend `pipeline/runner.py` to snapshot per-stage split outputs (references, not copies — the records are immutable mappings by construction). Snapshot points: post-Input, post-Filters/pre_split, post-Splits, post-Filters/post_split, post-Transformations, post-Augmentations, post-Featurizations, post-pipeline.
- [ ] Change `apply_reporting_visualizations` ([`pipeline/stages/visualizations.py`](../../src/datarefinery/pipeline/stages/visualizations.py)) to accept the snapshot mapping; dispatch each `VisualizationOp` against its declared stage's snapshot.
- [ ] Update the bundled scaffolder ([`scaffolder/init.py`](../../src/datarefinery/scaffolder/init.py)) to write `stage: post_pipeline` as the default when no stage is declared, preserving today's behavior.
- [ ] Test: a recipe with two `sample_grid` viz ops at `stage: post_filter` and `stage: post_transformations` materializes; both PNGs land in `report/visualizations/`; the pre-transformations PNG is visually recognizable as uint8 imagery, the post-transformations PNG shows the normalized representation.
- [ ] Test: G5 closes — a recipe with `normalize` Transformation + `augmented_sample_grid` at `stage: pre_transformations` materializes successfully and produces a visually sensible PNG.
- [ ] Remove the dead `_tile` clip-cast at [`augmented_sample_grid.py:144-145`](../../src/datarefinery/plugins/image_classification/visualizations/augmented_sample_grid.py#L144-L145) since the viz now reads uint8 by construction (or document why it remains as defense-in-depth).
- [ ] Update [`docs/guides/recipe-authoring.md` § Visualizations](../guides/recipe-authoring.md#visualizations) with the `stage:` vocabulary, the mapping from stage name to "what records you see," and worked examples per the DOC rule in the gap doc.
- [ ] Update [`docs/specs/modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md) if any manifest field or report subsection shape changes (the snapshot indirection is internal; per-stage report subsections may be a follow-up).
- [ ] Close G5 and G7 in [`dependency-gaps-v0.16.0.md`](dependency-gaps-v0.16.0.md) priority summary table; remove G5 and G7 rows from the recipe-side workarounds table.
- [ ] Version bump: minor (new capability — `VisualizationOp.stage` semantically functional for the first time). Per project-essentials cache-identity rules, evaluate whether the canonical-hash pinning test needs an update; constraining `VisualizationOp.stage` to a `Literal` doesn't perturb canonical bytes for recipes that already declared a valid stage value.

**Out of Scope** (negotiable at story-start):

- Per-stage report subsections (one report.md heading per snapshotted stage). Out of scope unless the developer opts it in; the v1 deliverable is single-section report with per-viz `stage:` annotations.
- Backfilling the FR-VIZ-1..4 visualizations to declare canonical stages (each already runs at `post_pipeline`; updating them to declare richer stages is a follow-up).
- Resume-from-stage during materialization. Snapshots are in-memory references for viz dispatch only, not a persisted resume artifact.

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
