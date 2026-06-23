# Consumer Gap Analysis — DataRefinery → ModelFoundry (running log)

A running log of friction met while taking a real consumer project through the intended
happy path: **recipe-writing → data-preparation (DataRefinery) → model-building
(ModelFoundry)**. Anything that needed *more* than authoring a recipe and running the two
tools is logged here — each gap as symptom → affected contract → diagnosis → recommended
fix → verification, plus the **workaround** used to keep delivery moving. Entries are
consumer-sanitized for hand-off into the public dependency repos.

## Gap index

| # | Gap | Target | Severity | Status |
|---|-----|--------|----------|--------|
| 1 | `image_folder` is one-level — fails on multi-level (taxonomy) trees | DataRefinery | blocks `materialize` (workaround exists) | workaround applied; fix requested |
| 2 | Input-hash blind to symlinked-dir content — silent stale-cache reuse | DataRefinery | silent **wrong data** (workaround exists) | workaround applied; fix requested |
| 3 | Audio spectrogram features are in-pipeline only and **cannot be persisted** (only uint8 PNG sink ships; float rejected) | DataRefinery | **blocks** audio→model hand-off (no workaround) | fix requested ([brief](../briefs/datarefinery-audio-feature-persistence.md)); blocks Model 2 |

Minor in-recipe friction (resolved during recipe authoring, no external workaround) is
collected at the end under [Minor friction](#minor-friction-resolved-in-recipe).

---

## Gap 1 — `image_folder` fails on multi-level (taxonomy) directory trees

| Field | Value |
|-------|-------|
| Target repo | DataRefinery |
| Related contract | `image_classification` loader — `image_folder` source type (`datarefinery/pipeline/inputs.py`, `_load_one_image_folder`); `Labels.source.derivation: parent_directory_name` |
| Sanitized | yes |
| First hit | 2026-06-22 |

### Symptom

A consumer project building a closed-set image classifier points an `image_folder`
source at a real-world dataset organized as a **two-level taxonomy** —
`<root_category>/<class>/<image files>` (e.g., a logo dataset whose ~2,300 brand
classes are grouped under 10 parent categories). The recipe declares pre-partitioned
`train`/`test` sources and derives labels with
`Labels.source = {kind: derived, derivation: parent_directory_name}`.

- `datarefinery validate` passes **all 29 static checks**.
- `datarefinery materialize` then fails immediately at load:

  ```
  image_classification loader: source 'train_data' root
  <path>/train contains no .png/.jpg/.jpeg files
  ```

The images plainly exist — one level deeper, under `<category>/<class>/`. This is a
layout-depth mismatch, not missing data, and it surfaces only at `materialize`, after
a fully green `validate`.

### Affected contract / abstraction

The `image_folder` source contract in the `image_classification` loader
(`datarefinery/pipeline/inputs.py`). `_load_one_image_folder` enumerates classes as the
**immediate** subdirectories of the source root:

```python
classes = sorted(p.name for p in root.iterdir() if p.is_dir())
```

and looks for image files directly within each such subdirectory. This encodes a
**strictly one-level ImageFolder contract**: `root/<class>/<image>`. A two-level tree
(`root/<category>/<class>/<image>`) is therefore read as "classes = the category dirs,"
none of which directly contain images → the "contains no … files" error. `image_flat`
does not help: it expects a *flat* directory of image files plus a sidecar manifest, and
is likewise non-recursive.

The mismatch is sharpened by `Labels.source.derivation: parent_directory_name`, which
labels each record by its **immediate parent directory** — a derivation that *would*
naturally support deeper nesting (label = the leaf class dir regardless of ancestors),
yet the loader's discovery never descends to that depth.

### Diagnosis

Two distinct gaps:

1. **No recursive / multi-level ingestion.** Neither `image_folder` nor `image_flat`
   walks below one level. Real-world image datasets frequently ship as a multi-level
   taxonomy (`category/class/images`), so a consumer must restructure the tree (copy or
   symlink the leaf class dirs into a flat one-level view) before DataRefinery will
   ingest it — friction the recipe-driven model is otherwise designed to remove.

2. **Validate/materialize asymmetry.** The "class dir contains only subdirectories, no
   images" condition is caught by none of the 29 static checks, so a misjudged layout
   passes `validate` clean and only fails at `materialize`. For a long-running pipeline
   this defers a trivially-detectable error past the cheap gate.

### Recommended fix

Behavior-level options, in order of preference (implementation design is DataRefinery's
own tech-spec):

1. **Optional recursive discovery on `image_folder`, label = immediate parent.** Add an
   opt-in (e.g. `recursive: true`, or a `class_level` / `label_depth` selector) so the
   loader walks to the image files and derives the class from each file's **immediate
   parent directory**, consistent with `parent_directory_name`. A `category/class/image`
   tree then yields `class` labels with no restructuring. Default stays one-level for
   backward compatibility.

2. **A dedicated taxonomy source type** (e.g. `image_tree`) that recursively discovers
   images and labels by immediate parent dir, leaving `image_folder` untouched.

3. **At minimum, a new static `validate` check** that flags a source root whose class
   subdirectories contain only further subdirectories (no image files) when recursion is
   off — failing fast at `validate` with a message that names the nesting and points at
   the fix. This closes the asymmetry even if (1)/(2) are deferred.

**Contract impact.** Recursive discovery must preserve the existing invariants: the
input-hash feeding cache identity (`_hash_image_folder`) must hash the
**recursively-discovered** file set so the same tree + seed still materializes
byte-identically; traversal must stay deterministically ordered (sorted). No change to
the `Labels` / `Splits` / `Transformations` contracts. The new validate check (3) is
purely additive.

### Workaround applied

A one-level ImageFolder **view** of the top-20 brands, built by
[`scripts/build_logo_imagefolder_view.py`](../../../scripts/build_logo_imagefolder_view.py):
`view/<partition>/<Brand>` → symlink to the nested `<Category>/<Brand>` dir — **no image
files copied** (40 directory symlinks for 20 brands × train/test). The recipe
(`recipes/logo_data.yaml`) points its `image_folder` sources at the view. The view lives
under gitignored `datasets/`, so nothing is committed, and it is obviated the moment
recursive ingestion lands.

### Verification

- A two-level fixture — `cat_a/brand_x/{1,2}.png`, `cat_b/brand_y/{1,2}.png` —
  materializes with `recursive: true` to records labeled `brand_x` / `brand_y`, with
  record count = the number of image files under the selected classes.
- With recursion off, the same fixture fails at **`validate`** (not `materialize`) with a
  message naming the empty-intermediate-directory condition.
- Determinism / round-trip unchanged: same tree + same seed ⇒ byte-identical instance;
  re-running hits the cache. The input-hash changes iff the discovered file set changes.
- Existing one-level `image_folder` recipes are unaffected (default behavior preserved).

---

## Gap 2 — input-hash blind to symlinked-directory content (silent stale cache)

| Field | Value |
|-------|-------|
| Target repo | DataRefinery |
| Related contract | `_hash_image_folder` / `_iter_files` (`datarefinery/pipeline/inputs.py`) — the per-source input hash that, with the canonical recipe hash and seed, forms cache identity |
| Sanitized | yes |
| First hit | 2026-06-22 |
| Triggered by | the Gap 1 workaround (an ImageFolder *view* built from directory symlinks) |

### Symptom

Using the Gap 1 workaround — a one-level ImageFolder view whose class dirs are
**symlinks** to the real (nested) class directories — a consumer changes the view's
contents (a different subset of classes), re-runs `materialize`, and DataRefinery
reports a **cache HIT** with the **same input hash**, silently returning the *previous*
instance. The materialized dataset still contains the old class set; no error, no warning.

### Affected contract / abstraction

Cache identity is `canonical-recipe-hash ⊕ input-hash ⊕ seed`, and the invariant is
"same recipe + inputs + seed ⇒ byte-identical instance; a *meaningful* input edit
invalidates and rebuilds." For an `image_folder` source the input portion is
`_hash_image_folder(root)`, which digests `(<relative_path>:<sha256(file_bytes)>)` for
every file under `root` via `_iter_files`. That walk **does not descend into symlinked
directories**, so a view composed of directory symlinks yields a content-blind
(effectively empty) file set — and therefore the **same** input hash regardless of which
classes the symlinks point at. Different inputs collide; a changed input does not rebuild.

The asymmetry is silent and dangerous: the *loader* (`_load_one_image_folder`) **does**
follow the symlinks, so data loads correctly on a cache miss — but the *hash* does not,
so on any subsequent run the stale instance is served as a hit.

### Diagnosis

A core reproducibility invariant is violated for symlinked-directory inputs. Because the
Gap 1 workaround *requires* symlink views, Gap 1 and Gap 2 compound: the very mechanism
needed to ingest a taxonomy tree also defeats cache identity. Note this is content-blind
in *both* directions — it will also wrongly cache-hit across genuinely different datasets
that happen to share a symlink-view root layout.

### Recommended fix

- `_iter_files` (for hashing) should **follow symlinked directories** — or resolve each
  source root before walking — so the input hash reflects the real, recursively-discovered
  file set. Add cycle protection (track visited real paths) to avoid symlink loops.
- Keep traversal deterministically ordered, and keep the loader and the hasher walking the
  **same** file set (the load/hash asymmetry is the root cause).
- Largely moot once Gap 1's native recursive ingestion lands (symlink views disappear), but
  content-hashing should follow symlinks regardless.

### Workaround applied

When the symlink view changes, purge the stale instance before re-materializing, since the
cache cannot detect the change:

```bash
datarefinery --cache-root data clean --by-recipe <recipe-hash-shard>
datarefinery --cache-root data materialize recipes/logo_data.yaml
```

(Alternatively, build the subset view from **real file copies** instead of directory
symlinks — for a small per-class subset the copy is cheap and restores correct cache
identity. We kept the symlink view + `clean` for this deliverable.)

### Verification

- After `clean --by-recipe`, `materialize` is a cache **miss** and the instance's labels
  match the current view (verified: canonical 20 brands present, prior set absent).
- A fixed `_iter_files` would produce a **different** input hash for two views pointing at
  different class sets, so changing the view rebuilds without a manual `clean`.

## Gap 3 — audio spectrogram features cannot be persisted for downstream consumption

| Field | Value |
|-------|-------|
| Target repo | DataRefinery |
| Related contract | audio Featurization outputs (`log_mel_spectrogram` → `mel`, fit-on-train `audio_normalize` → `feature`) are in-pipeline only; the `Sinks` contract's only writer `write_png_per_record` (`datarefinery/pipeline/sinks/writers.py`) |
| Sanitized | yes |
| First hit | 2026-06-22 |
| Filed as | [`briefs/datarefinery-audio-feature-persistence.md`](../briefs/datarefinery-audio-feature-persistence.md) (paired with the ModelFoundry consumption brief) |

### Symptom

Building Model 2 (songbird audio) end-to-end, the consumer runs the documented
audio chain — `audio_folder` decode → `window` → `log_mel_spectrogram` (`mel`) →
fit-on-train `audio_normalize` (`feature`) — and `materialize` succeeds. But the
materialized `dataset/<split>.jsonl` carries **only metadata** (`record_id`,
`source_record_id`, `window_index`, `label`, `path`, `sample_rate`); the
`sample_array` / `mel` / `feature` arrays are absent (in-pipeline only). Adding a
`Sinks` entry to persist `feature` fails at `materialize`:

```
sink 'persist_feature' at stage 'post_Featurizations': format='png_per_record'
expects uint8 on field 'feature'; got float32 — move the sink earlier than
normalize or pick a different field.
```

`png_per_record` is the only sink format that ships; `npy_per_record` / `parquet`
are deferred. So the float spectrogram features the plugin computes **cannot leave
the instance** in any form a downstream model can read.

### Affected contract / abstraction

The audio plugin's "in-pipeline vs persisted" rule (arrays never serialized to
JSONL) combined with the single shipped sink writer `write_png_per_record`, which
requires **uint8 HxW/HxWxC** and raises `MaterializeError` on any other dtype. The
on-disk dataset layout is the cross-repo consumption surface a modeling tool binds
to.

### Diagnosis

The plugin faithfully *computes* windowed spectrogram features but there is **no
serialization path for a float feature array** — `png_per_record` is uint8 (image
pixels); array sinks are deferred. A downstream modeling repo therefore has no way
to read the prepared features from a materialized audio instance. The modality
boundary the audio plugin proves on the *data* side never reaches a *model*. This
is the producing side's (DataRefinery's) half of the seam; the consuming side's
half is [ModelFoundry Gap 3](../modelfoundry/consumer-gap-analysis.md).

### Recommended fix

(Full behavior-level options in the brief.) Preferred: ship `npy_per_record` (or a
parquet-array sink) that persists the named float field per record and rewrites a
`feature_path`, mirroring `png_per_record`'s `image_path`. Alternatives: inline
npy-bytes in the JSONL, or a lossy uint8-quantization sink for the
spectrogram-as-image pattern. Coordinate rollout with the ModelFoundry consumption
fix (paired).

### Workaround applied

**None — Model 2 build paused.** Unlike Gaps 1–2 (which had scripted workarounds),
there is no consumer-side way to recover features the producer never writes: the
windowed `sample_array` is *also* in-pipeline-only, so even re-featurizing from the
instance is impossible — only the source clip `path` survives. A consumer *could*
bypass the plugin entirely (decode + window + log-mel + quantize to uint8 PNGs in a
script, then feed the existing image path), but that abandons the audio plugin's
featurization and fit-on-train contract. Per developer decision, Model 2 is treated
as **blocked on the dependency fix** rather than worked around (see Story C.c.2).

### Verification

- An audio recipe with a `Sinks` entry persisting `feature` as `npy_per_record`
  materializes without error; each record gains a `feature_path` resolving to an
  on-disk `(n_mels, n_frames)` array.
- Re-run is byte-identical + cache hit; a changed featurization parameter is a
  cache miss with different feature bytes.
- A downstream reader loads the arrays and regroups windows to clips by
  `source_record_id` (R7). Existing image recipes unaffected.

---

## Minor friction (resolved in-recipe)

Non-blocking friction that cost iteration but was solved within recipe authoring (no
external workaround). Logged for completeness — candidates for better docs/validation,
not necessarily code changes.

| When | Friction | Resolution |
|------|----------|------------|
| 2026-06-22 | With `Labels.source.kind: derived`, the loader does **not** attach `label` as a record field, so a sink `path_template` (and any consumer expecting `label`) sees a missing field. Non-obvious that a `label_from_path` Featurization is required to materialize the derived label onto the record. | Added an explicit `label_from_path` Featurization (`output_field: label`). A validate hint when a derived label is referenced downstream but never featurized would have caught it at the cheap gate. |
| 2026-06-22 | A pixel-altering `resize` requires a `Sinks` entry (validator check 26), but the sink **stage** interacts with pipeline order: sinking at `post_Transformations` runs before `Featurizations`, so a `{label}`-templated path fails; and `png_per_record` rejects the `float64` that `normalize` produces. | Sink at `post_Featurizations` (label available) and drop dataset-side `normalize` (a pretrained encoder applies its own ImageNet normalization, so DR stores uint8). Clearer stage-ordering docs / a validate cross-check (sink stage vs. fields referenced) would shorten this. |
