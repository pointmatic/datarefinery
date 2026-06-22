# Phase J · Subphase J-1 — Audio-classification design memo (Story J.n spike)

**Status:** spike deliverable — frozen design pending developer confirmation at the J.n approval gate.
**Owns:** the design that Stories J.o–J.w execute against.
**Method:** verify each developer-approved working recommendation (Q1–Q4 + R4/R5/decode) against current DataRefinery source; freeze stage placements, field names, decode library, and the normalization axis. Per J.n out-of-scope, Q1–Q4 conclusions are accepted — this memo verifies and operationalizes them, and flags two implementation refinements that the requirements/story drafts did not anticipate.

---

## 1. Verification results

### Q1 — Windowing as a record-count-changing `Generation` op ✅ verified

- **Generation runs after Splits.** `STAGE_NAMES` lists `"Splits"` then `"Generation"` in execution order ([runner.py:106–111](../../src/datarefinery/pipeline/runner.py#L106-L111)); the `_emit("Splits")` call ([runner.py:270](../../src/datarefinery/pipeline/runner.py#L270)) precedes `_emit("Generation")` ([runner.py:327](../../src/datarefinery/pipeline/runner.py#L327)). So a `Generation`-stage windowing op fans clips out *within their already-assigned split* — clip→window split-integrity (R6) is a free consequence of stage order, not something windowing must defend.
- **`manifest.record_counts` reflects post-Generation expansion.** The runner computes `record_counts={name: len(records) …}` from the final `split_map` after Generation has run (full-run manifest site, [runner.py:525](../../src/datarefinery/pipeline/runner.py#L525)). The FR-11 aggressive-mode precedent confirms record-multiplication is already manifest-visible (`record_counts["train"]` is the post-augmentation count; vendor-dependency-spec § manifest fields).

**Verdict:** windowing as `Generation` holds. No cascade break.

### Q1 corollary — `source_record_id` mechanism reuse ✅ verified

- FR-11 aggressive variants derive their id as `f"{source_record_id}__v{variant_index:03d}"` ([_realizer.py:49–59](../../src/datarefinery/plugins/image_classification/augmentations/_realizer.py#L49-L59)) and stamp both `source_record_id` and `variant_index` onto each emitted variant ([_realizer.py:113–115](../../src/datarefinery/plugins/image_classification/augmentations/_realizer.py#L113-L115)).
- An audio plugin has **no** aggressive augmentations in v1 (Q4 deferred), so a record is never simultaneously a window and a variant — **reusing `source_record_id` as the clip→window grouping key is unambiguous**. Add a sibling `window_index: int` parallel to `variant_index`, and derive window ids as `f"{source_record_id}__w{window_index:04d}"` (4-digit width for clip→window counts up to ~10k; the `__w` vs `__v` prefix keeps the two mechanisms textually distinguishable).

**Verdict:** reuse `source_record_id`; add `window_index`. Matches J.q's draft.

### Q2 — per-recipe canonical sample rate ⚠️ verified *with a placement refinement* (Finding A)

- Canonical bytes are `recipe.model_dump(mode="json")` → sorted compact `json.dumps` ([canonical.py:20–40](../../src/datarefinery/recipe/canonical.py#L20-L40)). Any pydantic field anywhere in the `Recipe` graph participates. So a `target_sample_rate` field **does** participate in cache identity — the recommendation's intent holds.
- **BUT** `InputSource` is a single shared model ([models.py:86](../../src/datarefinery/recipe/models.py#L86)) used by *all* modalities, and `model_dump` emits every field regardless of value (a `None` default still serializes as `"target_sample_rate":null`). Adding the field to the shared `InputSource` — or anywhere else on the shared `Recipe` graph — therefore perturbs the canonical bytes of **every existing image recipe**, invalidating every image user's cache for a field they never use. J.p's task note ("perturbs canonical bytes only for recipes declaring the audio plugin") is **not achievable** with a shared-model field.
- `InputSource.type` is already a free `str` (not a `Literal`), so audio source *type names* need no model change — only the *extra audio field* is the problem.

**See Finding A for the resolution.**

### Q3 — `source_record_id` is the documented consumer-bind grouping key ✅ verified

- The MF vendor-dependency-spec already documents `source_record_id` (for aggressive variants) in § JSONL records, and § Cache-identity / failure-modes language is in place. Audio needs its **own subsection** under § JSONL records ("Audio window records") rather than carrying the field verbatim, because the *semantics* differ (window-of-clip vs. augmented-variant-of-image) even though the field name is shared. This is exactly J.u's scope. The "DR owns the grouping key; consumer owns the aggregation math" boundary is consistent with the existing contract posture.

**Verdict:** field name carries; semantics get a dedicated subsection (J.u).

### Q4 — deferring audio-domain augmentations ✅ verified

- R1–R7 contain no transitive pull on augmentation behavior: decode (R2), windowing (R3/Generation), featurization (R4/Featurization), normalization (R5/Transformations), label propagation (R6/Splits-order), aggregation (R7/consumer-side) all map onto non-Augmentation stages.
- The existing `AugmentationOp` contract ([models.py:356](../../src/datarefinery/recipe/models.py#L356)) — `op`/`params`/`splits`/`seed`/`materialization`/`expansion` — is modality-agnostic; future SpecAugment-style time/freq masking would slot in as new ops under the same lazy/aggressive contract with **no contract change**.

**Verdict:** defer to Future cleanly. No v1 surface needed.

### R5 — normalize reuse vs. new op ⚠️ verified *with an axis refinement* (Finding B)

- The image `NormalizeOp` fits via `_per_channel_mean_std`, which reduces **all axes except the last**: `axes_to_reduce = tuple(range(stack.ndim - 1)) if stack.ndim >= 3 else None` ([transformations.py:226–240](../../src/datarefinery/plugins/image_classification/operations/transformations.py#L226-L240)). For a stack of images `(N, H, W, C)` this keeps axis `C` → per-channel stats. The "normalize over everything but the **last** axis" rule is an image-centric assumption (last axis = channel).
- librosa's native log-mel output is `(n_mels, n_frames)` — **mel is axis 0, not the last axis**. Stacking window features gives `(N, n_mels, n_frames)`; the existing reduction keeps the *last* axis (`n_frames`) → **per-frame** statistics, which is **not** the per-mel-bin normalization R5/J.t intends.

**See Finding B for the resolution.**

### R4 — log-mel only for v1 ✅ verified

- R4 lists "log-mel spectrogram, or MFCC." v1 ships **log-mel only**; MFCC → Future. Nothing in R1–R8 or the acceptance criteria requires MFCC. Matches J.s.

### Decode library — librosa ✅ recommended, with a packaging note

- **librosa** covers both decode+resample and log-mel featurization in one dependency (simplest path; satisfies R2 + R4). soundfile alone can't featurize; torchaudio is framework-coupled and undercuts the plugin-interface-honesty goal (R8).
- **Packaging:** librosa pulls a heavy transitive tail (`numba`/`llvmlite`, `scipy`, `soundfile`). The repo already isolates heavy optional deps behind extras — `[corruptions] = scikit-image, opencv-python-headless`, `[llm] = lmentry` ([pyproject.toml](../../pyproject.toml)). **Recommend an `[audio] = ["librosa"]` optional extra** rather than a base runtime dependency, keeping the default install lean. The `audio_classification` plugin imports librosa lazily (inside op `apply`, mirroring the writer-side `from PIL import Image` lazy-import pattern) so the plugin module is importable for discovery/contract-tests without librosa installed; ops raise an actionable `PluginError` ("install datarefinery[audio]") if invoked without it.

---

## 2. Findings requiring developer confirmation

These do **not** re-open the Q1–Q4 conclusions; they correct two implementation assumptions in the requirements/story drafts that would otherwise misfire.

### Finding A — `target_sample_rate` must not live on the shared `InputSource` model

**Problem.** A field on the shared `InputSource` (or anywhere on the shared `Recipe` graph) perturbs every image recipe's canonical bytes → blanket image-cache invalidation for an audio-only knob. Even pre-prod (where invalidation is "acceptable, note it"), this is avoidable cross-modality blast radius.

**Recommended resolution — discriminated source-type models.** Turn the source list into a discriminated union on `type`: keep image fields on an `ImageSource` variant (byte-identical to today's `InputSource` field set, so image canonical bytes are unchanged) and put `target_sample_rate` on an `AudioSource` variant that image recipes never instantiate. In a pydantic union, `model_dump` emits only the chosen variant's fields, so audio-only fields never touch image recipes' canonical bytes. The canonical-hash pin test ([test_canonical_hash_pin.py](../../tests/unit/test_canonical_hash_pin.py)) is the guard that confirms image bytes stay put.

**Alternative considered (not recommended).** Model decode as an explicit op whose `params` carry `target_sample_rate` (op params only serialize when the op is declared → no shared-model change). Rejected for v1 because R2 frames decode as *loader* behavior, and a post-Splits-but-pre-Generation decode op has no natural stage slot (decode must precede windowing). The discriminated-union keeps decode as loader behavior per R2 while isolating canonical bytes.

**Impact on J.p:** J.p's "add `target_sample_rate` to the audio input source pydantic model" becomes "introduce the `AudioSource` discriminated variant carrying `target_sample_rate`; leave the image source field set untouched." The "pre-prod re-materialize event for audio recipes only" claim then holds *by construction*.

### Finding B — per-mel-bin normalization needs an explicit axis; recommend `audio_normalize`

**Problem.** Reusing `NormalizeOp` on librosa-native `(n_mels, n_frames)` features yields per-**frame** stats, not the per-**mel-bin** stats R5/J.t intends (the existing op hardcodes "keep last axis").

**Two clean resolutions:**
- **(B1, recommended) dedicated `audio_normalize` op** that reduces over (examples, frames) keeping the mel axis, mirroring `NormalizeOp`'s fit/apply/persist/zero-variance-guard discipline. Keeps librosa-native `(n_mels, n_frames)` orientation (clean cross-repo contract; matches J.s as written) and makes the normalization axis *explicit* instead of inheriting the image "last axis = channel" assumption. To avoid duplication, extract the shared mean/std fit + zero-variance guard + parquet persistence into a helper that both `NormalizeOp` and `audio_normalize` call, parameterized by reduction axes.
- **(B2) reuse `NormalizeOp` by orienting features `(n_frames, n_mels)`** so mel becomes the last axis. Maximizes reuse but forces a non-librosa-native feature orientation into the cross-repo contract (a surprising transpose consumers must know about), and leaves the per-mel-bin correctness silently dependent on every future audio featurization keeping mel last.

**Recommendation: B1.** Explicit axis semantics + librosa-native orientation outweigh the modest duplication (mitigated by the shared helper). This realizes J.n's documented fallback ("reuse if the verify holds, else split into `audio_normalize`") — the verify does **not** hold for the librosa-native shape, so we split.

**Impact on J.t:** select option (b) `audio_normalize`; add the shared-helper extraction as an implementation note. Impact on J.s: confirm the frozen feature orientation is `(n_mels, n_frames)`.

---

## 3. Frozen design (for J.o–J.w)

| Concern | Decision |
|---|---|
| **Plugin** | `audio_classification`, real plugin (`is_stub() → False`), registered via `[project.entry-points."datarefinery.plugins"]` ([pyproject.toml:52](../../pyproject.toml#L52)). |
| **Input sources** | `audio_folder` (class-subdir labels) + `audio_flat` (+`label_from`); both support `unlabeled: true`. Modeled as an **`AudioSource` discriminated variant** carrying `target_sample_rate: int = 16000` (Finding A). |
| **Decode** | librosa, loader-side; resample to the source's `target_sample_rate`; emits `{record_id, sample_array, sample_rate, path}`. Deterministic per record. |
| **Windowing** | `window` op, **Generation** stage, `fit_on_train=False`, fully deterministic. Params: one of `window_length_samples` / `window_length_seconds`, `hop_samples`, `remainder: "pad_zero" \| "drop"`. Emits child records with `record_id = f"{source_record_id}__w{window_index:04d}"`, `source_record_id`, `window_index`, inherited `sample_rate`/`path`/`label`. |
| **Featurization** | `log_mel_spectrogram` op, **Featurization** stage, `fit_on_train=False`. Adds `feature: np.ndarray` of shape **`(n_mels, n_frames)`** (librosa-native). One output per input window. Params: `n_fft`, `hop_length`, `n_mels`, `f_min`, `f_max`, `power`. |
| **Normalization** | **`audio_normalize`** op (Finding B1), **Transformations** stage, `fit_on_train=True`, per-mel-bin (length-`n_mels` mean/std vectors), persisted to `fitted_statistics/<op_id>/` (JSON scalars + parquet vectors). `stats_from_instance` import works unchanged; zero-variance guard `std == 0 → 1.0` carries over. |
| **Labels** | clip-level; inherited by every window. Split-integrity guaranteed by Splits-before-Generation order; J.r adds a defensive validator check. |
| **Aggregation (R7)** | DR guarantees `source_record_id` as the clip↔window grouping key; consumer owns the aggregation math. No DR aggregation op. |
| **Augmentations** | deferred to Future (Q4). No v1 surface. |
| **Field names (frozen)** | `record_id`, `source_record_id`, `window_index`, `sample_array`, `sample_rate`, `feature`, `target_sample_rate`, `label`. |
| **Decode/feature library** | librosa, behind an **`[audio]` optional extra**, lazily imported in op `apply`. |
| **MFCC / other spectral / audio augmentations** | Future. |

---

## 4. Downstream story adjustments implied by this memo

- **J.o** — scaffold unchanged; `supported_sections` includes Input/Filters/Splits/Generation/Transformations/Featurizations/OutputExpectations/Visualizations (no Augmentations needed in v1, but inheriting it costs nothing).
- **J.p** — implement `target_sample_rate` via the `AudioSource` discriminated variant, **not** a field on shared `InputSource` (Finding A). Add `[audio]` extra + lazy librosa import.
- **J.q** — as drafted (`__w{window_index:04d}`, `source_record_id`, `window_index`).
- **J.r** — as drafted; the Splits→Generation guard is verified to already hold (defensive check).
- **J.s** — confirm frozen feature orientation `(n_mels, n_frames)`.
- **J.t** — select option (b) `audio_normalize` (Finding B1); extract shared mean/std helper to bound duplication.
- **J.u/J.v/J.w** — as drafted.

---

## 5. Spike conclusion

All four open questions (Q1–Q4) verify against current source and stand as the developer approved them. Two implementation refinements (Finding A: discriminated source model for `target_sample_rate`; Finding B: dedicated `audio_normalize` for per-mel-bin) correct assumptions in the story drafts that would otherwise cause (A) a blanket image-cache invalidation and (B) silently-wrong per-frame normalization. With those two confirmed, the design in § 3 is frozen for J.o–J.w. **No code, no tests, no version bump produced by this spike.**
