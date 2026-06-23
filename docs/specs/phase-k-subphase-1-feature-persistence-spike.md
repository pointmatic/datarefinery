<!--
Copyright (c) 2026 Pointmatic
SPDX-License-Identifier: Apache-2.0
-->

# Story K.b — [Spike] Audio feature-array persistence integration spike

**Flavor:** integration spike. **Deliverable:** ratified contract notes + a drafted
R-level feature-persistence requirement (text only). **No production code.** De-risks
FR-K-3 (the `npy_per_record` sink, Story K.c) and FR-K-4 (the double-normalize guardrail
+ the landed R-level requirement, Story K.d).

This is a **light** spike: the cross-repo contract was already settled in the 2026-06-23
ModelFoundry review round (Q1–Q6) and is pinned in
[`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md)
§ "Audio feature-array persistence — `npy_per_record` + `feature_path`". The spike's job is
to re-confirm that contract against current `main` source, draft the requirement text the
implementation stories will land, and capture the one open developer decision (doc layout).

---

## 1. Re-confirmed pinned contract (verified against current `main`)

The six binding answers from the 2026-06-23 MF review round, each re-confirmed against the
source they bind to. No contract drift found — the vendor-spec § is accurate.

| # | Pin | Re-confirmation |
|---|-----|-----------------|
| **Q1** | `feature_path` is **instance-root-relative** (`<instance>/<feature_path>`, e.g. `<instance>/features/<split>/<record_id>.npy`) — the **J.g sink-`path` bucket**, NOT the `image_path`/`dataset/`-relative bucket. | Confirmed against the J.g `path`-rewrite mechanism: sink output lands at `<instance>/<path_template_resolved_root>/…`, a **sibling** of `dataset/`. `image_path` (aggressive variants) is `dataset/`-relative; the two anchors genuinely differ. Matches `project-essentials.md` § "`feature_path` is instance-root-relative". |
| **Q2** | The sink persists the **raw `mel`** (pre-normalize `log_mel_spectrogram` output); the consumer applies the persisted per-mel-bin `audio_normalize` stats at load. Persisting the already-normalized `feature` ⇒ double-normalize. | Confirmed against `features.md` FR-12 #5 / FR-FEAT-1 / FR-FEAT-2: `log_mel_spectrogram` → `mel` (raw, deterministic), then fit-on-train `audio_normalize` → `feature`. Both fields coexist in-pipeline; persisting `mel` keeps the "normalization is the consumer's job" invariant. |
| **Q3** | On-disk dtype **`float32`** (the `mel` array, `librosa.power_to_db(...).astype(np.float32)`). Persisted `audio_normalize` `mean`/`std` are **`float64`** (same promotion as image `normalize` stats). | Confirmed against `features.md` FR-FEAT-1 (`mel` is a `float32` array) and § `audio_normalize` statistics (same parquet shape / zero-variance guard / float64 stats as image `normalize`). |
| **Q4** | On-disk rank **always 2-D `(n_mels, n_frames)`** in v1 (mono decode). The consumer owns the unsqueeze to `(1, n_mels, n_frames)`. `(C, n_mels, n_frames)` is **future**, not v1. | Confirmed against FR-3 loader (R2): mono `float32` via `librosa.load(..., mono=True)`, one log-mel per window ⇒ rank-2 always. Multi-channel is out of scope (phase plan § Out of scope). |
| **Q5** | `feature_path` **may be nested** (window `record_id` is `<clip_id>__w####`, and `clip_id` can carry `/`); join as a relative POSIX path, no assumed flat `features/<split>/` level. | Confirmed against the Story J.h nesting precedent for `image_path` / sidecar PNGs: `record_id` separators are stamped verbatim, the path-writer creates the nested subtree. |
| **Q6** | `feature_path` is **authoritative over any stray source `path`** on the same record (e.g. the decoded `.ogg` clip). | Confirmed against the parallel `image_path`-over-`path` rule for aggressive variants. |

**Pinned shape/orientation (the way a paired fix silently fails to line up):** on disk
`(n_mels, n_frames)` `float32`, librosa-native (mel bins on axis 0); the consumer
`np.load`s it, unsqueezes to `(1, n_mels, n_frames)`, and applies the persisted per-mel-bin
`audio_normalize` `mean`/`std` through the existing fit-on-train read path.

**Rejected (do not build):** the uint8-PNG spectrogram-as-image route — lossy (HDR float32 →
256 levels + clipping), not round-trippable (breaks byte-identical reproducibility), wrong
channel semantics (fake 3-channel RGB vs. true 1-channel), wrong normalization semantics
(image 0–255 vs. per-mel-bin). Both repos independently rejected it. The inline-npy/base64
route (option 2) is also rejected (bloats the JSONL, breaks the in-pipeline-array convention).

---

## 2. Additive versioning confirmed (no recipe `schema_version` bump)

The change is **additive** and therefore needs **no recipe `schema_version` bump**:

- A new `SinkOp.format` enum value (`npy_per_record`) extends the
  `format: Literal["png_per_record"]` ([`recipe/models.py:502`](../../src/datarefinery/recipe/models.py#L502)) — existing recipes never wrote it, so their canonical bytes are unchanged.
- A new **optional** per-record `feature_path` field — opt-in; absent on every existing recipe's records.

**Cache identity coverage.** Sink output is **instance content**, so it is covered by the
existing `(recipe_hash, input_hash, seed)` cache identity exactly as `png_per_record` is:
same recipe + inputs + seed ⇒ byte-identical `.npy`; a changed featurization param ⇒
different `mel` bytes ⇒ cache miss. No new cache-identity surface is introduced — the sink
does not participate in the recipe hash beyond the `layout`/`format` text the author writes
(which is already in canonical bytes via the `Sinks` section). Consumption is **read-only**:
the consumer never re-hashes the instance (loose-coupling invariant), so feature cache
identity stays DataRefinery's responsibility.

This supersedes the older "a float on-disk format would require a `schema_version` bump"
note that previously lived under § "Normalization is applied by the consumer" — the
vendor-spec § already records the supersession.

---

## 3. Drafted R-level feature-persistence requirement (to be LANDED in Story K.d)

The archived Phase J audio requirements brief specified R4 (compute the spectral feature)
and R5 (fit-on-train normalize) on the data side but scoped *feature consumption* entirely
to the modeling repo and declared the DR↔MF surface "unaffected" — so feature **persistence
on the DR side**, the bridge between "computed" (R4) and "consumed" (modeling repo), was
never specified by any requirement and fell through the seam. The text below closes that
seam in DataRefinery's live document chain.

> **Drafted text — NOT yet landed.** Story K.b only drafts this; Story K.d lands it in
> `features.md` (per the phase plan FR-K-4 #1). It is reproduced here verbatim so K.d can
> paste it. Placement: a new behavior point in **FR-12 (Featurizations)**, immediately
> after the existing "In-pipeline vs persisted (audio)" paragraph (`features.md` ~L521),
> plus a new row in the R1–R8 crosswalk table.

### Draft — new FR-12 behavior point

> **Feature-array persistence is a first-class data-side capability.** An in-pipeline
> array feature — one the JSONL writer drops because it is not JSON-native (audio `mel` /
> `feature` today; tabular/text array features as those plugins mature) — MUST have a
> persistence path so a prepared feature can cross the materialized-instance boundary to a
> downstream consumer. The data side fulfils this via the `npy_per_record` sink `format`
> (FR-K-3): it persists a named float field per record at `features/<split>/<record_id>.npy`
> (`float32`, librosa-native orientation for audio) and rewrites a per-record,
> **instance-root-relative** `feature_path` into `<split>.jsonl`. The array is a
> **sidecar** — never inlined into the JSONL — so the "arrays are in-pipeline; persist via
> sidecar" convention holds. For the fit-on-train-normalized case the blessed consumption
> contract is to persist the **pre-normalize** field (`mel`) and let the consumer apply the
> persisted per-mel-bin `audio_normalize` statistics at load (FR-6), keeping normalization
> the consumer's responsibility and avoiding double-normalization (enforced by the FR-K-4
> validator check). This requirement closes the persistence seam the archived Phase J audio
> brief left unspecified: a modality that *computes* a non-uint8 feature MUST be able to
> *persist* it, so the seam cannot silently re-open the next time a plugin derives an array
> feature. The shape-binding details (`feature_path` anchor, dtype, rank, nesting,
> authority over a stray `path`) are pinned in
> [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md)
> § "Audio feature-array persistence".

### Draft — new R-crosswalk row

> | R-ID | Requirement | Canonical home |
> |------|-------------|----------------|
> | R4/R5 egress | Feature-array **persistence** for downstream consumption | FR-12 feature-array persistence → FR-K-3 (`npy_per_record` + `feature_path`); guardrail FR-K-4 |

(Framed as an "R4/R5 egress" bridge rather than minting a new `R9`: the R1–R8 numbering
originated in the consumer's brief and persists only as cross-repo shorthand; the seam is
the *egress* of the already-numbered R4/R5 outputs, so it reads most honestly as their
persistence bridge. K.d may adjust the label if the developer prefers a distinct R-ID.)

---

## 4. MF gap-doc anchor-staleness flag (recorded)

The ModelFoundry-side gap doc [`modelfoundry/consumer-gap-solutions.md`](modelfoundry/consumer-gap-solutions.md)
(reviewed **2026-06-22**) described `feature_path` as "relative to `dataset/`" and "mirrors
how `png_per_record` rewrites `image_path`" — the **wrong anchor**. The contract was
corrected **one day later** (2026-06-23 MF review, vendor-spec **Q1**): `feature_path` is
**instance-root-relative** (the J.g sink-`path` bucket), NOT `dataset/`-relative. This was
staleness (the gap doc predated the review), not a live conflict — MF's *shipped* Gap-1 fix
(Story I.k) already anchors a bare relative `path` to the instance root, and vendor-spec Q1
says `feature_path` "joins that branch."

- **In-repo reference copy:** already corrected to the instance-root anchor (annotated with
  the 2026-06-23 correction). The conflict no longer surfaces from DR's copy.
- **Remaining cross-repo action — carried to Story K.e:** the *same* correction must be
  applied to the **authoritative copy in MF's own repo** when MF runs `plan_features`:
  *"build the `feature_path` loader branch against the instance-root anchor (vendor-spec Q1),
  not the `dataset/`-relative wording."* Neither half unblocks the consumer alone; they land
  together (K.e ↔ MF `plan_features`).

---

## 5. Doc-layout convention — developer decision (captured)

**Decision (developer, this session): per-consumer subdirectory, with the redundant prefix
dropped.** The directory now conveys the consumer, so the file name no longer repeats it.

- **DR-authored docs** live flat at `docs/specs/`. The DR seam brief was renamed
  `datarefinery-audio-feature-persistence.md` → [`audio-feature-persistence.md`](audio-feature-persistence.md).
- **MF-targeted / MF-mirrored docs** live under `docs/specs/modelfoundry/` (the `sync.sh`
  mirror dir + the jointly-authored `vendor-dependency-spec.md`). The MF seam brief was
  moved + renamed `modelfoundry-audio-feature-consumption.md` →
  [`modelfoundry/audio-feature-consumption.md`](modelfoundry/audio-feature-consumption.md).

**Cross-link fixups done in this spike** (DR-authored docs, broken by the rename):

- [`audio-feature-persistence.md`](audio-feature-persistence.md) — companion link → `modelfoundry/audio-feature-consumption.md`.
- [`modelfoundry/audio-feature-consumption.md`](modelfoundry/audio-feature-consumption.md) — companion link → `../audio-feature-persistence.md`; `advanced-and-probabilistic-requirements.md` link de-`../modelfoundry/`'d to same-dir.
- [`consumer-gap-solutions.md`](consumer-gap-solutions.md) — four references updated (`audio-feature-persistence.md`, `modelfoundry/audio-feature-consumption.md`).

**Deliberately left for later (not fixed here), to avoid stepping on shared/in-progress surfaces:**

- [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md) L192, L537 — the shared contract doc references the briefs with both DR:/MF:-prefixed paths and now-stale relative links (`../datarefinery-audio-feature-persistence.md`, `../modelfoundry-audio-feature-consumption.md`). **Reconcile these in Story K.c**, which already re-ratifies that exact § from forward-declared → shipped — folding the path fixups into the deliberate contract edit rather than touching the authoritative doc out of band.
- `modelfoundry/consumer-gap-solutions.md` (L54–55, L351, L353) — the MF-mirrored gap doc; currently hand-edited by the developer (already modified in the working tree). Leave to the developer / the next `sync` so we don't collide with in-progress edits.
- `consumer-gap-analysis.md` (L16, L220) — a received, dated consumer artifact referencing `../briefs/…` (the consumer's original filing path, stale even before the rename). Provenance, not a live DR cross-link; left as historical record.

---

## Deliverable summary

- Contract (Q1–Q6) re-confirmed against current `main`; no drift (§ 1).
- Additive-versioning + cache-identity coverage confirmed (§ 2).
- R-level feature-persistence requirement **drafted** for K.d to land (§ 3).
- MF gap-doc anchor-staleness flag recorded; cross-repo action carried to K.e (§ 4).
- Doc-layout convention decided + captured; DR-side cross-links fixed; shared-surface
  fixups deferred to K.c with rationale (§ 5).

No production code. Next: **Story K.c** — implement the `npy_per_record` sink writer +
`feature_path` rewrite + manifest wiring, and re-ratify the vendor-spec § to shipped.
