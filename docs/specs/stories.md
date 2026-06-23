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

## Phase K: Consumer Gap Resolution - Ingestion, Hash, Feature-Array

Phase K resolves three consumer-surfaced gaps catalogued in [`consumer-gap-solutions.md`](consumer-gap-solutions.md): generalized taxonomy/recursive **ingestion** (path-template + shared resolver), a symlink-blind input-**hash** correctness bug, and audio float-**feature-array** egress (`npy_per_record` + `feature_path`). The detailed plan is in [`phase-k-consumer-gap-resolution-plan.md`](phase-k-consumer-gap-resolution-plan.md). As an ongoing maintenance phase, it also absorbs **bugfixes and ad-hoc changes** as they arise — append them as new stories under this heading following the normal Version Cadence; they need not relate to the three founding gaps.

---

### Story K.a: Refactor README.md (v0.22.0/v0.23.0 catch-up — audio plugin, segmented identity) [Done]

Documentation-only refactor bringing the repo-root `README.md` current with the
Phase-J releases. No version bump — pure doc catch-up (the features already
shipped in v0.22.0 / v0.23.0); rides the next code-story release per Version
Cadence.

- [x] Announce `audio_classification` as a second fully-real plugin (intro, "Why", Plugin model): `audio_folder` / `audio_flat` sources + required `target_sample_rate`, `window` Generation op, `log_mel_spectrogram` + fit-on-train `audio_normalize` Featurizations
- [x] Add the `[audio]` extra (librosa) to Installation; add an audio recipe example to Quickstart
- [x] Bump recipe anatomy `schema_version: 1` → `3`
- [x] Rewrite cache-identity prose: flat hash → four-segment identity (`core` / `plugin` / `overlays` / `extensions`) + per-segment scoped invalidation
- [x] `variants` → `overlays` (recipe anatomy block, section-roles table, `--variant` → repeatable `--overlay`); document the `extensions` namespace
- [x] Fix instance layout: `recipe.yaml` → `recipe.json`; correct the validate-check count (23 → 29)
- [x] Add the `Sinks` recipe section (section-roles table + brief example) and the `export` CLI verb

---

## Subphase K-1: Audio Feature-Array Egress (Gap 3 - Blocker)

Resolves consumer Gap 3 (see [`consumer-gap-solutions.md`](consumer-gap-solutions.md)). Adds the additive `npy_per_record` float-array sink + `feature_path` so prepared audio features can be persisted for downstream consumption. Ships as a bundled **`v0.24.0`** minor (the multi-release-subphase exception, per the phase plan). Cross-repo: paired with ModelFoundry's `plan_features` loader work — neither half unblocks the consumer alone. The subphase's last story (K.e) owns the version bump.

---

### Story K.b: [Spike] Audio feature-array persistence integration spike [Done]

Integration spike that ratifies the cross-repo `feature_path` contract before implementation. Light — the 2026-06-23 MF review already settled Q1–Q6 in [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Audio feature-array persistence". De-risks FR-K-3 / FR-K-4. Deliverable: [`phase-k-subphase-1-feature-persistence-spike.md`](phase-k-subphase-1-feature-persistence-spike.md).

- [x] Re-confirm the pinned contract: `npy_per_record` at `features/<split>/<record_id>.npy`; persist the raw `mel` (pre-normalize); `feature_path` **instance-root-relative**; `(n_mels, n_frames)` `float32`, rank-2 in v1; `feature_path` nested-safe and authoritative over any stray `path`
- [x] Confirm additive versioning (new `SinkOp.format` enum value + optional `feature_path`) ⇒ no recipe `schema_version` bump; sink output covered by `(recipe_hash, input_hash, seed)` cache identity
- [x] Draft the live R-level feature-persistence requirement text for [`features.md`](features.md) (the seam the archived Phase J audio spec left unspecified) — drafted in the spike doc § 3, to be landed by Story K.d
- [x] Record the MF gap-doc anchor-staleness flag: the in-repo copy is fixed; MF's own repo copy must match at `plan_features` (instance-root anchor, not `dataset/`-relative) — cross-repo action carried to Story K.e
- [x] Settle the doc-layout convention for the copied seam docs (`docs/specs/` vs `docs/specs/modelfoundry/`) — developer's call; capture the decision — per-consumer subdir, prefix dropped; DR-side cross-links fixed, shared-surface fixups deferred to K.c
- [x] Deliverable: ratified contract notes + the drafted R-level requirement; no production code

---

### Story K.c: `npy_per_record` float-array sink + `feature_path` rewrite [Done]

Implements FR-K-3: the additive `npy_per_record` sink writer, the instance-root-relative `feature_path` JSONL rewrite, and manifest wiring, mirroring `png_per_record`. Bundled into `v0.24.0` (version bump + CHANGELOG owned by K.e).

- [x] Extend the `SinkOp.format` Literal with `npy_per_record` ([`recipe/models.py`](../../src/datarefinery/recipe/models.py)); the per-record `feature_path` is a serialization-time JSONL field (parallel to `image_path` — not a model field); updated [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) (re-ratified producer side forward-declared → shipped)
- [x] Implement the `npy_per_record` writer (`np.save`, `float32`) in [`pipeline/sinks/writers.py`](../../src/datarefinery/pipeline/sinks/writers.py); enable the currently-dead non-PNG branch in [`pipeline/sinks/runner.py`](../../src/datarefinery/pipeline/sinks/runner.py)
- [x] Rewrite `feature_path` at dataset serialization (instance-root-relative; nested-safe), parallel to the `png_per_record` `path` rewrite ([`pipeline/path_rewrite.py`](../../src/datarefinery/pipeline/path_rewrite.py) `feature_path_rewrite_plan` → [`pipeline/runner.py`](../../src/datarefinery/pipeline/runner.py) `_prepare_record_for_persistence`)
- [x] Manifest wiring: `manifest.sinks[<name>].format` reports `npy_per_record`; `features/<split>/` joins the atomic temp-then-promote unit (sink output writes under the instance temp dir)
- [x] Tests: deterministic byte-identical `.npy` across runs (same recipe + inputs + seed); changed featurization param ⇒ different recipe identity (cache miss); `(n_mels, n_frames)` `float32` on disk; nested `feature_path` round-trips

---

### Story K.d: Double-normalize guardrail + R-level persistence requirement [Planned]

Implements FR-K-4: a validator check preventing silent double-normalization, plus landing the live R-level feature-persistence requirement drafted in the K.b spike. Bundled into `v0.24.0`.

- [ ] Validator check (egress analogue of check 26): an `npy_per_record` sink that rewrites `feature_path` MUST target the pre-normalize field (`mel`), failing fast at `validate` if it points at the already-normalized `feature`; the message names the op
- [ ] Land the R-level feature-persistence requirement in [`features.md`](features.md) (the data side MUST be able to persist R4/R5 features); refresh any stale link to the archived Phase J audio requirements
- [ ] `recipe-authoring.md`: document `npy_per_record` and the `mel`-not-`feature` guardrail
- [ ] Tests for the new check (pass + fail cases); update the validate-check count where documented

---

### Story K.e: Cross-repo coordination + Subphase K-1 release (v0.24.0) [Planned]

Coordinates the paired rollout with ModelFoundry and ships the bundled **`v0.24.0`** release for Subphase K-1.

- [ ] CHANGELOG: a prominent cross-repo contract entry (new `npy_per_record` format + the `feature_path` shape-binding surface; additive, no `schema_version` bump) with a blast-radius note
- [ ] Flag to ModelFoundry: build the `feature_path` loader branch against the **instance-root** anchor (vendor-spec Q1), not the `dataset/`-relative wording; paired with MF `plan_features` (neither half unblocks alone)
- [ ] Confirm [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) § "Audio feature-array persistence" is re-ratified from forward-declared to shipped
- [ ] Ship `v0.24.0`: bump `__version__` and run the full local CI gate (`mypy src tests`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `pyve test`)

---

## Subphase K-2: Generalized Ingestion & Hash Correctness (Gaps 1 + 2)

Resolves consumer Gaps 1 and 2 (see [`consumer-gap-solutions.md`](consumer-gap-solutions.md)). Ships as a single bundled **`v0.25.0`** minor release: the spike (K.f) opens the subphase, and the resolver (K.h, FR-K-1) and the symlink-hash fix (K.g, FR-K-2) land together on a shared file-enumeration helper. The subphase's last story (K.i) owns the version bump.

---

### Story K.f: [Spike] Path-template grammar + shared cross-plugin resolver boundary [Planned]

Architectural spike (deliverable = a documented design decision, not production code) to settle the `layout` path-template grammar and the shared cross-plugin directory-resolver boundary before implementation. De-risks FR-K-1.

- [ ] Decide the `layout` template grammar: components `{label}`, `{split}`, `{file}`; wildcards `*` (exactly one ignored level) / `**` (any depth) — mirror the sink path-template grammar in [`pipeline/sinks/template.py`](../../src/datarefinery/pipeline/sinks/template.py) for surface consistency
- [ ] Specify the static validation rules (exactly one `{label}` for labeled sources; depth/consistency checks) that FR-K-5 will enforce
- [ ] Define the shared `path_tree` resolver interface: inputs (`layout` + plugin file-extension set + plugin decode hook), outputs (`[(path, record_id, label?, split?)]`); how the image and audio loaders call it
- [ ] Settle `{split}` vs per-source `InputSource.partition` precedence (mutual exclusion; template wins when present)
- [ ] Record the field-rename refutation (`image`/`sample_array` stay plugin-owned; no `observation`/`sample` generalization) as a closed decision
- [ ] Confirm the input hash must digest the **resolved** file set and that traversal stays deterministically sorted (the K.g coupling point)
- [ ] Capture the decided grammar + resolver boundary in the phase plan (or a short design memo); no production code

---

### Story K.g: Input hash follows symlinked directories [Planned]

Test-first bugfix for Gap 2: the hasher's `_iter_files` (`root.rglob("*")`) does not descend symlinked directories on Python 3.12, so a symlinked-dir tree hashes to an effectively empty file set — a silent stale-cache / wrong-data reproducibility bug, while the loader reads the real files. Implements FR-K-2; bundled into `v0.25.0`.

- [ ] Failing reproduction test: two symlink views with different targets must yield different `_hash_image_folder` digests, plus a loader-vs-hasher file-set-parity assertion
- [ ] Fix `_iter_files` ([`pipeline/inputs.py:382-383`](../../src/datarefinery/pipeline/inputs.py#L382-L383)) to follow symlinked directories with cycle protection (dedupe on resolved real-paths); keep traversal deterministically sorted
- [ ] Introduce the shared enumeration helper so the loader and hasher walk the **same** file set (the FR-K-1 coupling point)
- [ ] Verify `_hash_image_flat` (reuses `_hash_image_folder`) is fixed for free
- [ ] Housekeeping: check the audio plugin's hashing ([`plugins/audio_classification/inputs.py`](../../src/datarefinery/plugins/audio_classification/inputs.py)) for the same symlink-blind `rglob` pattern
- [ ] Note the cache-identity effect in CHANGELOG (resolved-file-set hashing; pre-prod invalidation acceptable)

---

### Story K.h: Shared `path_tree` resolver + `image_tree`/`audio_tree` source types [Planned]

Implements FR-K-1 per the K.f spike: the shared cross-plugin directory resolver, the `*_tree` source types, and the `layout` template, migrating the image and audio loaders onto one enumeration. Lands with K.g's shared helper; bundled into `v0.25.0`.

- [ ] Add `image_tree` / `audio_tree` source discriminants + `layout: str` to the recipe model ([`recipe/models.py`](../../src/datarefinery/recipe/models.py)); update [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) (shape-binding `core`/`plugin` surface)
- [ ] Implement the shared `path_tree` resolver (template + ext-set + decode hook → records); reuse the K.g enumeration helper
- [ ] Migrate `_load_one_image_folder` and the audio `audio_folder`/`audio_flat` loaders to delegate to the resolver; keep bare `image_folder`/`audio_folder` as sugar for `{label}/{file}` (backward-compatible)
- [ ] Reconcile `{split}` with `InputSource.partition` (mutual exclusion; template wins when present)
- [ ] `recipe-authoring.md`: document `*_tree` + the `layout` grammar with worked examples
- [ ] Tests: `class/image`, `category/class/image`, and `split/category/class/image` trees resolve; byte-identical re-materialization; deterministic ordering

---

### Story K.i: Validate check for unsatisfiable layouts (v0.25.0 — Subphase K-2 release) [Planned]

Additive static validator check (FR-K-5) that fails fast at `validate` when a `*_tree` source's `layout` cannot be satisfied by a well-formed tree, instead of deferring to `materialize`. Owns the bundled **`v0.25.0`** release for Subphase K-2.

- [ ] Add the validator check: exactly one `{label}` for labeled sources; flag a `{label}` level that resolves to only subdirectories (no files); depth consistency — the message names the offending nesting
- [ ] Tests for the new check (pass + fail cases); update the validate-check count where documented
- [ ] `recipe-authoring.md`: document the check
- [ ] Ship the bundled `v0.25.0` minor: bump `__version__`, add a CHANGELOG entry enumerating K-2 (recursive ingestion + symlink-hash fix), and run the full local CI gate (`mypy src tests`, `ruff check src/ tests/`, `ruff format --check src/ tests/`, `pyve test`)

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
- **`parquet` sink format** — a columnar sink format alongside the `npy_per_record` float-array sink (Phase K, FR-K-3), for consumers that prefer columnar feature storage over per-record `.npy` sidecars. Phase K ships only `npy_per_record`; `parquet` is deferred until a recipe surfaces a concrete need. Added during Phase K planning.
