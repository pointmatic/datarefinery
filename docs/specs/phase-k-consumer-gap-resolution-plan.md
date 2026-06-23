<!--
Copyright (c) 2026 Pointmatic
SPDX-License-Identifier: Apache-2.0
-->

# Phase K plan — Consumer Gap Resolution: Ingestion, Hash, Feature-Array

This is the `plan_phase` plan document for the Phase K expansion that absorbs the three consumer-surfaced gaps catalogued in [`consumer-gap-solutions.md`](consumer-gap-solutions.md). Phase K opened as "Data Ingestion Improvements, Bugfixes" with a single shipped story (K.a, the v0.22.0/v0.23.0 README catch-up). This plan broadens the phase to cover all three confirmed gaps and orders the remaining work as new stories under the same phase heading.

The gaps were investigated 2026-06-22 against the current `main` source and each concluded **confirmed**. For the per-gap evidence (file:line), corrections, and solution sketches, see [`consumer-gap-solutions.md`](consumer-gap-solutions.md); this plan summarises, orders, and scopes that work. The cross-repo half of the picture lives in the same consumer's report to the ModelFoundry repo, [`modelfoundry/consumer-gap-solutions.md`](modelfoundry/consumer-gap-solutions.md) — a consumer who authors recipes for both tools must understand the DR↔MF seam, so MF's gap tensions inform the DR scope (see § Cross-repo coordination).

---

## Phase K description revision

Phase K's existing heading in [`stories.md`](stories.md) is **"Data Ingestion Improvements, Bugfixes."** That title scoped only the ingestion (input) side. Gap 3 adds an **egress/persistence** capability (a float-array sink), which is architecturally distinct from ingestion, so the title is broadened (kept short):

- **Old:** `## Phase K: Data Ingestion Improvements, Bugfixes`
- **New:** `## Phase K: Consumer Gap Resolution - Ingestion, Hash, Feature-Array`

A short **phase preamble** lands under the heading (it does not exist today):

> Phase K resolves three consumer-surfaced gaps catalogued in [`consumer-gap-solutions.md`](consumer-gap-solutions.md): generalized taxonomy/recursive **ingestion** (path-template + shared resolver), a symlink-blind input-**hash** correctness bug, and audio float-**feature-array** egress (`npy_per_record` + `feature_path`). As an ongoing maintenance phase, it also absorbs **bugfixes and ad-hoc changes** as they arise — append them as new stories under this heading following the normal Version Cadence; they need not relate to the three founding gaps.

Story K.a (README catch-up, `[Done]`) remains as-is and continues to anchor the phase narrative. The new work is organised into two subphases (see § Story sequence). Story letters continue monotonically from K.a — the first new story is **K.b**.

---

## Gap analysis — what exists vs. what's needed

| Gap | What exists today | What is needed |
|---|---|---|
| **Gap 1 — taxonomy ingestion** | `image_folder` enumerates classes as immediate subdirs and globs images one level down ([`pipeline/inputs.py`](../../src/datarefinery/pipeline/inputs.py) `_load_one_image_folder`); `audio_folder`/`audio_flat` reimplement the identical one-level contract in [`plugins/audio_classification/inputs.py`](../../src/datarefinery/plugins/audio_classification/inputs.py). A `category/class/image` tree fails at `materialize` (validate is filesystem-blind). | A **named-component path-template** (`layout: "{split}/*/{label}/{file}"`) expressing arbitrary nesting, backed by a **shared cross-plugin directory resolver** the image and audio loaders both call. `{label}` subsumes `parent_directory_name`; `{split}` folds partitioning into the tree (reconciled with the existing per-source `partition`). Bare `image_folder` stays as sugar for `{label}/{file}` (backward-compatible). |
| **Gap 2 — symlink-blind input hash** | The hasher's `_iter_files` uses `root.rglob("*")` ([`inputs.py:382-383`](../../src/datarefinery/pipeline/inputs.py#L382-L383)); on Python 3.12 `**` does **not** descend symlinked dirs (`recurse_symlinks` is 3.13+), so a symlinked-dir tree hashes to an effectively empty file set — a silent stale-cache / wrong-data reproducibility bug. The loader, however, *does* read the real images → loader/hasher walk different sets. | `_iter_files` must follow symlinked directories with **cycle protection** (track visited resolved real-paths), keeping traversal deterministically sorted, so the hash digests the **resolved** file set. The durable fix is a **shared enumeration helper** so loader and hasher never diverge again. |
| **Gap 3 — audio float features cannot be persisted** | Only `png_per_record` (uint8) ships; the recipe model pins `format: Literal["png_per_record"]` ([`models.py:502`](../../src/datarefinery/recipe/models.py#L502)) and the JSONL writer drops numpy arrays. The plugin *computes* windowed log-mel features (`mel`/`feature`) but there is **no serialization path** for a float feature array — and no consumer-side workaround. | An additive **`npy_per_record`** sink `format` that persists a named float field per record at `features/<split>/<record_id>.npy` and rewrites a per-record **`feature_path`** into the JSONL, mirroring how `png_per_record` persists pixels + rewrites `path`. Plus the requirements-layer rule that closes the seam, and a validator guardrail against double-normalization. |

A cross-cutting concern, **cross-repo contract discipline**, runs through Gaps 1 and 3: any change to recipe shape, manifest, or on-disk layout is a binding surface for ModelFoundry (and other consumers) per [`project-essentials.md` § "Recipe / manifest / report shape changes need a cross-repo coordination check"](project-essentials.md). The relevant `vendor-dependency-spec.md` is updated in the same change.

---

## Feature requirements (mini features.md)

Each requirement is implemented as one or more stories in the [§ Story sequence](#story-sequence-and-version-bumps). Cross-references cite the canonical features.md FRs the work extends.

### FR-K-1 — Generalized path-template ingestion + shared cross-plugin resolver (Gap 1)

A new source type family expresses dataset layout as a **named-component path template** rather than an enumerated flavor:

```yaml
Input:
  sources:
    - name: logos
      type: image_tree            # audio_tree for the audio plugin
      path: datasets/logos
      layout: "{split}/*/{label}/{file}"
```

Grammar (mirrors the existing sink path-template grammar in [`pipeline/sinks/template.py`](../../src/datarefinery/pipeline/sinks/template.py) for recipe-surface consistency): `{label}` (the labeled component; subsumes `Labels.source.derivation: parent_directory_name`), `{split}` (folds partitioning into the tree), `{file}` (the file component), `*` (exactly one ignored level), `**` (any depth ignored). All current and reported flavors collapse to templates (`{label}/{file}`, `**/{label}/{file}`, `{split}/*/{label}/{file}`). Bare `image_folder` / `audio_folder` remain as sugar for `{label}/{file}` (fully backward-compatible).

The directory resolver — which path components mean what, where files live — is **modality-independent and factored into a shared `path_tree` resolver** that takes the `layout` template + the plugin's file-extension set + the plugin's decode hook. The image and audio loaders both delegate to it, eliminating the per-modality duplication. Modality-prefixed type names (`image_tree`, `audio_tree`) stay at the recipe surface for clarity; the resolver is shared underneath. The resolver deals in `path` + `record_id`, **not** the decoded payload field — so the per-record JSONL field name (`image`, `sample_array`) is unchanged (see § Out of scope, field rename).

`{split}` and the existing per-source `InputSource.partition` are **mutually exclusive** (template wins when present); `partition` is retained for the still-valid "separate roots per split" case. The input hash must digest the **resolved** file set (so the same tree + seed still materializes byte-identically); traversal stays deterministically sorted. New `layout` text adds to canonical recipe bytes (a `core`/`plugin`-segment surface — pre-prod invalidation acceptable per `project-essentials.md`).

### FR-K-2 — Input hash follows symlinked directories (Gap 2)

`_iter_files` follows symlinked directories with cycle protection (dedupe on resolved real-paths to avoid symlink loops), so the input hash digests the resolved file set rather than a symlink-blinded empty set. Because `recurse_symlinks=True` is unavailable on Python 3.12, the fix is an explicit walk (e.g. `os.walk(..., followlinks=True)` over the resolved root, or a manual stack that `resolve()`s and dedupes each dir), keeping traversal deterministically sorted. `_hash_image_flat` reuses `_hash_image_folder` and is fixed for free; the audio plugin's hashing is checked for the same `rglob` pattern as a housekeeping item. The loader and hasher walk the **same** file set via a shared enumeration helper — the load/hash asymmetry is the root cause, so unifying enumeration is the durable fix (and is the explicit coupling point with FR-K-1's resolver: they land together).

### FR-K-3 — `npy_per_record` float-array sink + `feature_path` (Gap 3)

DataRefinery adds an `npy_per_record` sink `format` that persists a named float field per record at `features/<split>/<record_id>.npy` and rewrites a per-record `feature_path` into `<split>.jsonl`. The array is a **sidecar**, never inlined into the JSONL — the "arrays are in-pipeline; persist via sidecar" convention holds. The contract is the one **ratified in the 2026-06-23 MF review round** and pinned in [`modelfoundry/vendor-dependency-spec.md` § "Audio feature-array persistence"](modelfoundry/vendor-dependency-spec.md):

- **Field persisted:** the raw **`mel`** (pre-normalize `log_mel_spectrogram` output); the consumer applies the persisted per-mel-bin `audio_normalize` stats at load. Persisting the already-normalized `feature` would double-normalize.
- **`feature_path` anchor:** **instance-root-relative** (`<instance>/<feature_path>`) — the J.g sink-`path` bucket, **NOT** the `image_path`/`dataset/`-relative bucket.
- **On-disk shape/dtype/rank:** `(n_mels, n_frames)`, `float32`, always 2-D in v1 (mono decode); the consumer owns the channel-dim unsqueeze to `(1, n_mels, n_frames)`. Persisted `audio_normalize` `mean`/`std` stay `float64`.
- **`feature_path` may be nested** (window `record_id` can carry `/`) and is authoritative over any stray source `path`.
- **Versioning:** additive (a new `SinkOp.format` enum value + a new optional per-record `feature_path` field) ⇒ **no recipe `schema_version` bump**; existing recipes' canonical bytes are unchanged. Sink output is instance content → covered by `(recipe_hash, input_hash, seed)` cache identity exactly as `png_per_record` is.
- **Rejected:** the uint8-PNG spectrogram route (lossy, non-round-trippable, wrong channel/normalization semantics). Both repos independently rejected it; **do not build it.**

`manifest.sinks[<name>].format` reports `npy_per_record` when shipped, and the section in `vendor-dependency-spec.md` is re-ratified from forward-declared to shipped at that point.

### FR-K-4 — Requirements-layer feature-persistence rule + double-normalize guardrail (Gap 3)

Two seam-closing additions accompany FR-K-3:

1. **A live R-level requirement** in [`features.md`](features.md) stating the data side MUST be able to *persist* R4 (spectral feature) / R5 (fit-on-train normalize) outputs for downstream consumption. The archived Phase J audio requirements spec covered *compute* (R4) and *normalize* (R5) but scoped *consumption* to the modeling repo and declared the cross-repo surface "unaffected," so persistence fell through the seam — Gap 3 is that unspecified bridge. Restating it in DataRefinery's live document chain prevents the seam from silently re-opening the next time a modality computes a non-uint8 feature.
2. **A validator check** (the egress analogue of check 26): an `npy_per_record` sink that rewrites `feature_path` MUST target the pre-normalize field (`mel`), failing fast at `validate` if it points at the already-normalized `feature`. This prevents the consumer from silently double-normalizing. ModelFoundry mirrors the guard at load (verify `field == mel` before applying stats).

### FR-K-5 — Additive validate check for unsatisfiable layouts (Gap 1)

A static validator check flags a `*_tree` source whose `layout` cannot be satisfied by a well-formed tree — e.g. a `{label}` level that resolves to only further subdirectories with no files, exactly one `{label}` for labeled sources, depth consistency — failing at the cheap static gate with a message naming the nesting, instead of deferring to `materialize`.

---

## Technical changes (mini tech-spec)

| Area | Change |
|---|---|
| `src/datarefinery/recipe/models.py` | Add `image_tree` / `audio_tree` source discriminants + `layout: str`; reconcile `{split}` vs `partition` (mutual exclusion). Extend `SinkOp.format` Literal with `npy_per_record`; add optional per-record `feature_path`. **All four are shape-binding surfaces** — `vendor-dependency-spec.md` updated in the same change. |
| `src/datarefinery/pipeline/inputs.py` (new shared resolver) | New `path_tree` resolver (template + ext-set + decode hook → `[(path, record_id, label?, split?)]`). `_load_one_image_folder` and the audio loaders delegate to it. New shared **enumeration helper** used by both the loader and `_iter_files` (the FR-K-1/FR-K-2 coupling point). Fix `_iter_files` to follow symlinks with cycle protection. |
| `src/datarefinery/plugins/audio_classification/inputs.py` | Delegate `audio_folder`/`audio_flat`/`audio_tree` to the shared resolver; verify hashing has no residual symlink-blind `rglob`. |
| `src/datarefinery/pipeline/sinks/` (`runner.py`, `writers.py`) | New `npy_per_record` writer (`np.save` of the named float field, `float32`); enable the currently-dead non-PNG sink branch. `feature_path` rewrite at dataset serialization (instance-root-relative), parallel to the `png_per_record` `path` rewrite. |
| `src/datarefinery/pipeline/manifest.py` | `manifest.sinks[<name>].format` reports `npy_per_record`; `features/<split>/` joins the atomic temp-then-promote unit. |
| `src/datarefinery/recipe/validator.py` | New checks: unsatisfiable-`layout` (FR-K-5) and `feature_path`-sink-targets-`mel` (FR-K-4). |
| Docs | `recipe-authoring.md` sections for `*_tree`/`layout` and `npy_per_record`; `features.md` R-level persistence requirement; `vendor-dependency-spec.md` re-ratification + the cross-repo coordination note; `CHANGELOG.md` blast-radius callouts. |

**Constraints to preserve:** determinism (deterministically-sorted traversal; byte-identical re-runs); the `pipeline.workers` determinism contract; cache-identity discipline (resolved file set drives the input hash; sink output covered by cache identity); the no-implicit-defaults rule for any new op params; loose-coupling invariants (the consumer reads sink output read-only and never re-hashes the instance).

---

## Cross-repo coordination (DataRefinery ↔ ModelFoundry)

**1. DR `consumer-gap-solutions.md` aligns with the binding contract.** Verified point-for-point against [`modelfoundry/vendor-dependency-spec.md` § "Audio feature-array persistence"](modelfoundry/vendor-dependency-spec.md): sink name/path, Q1 anchor (instance-root-relative), Q2 field (`mel`), Q3/Q4 dtype+rank, the rejected PNG route, and the additive/no-bump versioning all match. **No contract revision or renegotiation is required on the substance.**

**2. The MF-side gap doc's *stale* `feature_path` anchor — reconciled in-repo.** [`modelfoundry/consumer-gap-solutions.md`](modelfoundry/consumer-gap-solutions.md) (reviewed **2026-06-22**) stated `feature_path` was "relative to `dataset/`" and "mirrors how `png_per_record` rewrites `image_path`" — but the contract was **corrected one day later** in the 2026-06-23 MF review round (vendor-spec **Q1**): `feature_path` is **instance-root-relative**, the J.g sink-`path` bucket, **not** the `image_path`/`dataset/` bucket. The MF gap doc simply predated the review. It was staleness, not a live conflict — MF's *shipped* Gap-1 fix (Story I.k) already anchors a bare relative `path` to the instance root, and vendor-spec Q1 says `feature_path` "joins that branch." **The in-repo reference copy has been updated** to the instance-root anchor (three references, each annotated with the 2026-06-23 correction) so the conflict stops surfacing. **Remaining cross-repo action (K.e):** the *same* fix must be applied to the authoritative copy in MF's own repo when MF runs `plan_features` — *"build the `feature_path` loader branch against the instance-root anchor (vendor-spec Q1), not the `dataset/`-relative wording."*

**3. Paired rollout.** Gap 3 ships in two repos: DR ships `npy_per_record` (this phase, `plan_phase`); MF ships the feature-array loader branch (`plan_features`). **Neither half unblocks the consumer alone — they land together against the ratified contract.** DR owns feature cache identity; MF consumes read-only.

**4. Doc-layout decision (developer's call, non-blocking).** Both repos' seam docs cross-link a `docs/specs/modelfoundry/` layout, while the analysis docs live at `docs/specs/`. Settle the intended directory convention for these copied seam docs so cross-links resolve. This is a doc-layout question, not a code or contract change.

---

## Out of scope

Dispositions below were walked through with the developer. A **"Future"** disposition means the item is added to the `## Future` section of [`stories.md`](stories.md) (or, for a large item, gets its own `docs/specs/`-level spec — e.g. [`future-feature-tight-coupling-cache-identity.md`](future-feature-tight-coupling-cache-identity.md)). A **"Refuted"** disposition is a closed decision: not deferred, not pursued.

- **Field rename `image` → `observation`/`sample` — REFUTED (closed decision).** Not deferred. The directory resolver touches only `path` + `record_id`, never the decoded payload field, so the rename buys the resolver nothing. The per-record payload field name is a **plugin-owned binding surface** whose specificity is intentional: `image_classification` owns `image`, `audio_classification` owns `sample_array`/`mel`/`feature`, and each name carries real modality meaning at a consumer-binding surface. Collapsing them to a generic "observation"/"sample" *removes* information, overloads a term ("sample" already means a PCM sample in audio and the whole dataset in statistics), and would cost the full shape-binding rename ceremony (schema bump + migration + `vendor-dependency-spec.md` + deprecation horizon) for negative value. The resolver keeps modality-prefixed type names (`image_tree`, `audio_tree`) at the recipe surface for exactly this reason — clarity on top, DRY underneath.
- **Multi-channel `(C, n_mels, n_frames)` audio features — out of scope, no Future entry yet.** v1 decodes mono (`librosa.load(..., mono=True)`) and the featurization chain emits one log-mel per window, so arrays are always rank-2; vendor-spec Q4 has the consumer own the unsqueeze to `(1, n_mels, n_frames)`. A `C > 1` dimension would require a capability v1 lacks (multi-channel/stereo decode, or a delta/delta-delta feature-stacking op) — there is no concrete driver today, so it gets no `## Future` line yet (implicitly covered by "audio-plugin capabilities beyond v1"). When such a capability lands, the on-disk rank goes 2→3, a shape-binding change with its own coordination.
- **`parquet` sink format — Future.** Add to `## Future` in [`stories.md`](stories.md): a columnar sink format alongside `npy_per_record`; only `npy_per_record` lands this phase.
- **Inline npy/base64 in the JSONL (option 2) and the uint8-PNG spectrogram sink (option 3) — REFUTED.** Both independently rejected by both repos (bloat / lossy, breaks the in-pipeline-array and reproducibility contracts). Not built; documented-and-rejected only.
- **FR-ARCH-1 tight coupling** (sibling `recipe_hash` in the consumer's cache key) and **`stats_from_instance.variant` selector — already Future.** Both already live in `stories.md § Future`; tight coupling additionally has its own spec at [`future-feature-tight-coupling-cache-identity.md`](future-feature-tight-coupling-cache-identity.md). Unchanged by this phase.
- **MF-side loader work** (feature-array branch, `audio_normalize` load-time branch, window→clip regrouping). Separate repo via `plan_features`; in scope here only as the coordination flag (K.e).
- **`recursive: true` flag on bare `image_folder`** (the naive Gap-1 fix). Superseded by the path-template grammar; not shipped as a separate flavor.

---

## Story sequence and version bumps

Story K.a (`[Done]`) is unchanged. The new work splits into two subphases; story letters continue monotonically (K.b…). The phase opens each subphase with a spike (per the spike-first decision), and the FR-K-1 resolver and FR-K-2 hash fix **land together** (shared enumeration).

### Subphase K-1: Audio feature-array egress (Gap 3) — blocker, runs first

| Story | Title | FR | Bump |
|---|---|---|---|
| **K.b** | **[Spike]** Audio feature-array persistence integration spike — re-ratify the `feature_path` surface in `vendor-dependency-spec.md` (forward-declared → pinned), draft the live R-level persistence requirement, pin axis/dtype/rank, confirm cache-identity coverage, and record the MF gap-doc anchor-staleness flag. (Light spike: the 2026-06-23 review already settled Q1–Q6.) | FR-K-3/4 | none (spike) |
| **K.c** | Implement `npy_per_record` sink — writer (`float32`), `feature_path` rewrite (instance-root-relative), manifest wiring; `vendor-dependency-spec.md` re-ratified to shipped. | FR-K-3 | minor |
| **K.d** | Double-normalize guardrail validator check (`feature_path`-rewriting `npy_per_record` sink must target `mel`); `features.md` R-level requirement landed. | FR-K-4 | (rides K.c) |
| **K.e** | Cross-repo coordination — CHANGELOG blast-radius note, flag the instance-root anchor to MF, coordinate paired rollout with MF `plan_features`. Owns the bundled `v0.24.0` release. | — | (rides K.c) |

### Subphase K-2: Generalized ingestion & hash correctness (Gaps 1 + 2)

| Story | Title | FR | Bump |
|---|---|---|---|
| **K.f** | **[Spike]** Path-template grammar + shared cross-plugin resolver boundary — settle the `layout` grammar + static validation, the shared-resolver interface and how the image/audio plugins call it, `{split}` vs `partition` precedence, and the explicit field-rename refutation. Deliverable = decided grammar + resolver boundary, not production code. | FR-K-1 | none (spike) |
| **K.g** | Input hash follows symlinked directories (test-first bugfix) — failing reproduction test, `_iter_files` symlink-follow with cycle protection, shared enumeration helper, audio-hash `rglob` housekeeping check. | FR-K-2 | patch |
| **K.h** | Shared `path_tree` resolver + `image_tree`/`audio_tree` + `layout` — implement the resolver, migrate the image and audio loaders, `{split}`/`partition` reconciliation; lands with K.g's shared enumeration. | FR-K-1 | minor |
| **K.i** | Additive validate check for unsatisfiable layouts. Owns the bundled `v0.25.0` release. | FR-K-5 | (rides K.h) |

**Version cadence (confirmed): per-subphase release — the multi-release-subphase exception.** Subphase K-1 ships **`v0.24.0`** and Subphase K-2 ships **`v0.25.0`**. K-1 is a blocker, runs first. Rationale (required by the exception per the Phase and Story ID Scheme § "Multi-release exception"): K-1 (egress) and K-2 (ingestion + hash) are separable, conceptually distinct deliverables, and K-1 is gated on ModelFoundry coordination — a clean tag boundary between them aids the paired rollout.

Within each subphase the stories are **bundled** (phase-bundling option): stories carry no version in their title, and the subphase's **last code story owns the single bump** (magnitude = highest-impact change in the bundle — a `minor` each, for the new ingestion and egress features respectively). The `Bump` column above therefore reads as the change's *magnitude contribution*, not a per-story tag; the spikes contribute none, and `(rides …)` stories share the owning story's release. The Gap-2 correctness bugfix (K.g) rides the `v0.25.0` bundle rather than shipping as an earlier standalone patch because there is already a workaround.
