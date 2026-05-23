# Phase H sub-bundle 2 plan — Image Classification Plugin Extensions: augmentation policies + reporting visualizations

Second sub-bundle within Phase H ("Feature Refinements and Fixes"). Source feature recommendation: [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md). Prior sub-bundle plan: [phase-h-image-classification-extensions-plan.md](phase-h-image-classification-extensions-plan.md).

The first sub-bundle (H.i–H.n, shipped v0.10.0–v0.14.0) added per-class sampling, drop-by-label, corruption generation, and sibling-instance fitted statistics. This second sub-bundle adds the remaining image-classification capability extensions originally deferred to Future:

- **FR-11 extension** — augmentation operations support both `lazy` (declare-only; ModelFoundry realizes at train time) and `aggressive` (DataRefinery materializes augmented records into the cached dataset) modes per-op.
- **FR-AUG-1..4** — four schema-validated augmentation ops (`random_crop`, `horizontal_flip`, `color_jitter`, `random_erasing`) implementing both modes.
- **ModelFoundry cross-repo dependency spec** — a documented contract surface ModelFoundry binds against (Augmentations schema, on-disk dataset layout, manifest fields, report subsections, cache-identity contract).
- **FR-VIZ-1..4** — four reporting-mode visualizations (`pixel_distribution`, `augmented_sample_grid`, `corruption_severity_grid`, `severity_ladder`).

Two bundled releases: **AUG release v0.15.0** (H.o–H.s) and **VIZ release v0.16.0** (H.t–H.x).

## Reframing FR-11

The current FR-11 framing in features.md states: *"Augmentations apply on-the-fly during training; they are described in the recipe and report but do not produce additional persisted records."* That framing concedes DataRefinery's "prep and cache" value proposition for the `Augmentations` section — the section becomes a config-string passthrough to ModelFoundry rather than a first-class materialization step.

The extension introduced in H.p generalizes FR-11 to support both:

- **`lazy` (default; matches current FR-11):** Recipe declares the policy; the materialized dataset is unaugmented; ModelFoundry realizes per epoch at train time. Each epoch sees different augmented variants — the regularization effect remains.
- **`aggressive` (new):** DataRefinery realizes the augmentation deterministically per-record at materialization time. The augmented records live in `dataset/` and are cached normally. ModelFoundry sees pre-augmented records and skips the augmentation step entirely.

Both modes participate in cache identity through the recipe's canonical bytes (existing FR-4 mechanism). Changing materialization mode, expansion factor, or any other policy field invalidates the cache.

## Phase H description

Unchanged. Current text already covers "image-classification capability extensions that build on v1's input/featurization/filter/generation primitives." This sub-bundle extends augmentation and visualization; no description revision needed.

## Gap analysis

**What exists today (v0.14.0):**

- `Augmentations` section in the recipe (FR-11), but only as a declaration surface — no realization in the pipeline, no canonical augmentation ops registered with the `image_classification` plugin.
- Reporting visualizations limited to `class_distribution_histogram` and `sample_grid`.
- ModelFoundry consumes DataRefinery instances against an *implicit* contract scattered across features.md and tech-spec.md.

**What's needed:**

- FR-11 framework extension to support `materialization: lazy | aggressive` per op, with `expansion` field for aggressive mode.
- Aggressive-mode realizer in `pipeline/stages/augmentations.py` (currently a passthrough).
- Per-record seeding extension to `(record_id, variant_index)` for aggressive expansion.
- Four schema-validated augmentation ops in the `image_classification` plugin.
- A documented cross-repo dependency spec ModelFoundry can bind against (instead of reverse-engineering from spec sources).
- Four reporting-mode visualization ops.

## Feature requirements (mini features.md)

### AUG bundle

| ID | Feature | Type | Recipe surface |
|---|---|---|---|
| FR-11-ext | `materialization` + `expansion` fields on `AugmentationOp` | Framework extension | `materialization: lazy \| aggressive` (default `lazy`); `expansion: int` ≥ 1 (default 1; > 1 requires aggressive) |
| FR-AUG-1 | `random_crop` | New Augmentations op | Params: `size`, `padding`, `padding_mode` (`reflect`/`replicate`/`zero`/`constant`) |
| FR-AUG-2 | `horizontal_flip` | New Augmentations op | Params: `p` (probability per sample, default 0.5) |
| FR-AUG-3 | `color_jitter` | New Augmentations op | Params: `brightness`, `contrast`, `saturation`, `hue` (each a float magnitude) |
| FR-AUG-4 | `random_erasing` | New Augmentations op | Params: `p`, `scale` (range), `ratio` (range) |
| MF-DOC-1 | ModelFoundry dependency spec | New docs file | `docs/specs/modelfoundry/dependency-spec.md` |

### VIZ bundle

| ID | Feature | Type | Recipe surface |
|---|---|---|---|
| FR-VIZ-1 | `pixel_distribution` | New Visualizations op | Params: `bins`, `splits`. Reporting mode only. |
| FR-VIZ-2 | `augmented_sample_grid` | New Visualizations op | Params: `n_base`, `n_variants`, `seed`. Reporting mode only. |
| FR-VIZ-3 | `corruption_severity_grid` | New Visualizations op | Params: `n_images`, `corruption_types`, `severities`. Reporting mode only. Requires `[corruptions]` extras. |
| FR-VIZ-4 | `severity_ladder` | New Visualizations op | Params: `n_examples`, `corruption_type`. Reporting mode only. Requires `[corruptions]` extras. |

### Design decisions resolved

- **Schema-validated parameter dicts** (not opaque policy strings) for all augmentation ops. Pydantic `OperationSpec` per op; validator coverage via existing FR-2 check 18.
- **`lazy` is the default materialization mode** (backward-compatible with current FR-11 behavior). `aggressive` is opt-in.
- **Per-op materialization** (not per-section). A recipe may mix lazy and aggressive ops in one `Augmentations` block.
- **Option A on-disk representation for aggressive mode:** record multiplication. With `expansion: N`, the output is N × the input record count, each augmented variant a peer record in the dataset. Each variant carries metadata identifying the source record and the variant index.
- **Per-record seeding extends to `(record_id, variant_index)`** under aggressive mode: `sha256(global_seed || op_id || record_id || variant_index)` derives the per-variant seed. Worker scheduling does not affect output.
- **Augmentations remain train-only by default** (existing FR-11 check 5 enforces this). Validation/test splits never see aggressively-materialized augmented records.
- **FR-VIZ-2 implementation:** in aggressive mode, samples directly from the materialized augmented dataset. In lazy mode, realizes a small fixed number of augmented variants (using the same realizer code paths as aggressive) for the visualization only — these are not persisted to the dataset, just rendered into the report.

## Technical changes (mini tech-spec.md)

### AUG bundle new/modified

**New modules (image_classification plugin):**

- `src/datarefinery/plugins/image_classification/augmentations/__init__.py` — submodule init.
- `src/datarefinery/plugins/image_classification/augmentations/_realizer.py` — shared aggressive-mode realization scaffolding: per-record seeded RNG construction, variant emission, record-metadata tagging (`source_record_id`, `variant_index`).
- `src/datarefinery/plugins/image_classification/augmentations/random_crop.py` — FR-AUG-1.
- `src/datarefinery/plugins/image_classification/augmentations/horizontal_flip.py` — FR-AUG-2 (also the H.o spike exemplar).
- `src/datarefinery/plugins/image_classification/augmentations/color_jitter.py` — FR-AUG-3.
- `src/datarefinery/plugins/image_classification/augmentations/random_erasing.py` — FR-AUG-4.

**New docs file:**

- `docs/specs/modelfoundry/dependency-spec.md` — new subdirectory `docs/specs/modelfoundry/`. Documents the cross-repo contract: `Augmentations` schema, materialized dataset on-disk layout (including aggressive-mode record-multiplication semantics), manifest fields ModelFoundry reads, report subsections relevant to training/eval, cache-identity contract, schema-version coordination policy, forward-compatibility expectations, failure modes ModelFoundry should detect (e.g., recipe declares an op ModelFoundry hasn't implemented yet).

**Modified modules:**

- `src/datarefinery/recipe/models.py` — extend `AugmentationOp`: add `materialization: Literal["lazy", "aggressive"] = "lazy"` and `expansion: int = 1`. Model-level validation: `expansion > 1` requires `materialization == "aggressive"`; `expansion < 1` rejected.
- `src/datarefinery/recipe/validator.py` — augment check 18 plugin-specific schema validation path; no new top-level check number needed (existing check 5 train-only enforcement remains).
- `src/datarefinery/pipeline/stages/augmentations.py` — implement aggressive-mode record multiplication: for each record in the input, emit `expansion` augmented variants via the per-op realizer. Preserve lazy-mode passthrough semantics (declared but not realized).
- `src/datarefinery/pipeline/workers.py` — per-record seed derivation extends to `(record_id, variant_index)` for aggressive augmentation. Reorder-by-`(record_id, variant_index)` invariant maintained across worker boundaries.
- `src/datarefinery/reporting/report.py` — render augmentation policy summary; mode-aware (lazy: declares the policy; aggressive: reports the expansion-multiplied record count).
- `src/datarefinery/plugins/image_classification/__init__.py` — register the four new augmentation ops in the plugin's `supported_operations`.

### VIZ bundle new/modified

**New modules:**

- `src/datarefinery/plugins/image_classification/visualizations/__init__.py` — submodule init.
- `src/datarefinery/plugins/image_classification/visualizations/_render.py` — shared Matplotlib + Pillow rendering helpers (figure setup, PNG output to `report/visualizations/`, deterministic file naming).
- `src/datarefinery/plugins/image_classification/visualizations/pixel_distribution.py` — FR-VIZ-1.
- `src/datarefinery/plugins/image_classification/visualizations/augmented_sample_grid.py` — FR-VIZ-2. Reads from materialized augmented dataset (aggressive mode) or realizes inline (lazy mode) via the AUG-bundle realizer code paths.
- `src/datarefinery/plugins/image_classification/visualizations/corruption_severity_grid.py` — FR-VIZ-3. Lazy-imports `imagecorruptions` via the `[corruptions]` extras pattern established in H.m.
- `src/datarefinery/plugins/image_classification/visualizations/severity_ladder.py` — FR-VIZ-4. Same lazy-import pattern as FR-VIZ-3.

**Modified modules:**

- `src/datarefinery/plugins/image_classification/__init__.py` — register the four new visualization ops.

### Cache identity impact (pre-prod invalidation acceptable)

- **AUG release (v0.15.0):** Adding `materialization` and `expansion` fields to `AugmentationOp` with non-None defaults changes the canonical bytes of *every* recipe that declares any `Augmentations` op — even those that don't use the new fields, because the defaults serialize into the canonical form. Per `project-essentials.md` § "Cache identity is the reproducibility contract" pre-production rules, this is acceptable with prominent release-notes mention. Users re-materialize. The canonical-hash pinning test fixture is updated in lockstep if its recipe uses `Augmentations`.
- **VIZ release (v0.16.0):** New visualization op kinds. Only invalidates recipes that use one of the four new viz ops. The canonical-hash pinning test fixture should not use any of these (verify in H.x).

### Determinism

- **Aggressive-mode augmentation:** per-`(record_id, variant_index)` seeding is the existing per-record scheme extended one level. Same byte-identical output across `workers=1/2/4` invariant. H.o spike verifies this end-to-end.
- **Lazy-mode augmentation:** DataRefinery does not realize the augmentation, so determinism is ModelFoundry's responsibility. The recipe declares the seed; the manifest persists it. The dependency-spec doc (H.s) makes this responsibility explicit.

## Story sequence and version bumps

Ten stories across two bundled releases. Each story within a bundle runs unversioned (per the Version Cadence phase-bundling option); the bundle's release story owns the bump. Each release-magnitude is **minor** — new features.

### AUG bundle (release v0.15.0)

| Story | Title | Version | Notes |
|---|---|---|---|
| H.o | Architectural spike — aggressive-mode augmentation realization viability | (no bump) | Spike-only. Verifies per-record seeded augmentation produces byte-identical output across `workers=1/2/4`; validates Option A on-disk representation end-to-end; uses `horizontal_flip` as the simplest exemplar. No shipping code. |
| H.p | FR-11 extension — `materialization: lazy \| aggressive` framework | (no bump) | Pure framework: model fields, validator paths, stage runner aggressive-mode realization, worker seeding extension, report rendering hook. No new ops. |
| H.q | Spatial augmentations — `random_crop` + `horizontal_flip` (lazy + aggressive) | (no bump) | Two ops sharing the spatial-transform pattern. |
| H.r | Appearance augmentations — `color_jitter` + `random_erasing` (lazy + aggressive) | (no bump) | Two ops sharing the appearance-perturbation pattern. |
| H.s | **AUG release story** — ModelFoundry dependency spec + cross-cutting docs sweep + CHANGELOG + version bump | **v0.15.0** | Creates `docs/specs/modelfoundry/dependency-spec.md`; sweeps features.md / tech-spec.md / README.md for cross-references; CHANGELOG `## [0.15.0]` "Added" section with cache-invalidation callout; bumps `pyproject.toml` and `__init__.py` to 0.15.0; removes FR-AUG-1..4 from the `## Future` section of stories.md. |

### VIZ bundle (release v0.16.0)

| Story | Title | Version | Notes |
|---|---|---|---|
| H.t | FR-VIZ-1 `pixel_distribution` | (no bump) | Standalone. Per-channel histograms; no dependencies on the AUG bundle. |
| H.u | FR-VIZ-2 `augmented_sample_grid` | (no bump) | **Depends on H.r** (uses the aggressive-mode realizer; samples from materialized augmented dataset or realizes inline in lazy mode). |
| H.v | FR-VIZ-3 `corruption_severity_grid` | (no bump) | Uses `[corruptions]` extras shipped in H.m. Lazy-imports `imagecorruptions`. |
| H.w | FR-VIZ-4 `severity_ladder` | (no bump) | Same dependency as H.v. Simpler layout (one corruption × all severities × N images). |
| H.x | **VIZ release story** — cross-cutting docs sweep + CHANGELOG + version bump | **v0.16.0** | Sweeps features.md / tech-spec.md for cross-references; CHANGELOG `## [0.16.0]` "Added" section; bumps to 0.16.0; removes FR-VIZ-1..4 from the `## Future` section. |

Each working story (H.o–H.r, H.t–H.w) includes scoped doc edits for the surfaces it touches (per the H.j–H.n precedent). The release stories (H.s, H.x) do the cross-cutting consistency sweep, README install/extras snippets if applicable, CHANGELOG sections, version bumps, and Future-section cleanup. This avoids per-story version bumps while keeping doc fidelity per story.

## Out of Scope

Walk through each at the approval gate. Each is genuinely deferrable.

- **Combinable augmentation chains** — applying multiple augmentations in a single record-multiplication pass with shared variant indexing (e.g., `random_crop` then `color_jitter` producing one chained variant per index). Each op in `Augmentations` runs independently in this sub-bundle; chaining is a separate design with its own seed-derivation and variant-cardinality questions. **Deferred to Future.**
- **Augmentation realization for non-image plugins** (tabular, text). Augmentations remain image-classification-only in v1; tabular and text plugins are stubs and don't ship augmentation realization. **Deferred to Future.**
- **Hard-precondition coordination with ModelFoundry adoption.** DataRefinery ships the dependency spec as a *forward-declared* contract; ModelFoundry adopts the schema on its own schedule. This sub-bundle does not gate on ModelFoundry being ready to consume `materialization: lazy` policy. **Documented as an explicit non-precondition in the dependency-spec doc.**
- **Tight-coupling cache identity for sibling-instance dependencies (FR-ARCH-1).** Still deferred from the prior sub-bundle. **Stays in Future.**
- **Generic record-tagging primitive** factored out of FR-FILTER-1's bespoke params. Still deferred. **Stays in Future.**

## Future-section updates

After H.s lands: remove FR-AUG-1..4 from the existing Future entry "Image-classification plugin: additional capabilities deferred from Phase H sub-bundle."

After H.x lands: remove FR-VIZ-1..4 from the same Future entry.

The remaining Future entries (FR-ARCH-1 tight coupling, generic record-tagging primitive) stay.
