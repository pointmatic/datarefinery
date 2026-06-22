# Requirement Spec: Audio-Classification Modality Plugin

**Target repo:** DataRefinery
**Status:** Proposed (consumer requirement)
**Type:** New modality plugin

This document is written to drop into DataRefinery's own document chain. It states *what* a consumer project needs from the data-preparation side to support an audio-classification problem, and *which existing contracts* that touches — not *how* to implement it. Terminology follows DataRefinery's `concept.md` / `features.md` / `tech-spec.md`.

---

## Context

A consumer project is building two classifiers against a single, shared data-preparation grammar: one image problem (already served by the `image_classification` plugin) and one **audio** problem. The audio problem is a non-image modality used deliberately as a *modality-boundary test* — it exercises whether the pipeline's abstractions (stages, fit-on-train discipline, determinism, caching, plugin interface) generalize beyond image data without becoming "image with extra steps."

The audio data has properties the current image plugins do not address:

- **Variable-length clips.** Recordings differ in duration; the model consumes fixed-length inputs, so each clip must be windowed into one or more fixed-length frames.
- **A spectral feature step.** The model trains on a time-frequency representation (log-mel spectrogram, or MFCC), derived on the data side rather than inside the model.
- **Clip-level (weak) labels.** A label applies to an entire clip, not to each window cut from it. The target species may be present in only part of the clip, and recordings carry quality variance and background noise.
- **Test-time aggregation.** A clip's prediction is formed by aggregating across the windows cut from that clip.

There is precedent for the consumer following an existing plugin: `image_classification` is fully implemented, while `tabular` and `text` ship as stubs that validate cleanly and fail at materialize time. This request asks DataRefinery to add an **`audio_classification`** plugin in that same shape, implemented (not stubbed) to the extent the requirements below define.

---

## Requirements

Behavior-level requirements, numbered. Each is phrased as a capability the recipe author must be able to express and the pipeline must honor.

### R1 — Audio input sources

The plugin SHALL declare audio input source type(s) analogous to the existing image sources:

- A directory-of-class-subdirectories form (labels derived from directory name at load time), parallel to `image_folder`.
- A flat-directory-plus-sidecar-manifest form, parallel to `image_flat` with `label_from`, for datasets whose labels live in a CSV/manifest joined by record id.
- Support for an `unlabeled: true` partition (typical heldout/eval sets), consistent with the existing `Labels.source.kind: direct` semantics.

Each loaded record SHALL establish a baseline `record_id` and a path to its audio payload, so that downstream per-record seeding and caching behave exactly as for image records.

### R2 — Decode

The plugin SHALL decode audio payloads to a canonical in-pipeline representation (sample array + sample rate), with a declared, deterministic resampling policy when source sample rates differ. Decode is a deterministic, per-record operation: same input bytes → same decoded array.

### R3 — Windowing of variable-length clips

The plugin SHALL provide an operation that turns a variable-length clip into one or more fixed-length windows, with author-declared window length and hop/stride, and a declared, deterministic policy for the trailing remainder (pad vs. drop). Windowing is the **key design point** — see Open Questions for whether it lands as a record-count-changing `Generation` operation or a fixed-tensor `Featurization`. Whichever placement is chosen, the operation MUST:

- Preserve the parent clip's `record_id` association so that test-time aggregation (R7) can group windows back to their source clip.
- Be deterministic and reproducible per record under the existing seeding contract.

### R4 — Spectral featurization (data side)

The plugin SHALL provide a `Featurization`-stage operation that converts a fixed-length window into a time-frequency feature (log-mel spectrogram or MFCC), with author-declared parameters (e.g., FFT/window size, mel bands, hop). This is a derive-new-feature operation: one feature output per input window, no record-count change, consistent with the `Featurizations` stage contract.

### R5 — Fit-on-train feature normalization

Feature normalization of the spectral representation SHALL follow DataRefinery's existing fit-on-train discipline:

- The normalization operation declares its fit source as the training split (`fit_source: train`), is fit **only** on the training split, and is applied across all declared splits using the persisted statistics.
- Fitted statistics persist to `fitted_statistics/<op_id>/` in the existing structured formats (scalars as JSON, vectors as parquet) — no opaque pickles.
- The existing `stats_from_instance` sibling-import path SHALL work for audio normalization unchanged (so a separate evaluation recipe can read training statistics from a sibling instance), preserving the mutual-exclusivity of `fit_source` and `stats_from_instance`.

### R6 — Weak / clip-level label semantics

The plugin SHALL let a recipe author express that labels are **clip-level** and propagate to the windows cut from a clip. At minimum:

- A label declared on a clip is inherited by every window derived from that clip.
- Label-dependent stages (stratified splitting, label filters, label-reading featurizations) operate at the **clip** level, not the window level, so that all windows of one clip stay within a single split (no train/eval leakage across a clip's windows).

Robust handling of *noisy* labels (label-confidence weighting, noise-robust losses) is **out of scope for the data side** and belongs to the modeling repo; this requirement covers only the clip→window label-propagation and split-integrity semantics.

### R7 — Test-time window aggregation

The plugin SHALL provide a declared mechanism to aggregate window-level outputs back to a single clip-level result at evaluation time (e.g., mean/max over a clip's windows), keyed on the parent `record_id` from R3. The aggregation policy is author-declared and deterministic.

### R8 — Plugin-interface conformance

The `audio_classification` plugin SHALL conform to the existing `Plugin` protocol: declare `name`, `supported_sections`, `supported_operations` (each with its `OperationSpec` parameter schema, fit-on-train flag, applicable splits, and stage-applicability), implement `operation_factory`, and report `is_stub()` honestly. It SHALL be discoverable via the existing `datarefinery.plugins` entry-point group. Operations MUST be assigned to the correct stage so the recipe validator's stage-applicability checks apply unchanged.

---

## Contract impact

Which existing DataRefinery invariants/contracts this touches, and the claim that none are silently violated (the consumer's VT-3 gate cross-checks this section against the current contracts).

- **Stage model (unchanged).** All new operations map onto existing stages (`Input`, `Filters`, `Splits`, `Generation`, `Transformations`, `Featurizations`, `Augmentations`, `OutputExpectations`, `Visualizations`). No new stage is introduced. The only contract-sensitive choice is whether windowing is a record-count-changing `Generation` op (which MUST record the count change in the manifest, per the Generation contract) or a fixed-tensor `Featurization` op (one output per input) — see Open Questions.
- **Determinism (preserved).** Every stochastic audio operation is seeded through the existing `derive_seed(master_seed, op_name)` / per-record seeding contract; same recipe + inputs + seed yields a byte-identical instance. Decode/resample, windowing, and featurization are deterministic.
- **Caching identity (preserved).** Audio operations participate in the existing `(recipe_hash, input_hash, seed)` cache identity. No new cache-key surface is added; cosmetic recipe edits remain cache hits and semantic edits remain cache misses.
- **Fit-on-train discipline (preserved).** Normalization fits only on the training split, persists to `fitted_statistics/<op_id>/`, and is enforced by the existing validator check that fit-on-train transforms declare the training split as fit source. `fit_source` vs. `stats_from_instance` mutual exclusivity is unchanged.
- **Plugin-interface honesty (preserved).** The audio plugin is a genuine second-category modality validating the abstractions, added as a real plugin under the existing protocol and discovery mechanism — not a fork of the image plugin.
- **Label/split integrity (extended, not broken).** Clip-level labels and the "all windows of a clip stay in one split" rule extend the existing label semantics; the existing rule that label-dependent stages are rejected on unlabeled splits remains in force.
- **Cross-repo contract (unaffected).** This is a data-preparation requirement; it does not alter the DataRefinery↔ModelFoundry shared surface. The model's consumption of windowed, normalized features and its MC-dropout inference path live entirely in the modeling repo.

---

## Acceptance criteria

Testable, for DataRefinery to verify (phrased to match the existing acceptance-criteria and contract-test conventions).

1. A recipe author can take a directory of audio clips (class-subdirectory or flat+manifest form) and produce a materialized instance via `init` → `validate` → `materialize` with no manual workarounds.
2. Re-running the same audio recipe + inputs + seed produces a **byte-identical** instance (excluding the documented `created_at` / `elapsed_seconds` fields).
3. Cosmetic recipe edits (whitespace, comments, key reordering) yield a cache **hit**; semantic edits (changed window length, mel-band count, added/removed op) yield a cache **miss**.
4. Windowing produces deterministic, reproducible windows for a fixed seed and input set, identical across worker counts; each window retains its parent clip `record_id`.
5. Spectral featurization adds exactly one feature output per input window (no record-count change at the `Featurization` stage).
6. Normalization fits on the training split only and persists structured `fitted_statistics/<op_id>/` (JSON scalars / parquet vectors); a sibling recipe importing those statistics via `stats_from_instance` reads them through without duplicating them.
7. Clip-level labels propagate to all windows of a clip, and stratified splitting keeps every window of a given clip within a single split (verifiable: no clip's `record_id` appears in two splits).
8. The plugin passes a plugin-contract test asserting its declared sections, operation list, and parameter schemas; stage-applicability and fit-on-train validator checks fire correctly against fixture recipes.
9. A failed audio materialization leaves a `FAILED`-marked temp directory and never produces a partial cached instance.

---

## Open questions

1. **Windowing placement (primary).** Should windowing be a record-count-changing `Generation` operation (one clip → N window records, fan-out recorded in the manifest) or a fixed-tensor `Featurization` that emits a windowed tensor per clip without changing record count? The `Generation` form makes each window a first-class record (clean per-window stratification and seeding, but the clip→window grouping for R7 aggregation must be tracked explicitly); the `Featurization` form keeps one record per clip (grouping is implicit, but per-window operations and counts become tensor-internal rather than pipeline-visible). This choice drives how R3, R6, and R7 are expressed and is the main decision requested of DataRefinery.
2. **Resampling canonicalization.** Should a single target sample rate be mandated at decode (R2), or should the plugin support per-recipe target rates? A fixed canonical rate simplifies cache identity reasoning.
3. **Aggregation ownership.** Is test-time window aggregation (R7) a DataRefinery `Visualizations`/reporting-side concern, a declared output-shaping concern, or should it be left entirely to the modeling repo with DataRefinery only guaranteeing the clip↔window key? The consumer's preference is that DataRefinery guarantee the grouping key and the modeling repo own the aggregation math — confirmation requested.
4. **Augmentation scope.** Are audio-domain training-time augmentations (time/frequency masking, time shift) in scope for v1 of this plugin, or deferred? If in scope, they follow the existing lazy/aggressive `Augmentations` contract and seeding.
