# Phase H sub-bundle plan — Image Classification Plugin Extensions

This plan extends Phase H ("Feature Refinements and Fixes") with a coherent sub-bundle of image-classification capability work. Source feature recommendation: [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

The sub-bundle is intentionally narrow — the **minimum-viable** subset from the recommendation doc's "Dependencies and Suggested Order" — sufficient to enable the most demanding pattern the recommendation addresses (two sibling recipes where one consumes the other's fitted statistics, with corruption generation downstream). All other recommended features are deferred to `## Future` with a pointer back to the recommendation doc.

## Phase H description revision

Current Phase H description (stories.md:31) frames the phase as small contained refinements. The sub-bundle adds new capabilities (filter ops, a generation op, a transformation parameter, an architectural decision) and so the phase description is broadened to encompass both refinement work and image-classification capability extensions that build on the v1 surface — while keeping the per-story scope tight and shippable.

Proposed replacement text:

> Refinements to the v1 feature surface, post-release fixes, and image-classification capability extensions that build on v1's input/featurization/filter/generation primitives. Each story is scoped to one user-visible capability or one focused fix so versions can ship independently.

## Gap analysis

**What exists today (v0.9.4):**

- Image plugin source types: `image_folder`, `image_flat` (H.a); partition handling (H.b, H.d).
- `Filters` operations: existing `filter_by_label`, stratified sampling primitives. **No** balanced per-class subsample with disjoint-pool selection. **No** per-class fractional subsample for controlled-imbalance construction. **No** "drop tagged records" companion.
- `Generation` operations: existing image generation primitives. **No** corruption-based generation for robustness evaluation.
- `Transformations`: `normalize` fits statistics from a `fit_source` partition declared within the same recipe. **No** mechanism to import fitted statistics from a *sibling* materialized instance.
- Cache identity: `SHA-256(canonical_recipe_bytes) ⊕ SHA-256(raw_input_bytes) ⊕ seed`. **No** notion of sibling-instance dependency.

**What's needed (this sub-bundle):**

- A balanced per-class subsample filter op with optional declarative tagging for disjoint-pool selection (FR-FILTER-1).
- A per-class fractional subsample filter op for controlled-imbalance dataset construction, inheriting FR-FILTER-1's tagging mechanism (FR-FILTER-2).
- A drop-by-label filter op that consumes those tags (FR-FILTER-3).
- A Generation op wrapping the canonical `imagecorruptions` (Hendrycks-Dietterich) reference (FR-GEN-1).
- A `stats_from_instance` parameter on `normalize` (extensible to future fit-phase ops) that imports fitted statistics from a sibling instance (FR-TRANS-1).
- A documented decision on cache-identity coupling between dependent recipes (FR-ARCH-1, loose for this bundle).

## Feature requirements (mini features.md)

In scope for this sub-bundle:

| ID | Feature | Type | Recipe surface |
|---|---|---|---|
| FR-FILTER-1 | `sample_per_class` (with optional `label` + `exclude_already_labeled`) | New Filters op | Op name `sample_per_class`; params `n_per_class`, `label?`, `exclude_already_labeled?` |
| FR-FILTER-2 | `sample_per_class_fractional` (inherits FR-FILTER-1's tagging params) | New Filters op | Op name `sample_per_class_fractional`; params `n_per_class_base`, `fractions: dict[str, float]`, `label?`, `exclude_already_labeled?` |
| FR-FILTER-3 | `drop_by_label` | New Filters op | Op name `drop_by_label`; param `labels: list[str]` |
| FR-GEN-1 | `imagecorruptions_apply` | New Generation op | Op name `imagecorruptions_apply`; params `corruption_types`, `severities`, `preserve_original`, `tag_fields` |
| FR-TRANS-1 | `stats_from_instance` parameter | Param on existing `normalize` (extensible) | `stats_from_instance: { recipe: <path-or-name>, op_id: <name> }` |
| FR-ARCH-1 | Multi-instance cache-identity decision: **loose coupling** | Documented decision; no cache-identity change | None (zero-byte change to canonical recipe) |

**Design decisions resolved (open questions in the recommendation doc):**

- **FR-FILTER-1 tagging:** bespoke `label` + `exclude_already_labeled` params on `sample_per_class`. A separate generic record-tagging primitive that multiple filter ops could share is deferred to Future.
- **FR-FILTER-3:** distinct `drop_by_label` op (reads cleaner in recipes than a parameter on existing primitives, matches the source doc's stated preference).
- **FR-GEN-1 dependency placement:** `image_classification[corruptions]` extras group. Base plugin stays lean.
- **FR-GEN-1 validation on unsupported corruption names:** fail-fast at recipe validation time *when the `[corruptions]` extras are installed*; deferred-with-clear-error at materialization time when not (the validator can't enumerate the corruption vocabulary without the dep).
- **FR-ARCH-1 coupling:** loose. With loose coupling, no cache-identity change is needed for this bundle — the decision lives in docs and in the FR-TRANS-1 story, not as a separate implementation story. Tight coupling deferred to Future as a follow-up.

## Technical changes (mini tech-spec.md)

**New modules / files:**

- `src/datarefinery/plugins/image_classification/filters_sample_per_class.py` — FR-FILTER-1.
- `src/datarefinery/plugins/image_classification/filters_sample_per_class_fractional.py` — FR-FILTER-2.
- `src/datarefinery/plugins/image_classification/filters_drop_by_label.py` — FR-FILTER-3.
- `src/datarefinery/plugins/image_classification/generation_imagecorruptions.py` — FR-GEN-1 (importable only when `[corruptions]` extras installed; module-level guard with clear ImportError).
- New tests under `tests/plugins/image_classification/` for each op.

**Modified modules:**

- `src/datarefinery/plugins/image_classification/__init__.py` — register the four new ops in the plugin's op registry.
- `src/datarefinery/plugins/image_classification/transformations_normalize.py` (or equivalent) — add `stats_from_instance` parameter handling.
- `src/datarefinery/recipe/models.py` — pydantic model additions for the new op params; `StatsFromInstanceSpec` model for FR-TRANS-1.
- `src/datarefinery/cache/loader.py` (or equivalent) — read fitted-statistics directory from a sibling cached instance by recipe-path-or-name resolution. Loose coupling: no cache-identity field change.
- `pyproject.toml` — add `[project.optional-dependencies] corruptions = ["imagecorruptions", "opencv-python-headless", "scikit-image"]`.

**Dependency additions (extras group only, not base):**

- `imagecorruptions`
- `opencv-python-headless` (transitive; pinned headless to avoid GUI deps)
- `scikit-image` (transitive)

**Cache-identity impact (pre-prod invalidation acceptable):**

- FR-FILTER-1, FR-FILTER-2, FR-FILTER-3, FR-GEN-1, FR-TRANS-1 each add new op kinds or new fields. Per `project-essentials.md` § "Cache identity is the reproducibility contract" pre-production rules, this is acceptable with a release-notes mention. Users re-materialize.
- The canonical-hash pinning test fixture is updated in lockstep with whichever story changes the fixture's canonical bytes (most likely none — the pinned fixture should remain a simple recipe that doesn't use any of these new ops, so its bytes are unaffected). Each story verifies the pin is untouched.

**Determinism:**

- `sample_per_class`, `sample_per_class_fractional`, and FR-GEN-1 must produce byte-identical output across `workers=1/2/4` per the determinism contract in `pipeline.workers`. Integration tests assert this.
- FR-GEN-1's underlying `imagecorruptions` calls are seeded from the recipe's master seed via the per-record seeding scheme (`pipeline.workers` § per-record seeding).

## Story sequence and version bumps

Six stories. Pre-1.0 per-story bumping (per Version Cadence). Current baseline: v0.9.4.

| Story | Title | Version | Notes |
|---|---|---|---|
| H.i | Integration spike — `imagecorruptions` extras viability | (no bump) | Spike-only; deliverable is documented outcome (does the extras-install cleanly? can we enumerate the corruption vocabulary? is a single corruption call deterministic with seeding?). No shipping code, no version bump. |
| H.j | v0.10.0 `sample_per_class` filter op with disjoint-pool labeling | v0.10.0 | FR-FILTER-1. Cache-invalidating (new op kind). |
| H.k | v0.11.0 `sample_per_class_fractional` filter op | v0.11.0 | FR-FILTER-2. Inherits H.j's tagging mechanism. Cache-invalidating. |
| H.l | v0.12.0 `drop_by_label` filter op | v0.12.0 | FR-FILTER-3. Cache-invalidating. |
| H.m | v0.13.0 `imagecorruptions_apply` Generation op + `[corruptions]` extras | v0.13.0 | FR-GEN-1. Depends on H.i spike outcome. Cache-invalidating. |
| H.n | v0.14.0 `stats_from_instance` on `normalize` + FR-ARCH-1 loose-coupling decision documented | v0.14.0 | FR-TRANS-1 + FR-ARCH-1 (loose). Cache-invalidating (new param). |

Each minor bump reflects a feature addition under pre-1.0 semver.

## Out of Scope

Each item below is genuinely deferrable — the work is valuable but not required for the minimum-viable pattern this sub-bundle enables. Walk through each at the approval gate.

- **FR-AUG-1..4 augmentation policies** (`random_crop`, `horizontal_flip`, `color_jitter`, `random_erasing`) — non-materialized policies forwarded to ModelFoundry. Touches the ModelFoundry framework-adapter boundary, which is out of DataRefinery's v1 surface. **Deferred to Future.**
- **FR-VIZ-1..4 reporting visualizations** (`pixel_distribution`, `augmented_sample_grid`, `corruption_severity_grid`, `severity_ladder`) — report-quality improvements; the recommendation doc itself tiers these as "nice to have." **Deferred to Future.**
- **FR-ARCH-1 tight coupling** — sibling-instance `recipe_hash` participating in cache identity. Loose coupling is sufficient for the small-scale single-author workflow this bundle enables; tight coupling becomes a real correctness concern in multi-team or longitudinal workflows. **Deferred to Future** as a follow-up upgrade.
- **Generic record-tagging primitive** — a shared tagging mechanism multiple filter ops could use, instead of the bespoke `label` / `exclude_already_labeled` params on `sample_per_class`. Larger refactor; the bespoke params are the minimum needed. **Deferred to Future.**
- **New source types beyond `image_folder` / `image_flat`** — out of this bundle's scope; explicitly out of scope in the recommendation doc.
- **New plugins beyond image_classification** — out of this bundle's scope.
- **ModelFoundry-facing concerns** (training-time augmentation realization, framework adapters) — belong in ModelFoundry's spec, not DataRefinery's.

## Future-section addition

After approval, the `## Future` section in `stories.md` will get a single entry (with sub-bullets) pointing to the recommendation doc for the deferred items:

> - **Image-classification plugin: additional capabilities deferred from Phase H sub-bundle** — see [`phase-h-datarefinery-feature-recommendation.md`](phase-h-datarefinery-feature-recommendation.md) for full specifications:
>   - FR-AUG-1..4 augmentation policies (`random_crop`, `horizontal_flip`, `color_jitter`, `random_erasing`)
>   - FR-VIZ-1..4 reporting visualizations (`pixel_distribution`, `augmented_sample_grid`, `corruption_severity_grid`, `severity_ladder`)
>   - FR-ARCH-1 tight coupling (sibling `recipe_hash` in cache identity)
>   - Generic record-tagging primitive (factored out of `sample_per_class`'s bespoke `label` / `exclude_already_labeled` params)
