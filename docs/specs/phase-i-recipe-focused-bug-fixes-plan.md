<!--
Copyright (c) 2026 Pointmatic
SPDX-License-Identifier: Apache-2.0
-->

# Phase I plan — Recipe-focused Bug Fixes and Feature Gaps in v0.16.0

This is the `plan_phase` plan document for the Phase I expansion that absorbs the runtime implementation gaps catalogued in [`dependency-gaps-v0.16.0.md`](dependency-gaps-v0.16.0.md). Phase I was opened in v0.16.0 to triage gaps surfaced by a downstream consumer recipe exercising the image-classification plugin end-to-end. Stories I.a–I.c closed three of those gaps (G4, G5/G7 reclassification, G8) as part of the initial debug-cycle pass. This plan scopes the remaining sixteen open items as new stories in the same phase.

For the consumer-side gap catalogue (one section per G item with symptom / root cause / suggested fix direction), see [`dependency-gaps-v0.16.0.md`](dependency-gaps-v0.16.0.md). This plan summarises and orders that work; the depth is in the gap doc.

---

## Phase I description revision

Phase I's existing description ([`stories.md` § Phase I](stories.md)) opens "Phase I collects investigation and fix work surfaced by the consumer cross-check against DataRefinery v0.16.0 (see [`dependency-gaps-v0.16.0.md`](dependency-gaps-v0.16.0.md), entries G1–G17 + DOC)." Two adjustments to that prose are landing alongside this plan:

1. **Title** updated to "Recipe-focused Bug Fixes and Feature Gaps in v0.16.0" (`plan_phase` step 0 — already applied).
2. **Body** broadens the gap range from "G1–G17" to "G1–G19 + DOC" (G18 and G19 were captured after the initial gap doc was written).

The phase's debug-cycle origins (I.a–I.c) remain the anchoring narrative: each new story below closes a specific G item with a code change, a test pin, the corresponding `recipe-authoring.md` section per the DOC rule, and any cross-repo coordination required by [`project-essentials.md` § "Recipe / manifest / report shape changes need a cross-repo coordination check"](project-essentials.md).

---

## Gap analysis — what exists vs. what's needed

DataRefinery v0.16.2 ships a schema-versioned recipe surface, a plugin-driven operation factory, a contracts evaluator, and a reporting pipeline. The remaining gaps fall into five families:

| Family | What exists today | What is needed |
|---|---|---|
| **Plugin op registration** | `_TRANSFORMATION_OPS`, `_FEATURIZATION_OPS`, `_VISUALIZATION_OPS` factories with a stable core (normalize, sample_grid, etc.) | Three additional ops the consumer surface relies on: `cast` (rename + factory + `scale` param), `categorical_encode`, `flatten`. One additional viz param (`group_by` on histogram). |
| **Schema cross-section consistency** | Each section model is internally consistent; the union is not | Filters' nested `predicate:` and Generation's `applies_at:` / nested `op:` diverge from the canonical top-level `op:` + `splits:` + `params:` shape every other section uses. Resolved together as a `schema_version: 1 → 2` migration cluster. |
| **Contracts evaluator vocabulary** | `record_count`, `required_field`, `dtype`, `range`, `distributional` (placeholder) — five scalar-record kinds | Per-split / per-class kinds (`split_record_counts`, `per_class_count_per_split`, `count_by_field`, `count_by_fields`), structural kinds (`shape_equals`, `value_in_set`, `per_class_count_equals`), and the `*_equals` / `*_in_set` / `*_range` naming pass (part of the schema-v2 cluster). |
| **Pipeline runner — stage exposure** | Visualizations run once post-pipeline; Generation extends source records; Splits assumes partition-tagged inputs | Stage-aware viz dispatch with per-stage snapshots; opt-in replace-input-records for Generation; tag-driven `Splits.applies_to` for filter-tagged pools. |
| **Sibling-instance resolver** | `resolve_sibling_stats` hashes sibling recipe verbatim | Strip variants before hashing (one-line fix) so `stats_from_instance` succeeds when the sibling declares variants. |

A sixth concern — **documentation discipline** — runs across every family. Per the DOC rule in [`dependency-gaps-v0.16.0.md` § DOC](dependency-gaps-v0.16.0.md): every fix lands its `recipe-authoring.md` section in the same story. Pre-existing drift for already-shipped capabilities (Featurizations missing `image_size_stats`; Filters missing `sample_per_class*` and `drop_by_label`; Visualizations missing FR-VIZ-1..4) closes alongside whichever new story touches the same section, not as a separate sweep story.

---

## Feature requirements (mini features.md)

Each requirement below is implemented as a story in the [story sequence](#story-sequence-and-version-bumps) section. Cross-references to canonical features.md FR numbers cite the existing FRs the work extends or fulfils.

### FR-I-1 — Sibling-stats resolver tolerates sibling variants (G19)

`resolve_sibling_stats` strips the sibling recipe's variants block before computing the canonical hash, matching the cache-key derivation already used by the materialize path. After the fix, any sibling recipe that declares variants (the canonical authoring pattern per the recipe-authoring guide) resolves successfully under `stats_from_instance`. The future variant-selecting form (`stats_from_instance.variant: <name>`) is documented as planned but not implemented in this phase. Extends FR-TRANS-1.

### FR-I-2 — `cast` Transformation, replacing the declared-but-unimplemented `cast_dtype` (G2)

The canonical operation name is `cast`, with parameters `dtype: str` (required) and `scale: float = 1.0` (optional). The op registers in `_TRANSFORMATION_OPS` and applies record-by-record without a fit phase. The existing schema-only `cast_dtype` declaration is removed (no aliasing; aliasing two names for the same op doubles the surface authors have to learn). The sibling unimplemented Transformation `to_grayscale` is removed from the OperationSpec table in the same pass (see Out of Scope for the implement-vs-remove decision).

### FR-I-3 — `categorical_encode` Featurization (G3)

`categorical_encode` derives an integer-encoded field from a categorical source field, with two modes: (a) recipe-declared vocabulary (a literal list of category names — the op is deterministic, no fit phase) and (b) fit-on-train (vocabulary derived from the training split, persisted to `fitted_statistics/<op_name>/vocabulary.parquet`, replayed identically on val/test). The fit-on-train mode is the FR-TRANS-1 pattern transplanted to Featurizations.

### FR-I-4 — `flatten` Featurization (G9)

`flatten` reshapes a multi-dimensional field to a 1-D vector via `np.asarray(v).reshape(-1)`. No parameters; no fit phase. The opration unblocks variant overlays that materialize both the original tensor and a flattened view (e.g., MLP-shaped consumption alongside CNN-shaped consumption from a single recipe).

### FR-I-5 — `seed_derive_from: master` on Filters and Generation (G11)

A new `SeedDerivationSpec` accepts the literal `"master"` as an alternative to a fixed integer at every seeded-op site (Filters, Generation, future-Augmentation, future-Splits). Resolution at materialize time computes `derived_seed = sha256(recipe.seed.to_bytes(8, "big") + op_name_bytes).digest()[:8]`. The derivation function is pinned by test; it participates in cache identity (the master seed already does; the per-op derived seed is a deterministic function of it). Documented in a new `recipe-authoring.md § Seeds and determinism` section.

### FR-I-6 — Per-split / per-class / structural assertion kinds (G6 + G16b)

Six new assertion kinds land together (they share evaluator plumbing):

- `split_record_counts` — `{counts: {<split>: <int>, …}}`
- `per_class_count_per_split` — `{field: <label_field>, per_class: <int>}` (warning-severity tolerant of stratification rounding)
- `count_by_field` — `{field: <name>, value_per_key: <int>}`
- `count_by_fields` — `{fields: [<name1>, <name2>], value_per_combination: <int>}`
- `shape_equals` — `{field: <name>, value: [<dim>, <dim>, <dim>]}` (asserts ndarray shape)
- `value_in_set` — `{field: <name>, value: [<v>, <v>, …]}`
- `per_class_count_equals` — `{field: <label_field>, value: <int>}` (single-split form)

The evaluator signature changes for `evaluate_output_expectations`: `Iterable[Record]` → `Mapping[str, list[Record]]` keyed by split name. `evaluate_input_contracts` keeps the flat form (input contracts run pre-splits).

The naming-rename pass for the existing five kinds (`dtype` → `dtype_equals`, `range` → `value_range`, `record_count` → `record_count_in_range`, etc., G16a) lands separately as part of the schema-v2 cluster (FR-I-15 below), since it is canonical-bytes-perturbing.

### FR-I-7 — `class_distribution_histogram` accepts `group_by` (G17)

A `group_by: str` optional param on the `class_distribution_histogram` viz selects the field to bucket on; default is `Labels.field` (current behaviour). A validator check ensures `group_by` names a known field per `Output.record_schema` or a Generation-introduced tag field.

### FR-I-8 — Generation `replace_input_records` (G18)

A new `GenerationOp.replace_input_records: bool = False` field declares whether Generation's output augments (current behaviour, default) or replaces the input records. The default preserves backward compatibility for existing Generation use sites; the opt-in covers transformation-style Generation ops (e.g., on-the-fly image corruption) that produce N output records per input and don't want the originals tagged along. No schema bump required.

### FR-I-9 — `SampleData.selector.kind` and `selector.splits` (G14)

`SampleSelector` gains `kind: Literal["uniform", "per_class"] = "uniform"` and `splits: list[str] | None = None`. `kind: per_class` requires `Labels.field` populated (validator check); selects `n` records per class from the declared splits. `kind: uniform` (default) preserves the current behaviour.

### FR-I-10 — `Splits.class_balance` dict shape (G10, MF-side decision)

`SplitsSection.class_balance: str | None` widens to `str | dict[str, Any] | None`. The dict shape is `{strategy: <str>, applies_to: [<split>, …]}`. DataRefinery's runtime treats the field as a forward-declared training-time hint — **no resampling, no weight emission at the DataRefinery layer**. The strategy is surfaced verbatim through `SplitResult.class_balance` and `manifest.class_balance`; consumer tools (ModelFoundry today; others later) bind against the dict shape via [`dependency-spec.md`](modelfoundry/dependency-spec.md). Authoring guidance in `recipe-authoring.md § Filters vs Splits for class imbalance` is updated to spell out the runtime-vs-training-time separation explicitly so authors don't expect post-balance record counts.

### FR-I-11 — Tag-driven `Splits.applies_to` (G1)

Validator check 20 (`partitions_consistent`) broadens to also accept `applies_to` values that match a filter-emitted tag (the `label` parameter of `sample_per_class` / `sample_per_class_fractional`). At pipeline-runner time, `pipeline/stages/splits.py` partitions only records carrying the named tag and passes through every other tagged record verbatim under its existing tag-driven partition.

### FR-I-12 — `tag_fields` dict-rename form for `imagecorruptions_apply` (G13)

`ImageCorruptionsApplyParams.tag_fields: list[str] | dict[str, str]`. The list form (canonical names, today's behaviour) remains valid and is the documented default. The dict form maps the **authored output field name** → the **canonical tag name** the runtime understands (`corruption`, `severity`, `source_path`). The runtime asserts each dict value is in the canonical set at validate time.

### FR-I-13 — Stage-aware visualization dispatch (G7, preexisting story)

The pipeline runner snapshots per-stage split outputs (references, not copies). `apply_reporting_visualizations` accepts the snapshot mapping and dispatches each declared `VisualizationOp` against its declared stage. `VisualizationOp.stage` constrains from `str` to `Literal[<valid stage names>]` so unknown-stage typos fail at validate time. The bundled scaffolder defaults `stage: post_pipeline` when no stage is declared (preserving today's behaviour for unmigrated recipes). Closes G5 as a side effect: `augmented_sample_grid` at `stage: pre_transformations` reads uint8 records by construction. Fulfils FR-VIZ-* the augmentation-preview corner.

### FR-I-14 — `schema_version: 1 → 2` migration framework (G15 + G12 + G16a cluster)

A coordinated schema-v2 bump packages three canonical-bytes-perturbing reshapes into a single migration so users see one cache invalidation rather than three. Sub-numbered story cluster:

- **FR-I-14.1 (G15)** — `FilterOp` reshapes from `{name, predicate: {op, ...rest}, stages, splits, seed}` to `{name, op, params, stages, splits, seed}`. Matches every other section's shape. Loader migration entry reshapes v1 recipes into v2 form prior to canonical-bytes computation.
- **FR-I-14.2 (G12)** — `GenerationOp` lifts `op` to top level; renames `applies_at: list[str]` → `splits: list[str]`; allows `output_schema: dict[str, FieldSpec] | Literal["matches_input"]` (shorthand expands to the input record schema plus declared tag fields at materialize time); seed accepts `int | SeedDerivationSpec` (per FR-I-5).
- **FR-I-14.3 (G16a)** — Assertion `kind` naming pass: rename to `*_equals` / `*_in_set` / `*_range` family across InputContracts and OutputExpectations. The five existing v1 kinds (`dtype`, `range`, `record_count`, `required_field`, `distributional`) each get a v2 canonical name; v1 names are removed (not aliased) and the migration entry rewrites them. The version bump to v0.17.0 lands here as the cluster-closing story along with the canonical-hash pin update, the release-notes blast-radius announcement, and the integration test that v1→v2 migration produces identical post-migration canonical bytes for a representative fixture.

Per [`project-essentials.md` § "Cache identity is the reproducibility contract — invalidations are ceremonious"](project-essentials.md), this is a pre-production cache-invalidating change: documented in release notes, noted as a one-time re-materialization cost, but does not require the post-production ceremony (no `schema_version` re-pinning beyond the v1 → v2 bump itself).

---

## Technical changes (mini tech-spec.md)

### Module impact summary

| Module | Change |
|---|---|
| `src/datarefinery/recipe/models.py` | `SeedDerivationSpec` added; `FilterOp` reshape (v2); `GenerationOp` reshape (v2); `SplitsSection.class_balance` widens; `SampleSelector` adds `kind` and `splits`; `VisualizationOp.stage` narrows to `Literal[…]`; `ImageCorruptionsApplyParams.tag_fields` widens. |
| `src/datarefinery/recipe/loader.py` | `SUPPORTED_SCHEMA_VERSIONS` extends `{1}` → `{1, 2}`; `migrations[(1, 2)]` adds three rewrites (Filters reshape, Generation reshape, assertion-kind renames). |
| `src/datarefinery/recipe/variants.py` | No change for FR-I-1; existing `apply_variant(recipe, None)` semantics already strip variants. |
| `src/datarefinery/recipe/validator.py` | Check 20 broadens (FR-I-11 tag-driven Splits.applies_to); new check for FR-I-7 (group_by names a known field); new check for FR-I-9 (per_class kind requires Labels.field); new check for FR-I-12 (tag_fields dict values are in canonical set). |
| `src/datarefinery/pipeline/contracts.py` | Six new `kind` evaluators (FR-I-6); `evaluate_output_expectations` signature changes to per-split mapping; flat fall-through preserved by routing single-split as a one-key mapping. |
| `src/datarefinery/pipeline/stages/splits.py` | Tag-driven `applies_to` branch (FR-I-11). `class_balance` dict shape passes through verbatim to `SplitResult.class_balance` (FR-I-10). |
| `src/datarefinery/pipeline/stages/generation.py` | `replace_input_records` branch (FR-I-8); `output_schema: matches_input` expansion (FR-I-14.2). |
| `src/datarefinery/pipeline/stages/featurizations.py` | New `CategoricalEncodeOp` and `FlattenOp` (FR-I-3, FR-I-4) — added to `_FEATURIZATION_OPS`. |
| `src/datarefinery/pipeline/stages/transformations.py` | `CastOp` registered (FR-I-2); `cast_dtype` OperationSpec entry removed; `to_grayscale` OperationSpec entry removed (see Out of Scope). |
| `src/datarefinery/pipeline/stages/visualizations.py` | Stage-aware dispatch (FR-I-13); receives per-stage snapshot mapping. |
| `src/datarefinery/pipeline/runner.py` | Per-stage snapshot map plumbed to viz layer (FR-I-13); `STAGE_NAMES` is the source for the `Literal` constraint. |
| `src/datarefinery/cache/sibling_stats.py` | `resolve_sibling_stats` calls `apply_variant(load_recipe(path), None)` before hashing (FR-I-1). |
| `src/datarefinery/cache/identity.py` | Canonical-hash pin fixtures updated under v2 (FR-I-14.3). |
| `src/datarefinery/plugins/image_classification/plugin.py` | OperationSpec table updates for `cast`, `categorical_encode`, `flatten`; `class_distribution_histogram.group_by` param; runtime-side `tag_fields` dict-form handling. |
| `src/datarefinery/scaffolder/init.py` | Scaffolder emits `stage: post_pipeline` explicitly (FR-I-13); recipes consume v2 shape. |
| `docs/guides/recipe-authoring.md` | Per the DOC rule: every story above lands its `recipe-authoring.md` section update. Pre-existing drift (Featurizations / Filters / Visualizations sections per the DOC table in the gap doc) closes alongside the first story that touches each section. |
| `docs/specs/features.md` | New FR rows per FR-I-* above where the capability is a recipe-author-visible surface. |
| `docs/specs/tech-spec.md` | Schema-version section updated to enumerate `{1, 2}` and the migration; assertion-kind enumeration updated; stage-aware viz dispatch noted in the Visualizations runner section. |
| `docs/specs/modelfoundry/dependency-spec.md` | Cross-repo coordination per [`project-essentials.md` § "Recipe / manifest / report shape changes need a cross-repo coordination check"](project-essentials.md): document the `class_balance` dict shape (FR-I-10) as the ModelFoundry-binding contract; document v1→v2 recipe-model migration explicitly. |

### Cache-identity impact

| Change | Canonical-bytes-perturbing? | Cache invalidation? |
|---|---|---|
| FR-I-1 (sibling resolver) | No | No — fixes a lookup; doesn't change cache keys. |
| FR-I-2 (`cast` Transformation) | Yes for any recipe declaring `op: cast_dtype` — the field value changes. | Yes (only recipes using `cast_dtype` today, which today fail at materialize so are not cached). |
| FR-I-3, FR-I-4 (new ops) | No — new ops don't perturb existing recipes' canonical bytes. | No. |
| FR-I-5 (`seed_derive_from: master`) | Yes for recipes adopting the new form; deterministic for recipes that keep explicit ints. | Yes only for recipes that switch (one-time, opt-in). |
| FR-I-6 (new assertion kinds) | No — new kinds don't perturb existing canonical bytes. | No. |
| FR-I-7 (`group_by` param) | No for recipes without the param; yes for adopters. | No / opt-in. |
| FR-I-8 (`replace_input_records`) | No for recipes without the field (default `False` matches today's behaviour); yes for adopters. | No / opt-in. |
| FR-I-9 (SampleData kind/splits) | No for recipes without the new fields. | No. |
| FR-I-10 (class_balance dict) | Yes for recipes adopting the dict shape. | No / opt-in. |
| FR-I-11 (tag-driven applies_to) | Yes for recipes using the new pattern. | No / opt-in. |
| FR-I-12 (tag_fields dict-rename) | Yes for recipes using the new shape. | No / opt-in. |
| FR-I-13 (stage-aware viz) | Yes if `VisualizationOp.stage` becomes a `Literal` — but only for recipes that declared an out-of-vocabulary stage string, which today silently runs at `post_pipeline` only. The default `post_pipeline` value is preserved. | Marginal; pinned-hash test catches. |
| **FR-I-14 (schema v2 cluster)** | **Yes — Filters reshape + Generation reshape + assertion naming pass all perturb canonical bytes for any recipe using those sections.** | **Yes — every existing cached instance becomes stale once v2 migration runs. Pre-production rules apply (per project-essentials): documented in release notes; users re-materialize.** |

The clustering of FR-I-14.1/2/3 into a single v2 bump is deliberate: it batches three cache-invalidating reshapes into one re-materialization event for users rather than three.

---

## Story sequence and version bumps

With the existing higher priority bundle 1 (sink) stories, these additional stories are bundled into another three release groups, totalling four bundles in Phase I. Within a bundle, work stories carry no version in their title; a dedicated **release-ceremony story** at the end of the bundle owns the version bump, the CHANGELOG entry, the `pyproject.toml` / `__init__.py` bump, and (where relevant) the canonical-hash pin update and release-notes blast-radius announcement. This keeps the release-bump commit clearly identifiable in the commit history rather than buried in a feature story's commit.

Ordering rationale: (a) doc-sanitize first so subsequent stories don't inherit leakage by citation; (b) cheap unblocks early (G19 single-line fix); (c) additive features in the middle; (d) the schema-v2 cluster last so its migration doesn't perturb prior stories' tests.

### Bundle 2 — quick patches (v0.17.1)

| # | Story ID | Title | Closes |
|---|---|---|---|
| 1 | I.h | Sanitize consumer-context leakage in dependency-gaps doc + preexisting story body | — |
| 2 | I.i | G19 — sibling-stats resolver strips variants | G19 |
| 3 | I.j | **Release v0.17.1** (Phase I bundle 2) | — |

### Bundle 3 — additive feature surface (v0.18.0)

| # | Story ID | Title | Closes |
|---|---|---|---|
| 4 | I.k | G2 — `cast` Transformation (rename + factory + `scale` param) | G2 |
| 5 | I.l | G3 — `categorical_encode` Featurization | G3 |
| 6 | I.m | G9 — `flatten` Featurization | G9 |
| 7 | I.n | G11 — `seed_derive_from: master` on Filters and Generation | G11 |
| 8 | I.o | G6 + G16b — per-split / per-class / structural assertion kinds | G6, G16b |
| 9 | I.p | G17 — `class_distribution_histogram.group_by` | G17 |
| 10 | I.q | G18 — Generation `replace_input_records` | G18 |
| 11 | I.r | G14 — SampleData `kind` + `splits` | G14 |
| 12 | I.s | G10 — `Splits.class_balance` dict shape (MF-binding hint) | G10 |
| 13 | I.t | G1 — tag-driven `Splits.applies_to` | G1 |
| 14 | I.u | G13 — `tag_fields` dict-rename form | G13 |
| 15 | I.v | G7 — stage-aware visualization dispatch (closes G5) | G7, G5 |
| 16 | I.w | **Release v0.18.0** (Phase I bundle 3) | — |

### Bundle 4 — schema v2 migration (v0.19.0)

| # | Story ID | Title | Closes |
|---|---|---|---|
| 17 | I.x.1 | G15 — Filters reshape `predicate:` → `op:` + `params:` (+ loader migration framework) | G15 |
| 18 | I.x.2 | G12 — Generation reshape (top-level `op:`, `splits:`, `matches_input` shorthand) | G12 |
| 19 | I.x.3 | G16a — assertion `kind` naming pass | G16a |
| 20 | I.y | **Release v0.19.0** (Phase I bundle 4, schema_version 1→2) | — |

### Renumber note

There was a preisting story (G7 placeholder, `[Planned]`) that was **renumbered and rewritten** in two steps:

- **New I.h** carries the doc-sanitize work above (Bundle 1).
- **New I.v** carries the G7 stage-aware viz dispatch work that was the preexisting story body (Bundle 3).

Per the [Inserting a new story](go.md#inserting-a-new-story) renumber rule, the original I.h is renumberable because it is `[Planned]` and no references have accreted: no commits name it, no docs outside `stories.md` and `dependency-gaps-v0.16.0.md` cite it. Verified by `git log --all --grep='I\.d'` (returns I.b's tests-not-I.h only) and `grep -RFn 'I.h' docs/ CHANGELOG.md` (returns this plan doc and `dependency-gaps-v0.16.0.md` G5 entry, both of which are updated in the I.h-sanitize story).

### Bump rationale

- **v0.16.3** is a patch bump — Bundle 1 fixes a broken capability (G19's sibling-stats resolver lookup) and sanitizes documentation. No new capability.
- **v0.17.0** is a minor bump — Bundle 2 adds twelve new recipe-author-visible capabilities (new ops, new assertion kinds, new schema field shapes, stage-aware viz dispatch). None of them perturb canonical bytes for existing recipes (each is opt-in or backward-compatible). Bundle 2 ships *one* minor bump rather than twelve because the capabilities are interrelated and don't have user-visible reasons to release individually.
- **v0.18.0** is a minor bump (still pre-1.0) — Bundle 3 ships the coordinated schema v1→v2 migration. Per [`project-essentials.md` § "Cache identity is the reproducibility contract"](project-essentials.md), pre-production cache invalidation is acceptable but is documented in release notes and noted as a one-time re-materialization cost.

---

## Out of Scope

Items considered for this phase and explicitly deferred. Each below is a candidate for a follow-up phase or for the `Future` section in `stories.md`.

1. **Sibling tight coupling (FR-ARCH-1).** Folding the sibling recipe's `recipe_hash` into the consumer recipe's cache identity so upstream re-materialization auto-invalidates downstream. Documented in [`project-essentials.md` § "Sibling-instance dependencies are loose-coupled in v1"](project-essentials.md) as Future. Phase I closes G19 (the lookup-mechanics bug) but does not adopt tight coupling.
2. **`stats_from_instance.variant: <name>` selector.** Letting a consumer recipe pin a specific sibling-variant's fitted statistics. Added to `stories.md § Future` as part of this plan (not previously tracked there).
3. **Implement vs. remove `to_grayscale`.** FR-I-2 removes the OperationSpec entry as part of the `cast_dtype` → `cast` rename to keep the surface honest. A real `to_grayscale` op (with the documented `method: average | luminance | …` parameter set) is left for a future image-plugin phase.
4. **Plugin-pluggable reserved-set hook for validator check 23.** I.c noted this for tabular/text plugins; not surfaced by the current consumer surface (image_classification only).
5. **Per-stage report subsections.** FR-I-13 plumbs per-stage snapshots through the visualization layer; a richer report structure (one `report.md` heading per snapshotted stage) is deferred.
6. **Generic record-tagging primitive.** FR-FILTER-1's bespoke `label` / `exclude_already_labeled` params remain bespoke; a shared mechanism multiple filter ops can use is documented in Future.
7. **Default-change discipline tooling.** Expanded canonical-hash pinning across multiple fixture recipes covering more pydantic field defaults. Listed in `stories.md` Future as production-readiness work.
8. **`init` scaffolder grand sweep for v2.** The bundled scaffolder ([`scaffolder/init.py`](../../src/datarefinery/scaffolder/init.py)) must emit valid v2-shape recipes after Bundle 3 lands — that minimal correctness update is **in scope** for the relevant Bundle 3 stories (top-level `op:` for Filters, `splits:` for Generation, v2 assertion naming). A *grand sweep* that actively showcases new v2 affordances in the scaffolded recipe (`seed_derive_from: master` on every seeded op, tag-driven `applies_to` example, `replace_input_records: true` demo, etc.) is **out of scope** — that is UX polish, not correctness, and is best done as a follow-up phase that designs the scaffolded recipe as a teaching artifact end-to-end.
9. **`distributional` assertion kind beyond placeholder.** The existing v1 placeholder ships as v2 `distributional` (renamed under the FR-I-14.3 naming pass) but stays a placeholder; a real distributional evaluator is deferred to a future contracts-evaluator phase.
10. **Splits-stage class_balance runtime behaviour.** Per FR-I-10 (MF-side decision), DataRefinery does not resample or emit weights. A future-phase decision could revisit this if downstream tools other than ModelFoundry want a self-contained materialized instance.

---

## Future-section addition

As part of the I.h sanitize story, the following items are added to `stories.md § Future`:

- **`stats_from_instance.variant: <name>` selector** — sibling-instance fitted-stat resolution against a specific variant overlay (Out-of-Scope item 2).
- **Real `distributional` assertion kind** — replace the v1 placeholder with a real evaluator (KS test, JS divergence, etc.) (Out-of-Scope item 9).
- **Plugin-pluggable validator-check reserved-set hook** — for tabular/text loaders' stamped fields (Out-of-Scope item 4; carried forward from Story I.c's prevention notes).
- **`to_grayscale` Transformation op** — implement with the documented `method` parameter set, not just declare in OperationSpec (Out-of-Scope item 3).
- **Scaffolder v2 grand sweep** — adopt every new v2 affordance in the bundled scaffolder (Out-of-Scope item 8).
- **DR-side `class_balance` resampling** — physically resample / weight at the Splits stage rather than passing the strategy through as an MF-binding hint (Out-of-Scope item 10).

The existing `Future` section already contains entries for sibling tight coupling, generic record-tagging primitive, and default-change discipline tooling (Out-of-Scope items 1, 6, 7) — those do not need duplicating.

---

## Acceptance criteria

Phase I (expanded) is complete when:

1. All seventeen new stories above are `[Done]`.
2. Each story closed its corresponding G entry in [`dependency-gaps-v0.16.0.md`](dependency-gaps-v0.16.0.md) priority summary table.
3. The recipe-side workarounds table at the bottom of the gap doc is empty of unresolved rows (every G has either a "closed in vX.Y.Z" disposition or is moved to `Future`).
4. `recipe-authoring.md` has no remaining DOC-rule gaps: every implemented op surface has a section with a worked YAML example and a full param table.
5. `dependency-spec.md` is updated for cross-repo contract surface changes (recipe model v2; manifest fields for `class_balance` hint; report subsections unchanged unless FR-I-13's per-stage option is opted in by a follow-up).
6. The v1→v2 migration round-trip test pins canonical bytes: an authored v1 recipe migrated to v2 produces canonical bytes byte-identical to the same recipe authored directly in v2 shape.
7. The integration test suite passes under v0.18.0 with no behavioural regressions other than the documented v2 cache invalidation.
