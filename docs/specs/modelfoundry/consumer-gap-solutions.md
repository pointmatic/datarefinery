# Consumer Gap Solutions — ModelFoundry

Investigation conclusions for each gap logged in
[`consumer-gap-analysis.md`](consumer-gap-analysis.md). Every gap was reproduced
against the **current source** (not the gap author's recollection); each entry
records a **verdict**, the **evidence** (file:line) behind it, and a **solution**
— a concrete fix, a planned spike/story, or the specific information still
needed.

**Verdict vocabulary**

- **confirmed** — gap reproduced against the code; a solution is determined, or a
  spike/story is planned to develop one.
- **refuted** — the claim (or a load-bearing sub-claim) is wrong: an already-built
  path exists; the corrected information / example is given.
- **pending** — needs more information, data, clarification, or a worked example
  before a verdict or solution can be fixed.

> **Method note.** Three independent read-only investigations (one per gap) traced
> the claims to source. Where a gap bundles several sub-claims, each is graded
> separately — Gap 2 and Gap 3 each contain a sub-claim that is **refuted** even
> though the headline gap is **confirmed**.

---

## Verdict summary

| # | Gap | Headline verdict | Notable sub-finding | Disposition |
|---|-----|------------------|---------------------|-------------|
| 1 | DR writes instance-relative `path`; MF resolves a bare `path` relative to **CWD** | **confirmed** | Workaround script exists (at `scripts/examples/`, not the cited path) | ✅ **FIXED — Story I.k, v0.17.1**: `_decode` anchors instance-relative `path` to the instance + bind-time fail-fast gate |
| 2 | MF encoder path applies **no** HF image-processor preprocessing | **confirmed** | The "uint8-sink vs. normalize **collision**" framing is **refuted** — `normalize` is a fit-on-train op applied at load, so resize-via-sink + normalize coexist | Try existing load-time normalize path first; **spike** the residual (exact pretrained stats vs. fit-on-train) |
| 3 | PyTorch loader is image-only; no audio / feature-array path | **confirmed** | MC-dropout path is **already built and modality-agnostic** (sub-claim refuted-in-the-good-sense — it is *not* the blocker) | **Decision: spectrogram-as-image is the wrong (lossy) solution** — build the feature-array path (`npy_per_record` + `feature_path`); cross-repo **`plan_features`** (both briefs exist) |

---

## Doc-hygiene findings (apply regardless of gap disposition)

Both artifacts the analysis cites **exist** in this repo, but they were **authored
in / copied from the consumer project**, which explains two things: the cited
paths are **stale** (the consumer's layout differs), and the script **does not run
here** (it targets the consumer's `data/instances/` layout and instances, not
ModelFoundry's). Treat them as **reference copies of consumer-side artifacts**, not
as MF-native tooling. Fixing the citation paths is a one-line-each correction;
nothing here blocks a fix.

- **Workaround script** — cited as `scripts/add_mf_image_path_sidecar.py`
  ([gap analysis Gap 1](consumer-gap-analysis.md), "Workaround applied"); the copy
  here is [`scripts/examples/add_mf_image_path_sidecar.py`](../../scripts/examples/add_mf_image_path_sidecar.py).
  It documents the consumer's idempotent sidecar patch (adds
  `image_path = ../images/...`); it is **illustrative — not runnable in this repo**.
  The Gap-1 fix below **supersedes the technique** entirely.
- **Audio brief** — cited as `briefs/modelfoundry-audio-feature-consumption.md`
  (i.e. `docs/briefs/…`, [gap analysis Gap 3](consumer-gap-analysis.md), "Filed as");
  the copy here is [`docs/specs/modelfoundry-audio-feature-consumption.md`](modelfoundry-audio-feature-consumption.md).
  Its companion DR brief is `datarefinery-audio-feature-persistence.md`. As a
  consumer-authored seam brief, its behavior-level requirements are the input to
  MF's own `plan_features`; the implementation design is MF's to author.
- **Also note:** the script header and the brief reference
  `docs/specs/modelfoundry/consumer-gap-analysis.md` (a `modelfoundry/`
  subdirectory — the consumer's family-doc layout), whereas the analysis lives at
  `docs/specs/consumer-gap-analysis.md` here. Settle the intended directory
  convention for these copied seam docs so the cross-links resolve — a doc-layout
  question for the developer, not a code fix.

---

## Gap 1 — bare `path` resolved relative to CWD, not the instance

### Verdict: **confirmed**

Reproduced exactly. DataRefinery's `png_per_record` sink rewrites each record's
`path` to an **instance-relative** string; ModelFoundry's loader resolves a bare
`path` (no `image_path` sidecar) with a bare `Path(...)`, which Python anchors to
the **current working directory**. Both tools' `validate` pass because no check
verifies image resolvability — the failure only surfaces mid-training as
`FileNotFoundError`.

### Evidence

- **MF resolves bare `path` against CWD** — [plugins/pytorch/data.py:213-214](../../src/modelfoundry/plugins/pytorch/data.py#L213-L214):
  ```python
  relative = record.get("image_path")
  path = self._dataset_dir / str(relative) if relative else Path(str(record["path"]))
  ```
  The `else` branch is a bare `Path(...)` → CWD-relative. Only `image_path` is
  instance-anchored (relative to `_dataset_dir = instance.path / "dataset"`,
  [data.py:62](../../src/modelfoundry/plugins/pytorch/data.py#L62)).
- **DR writes `path` (not `image_path`), instance-relative** — the installed
  `datarefinery` package's `pipeline/path_rewrite.py` (`qualifying_image_sinks`)
  rewrites the `image` field's record `path` for `format == "png_per_record"`
  sinks; it never emits an `image_path` field.
- **No validate-time resolvability gate** — `recipe/validator.py` checks 1–22
  validate metadata (splits, counts, schemas, input-shape) but never that a
  record's image file exists. `pipeline/data_binding.py::_verify_aggressive_sidecars`
  ([data_binding.py:211-232](../../src/modelfoundry/pipeline/data_binding.py#L211))
  checks **only** `image_path` sidecars (`if not relative: continue`) — bare
  `path` records are skipped.

### Why both `validate`s pass but training dies

The instance is well-formed (splits, labels, counts all correct), so MF `validate`
and DR `materialize` are green. The mismatch is purely in *runtime path
resolution*, exercised only when the DataLoader pulls pixels — deep into a
potentially long run. This is the silent-failure class the gap names.

### Solution (determined — debug story)

Two layers, smallest first:

1. **Fix the resolution (1 file).** In [data.py:_decode](../../src/modelfoundry/plugins/pytorch/data.py#L210),
   anchor a bare **relative** `path` to the **instance root** (DR writes
   `images/train/<Class>/<id>.png`, which is instance-root-relative — note that
   is one level *above* `dataset/`, matching the consumer's `../images/...`
   sidecar workaround). Preserve absolute paths as-is for back-compat:
   ```python
   relative = record.get("image_path")
   if relative:
       path = self._dataset_dir / str(relative)
   else:
       bare = Path(str(record["path"]))
       path = bare if bare.is_absolute() else self.instance.path / bare
   ```
   This **supersedes** the consumer-side
   [`scripts/examples/add_mf_image_path_sidecar.py`](../../scripts/examples/add_mf_image_path_sidecar.py)
   technique (which patches in an `image_path = ../images/...` sidecar so MF's
   instance-anchored branch resolves) — once a bare relative `path` anchors to the
   instance, no sidecar patch is needed at all, in this repo or the consumer's.
2. **Add the cheap gate.** Extend `_verify_aggressive_sidecars` (or add a
   validator check) to confirm every record's image is resolvable from the
   instance — surfacing the error at `validate`/bind time rather than mid-train.
   Cover both branches (bare `path` and `image_path`).

**Test-first (debug mode):** a `_decode` unit test where the record carries only
an instance-relative `path`, run with `cwd != instance.path`, currently raises
`FileNotFoundError` and must pass after the fix. (Existing
`test_pytorch_data_adapter` fixtures pass today only because the test's CWD
happens to align with where the PNGs are written — they don't exercise the
CWD-divergent case.)

**Cross-repo note (housekeeping, not blocking).** The DR-side alternative — have
`png_per_record` also emit an `image_path` sidecar relative to `dataset/` — would
align both tools on MF's preferred branch. Record as a family-coordination item;
the MF-side fix stands alone and is the smaller change.

### ✅ Resolution — shipped (Story I.k, v0.17.1)

Both layers landed via the debug cycle:

- **Resolution fix** — extracted
  [`_resolve_image_path`](../../src/modelfoundry/plugins/pytorch/data.py#L210): a
  bare `path` is used as-is when **absolute** and anchored to **`self.instance.path`**
  when **relative** (the sink case); `image_path` sidecars unchanged.
- **Fail-fast gate** — `_verify_aggressive_sidecars` →
  [`_verify_record_images_resolvable`](../../src/modelfoundry/pipeline/data_binding.py#L211)
  refuses an instance-relative bare `path` whose file is absent **at bind time**
  (absolute source paths skipped).
- **Tests** — `test_decode_resolves_instance_relative_path_from_other_cwd`
  (regression; failed with `FileNotFoundError` before the fix) +
  `test_instance_relative_path_missing_refused` / `_present_binds` (gate). Full CI
  gate green.
- **Patch, not cache-invalidating** — resolution logic only; recipe hash /
  canonical bytes / output bytes unchanged for runs that already succeeded. The
  consumer-side sidecar script is now obsolete.

Outstanding (tracked as `[ ]` housekeeping on Story I.k): fix the stale citation
paths in `consumer-gap-analysis.md`; optional DR-side `image_path`-sidecar
alignment.

---

## Gap 2 — encoder path applies no HF image-processor preprocessing

### Verdict: **confirmed** (headline) — with a **refuted** sub-claim (the "collision")

The headline fact is true: MF never instantiates or applies a HuggingFace image
processor. But the gap's **diagnosis** — that supplying the encoder's
normalization on the data side is impossible because it *collides* with the
uint8-only `png_per_record` sink — is **refuted** by how MF actually applies
normalization. That changes the recommended path.

### Evidence (headline confirmed)

- **Encoder spec carries no preprocessing field** —
  [plugins/pytorch/architecture.py:133-137](../../src/modelfoundry/plugins/pytorch/architecture.py#L133)
  (`EncoderParams`: `source`, `id`, `frozen` only).
- **No image processor is ever loaded or applied** —
  [architecture.py:650-651](../../src/modelfoundry/plugins/pytorch/architecture.py#L650)
  loads `AutoModel.from_pretrained(...)` only; the forward pass
  ([architecture.py:548-554](../../src/modelfoundry/plugins/pytorch/architecture.py#L548))
  feeds `pixel_values=x` straight through. No `AutoImageProcessor` /
  `image_mean` / `image_std` / `image_size` anywhere under `plugins/pytorch/`.
- **Load-time normalization is DR-stats-or-`[0,1]`** —
  [data.py:179-208](../../src/modelfoundry/plugins/pytorch/data.py#L179): with no
  fit-on-train op, `image = image / 255.0` (`[0,1]`); a frozen ImageNet-pretrained
  ViT then sees the wrong input distribution.
- **The behavior is contract-documented** (so it is by-design, not an
  implementation oversight) — `features.md` FR-21 / validator check 21 specify
  "normalization in 0-255 pixel units" as the **data-side** contract. The gap is
  the *intuition mismatch* (a `transformers` user expects auto-preprocessing) plus
  the silent quality cost.

### The "collision" sub-claim — **refuted**, with the corrected mechanism

The gap states a `normalize` transform "makes the image `float`, which the
`png_per_record` sink rejects (uint8 only)," concluding resize-persistence and
normalization can't coexist. **In MF's model they can**, because `normalize` /
`mean_subtract` are **fit-on-train ops applied at load over the persisted uint8
pixels** — they do **not** rewrite the sinked bytes:

- [data.py:39](../../src/modelfoundry/plugins/pytorch/data.py#L39):
  `_FIT_ON_TRAIN_OPS = frozenset({"normalize", "mean_subtract"})`.
- [data.py:_resolve_normalization_steps](../../src/modelfoundry/plugins/pytorch/data.py#L89)
  reads each `normalize`/`mean_subtract` op's persisted `mean`/`std` vectors.
- [data.py:__getitem__](../../src/modelfoundry/plugins/pytorch/data.py#L179)
  applies `(x - mean) / std` at load on the 0-255 pixels.
- The geometry guard ([data.py:72-85](../../src/modelfoundry/plugins/pytorch/data.py#L72))
  treats fit-on-train ops as *non*-baked, so a pipeline of **resize (baked → uint8
  PNG sink) + normalize (fit-on-train → stats applied at load)** passes the guard
  and is the intended shape.

So the consumer's documented mitigation ("train with `[0,1]`, note the caveat")
was **not the only option** — declaring the encoder's expected normalization as a
DR `normalize` op would have MF apply it at load over the uint8 sink, no collision.

### Residual open question — **pending** (drives the spike)

What remains genuinely uncertain: a frozen pretrained encoder wants its **exact
pretrained stats** (e.g. ImageNet mean/std), but DR's `normalize` is typically
**fit-on-train** — fitted stats ≈ but ≠ the pretrained distribution. Whether DR
can persist **fixed** (author-supplied) `normalize` stats is a DataRefinery
question not answerable from this repo.

### Solution (spike — design choice is non-obvious)

1. **Cheapest first (validate the refutation):** author a recipe that declares the
   encoder's mean/std as a DR `normalize` op and confirm MF applies it at load to
   the uint8-sinked pixels (expected to work per the evidence above). If DR
   supports fixed stats, this likely closes the gap with **zero MF code**.
2. **If exact pretrained stats can't be supplied data-side**, spike adding an
   **optional HF-image-processor application to the `Encoder` op** — e.g.
   `EncoderParams.apply_image_processor: bool` (and/or explicit
   `image_mean`/`image_std`/`image_size`), applied in `_PretrainedClassifier`
   before the encoder. **Cache-identity caveat:** this moves a behavior-affecting
   value into the recipe, so it must follow the no-implicit-defaults rule
   (author-required, emitted by the scaffolder) and is **cache-relevant** — weigh
   against keeping normalization a pure data-side concern.
3. **Either way, document the contract** at the recipe surface (the `Encoder` op
   does not auto-preprocess; normalization is data-side) — that closes the
   *intuition* gap independent of the code decision.

Spike deliverable: a decision (data-side fixed-stats vs. encoder-applied
preprocessing) + the recipe-surface documentation. Cross-repo coordination
required for option 1.

---

## Gap 3 — PyTorch loader is image-only; no audio / feature-array path

### Verdict: **confirmed** (headline) — MC-dropout sub-claim **refuted-in-the-good-sense** (already built)

The loader is image-only end-to-end; there is no path to consume audio /
spectrogram feature arrays. Confirmed. The gap's own assertion that the
**MC-dropout stochastic path is already implemented and modality-agnostic** is
also confirmed — i.e. the stochastic inference machinery is **not** the blocker;
the gap is purely getting non-image features *into* the model.

### Evidence (loader is image-only)

- **`_decode` always PIL-decodes RGB** —
  [data.py:210-220](../../src/modelfoundry/plugins/pytorch/data.py#L210)
  (`Image.open(path)` → `.convert("RGB")`); an `.ogg` path cannot be decoded. No
  `.npy` / `np.load` / array / `feature_path` branch exists in the file.
- **Normalization resolver is image-only** —
  [data.py:89-103](../../src/modelfoundry/plugins/pytorch/data.py#L89) matches
  only `normalize` / `mean_subtract` and reshapes for CHW image channels
  (`.view(-1, 1, 1)`); there is no `audio_normalize` branch, and
  `_FIT_ON_TRAIN_OPS` ([data.py:39](../../src/modelfoundry/plugins/pytorch/data.py#L39))
  does not register it.

### Evidence (MC-dropout already built and modality-agnostic — sub-claim refuted)

- [plugins/pytorch/stochastic.py:94-118](../../src/modelfoundry/plugins/pytorch/stochastic.py#L94)
  (`mc_forward_proba`) runs T seeded active-dropout passes over an arbitrary
  `batch` tensor and softmaxes the **logits** — it never touches input decoding.
- `mc_aggregate` / `predictive_entropy` / `enable_mc_dropout` operate purely on
  probability stacks and `nn.Module` dropout layers
  ([stochastic.py:61-91](../../src/modelfoundry/plugins/pytorch/stochastic.py#L61)).
- The recipe `Inference` block is modality-agnostic and already modeled —
  [recipe/models.py:91-128](../../src/modelfoundry/recipe/models.py#L91)
  (`InferenceSpec`: `mode: point|mc_dropout`, `mc_samples`).

So **no work is needed on the stochastic path** — the consumer's note is
accurate, and confirming it scopes the real work to the loader alone.

### Decision: spectrogram-as-image is **not** the right solution

Asked directly — *is modeling the spectrogram as an image correct?* **No.** It is a
lossy stopgap, not the right contract. Build the **feature-array consumption path**.
Reasons, specific to audio features (not generic preference):

1. **Quantization is genuinely lossy here.** A log-mel spectrogram is `float32`
   with high dynamic range (a dB-scale field). The PNG route requires quantizing to
   **uint8 (256 levels) + range clipping** — the DataRefinery brief's own option 3
   wording. For natural images 8-bit *is* the native representation; for audio
   features it discards precision the model trains on. (Both briefs flag the route
   as "lossy.")
2. **Wrong normalization contract.** The image path applies image semantics
   (0-255 pixel units, RGB per-channel stats or `/255`); audio needs
   `audio_normalize` — **per-mel-bin** fit-on-train standardization (R5). Forcing
   audio through the image normalizer applies statistics of the wrong shape and
   meaning.
3. **Wrong channel semantics.** `_decode` does `.convert("RGB")` →
   [data.py:219](../../src/modelfoundry/plugins/pytorch/data.py#L219) — 3 channels.
   A spectrogram is **1 channel** `(1, n_mels, n_frames)` (or `C` feature
   channels). RGB triples the data meaninglessly / fakes a 3-channel encoding.
4. **Breaks the reproducibility contract.** A PNG round-trip of a float array is
   **not lossless** — you cannot recover the exact features the determinism
   guarantee (QR-3/FR-25) is defined over. The `.npy` feature-array path *is*
   lossless and round-trips, which is why DR's preferred sink is `npy_per_record`,
   not a quantized PNG.
5. **It would add divergence, not reuse.** The PNG route is not free even on the
   data side — DR would have to ship a **new uint8-quantization sink mode** (its
   brief's option 3) purely to work around MF's missing branch, producing a second,
   lossy representation of features DR already computes as float. The proper path
   reuses DR's existing sink mechanism (`npy_per_record`, additive) and keeps the
   "arrays are in-pipeline; persist via a sidecar" convention intact.

The developer already **declined** the spectrogram-PNG interim
([`consumer-gap-analysis.md`](consumer-gap-analysis.md) Gap 3, "Model 2 build
paused"). This verdict confirms that call: the interim is a hack; the
feature-array path is the solution.

### Plan: the proper feature-array consumption path (cross-repo, `plan_features`)

This is a new capability spanning two repos, not a debug fix. Both briefs exist and
agree on the contract —
[`modelfoundry-audio-feature-consumption.md`](modelfoundry-audio-feature-consumption.md)
(consume) paired with
[`datarefinery-audio-feature-persistence.md`](datarefinery-audio-feature-persistence.md)
(persist). **Neither half alone unblocks the consumer — they land together.**

**Shared on-disk contract (pin jointly with DR before coding):**
- DR ships an **`npy_per_record`** array sink: persists the float field per record
  at `features/<split>/<record_id>.npy`, shape **`(n_mels, n_frames)`**, and
  rewrites a **`feature_path`** relative to `dataset/` (mirrors how
  `png_per_record` rewrites `image_path`). Sink output is instance content →
  covered by cache identity exactly as PNG is.
- DR persists the **`audio_normalize`** fit-on-train stats (per-mel-bin).

**ModelFoundry side (the story):**
- **Feature-array branch in `_decode`** ([data.py:210](../../src/modelfoundry/plugins/pytorch/data.py#L210)):
  when a record carries `feature_path`, `np.load` it into a
  `(1, n_mels, n_frames)` tensor (general `(C, n_mels, n_frames)` if multi-channel)
  instead of `Image.open`. Default image path unchanged (additive).
- **`audio_normalize` branch in `_resolve_normalization_steps`**
  ([data.py:89](../../src/modelfoundry/plugins/pytorch/data.py#L89)): read
  per-mel-bin stats with audio-appropriate reshape; register `audio_normalize` in
  [`_FIT_ON_TRAIN_OPS`](../../src/modelfoundry/plugins/pytorch/data.py#L39) so the
  geometry guard treats it as fit-on-train, not a baked transform.
- **Branch selection** to decide in the story: per-record (`feature_path` /
  `image_path` / bare `path` presence) vs. per-instance (manifest modality flag).
  Per-record field presence is the lighter-touch option and composes with the
  Gap-1 resolution precedence.
- **Window→clip regrouping** by `source_record_id` (R7) for evaluating MC-dropout
  predictions at the clip level — confirm where this lives (loader vs. evaluation).

**Already done — do not rebuild:** the MC-dropout stochastic path
([stochastic.py](../../src/modelfoundry/plugins/pytorch/stochastic.py#L94)) and the
`Inference` recipe block ([models.py:91-128](../../src/modelfoundry/recipe/models.py#L91))
are modality-agnostic and implemented. The work is purely the loader.

**Acceptance tests** (from the MF brief's verification): a materialized audio
instance + spectrogram-CNN recipe with `Inference: {mode: mc_dropout, mc_samples: T}`
trains end-to-end producing per-record `predictive_entropy` / `mc_variance` and
`ece` over MC-aggregated means; the run is deterministic and round-trips from disk;
default image recipes are unaffected.

**Mode note:** route through **`plan_features`** (new capability + cross-repo
contract), not `debug`. Sequence: settle the shared contract with DR → DR ships
`npy_per_record` → MF ships the consumption branch (or in parallel against the
agreed contract, since neither ships value alone).

### Cross-repo coordination (DataRefinery plan, confirmed 2026-06-22)

DataRefinery's own solutions doc
([`datarefinery/consumer-gap-solutions.md`](datarefinery/consumer-gap-solutions.md)
Gap 3) confirms the producing half and **agrees on the contract**: its preferred
fix is the **`npy_per_record`** sink (`features/<split>/<record_id>.npy`,
`feature_path` relative to `dataset/`, `(n_mels, n_frames)` on disk) — exactly what
MF's consumption branch above consumes. The axis orientation is pinned identically
on both sides (disk `(n_mels, n_frames)` → tensor `(1|C, n_mels, n_frames)`), which
is the obvious way a "paired" fix silently fails to line up. Two coordination points
that bind the MF side:

1. **The family must commit to the float-array path, not the PNG hack.** DR's plan
   still lists its **option 3 (uint8-quantization PNG sink)** as a live spike
   candidate. That is the same spectrogram-as-image route MF **rejected above** as
   lossy and contract-breaking. If DR's spike landed on option 3, MF would be forced
   back onto the lossy path. **MF's position into the joint spike: choose
   `npy_per_record` (DR option 1).** Both repos independently flag the PNG route as
   lossy — align on the float-array sink and drop option 3.
2. **`feature_path` is a shape-binding surface → vendor-dependency-spec.** DR flags
   the new per-record `feature_path` field as a contract surface requiring a
   `modelfoundry/vendor-dependency-spec.md` update and coordinated rollout. That spec
   is currently **forward-declared** (see `stories.md` Future, "authored at the
   pre-production release") — the audio seam is a concrete reason it must capture the
   `feature_path` / feature-array layout when it lands. MF consumes the sink output
   **read-only** (the loose-coupling invariants in `project-essentials.md` hold — MF
   never re-hashes DR's instance), so cache identity for the features stays DR's
   responsibility; MF just reads them.

**Net:** the seam is aligned end-to-end. The only decision that could still split
the two halves is option-1-vs-option-3 at the spike — and both sides already lean
option 1. No conflict with anything MF shipped.

---

## Recommended next actions

1. **Gap 1 → ✅ DONE (Story I.k, v0.17.1).** Fixed via the debug cycle: loader
   anchors instance-relative `path` to the instance + bind-time fail-fast gate;
   full CI gate green. Consumer-side sidecar workaround is now obsolete.
2. **Gap 2 → quick experiment, then spike.** First validate the refutation
   (encoder stats as a DR `normalize` op applied at load — possibly zero MF code).
   If exact pretrained stats can't be supplied data-side, spike the
   Encoder-applies-preprocessing option (with its cache-identity implications).
   Document the recipe-surface contract either way.
3. **Gap 3 → plan_features (proper path, not the PNG hack).** Decision recorded:
   spectrogram-as-image is lossy and wrong; build the feature-array path. Both
   briefs exist and agree on the contract (`npy_per_record` + `feature_path`
   relative to `dataset/`, `(n_mels, n_frames)` float arrays, `audio_normalize`
   stats). Settle the shared contract with DataRefinery, then author the loader
   story (feature-array branch + `audio_normalize`) with the brief's verification
   as acceptance tests. The MC-dropout path is done; do not re-investigate it.
