# DataRefinery 0.16.0 — dependency gaps from a consumer repo

This document is a consumer-side punch list of runtime gaps in
**datarefinery 0.16.0** surfaced while authoring `recipes/cifar10-base.yaml`
in Story B.b (and anticipated to recur in Story B.c's `cifar10c-eval.yaml`).
It is written for the DataRefinery maintainer to drive upstream fixes.

**Pin.** All findings are against installed package version `0.16.0`.
Verify with `datarefinery --version`. As of this writing, the locally
installed source tree is:

```
.pyve/envs/my-repo-name/lib/python3.12/site-packages/datarefinery/
```

Path references below use the `datarefinery/...` package-internal layout; in
the DR source repo, these map to `src/datarefinery/...`.

**Scope of "gap".** Every item below is a **runtime implementation gap, not
a recipe-schema gap.** The recipe schema (`schema_version: 1`) — defined by
the pydantic models in `datarefinery/recipe/models.py` — already declares
every section and field referenced. Each gap is one of:

| Category | What it means |
|---|---|
| **Plugin op registration** | Op declared in plugin's `_supported_operations()` (validator passes) but missing from the corresponding runtime factory table (`_TRANSFORMATION_OPS`, `_FEATURIZATION_OPS`, …) → NotImplementedError at materialize time. |
| **Validator semantics** | A schema-level `str` / `dict` field is constrained by a validator check to a narrower vocabulary than the schema permits. |
| **Contracts evaluator** | New `assertion.kind` values not yet implemented in `pipeline/contracts.py`. Schema accepts them (assertion is `dict[str, Any]`); evaluator rejects unknown kinds. |
| **Pipeline runner / stage hookup** | Schema field present but only one stage value is exercised, or runtime stages don't expose intermediate state to consumers. |
| **Plugin runtime interaction** | Multiple plugin features compose incorrectly at runtime (e.g. uint8/float dtype assumption between Transformations and Augmentations). |

None of these require a `schema_version` bump.

---

## Priority summary

| ID | Title | Severity for consumer repo | Category |
|---|---|---|---|
| G1 | `Splits.applies_to` doesn't accept `sample_per_class_tags` labels | **Blocking (workaround used)** | Validator semantics |
| G2 | `cast` Transformation: name + `scale` param + runtime factory missing | Blocking (workaround used) | Plugin op registration |
| G3 | `categorical_encode` Featurization missing from plugin | Blocking for Phase D Module 3 (`mlp_flat`); deferred | Plugin op registration |
| G4 | `label_from_path` collides with `image_flat` + `label_from` loader | **Closed in v0.16.2** (Story I.c) | Validator semantics |
| G5 | `augmented_sample_grid` viz raises on post-normalize float images | **Subsumed by G7** (not a defect; surfaces missing stage-aware viz dispatch) | Plugin runtime interaction |
| G6 | `OutputExpectations` only supports flat-record assertion kinds | Friction (out-of-band verification used) | Contracts evaluator |
| G7 | All reporting visualizations run at `post_pipeline` only | Friction (pre/post-normalize merged) | Pipeline runner |
| G8 | `tensor`-typed fields can't satisfy `dtype` / `range` assertions | **Closed in v0.16.1** (Story I.b) | Contracts evaluator |
| G9 | `flatten` Featurization missing from plugin | **Blocking for Phase D Module 3 (`mlp_flat`); deferred** | Plugin op registration |
| G10 | `Splits.class_balance` is metadata-only; dict shape + runtime resampling unsupported | **Blocking for Phase D Module 9 `imbalanced_oversample` / `imbalanced_classweight` variants** | Schema + pipeline runner |
| G11 | `seed_derive_from: master` not recognized on Filters / Generation | Friction (explicit ints used in spec workaround) | Schema |
| G12 | `Generation` schema shape divergence: top-level `op:`, `splits:` vs `applies_at:`, `output_schema: matches_input` shorthand | **Blocking for Recipe B (`cifar10c_eval.yaml`)** | Schema |
| G13 | `tag_fields` rename mapping for `imagecorruptions_apply` (`list[str]` vs `dict[str, str]`) | Friction (canonical names used) | Schema (param shape) |
| G14 | `SampleData.selector` lacks `kind` and `splits` | Friction (`SampleData` section dropped) | Schema |
| G15 | `Filters` schema requires nested `predicate:`; spec authors expect flat `op:` / `params:` | **Blocking (recipe doesn't parse)** | Schema (cross-section consistency) |
| G16 | Assertion `kind` vocabulary missing: `value_in_set`, `shape_equals`, `per_class_count_equals`, plus `*_equals` / `*_count` renames | **Blocking (every assertion in both recipes fails validate or materialize)** | Contracts evaluator |
| G17 | `class_distribution_histogram` lacks `group_by` param | Friction (viz dropped) | Plugin op param schema |
| G18 | `Generation` stage extends each target split rather than replacing source records | **Blocking for Recipe B (`cifar10c_eval.yaml`)** — phase plan's 12,000-record test split becomes 13,000 | Pipeline runner |
| G19 | `resolve_sibling_stats` doesn't strip variants before hashing the sibling recipe | **Blocking whenever the sibling declares variants** — `stats_from_instance` lookups fail with `SiblingInstanceNotFoundError` | Pipeline runner / sibling resolver |
| **DOC** | recipe-authoring.md has not kept up with the implemented op surface | **Blocking the principle "no implementation without documentation"** | Documentation discipline |

**Severity guide for consumer repo:**
- **Blocking** = the project's Recipe A or Recipe B can't be authored as the phase plan specs them; a deviation is in place and documented.
- **Friction** = a phase-plan feature was dropped or weakened; the Task 2 deliverable still ships, but later phases will hit the same limit.

---

## DOC — Documentation discipline (foundational rule)

**No implementation without documentation.** A capability that exists in code but is not described in [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) (or the equivalent user-facing reference for its surface) is **not delivered**. A recipe author has no canonical place to learn the op exists, what to call it, or what params it accepts — so the "feature" is a private affordance of the codebase, not a contract DataRefinery offers its consumers. Closing each G item in this doc therefore requires:

1. **Code change** (factory registration, OperationSpec entry, runtime branch).
2. **Test pin** (the test that previously asserted `NotImplementedError` flips, or a new behavior test lands).
3. **`recipe-authoring.md` entry** under the relevant § (Transformations / Featurizations / Filters / Generation / Visualizations / OutputExpectations / Splits sub-partitioning), with a worked YAML example and the full param table.
4. **`features.md` cross-reference** if the capability touches an FR.
5. **`docs/specs/modelfoundry/dependency-spec.md` update** if the change touches a cross-repo contract surface (recipe model, manifest, report) — per `project-essentials.md` § "Recipe / manifest / report shape changes need a cross-repo coordination check."

**Documentation drift observed in v0.16.0.** Quick scan of `recipe-authoring.md` against the implemented surface:

| Section | Documented (with example) | Implemented but undocumented |
|---|---|---|
| `Transformations` | `normalize` only | `resize`, `mean_subtract` (`cast_dtype` / `to_grayscale` are also declared-but-unimplemented — see G2) |
| `Augmentations` | All four ops ✓ (clean) | — |
| `Featurizations` | `label_from_path` only | `image_size_stats` |
| `Filters` | `filter_by_label`, `random_sample` only | `sample_per_class`, `sample_per_class_fractional`, `drop_by_label` (all shipped in v0.10.0–v0.12.0) |
| `Generation` | `output_schema` shape generally, no specific op | `imagecorruptions_apply` and its param surface (`corruption_types`, `severities`, `preserve_original`, `tag_fields`) |
| `Visualizations` | `class_distribution_histogram`, `sample_grid` | `mean_image_per_class`, `pixel_distribution`, `augmented_sample_grid`, `corruption_severity_grid`, `severity_ladder` (FR-VIZ-1..4, all shipped in Stories H.t–H.w) |
| `InputContracts` / `OutputExpectations` | All five v1 kinds documented ✓ (matches reality) | — |
| `Splits.applies_to` | Partition-based form documented | Tag-driven form (see G1) is not even mentioned as a planned extension |

**How to apply:** before merging any of the G fixes below, the implementing story must include the corresponding `recipe-authoring.md` section. A pre-existing documentation gap for an already-shipped feature (the table above) is **its own work item** — close it before, or alongside, the next op-registration story in the same § so the canonical user-facing reference is rebuilt as you go rather than left to a one-shot sweep.

The recipe-side workarounds table at the bottom of this doc lists which G items intersect which already-shipped capabilities; use it to scope the alongside-this-G doc additions.

---

## G1 — `Splits.applies_to` doesn't accept `sample_per_class_tags` labels

**Severity:** Blocking for consumer repo (Recipe A & B both rely on disjoint-pool
sampling per the phase plan).

**Category:** Validator semantics.

**Schema view.** `SplitsSection.applies_to: str | None`
([`datarefinery/recipe/models.py:258`](file)) — schema permits any string.

**Current runtime behavior.** Validator check 20
(`partitions_consistent`, [`datarefinery/recipe/validator.py:779`](file))
constrains `applies_to` to reference a name declared in
`InputSource.partition` on some source. If a recipe wires
`applies_to: train_pool` where `train_pool` is only a `sample_per_class`
`label` tag (i.e. a value of `sample_per_class_tags` on records, set by
the FR-FILTER-1 non-destructive tagging mode), the validator rejects with:

```
Splits.applies_to='train_pool' not present in source partitions [...]
```

**Why this matters for consumer repo.** The phase plan
([`docs/specs/phase-b-task2-data-preparation-plan.md` § 3](../phase-b-task2-data-preparation-plan.md))
specifies a disjoint-pool design:

1. `sample_per_class n=200, label=train_pool` (tags 2,000 records).
2. `sample_per_class n=100, label=test_pool,
   exclude_already_labeled=[train_pool]` (tags 1,000 disjoint records).
3. `Splits.applies_to: train_pool` (sub-partition only the train-pool
   records 85/15 → train + val; test_pool flows through as `test`).

The disjoint-pool guarantee at the filter layer is the key property:
Recipe B (corruption eval) replays steps 1–2 bit-identically and then
`drop_by_label: [train_pool]` to retain only the same 1,000 test records.
Bit-identity is provable record-by-record because the test_pool tagging
is deterministic in the filter, not stochastic in the splitter.

**Workaround in 0.16.0 (Story B.b).** Collapse to a single destructive
`sample_per_class n=300` (3,000 records) + three-way stratified Splits
`{train: 17/30, val: 3/30, test: 10/30}, stratify_by: label, seed: 11`.
Outcome counts are exact (1700/300/1000, 170/30/100/class), but test-split
membership is determined by the stratified-sampling RNG, not by the filter.
Recipe B inherits the same membership only by replaying the identical
filter + Splits config; if Splits-side semantics drift, bit-identity drifts.

**Suggested fix direction.**

1. **Lowest blast radius:** broaden check 20 to also accept `applies_to`
   values that match any `FilterOp.predicate.params.label` where the
   predicate op is one of `{sample_per_class, sample_per_class_fractional}`.
   At pipeline-runner time, `Splits` would partition only records whose
   `sample_per_class_tags` contains the named label and pass through every
   other record verbatim under its existing tag-driven partition.
2. **Pipeline-runner change:** `pipeline/stages/splits.py` needs to learn
   the "tag → partition" pass-through. When `applies_to` names a tag, the
   stage produces sub-splits per `ratios` for the tagged records, and
   emits the untagged-or-other-tagged records as `<other_tag>` splits.
3. **Doc update:** [`recipe-authoring.md` § Splits / sub-partitioning](../recipe-authoring.md)
   needs a new "Sub-partitioning via tag" subsection paralleling the
   existing `InputSource.partition` one.

**Tests that would prove the fix.**

- A recipe with two `sample_per_class` filters tagging `train_pool` /
  `test_pool` + `Splits.applies_to: train_pool` validates clean.
- Materializing it produces splits `{train, val, test}` with counts
  matching the tag populations (within stratification rounding).
- Re-running with the recipe edited to swap the order of the two filters
  produces the **same** test split (proving tag-driven membership is
  filter-determined, not splitter-determined).

---

## G2 — `cast` Transformation: declared but unimplemented, plus naming and `scale` param

**Severity:** Blocking for consumer repo (the phase plan calls for uint8 → float32
cast before normalize).

**Category:** Plugin op registration.

**Schema view.** `TransformationOp` ([`datarefinery/recipe/models.py:274`](file))
permits any string for `op`. Validator check 18 (`plugin_operation_params_validate`)
delegates to the plugin's `OperationSpec` table.

**Current runtime behavior.** The image_classification plugin's
`_supported_operations()` ([`datarefinery/plugins/image_classification/plugin.py:219`](file))
declares:

```python
"cast_dtype": OperationSpec(
    parameters={"dtype": ParameterSpec(type="str", required=True)},
    applicable_sections=frozenset({"Transformations"}),
),
```

So validator check 18 passes a recipe that uses `op: cast_dtype`. But
`_TRANSFORMATION_OPS` ([`plugin.py:92`](file)) only registers `resize`,
`normalize`, and `mean_subtract` — no `cast_dtype`. At materialize time:

```
NotImplementedError: image_classification operation factory not yet
implemented (section='Transformations', op='cast_dtype')
```

**Why this matters for consumer repo.** The phase plan specs `cast: uint8→float32
(scale 1/255)` before `normalize` to (a) match the standard PyTorch
training-time tensor representation and (b) cleanly separate dtype/scale
from statistical normalization. Without `cast_dtype`, `NormalizeOp`
auto-promotes uint8 → float64 (its internal `np.asarray(..., dtype=float64)`
call) and the cached image dtype lands as float64 — twice the per-pixel
storage cost and a mismatch with what downstream training code expects.

**Workaround in 0.16.0 (Story B.b).** Omit the Transformation entirely;
let `NormalizeOp` do the implicit promotion. `Output.record_schema` declares
`image.dtype: float64` to match reality (not the spec's `float32`).

**Suggested fix direction.**

Add a `CastDtypeOp` class to
[`datarefinery/plugins/image_classification/operations/transformations.py`](file)
and register it in `_TRANSFORMATION_OPS`. Reference shape — modeled on
`MeanSubtractOp` (no fit phase, deterministic per-record apply):

```python
class CastDtypeOp:
    fit_on_train: bool = False

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues | None,
        *,
        label_field: str | None,
    ) -> list[Record]:
        del fitted, label_field
        target_dtype = np.dtype(params["dtype"])
        scale = params.get("scale", 1.0)  # optional; default 1.0
        return [
            _replace_image(
                r,
                (np.asarray(r["image"]).astype(target_dtype) * scale)
                if scale != 1.0
                else np.asarray(r["image"]).astype(target_dtype),
            )
            for r in records
        ]
```

Add `scale: float, default=1.0` to the `OperationSpec.parameters` so the
common `uint8 → float32 / 255.0` pattern is one op rather than a `cast` +
`mean_subtract` combo.

**Naming decision: rename to `cast`.** The consumer recipe (and the original
phase plan) writes `op: cast`, not `op: cast_dtype`. Three reasons to make
the canonical name `cast`:

1. **Symmetry** with `mean_subtract` and `normalize` — single-verb op names
   are the established pattern in the Transformations section.
2. **`scale` is part of the op**, not just dtype conversion. The full
   semantic is "cast dtype, optionally with a multiplicative scale," and
   `cast` captures that better than the dtype-only `cast_dtype`.
3. **It's what consumers reach for** — `op: cast` is what the consumer spec
   author wrote without consulting any documentation, which is the natural
   pull. Aligning the canonical name with that natural pull lowers the
   author-friction cost of using DataRefinery.

The implementing story must:

- Rename `"cast_dtype"` → `"cast"` in `_supported_operations()` and (when
  added) in `_TRANSFORMATION_OPS`.
- Update the pinned-`NotImplementedError` test in
  [`tests/plugin_contract/test_image_classification.py`](file) — both the
  `EXPECTED_OPERATIONS` set entry and the assertion that calls
  `operation_factory("Transformations", "cast_dtype")`.
- Decide what to do about `to_grayscale` in the same pass (today's other
  declared-but-unimplemented Transformation): either implement it too, or
  remove the OperationSpec entry and the corresponding test pin until a
  story actually adopts it. Carrying schema-level declarations of ops the
  runtime refuses is the original "declared but not implemented" pattern
  that produced G2 — don't replicate it for a sibling op.
- Add a worked YAML example to `recipe-authoring.md` § `Transformations`
  showing `op: cast` with both `dtype` and `scale`, plus the canonical
  `uint8 → float32 / 255.0` pre-normalize use case (per DOC).
- Update the cross-repo contract surface in
  [`docs/specs/modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md)
  if the op affects manifest fields ModelFoundry binds against.

Also: the existing `mean_subtract` and `resize` Transformations should be
backfilled into `recipe-authoring.md § Transformations` at the same time
(they currently aren't documented user-facing; only `normalize` is). See
the DOC drift table.

**Tests that would prove the fix.**

- Recipe with `cast dtype=float32 scale=0.00392156862745098`
  followed by `normalize fit_source=train` materializes successfully.
- Cached image dtype is `float32` (not `float64`).
- Without the `scale` param, only dtype changes (values are reinterpreted,
  not rescaled).
- `op: cast_dtype` is rejected by validator check 18 with the suggestion
  "did you mean `cast`?" (i.e., the old name is removed cleanly, not
  silently aliased — aliasing two names for the same op multiplies the
  surface authors have to learn and check).

---

## G3 — `categorical_encode` Featurization missing from plugin

**Severity:** Blocking for Phase D Module 3 (`mlp_flat` variant); deferred
in Phase B (Task 2 doesn't need `label_id`).

**Category:** Plugin op registration.

**Schema view.** `FeaturizationOp.op: str` ([`recipe/models.py:310`](file))
permits any string. Validator check 18 delegates to the plugin's
`OperationSpec` table.

**Current runtime behavior.** The image_classification plugin's
`_FEATURIZATION_OPS` ([`plugin.py:98`](file)) registers only:

```python
_FEATURIZATION_OPS: dict[str, Operation] = {
    "label_from_path": LabelFromPathOp(),
    "image_size_stats": ImageSizeStatsOp(),
}
```

`categorical_encode` is also missing from `_supported_operations()`, so
validator check 18 also rejects it.

**Why this matters for consumer repo.** The phase plan
([§ 3](../phase-b-task2-data-preparation-plan.md) feat. row 6) calls for
`categorical_encode` to derive `label_id: int32` from `label: str` using
alphabetical CIFAR-10 ordering (0=airplane, 1=automobile, …, 9=truck).
Downstream model-training code (ModelFoundry, PyTorch DataLoaders) wants
integer label ids; deriving them at materialize time is cleaner than
re-doing the same mapping in every notebook that reads the JSONL.

**Workaround in 0.16.0 (Story B.b).** Omit the Featurization. Downstream
consumers map `label` → `label_id` at JSONL-read time via a hard-coded
class list. Acceptable for Phase B; problematic for Phase D Module 3
(`mlp_flat` variant) where the variant overlay would otherwise be the
clean place to express the encoding.

**Suggested fix direction.**

Add a `CategoricalEncodeOp` class to a new
[`datarefinery/plugins/image_classification/operations/featurizations.py`](file)
(or extend the existing file). Schema:

```python
"categorical_encode": OperationSpec(
    parameters={
        # If `vocabulary` is given, the encoding is fixed; otherwise it's
        # fit on the training split (fit-on-train discipline).
        "vocabulary": ParameterSpec(type="list[str]", required=False),
        "ordering": ParameterSpec(
            type="str", required=False, default="alphabetical"
        ),  # "alphabetical" | "first_seen"
        "output_dtype": ParameterSpec(
            type="str", required=False, default="int32"
        ),
    },
    fit_on_train=True,  # when vocabulary is unset
    applicable_sections=frozenset({"Featurizations"}),
),
```

Runtime: if `vocabulary` is set, `apply` walks records and writes
`output_field` per the mapping; if `vocabulary` is unset, `fit` derives
the vocabulary from the train split (`sorted(set(labels))` for
alphabetical, `list(dict.fromkeys(labels))` for first_seen) and persists
it to `fitted_statistics/<op_name>/vocabulary.parquet`; `apply` reads
the persisted vocabulary and writes per-record.

**Tests that would prove the fix.**

- Recipe with `inputs: [label]`, `output_field: label_id`,
  `op: categorical_encode`, `params: { vocabulary: [airplane,
  automobile, bird, cat, deer, dog, frog, horse, ship, truck] }`
  materializes; every record has `label_id ∈ {0..9}` matching the
  declared vocabulary.
- Without `vocabulary`, the same recipe fits the vocabulary on train,
  persists it to `fitted_statistics/`, and Recipe B can import it via
  `stats_from_instance` for consistent inference-time encoding.

---

## G4 — `label_from_path` collides with `image_flat` + `label_from` loader

**Status (Story I.c, v0.16.2):** **Closed.** Added validator check 23 (`featurization_output_field_loader_collision`) that detects any Featurization whose `output_field` collides with a loader-stamped field (`record_id`, `image`, `path`; plus `label` when Labels are direct with a label source; plus `partition` when an InputSource declares one). The check shifts the failure from materialize time (the runtime collision detector at `pipeline/stages/featurizations.py:110-115`) to validate time. The runtime check remains as second-line defense.

**Severity:** Friction (workaround in place; Recipe A omits the Featurization entirely) → **Closed v0.16.2**.

**Category:** Validator semantics (shift-left of a runtime check that already existed).

**Symptom.** When `Input.sources[*]` is `image_flat` with `label_from`
(sidecar manifest) AND `Labels.source.kind` is `direct`, the loader
attaches `label` to every record at load time. If the recipe ALSO declares
a Featurization `op: label_from_path, output_field: label`, materialization
fails at the Featurizations stage with:

```
Featurizations['derive_label_from_path'].output_field 'label' collides
with an existing field in split 'train'
```

**Why this is a gap.** Both patterns are documented in
[`recipe-authoring.md` § Labels](../recipe-authoring.md): `direct` for
image_flat+label_from OR a Featurization for derived. The recipe-authoring
guide doesn't currently call out that you must choose one or the other; a
recipe author who copies the reference recipe's Featurizations block
verbatim onto an image_flat + label_from input runs into this collision.

**Suggested fix direction.**

Two options, not mutually exclusive:

1. **Validator check (preferred).** Add a check rejecting recipes where
   the loader will attach a field AND a Featurization declares the same
   `output_field`. The check needs to walk
   `Input.sources[*]` and figure out which fields the loader will stamp
   (path, label-when-image_flat+label_from-direct, partition-when-declared,
   record_id). Cross-reference Featurization `output_field` values.
2. **Doc update.** Make `recipe-authoring.md` § Labels and § Featurizations
   explicit about the choice. The current text says "Direct labels are
   populated by the input loader" and "Derived labels are produced by a
   Featurization" but doesn't say "if you declare both, the Featurization
   will fail at runtime."

**Tests that would prove the fix.**

- Validator rejects an image_flat + label_from + Labels.direct recipe
  that also declares `label_from_path` Featurization with
  `output_field: label`, naming the specific collision.
- Validator still accepts the same recipe if the Featurization writes to
  a different `output_field` (e.g. `output_field: label_from_filename`
  for cross-checking).

---

## G5 — `augmented_sample_grid` viz raises on post-normalize float images

**Status (Story I.a investigation, May 2026):** **Reclassified — not a defect.**
G5 is the surface symptom of G7 (no stage-aware visualization dispatch). The
proper fix is G7; G5 has no independent fix path.

**Severity:** Subsumed by G7. Friction (Recipe A drops the viz; augmentations
remain declared as lazy policy and work fine at training time).

**Category:** Plugin runtime interaction (surface) / Pipeline runner (root cause).

**Symptom.** Reporting-mode `augmented_sample_grid` viz raises at
materialize time:

```
Visualizations['augmentation_preview'] (op='augmented_sample_grid',
mode='reporting') failed: TypeError: Cannot handle this data type:
(1, 1, 3), <f8
```

**Why it happens.** The pipeline runs Transformations (incl.
`normalize fit_source=train`) BEFORE Visualizations. By the time
`augmented_sample_grid` ([`visualizations/augmented_sample_grid.py`](file))
sees the records, `image` is float64 in z-score range (~[-2, 2]). The
PIL-backed augmentation realizers
([`augmentations/horizontal_flip.py:52`](file),
[`augmentations/color_jitter.py:70`](file), etc.) call
`Image.fromarray(img_arr)` which only accepts uint8. The `_tile` function
([`visualizations/augmented_sample_grid.py:138`](file)) tries to clip-cast
to uint8 AFTER the realizer runs, but the realizer itself fails first.

**Investigation finding (Story I.a).** Three candidate "minimal fixes"
were considered:

1. **Convert TypeError → actionable RecipeError at the viz layer.**
   Error-message quality only; the recipe still cannot use the viz
   post-normalize. Pure polish; rejected as not actually fixing anything.
2. **Make realizers float-tolerant (e.g., `np.flip` for horizontal_flip;
   clip-cast inside color_jitter).** Suppresses the crash, but the viz's
   `_tile` then clip-casts z-score values ~[-2, 2] to uint8 [0, 255],
   producing mostly-black tiles. Silently wrong is worse than crashing;
   rejected.
3. **Stage-aware viz dispatch (= G7).** The viz runs at `stage:
   pre_transformations`, reads uint8 records before `normalize` ran, and
   the augmentation preview is correct end-to-end. The only honest fix.

Conclusion: G5's `TypeError` is the wrong error message for a correct
condition — `augmented_sample_grid` is semantically defined on pixel
arrays, and z-score values aren't pixels. The viz crashes because it has
no architectural option to observe the pre-normalize representation.
That architectural option is G7. **There is no G5-specific code change
that makes the viz produce a correct PNG.**

**Why this matters for consumer repo.** The phase plan's
`augmentation_preview` viz is intended as a learner-facing "what does the
augmentation actually do?" thumbnail in `report/visualizations/`. Without
G7, the report shows the pre-augmentation sample_grid only.

**Fix path.** Implement G7. When G7 lands, this entry can be closed in
the same release.

**Tests that would prove the fix.** See G7. There is no G5-only test
that proves the fix because G5 has no independent fix.

---

## G6 — `OutputExpectations` only supports flat-record assertion kinds

**Severity:** Friction (Recipe A drops per-split / per-class expectations
and verifies out-of-band via JSONL inspection).

**Category:** Contracts evaluator.

**Schema view.** `Expectation.assertion: dict[str, Any]`
([`recipe/models.py:127`](file)) — schema accepts any kind.

**Current runtime behavior.** `pipeline/contracts.py`
([`pipeline/contracts.py:241`](file)) dispatches on `assertion["kind"]`
and implements only:

| `kind` | What it asserts |
|---|---|
| `record_count` | Flat record-count bounds on the entire dataset |
| `required_field` | Field present + non-None in every record |
| `dtype` | Field values are instances of the Python type matching the tag |
| `range` | Field values are in `[min, max]` (scalar comparison) |
| `distributional` | Placeholder; always passes in v1 with a "deferred" note |

Anything else → `unknown assertion kind` failure.

Additionally:
- `evaluate_output_expectations` operates on a flat record iterable; the
  `per-split` dimension is not exposed
  ([`contracts.py:325`](file) comment: *"per-split expectations are not
  yet expressible (deferred to a post-v1 expectation extension)"*).
- `_eval_dtype` uses `isinstance(v, accepted)` where `accepted` is a
  Python type tuple — numpy ndarrays don't satisfy `isinstance(arr, int)`,
  so `dtype: uint8` on the `image` field always fails. See G8.

**Why this matters for consumer repo.** The phase plan calls for:

- Per-split record-count expectations: `train=1700, val=300, test=1000`.
- Per-class warning-severity expectations: 170/30/100 per class.
- Tensor value-range expectation post-normalize on `image`.

None of these are expressible in 0.16.0. Recipe A asserts the flat total
(record_count=3000) and falls back to reading `manifest.json` out-of-band
for per-split verification; per-class verification reads JSONL.

**Suggested fix direction.**

Add three new evaluator kinds to `pipeline/contracts.py`:

1. **`split_record_counts`** — `{kind: split_record_counts, counts: {train:
   1700, val: 300, test: 1000}}`. Evaluator receives per-split records
   (requires changing `evaluate_output_expectations` to accept
   `Mapping[str, list[Record]]` instead of a flat iterable).
2. **`per_class_count`** — `{kind: per_class_count, field: label,
   per_class: 170}` or `{counts: {airplane: 170, …}}`. Same per-split
   plumbing.
3. **`tensor_range`** — `{kind: tensor_range, field: image, min: -3.5,
   max: 3.5}`. Numpy-aware version of `range`; reduces over the array.

The signature change for `evaluate_output_expectations` is the
load-bearing part — `evaluate_input_contracts` can keep the flat form
(InputContracts run pre-splits).

Cross-link: documenting per-split / per-class evaluator semantics also
nudges `recipe-authoring.md` § OutputExpectations to grow a "cross-split
assertions" subsection.

**Tests that would prove the fix.**

- Recipe with `OutputExpectations` declaring per-split counts and
  per-class counts (warning severity) materializes; expectations pass.
- Mutating a Splits ratio causes per-split expectations to fail with a
  precise diff message ("split 'val' expected 300, got 350").

---

## G7 — All reporting visualizations run at `post_pipeline` only

**Severity:** Friction (Recipe A collapses pre/post-normalize sample_grid
to one op).

**Category:** Pipeline runner.

**Schema view.** `VisualizationOp.stage: str`
([`recipe/models.py:320`](file)) — schema permits any string.

**Current runtime behavior.** The visualization stage runs once at
`apply_reporting_visualizations`
([`pipeline/stages/visualizations.py:97`](file)) with the final post-
pipeline splits. The `stage` field is read but the runtime doesn't
dispatch viz ops to intermediate stages. The bundled scaffolder writes
`stage: post_pipeline` ([`datarefinery/scaffolder/init.py:193`](file)).

**Why this matters for consumer repo.** The phase plan distinguishes
`sample_grid_pre_normalize` from `sample_grid_post_normalize` — the
former is the learner-facing "what does the raw data look like?" view
(uint8, recognizable images), the latter is the "what does the model
actually see?" view (z-score-normalized). Both are pedagogically
valuable; the post-pipeline-only runtime collapses them.

This is also the underlying machinery G5 needs: an augmentation preview
that shows augmented variants of the **pre-normalize** representation.

**Suggested fix direction.**

Plumb intermediate-stage splits through to the viz layer. Two design
sketches:

1. **Stage snapshots.** Each pipeline stage that materially changes
   records snapshots a reference to its outputs. `apply_reporting_visualizations`
   receives a `Mapping[str, Mapping[str, list[Record]]]` (outer key: stage
   name, inner key: split name). Each `VisualizationOp.stage` selects
   which snapshot to render against.
2. **Per-stage viz dispatch.** Each pipeline stage that has visualizations
   targeting it runs them inline before promoting. Less memory-heavy
   (no snapshots) but more invasive (every stage needs to know about
   viz dispatch).

The first design is more localized. `STAGE_NAMES` in
[`pipeline/runner.py:96`](file) already enumerates the valid stages;
constrain `VisualizationOp.stage` to that vocabulary (model-level
`Literal[...]`) and document the mapping.

**Tests that would prove the fix.**

- Recipe with two `sample_grid` viz ops, `stage: pre_transformations` and
  `stage: post_transformations`, materializes; both PNGs land in
  `report/visualizations/`; the pre-transformations PNG is visually
  recognizable as CIFAR-10, the post-transformations PNG shows the
  normalized representation.

---

## G8 — `tensor`-typed fields can't satisfy `dtype` / `range` assertions

**Status (Story I.b, v0.16.1):** **Closed.** Both `_eval_dtype` and `_eval_range` now accept ndarray field values. `dtype` compares `v.dtype.name` against the expected tag; `range` reduces via `v.min()`/`v.max()` and compares scalars. No new assertion kinds were added — the broader G16 work (tensor-aware kinds beyond `dtype`/`range`) remains open. Recipe A's `dtype: uint8` and `value_range: ±3` assertions on the `image` field can now be restored.

**Severity:** Friction (sub-case of G6; Recipe A drops these assertions) → **Closed v0.16.1**.

**Category:** Contracts evaluator.

**Symptom.**

```yaml
OutputExpectations:
  - field: image
    assertion: { kind: dtype, expected: uint8 }
    severity: error
```

…fails because `_eval_dtype` ([`pipeline/contracts.py:158`](file))
does `isinstance(v, accepted)` where `accepted = _PY_DTYPE_TAGS["uint8"]
= (int,)`. A numpy ndarray is not an `int`, so the assertion fails for
every record.

```yaml
- field: image
  assertion: { kind: range, min: -3.5, max: 3.5 }
  severity: error
```

…fails because `_eval_range` ([`pipeline/contracts.py:191`](file)) does
`v < lo` / `v > hi` on the field value. For a numpy array, this returns
an element-wise boolean array, which then raises
`ValueError: The truth value of an array with more than one element is
ambiguous.`

**Why this matters for consumer repo.** The phase plan's `value_range
post-normalize` and `image shape=[32,32,3] + dtype=uint8` checks are both
tensor-level. v1 expectations don't have tensor-aware kinds.

**Suggested fix direction.**

Two complementary changes:

1. Teach `_eval_dtype` to detect ndarray inputs and check
   `v.dtype.name == expected` (with the existing PY tag aliases acting
   as fallback for scalar fields).
2. Add a dedicated `tensor_range` kind that calls
   `np.asarray(v).min()` / `.max()` and compares the scalars. (Trying
   to overload the existing `range` kind for tensors is possible but
   confuses scalar-field semantics for the no-op case.)

A `tensor_shape` kind (`{kind: tensor_shape, field: image, shape: [32,
32, 3]}`) would round out the set and let recipes structurally re-assert
the `Output.record_schema` shape at the value level.

**Tests that would prove the fix.**

- `dtype: uint8` on `image` passes when records carry uint8 ndarrays;
  fails (with a clear message) when records carry float arrays.
- `tensor_range min=0 max=255` on `image` passes for uint8 images; fails
  on a synthetic record with values outside the range.
- `tensor_shape shape=[32, 32, 3]` rejects a record whose image was
  resized to 28x28x3.

---

## G9 — `flatten` Featurization missing from plugin

**Severity:** Blocking for Phase D Module 3 (`mlp_flat` variant); deferred
in Phase B.

**Category:** Plugin op registration.

**Schema view.** `FeaturizationOp.op: str`
([`datarefinery/recipe/models.py:310`](file)) permits any string; check 18
delegates to the plugin's `OperationSpec` table.

**Current runtime behavior.** `op: flatten` is not in
`_supported_operations()` ([`plugin.py`](file)) and not in
`_FEATURIZATION_OPS` ([`plugin.py:98`](file)). Recipes declaring
`op: flatten` fail validator check 18 with the standard "unknown op for
plugin image_classification" error.

**Why this matters for consumer repo.** The `mlp_flat` variant materializes
both the 3-D image and a 3,072-dim flat vector so Module 3's MLPClassifier
can read `image_flat` directly without a per-framework reshape step:

```yaml
mlp_flat:
  Featurizations:
    - name: flatten_image
      inputs: [image]
      output_field: image_flat
      op: flatten
      splits: [train, val, test]
```

This is the cleanest place to express the reshape — the alternative is to
have every Module 3 notebook insert framework-specific reshape code, which
defeats the recipe-as-truth discipline.

**Workaround in 0.16.0.** None expressible in the recipe; downstream
notebook code does the reshape at read time. This is acceptable for Phase
B (Task 2 has no MLP) and problematic for Phase D Module 3 where the
variant overlay would otherwise be the clean place to declare the shape
change.

**Suggested fix direction.**

Add a `FlattenOp` class to
[`datarefinery/plugins/image_classification/operations/featurizations.py`](file)
and register it in `_FEATURIZATION_OPS`. Reference shape:

```python
class FlattenOp:
    fit_on_train: bool = False

    def apply(
        self,
        records: list[Record],
        params: Mapping[str, Any],
        fitted: FittedValues | None,
        *,
        label_field: str | None,
        inputs: list[str],
        output_field: str,
    ) -> list[Record]:
        del fitted, label_field, params
        if len(inputs) != 1:
            raise PluginError(
                f"flatten requires exactly one input field (got {inputs!r})"
            )
        src = inputs[0]
        return [
            {**r, output_field: np.asarray(r[src]).reshape(-1)}
            for r in records
        ]
```

OperationSpec: no params; `applicable_sections=frozenset({"Featurizations"})`.

Per DOC: add a `recipe-authoring.md § Featurizations` example showing
`op: flatten` reading from `image` and writing to `image_flat`. Same pass
should backfill `image_size_stats` (already shipped, currently
undocumented).

**Tests that would prove the fix.**

- Recipe with `Output.record_schema.image_flat: { dtype: float32, shape: [3072] }`
  and a `flatten` Featurization with `inputs: [image]` materializes; every
  record has `image_flat.shape == (3072,)` and the values are
  `image.reshape(-1)`.
- Variant overlay with `Featurizations: [flatten_image, ...]` resolves
  cleanly via `apply_variant`.

---

## G10 — `Splits.class_balance` is metadata-only; dict shape and runtime resampling unsupported

**Severity:** Blocking for Phase D Module 9 `imbalanced_oversample` and
`imbalanced_classweight` variants.

**Category:** Schema + pipeline runner.

**Schema view.** `SplitsSection.class_balance: str | None`
([`datarefinery/recipe/models.py:257`](file)) — accepts a flat string tag
only.

**Current runtime behavior.** The splits stage explicitly documents that
`class_balance` is **metadata, not behavior**
([`pipeline/stages/splits.py:19-21`](file)):

> `class_balance` is a tag passed through to `SplitResult.class_balance`
> for downstream tools (ModelFoundry handles weighting/resampling at
> training time per features.md FR-7 #4); this stage does no resampling.

So even a recipe that gets the schema shape right (`class_balance: "oversample"`)
produces no resampled output — the tag rides through the manifest but the
materialized splits are unchanged from the raw stratified ratios.

**Why this matters for consumer repo.** The phase plan's three Module 9
variants are:

1. `imbalanced` — declare the skew, do nothing about it (baseline).
2. `imbalanced_oversample` — same skew, mitigate by oversampling minority
   classes back to majority count.
3. `imbalanced_classweight` — same skew, mitigate by emitting
   inverse-frequency weights for the training loss.

Variants (2) and (3) both write the spec's dict shape:

```yaml
Splits:
  class_balance:
    strategy: oversample_minority_to_majority   # or: emit_inverse_frequency_weights
    applies_to: [train]
```

Two problems compound: (a) pydantic rejects the dict shape outright (model
is `str | None`), and (b) even if (a) is fixed, the runtime does no work.

**Decision needed: where does class-balance resampling live?** Two coherent
options:

1. **DataRefinery handles it.** The Splits stage (or a new post-Splits
   stage) implements `oversample_minority_to_majority` by duplicating
   minority-class records in the named split until counts match the
   majority; `emit_inverse_frequency_weights` adds a `class_weight` field
   to every train record (or a sidecar table). The materialized instance
   is self-contained — every consumer reads balanced training data without
   any framework-specific mitigation logic.
2. **ModelFoundry handles it.** Today's stance per `splits.py` doc. The
   recipe declares intent; ModelFoundry's framework adapter applies the
   strategy at training time. The materialized instance is unchanged; the
   strategy lives in training-loop configuration, not in the prepared
   dataset.

Option (2) is what `splits.py` describes, and it's defensible — but the
recipe-as-truth discipline says the **prepared dataset** is the
handoff artifact; pushing resampling into ModelFoundry means the prepared
dataset's record counts don't match the strategy the recipe declares.
That conflicts with FR-23's split-record-count assertions (`170/30/100`
per class for the balanced case wouldn't apply for an oversampled
variant).

This is a **plan_phase decision**, not a debug fix. The right move is to
escalate to the developer: which option, and what does the schema look
like? Don't silently implement either path.

**Workaround in 0.16.0.** Drop both mitigation variants from the
spec; Module 9 demonstrates the baseline-vs-balanced comparison
qualitatively (sample counts in the report) without an
oversampled/weighted materialized instance.

**Suggested fix direction.**

Convene a design pass with stakeholders (DR, ModelFoundry, consumer
curricula). Outputs:

1. Decision: (1) DR-side or (2) MF-side resampling.
2. If (1): schema change to `SplitsSection.class_balance` (string → tagged
   union); new stage or branch in `pipeline/stages/splits.py`; OutputExpectations
   updated to reason about post-balance counts.
3. If (2): keep `class_balance: str | None` but add the dict form as a
   ModelFoundry-binding sidecar in `dependency-spec.md`; document
   explicitly in `recipe-authoring.md § Splits` that this is a
   forward-declared training-time hint, not a DR runtime behavior, so
   recipe authors don't expect record counts to change.

Either way, per DOC, the implementing story documents the chosen shape
in `recipe-authoring.md § Filters vs Splits for class imbalance` (which
already exists and currently lists "removal via filters" + "ModelFoundry
hint" as the two options — that section needs the resampling story added).

---

## G11 — `seed_derive_from: master` not recognized on Filters / Generation

**Severity:** Friction (workaround: explicit ints).

**Category:** Schema (parameter vocabulary).

**Schema view.** Filter params live inside `FilterOp.predicate:
dict[str, Any]` (opaque to pydantic); plugin OperationSpecs declare which
keys are valid. `GenerationOp.seed: int` is required and explicit.

**Current runtime behavior.** Nothing in the codebase recognizes
`seed_derive_from`. The plugin's `sample_per_class` /
`sample_per_class_fractional` / `drop_by_label` OperationSpecs declare
`seed: int, required=True`; passing `seed_derive_from: master` instead of
`seed: <int>` fails validator check 18 with "unknown parameter
'seed_derive_from'" and "required parameter 'seed' missing." Generation's
explicit `seed: int` field has the same shape.

**Why this matters for consumer repo.** The phase plan uses
`seed_derive_from: master` on every filter and on Recipe B's
`apply_corruptions` Generation, so that all derived seeds are functions of
the recipe-level `seed: 20260509`. Editing the master seed (e.g., for
Module 10's seed-override stretch exercise) propagates to every operation
without per-site edits. With explicit ints, the master-seed-override
discipline becomes "find and replace 7 integers across the recipe," which
defeats the point.

**Workaround in 0.16.0.** Hard-code distinct integers for every seeded op
(`seed: 11` on Splits, `seed: 101/102/103` on augmentations, etc.). The
master-seed-override exercise becomes manual.

**Suggested fix direction.**

Add a `SeedDerivation` schema (string `"master"` for now; extensible to
`"sibling:<recipe_id>"` etc.) and accept it as an alternative to a literal
`int` at every seeded-op site:

- `FilterOp.predicate.seed` (via OperationSpec on each filter op's
  `parameters`).
- `GenerationOp.seed` (model field — change `int` to
  `int | SeedDerivationSpec`).
- `AugmentationOp.seed` already optional; keep the form for explicit ints
  too.
- `SplitsSection.seed` likewise.

Resolution: at materialize time, the recipe loader walks every site with
`seed_derive_from: master` and computes
`derived_seed = sha256(recipe.seed.to_bytes(8, "big") + op_name_bytes).digest()[:8]`
(or similar — the exact derivation function must be documented in
`tech-spec.md` and pinned by test, since it participates in cache
identity).

Per DOC: add `recipe-authoring.md § Seeds and determinism` documenting
the master-seed-derivation policy, the cache-identity implications (yes,
master seed is part of the recipe → part of canonical bytes → part of
cache identity), and the per-op-seed escape hatch.

**Tests that would prove the fix.**

- Recipe with `seed: 100` and three filters using `seed_derive_from:
  master` materializes; each filter receives a distinct, deterministic
  derived seed.
- Changing `recipe.seed: 100 → 200` produces three new derived seeds (no
  collision with the prior set).
- Two filters with the same `op` but different `name` receive different
  derived seeds (the op name and the filter `name` both feed the
  derivation).

---

## G12 — `Generation` schema shape divergence

**Severity:** Blocking for Recipe B (`cifar10c_eval.yaml`).

**Category:** Schema.

**Schema view.** [`GenerationOp`](file) declares:

```python
class GenerationOp(_Frozen):
    name: str
    inputs: list[str]
    output_schema: dict[str, FieldSpec]   # required, explicit
    seed: int                              # required, int
    applies_at: list[str] = ["train"]
    params: dict[str, Any] = {}
```

with pydantic `extra="forbid"`.

**Current runtime behavior.** The consumer phase plan's Recipe B writes:

```yaml
Generation:
  - name: apply_corruptions
    op: imagecorruptions_apply         # ← not at top level today
    inputs: [image, label, path]
    output_schema_matches_input: true  # ← not in model
    splits: [test_pool]                # ← model uses `applies_at`
    seed_derive_from: master           # ← model uses `seed: int` (see G11)
    params:
      corruption_types: [...]
      severities: [...]
      preserve_original: false
      tag_fields:                      # ← model expects list[str], spec wants dict-rename
        corruption: corruption_type
        severity: severity
        source_path: original_path
```

Four divergences from the model:

1. **`op:` at top level.** Today the op name lives under `params.op` or
   is inferred from the GenerationOp's role; consumer recipes (and the
   other section shapes in DataRefinery — Transformations, Augmentations,
   Featurizations all use top-level `op:`) expect `op:` at the same level
   as `name:`. **Inconsistency between sections is the root cause** — the
   pattern is right; Generation is the outlier.
2. **`output_schema_matches_input: true`.** The model requires an explicit
   `output_schema: dict[str, FieldSpec]`. For corruption-apply (which
   preserves the input record shape and only adds tag fields), forcing
   the author to re-state the schema is busywork.
3. **`splits:` vs `applies_at:`.** Same concept, different name. Every
   other section uses `splits:`; only Generation says `applies_at:`. Pick
   one and rename — `splits:` is the established term.
4. **`tag_fields:` rename mapping** — see G13 below; sub-case of this gap.

**Why this matters for consumer repo.** Recipe B is the entire Module 11
deliverable. As written it produces four parse errors stacked on top of
each other; the author can't recover without rewriting the whole
Generation block.

**Workaround in 0.16.0.** Rewrite to the model's shape:

```yaml
Generation:
  - name: apply_corruptions
    inputs: [image, label, path]
    output_schema:
      image: { dtype: uint8, shape: [32, 32, 3] }
      label: { dtype: str }
      path: { dtype: str }
      corruption: { dtype: str }
      severity: { dtype: int8 }
      source_path: { dtype: str }
    seed: 20260509
    applies_at: [test_pool]
    params:
      op: imagecorruptions_apply
      corruption_types: [...]
      severities: [...]
      preserve_original: false
      tag_fields: [corruption, severity, source_path]
```

**Suggested fix direction.**

Schema redesign of `GenerationOp` to match the other section shapes:

```python
class GenerationOp(_Frozen):
    name: str
    op: str                                                # ← lift to top level
    inputs: list[str]
    output_schema: dict[str, FieldSpec] | Literal["matches_input"]   # ← allow shorthand
    splits: list[str] = ["train"]                          # ← renamed from applies_at
    seed: int | SeedDerivationSpec                         # ← per G11
    params: dict[str, Any] = {}
```

The `Literal["matches_input"]` value is the "pass-through-with-tag-fields"
shorthand; the runtime expands it to a concrete `dict[str, FieldSpec]` by
copying the input record shape and adding the declared `tag_fields` from
the op's params.

**This is a breaking change to the cross-repo contract** (recipe model
shape changes). Per `project-essentials.md` § "Recipe / manifest / report
shape changes need a cross-repo coordination check":

- Bump `schema_version: 1 → 2`.
- Add a migration in `recipe.loader.migrations` mapping
  `applies_at → splits`, top-level `op:` reshape, etc.
- Update `dependency-spec.md` naming both old and new field names with a
  deprecation horizon.
- Release-notes blast-radius announcement.

Per DOC: rewrite `recipe-authoring.md § Generation` with a worked
`imagecorruptions_apply` example using the new shape.

**Tests that would prove the fix.**

- Recipe with `Generation` in the new shape (top-level `op:`, `splits:`,
  optional `output_schema: matches_input`) validates clean and
  materializes.
- A v1-shape recipe (the current model) loaded through the loader runs
  the v1→v2 migration cleanly and produces an identical materialized
  instance (regression-pin the canonical hash through migration).
- `output_schema: matches_input` produces a manifest whose
  `output.record_schema` is the input record schema plus any `tag_fields`
  the op declares.

---

## G13 — `tag_fields` rename mapping for `imagecorruptions_apply`

**Severity:** Friction (workaround: accept the canonical field names).

**Category:** Schema (param shape).

**Schema view.** `ImageCorruptionsApplyParams.tag_fields: list[str]`
([`recipe/models.py:205`](file)) with a fixed-name default of
`["corruption", "severity", "source_path"]`. The runtime
([`generation_imagecorruptions.py:78-80`](file)) checks for fixed
strings:

```python
tag_corruption = "corruption" in parsed.tag_fields
tag_severity = "severity" in parsed.tag_fields
tag_source_path = "source_path" in parsed.tag_fields
```

So `tag_fields` is a *subset selector*: which of the three tags to emit,
not a rename mapping.

**Current behavior.** Authors can include or omit any of the three
canonical tag names; they cannot rename them. A spec writing

```yaml
tag_fields:
  corruption: corruption_type
  severity: severity
  source_path: original_path
```

(a dict mapping output field → semantic) fails pydantic with "expected
list[str], got dict."

**Why this matters for consumer repo.** Recipe B's spec wanted to remap
`source_path` → `original_path` for downstream readability. The fixed
names are usable; the rename is a quality-of-life ask.

**Workaround in 0.16.0.** Use the canonical names verbatim
(`corruption`, `severity`, `source_path`). Downstream notebook code reads
`source_path` instead of `original_path`.

**Suggested fix direction.**

Extend `tag_fields` to accept both shapes:

```python
tag_fields: list[str] | dict[str, str] = Field(
    default_factory=lambda: ["corruption", "severity", "source_path"]
)
```

When a dict, the keys are the **output field names** the records will
carry; the values are the **canonical tag names** the runtime understands
(`corruption`, `severity`, `source_path`). The runtime walks the dict,
asserts each value is in the canonical set, and writes each tag under the
authored key.

Per DOC: document both shapes in `recipe-authoring.md § Generation` —
list form (which canonical tags to emit) and dict form (output-field
rename).

**Tests that would prove the fix.**

- `tag_fields: [corruption, severity]` produces records with `corruption`
  and `severity` keys but no `source_path` (subset selection).
- `tag_fields: {kind: corruption, level: severity}` produces records with
  `kind` and `level` keys carrying the corruption-name and severity-level
  values (renamed).
- `tag_fields: {kind: bogus}` is rejected at validate time with "unknown
  canonical tag 'bogus'; valid: [corruption, severity, source_path]."

---

## G14 — `SampleData.selector` lacks `kind` and `splits`

**Severity:** Friction (SampleData dropped in spec workaround).

**Category:** Schema.

**Schema view.** [`SampleSelector`](file):

```python
class SampleSelector(_Frozen):
    n: int | None = None
    fraction: float | None = None
    seed: int | None = None
```

No `kind`, no `splits`. Pydantic `extra="forbid"`.

**Current behavior.** Recipes can ask for "n records" or "fraction of
records" from the unified post-pipeline dataset, with optional seed. They
cannot ask for "1 per class" (per-class semantics) or "from the train
split only" (split selection).

**Why this matters for consumer repo.** Recipe A's `SampleData` was
designed as "one record per class from the train split, deterministic by
seed" — a 10-record sample-grid for the Module 2 lesson:

```yaml
SampleData:
  selector:
    kind: per_class
    n: 1
    splits: [train]
```

Neither `kind` nor `splits` is in the model.

**Workaround in 0.16.0.** Drop the `SampleData` section. The Module 2
sample-grid comes from the `Visualizations.sample_grid` op with
`per_class: true, n: 10` parameters instead.

**Suggested fix direction.**

Extend `SampleSelector`:

```python
class SampleSelector(_Frozen):
    n: int | None = None
    fraction: float | None = None
    seed: int | None = None
    kind: Literal["uniform", "per_class"] = "uniform"   # ← new
    splits: list[str] | None = None                     # ← new; None means all
```

Runtime: `kind: per_class` requires the recipe's `Labels.field` to be
populated (validator check) and picks `n` records per class from the
declared splits. `kind: uniform` (default) keeps current behavior.

Per DOC: rewrite `recipe-authoring.md § SampleData` with both kinds and
the splits-selector example.

**Tests that would prove the fix.**

- `kind: per_class, n: 1, splits: [train]` on a 10-class CIFAR-style
  fixture yields exactly 10 records, one per class, all from train.
- `kind: uniform, n: 10` (no splits) yields 10 records sampled across
  all splits (current behavior preserved).
- `kind: per_class, n: 1` on an unlabeled-only source fails validate
  with a clear message.

---

## G15 — `Filters` schema requires nested `predicate:`; consumers expect flat `op:` / `params:`

**Severity:** Blocking (recipe doesn't parse).

**Category:** Schema (cross-section consistency).

**Schema view.** [`FilterOp`](file):

```python
class FilterOp(_Frozen):
    name: str
    predicate: dict[str, Any]    # ← all the op-shaped stuff lives in here
    stages: list[Literal["pre_split", "post_split"]] = ["pre_split"]
    splits: list[str] = []
    seed: int | None = None
```

with the op name living inside `predicate.op` and op params alongside it
(see [`recipe-authoring.md § Filters`](../guides/recipe-authoring.md#filters-optional)).

**Current behavior.** The author must write:

```yaml
Filters:
  - name: balanced_subset_train_pool
    predicate:
      op: sample_per_class
      n_per_class: 200
      label: train_pool
    stages: [pre_split]
```

But consumer recipes — including the consumer spec — write the same shape
every **other** section uses (Transformations, Augmentations,
Featurizations, Visualizations all have top-level `op:` and `params:`):

```yaml
Filters:
  - name: balanced_subset_train_pool
    op: sample_per_class
    params:
      n_per_class: 200
      label: train_pool
    stages: [pre_split]
```

The consumer spec's Filters block produces a pydantic ValidationError on
every filter ("missing required field 'predicate'") before validate is
reached.

**Why this matters for consumer repo.** Every filter in both recipes
uses the flat shape. Recipe A has 2 filters; Recipe B has 3; the
`imbalanced*` variants override Filters. None parse.

**Workaround in 0.16.0.** Rewrite every filter into the `predicate:`
nested form.

**Suggested fix direction.**

`FilterOp` should accept the flat shape that the rest of the recipe
already uses:

```python
class FilterOp(_Frozen):
    name: str
    op: str                              # ← lift from predicate.op
    params: dict[str, Any] = {}          # ← rename from predicate
    stages: list[Literal["pre_split", "post_split"]] = ["pre_split"]
    splits: list[str] = []
    seed: int | None = None
```

The validator's predicate-shape inspections (`predicate.get("op") ==
"filter_by_label"` at [validator.py:928](file), and a similar check at
:364) port to `op == "filter_by_label"` / `op == "class_balance"` directly.
This is a small validator delta — the bigger lift is the schema rename
and the migration.

Per `project-essentials.md` cross-repo coordination check: schema rename
is a `schema_version` bump. Add a v1→v2 migration in
`recipe.loader.migrations` that reshapes `predicate: {op: X, ...rest}`
into `op: X` + `params: rest`.

Per DOC: rewrite `recipe-authoring.md § Filters` with the new flat
shape; add the previously-undocumented filters (`sample_per_class`,
`sample_per_class_fractional`, `drop_by_label`) at the same time.

**Tests that would prove the fix.**

- New-shape recipe with flat `op:` / `params:` filters validates.
- Old-shape v1 recipe goes through the v1→v2 migration and produces an
  identical canonical-hash (i.e., reshape is purely syntactic; canonical
  bytes after migration match what the new shape would emit directly).
- Validator check 21 (label/unlabeled-split sanity) still rejects
  `filter_by_label` on unlabeled splits after the rename.

---

## G16 — Assertion `kind` vocabulary: missing kinds + naming inconsistencies

**Severity:** Blocking (every assertion in both consumer recipes fails).

**Category:** Contracts evaluator (plus naming).

**Schema view.** `Contract.assertion: dict[str, Any]` and
`Expectation.assertion: dict[str, Any]` — fully opaque to pydantic, so
assertions are not validate-caught. The contracts evaluator
([`pipeline/contracts.py`](file)) dispatches on `assertion["kind"]` at
materialize time and rejects unknown kinds.

**Current vocabulary** (per `contracts.py` and `recipe-authoring.md §
InputContracts`):

| `kind` | Required | What it checks |
|---|---|---|
| `record_count` | one of `min`/`max` | Total record count is in bounds. |
| `required_field` | `field` | Field is present and non-`None` in every record. |
| `dtype` | `field`, `expected` | Field dtype matches (scalar Python types only). |
| `range` | `field`, `min`/`max` | Numeric field in bounds (scalar comparison only). |
| `distributional` | `field`, kind-specific | v1 placeholder, always passes. |

**What consumer recipes (and the consumer spec) write:**

| Spec `kind` | DR has | Issue |
|---|---|---|
| `shape_equals` | (none) | Missing kind — shape only lives in `Output.record_schema` today. |
| `dtype_equals` | `dtype` | Name mismatch + structure (`value:` vs `expected:`). |
| `record_count_equals` | `record_count` | Name mismatch + structure (`value:` vs `min:`/`max:`). |
| `value_in_set` | (none) | Missing kind. |
| `per_class_count_equals` | (none) | Missing kind. |
| `value_range` | `range` | Name mismatch only (`min`/`max` structure matches). |
| `split_record_counts` | (none) | Missing kind (see G6). |
| `per_class_count_per_split` | (none) | Missing kind (see G6). |
| `count_by_field` | (none) | Missing kind. |
| `count_by_fields` | (none) | Missing kind. |

**Why this matters for consumer repo.** **Every assertion in both
recipes uses a `kind` that DR doesn't recognize.** This produces a
materialize-time `ContractError: unknown assertion kind 'shape_equals'`
(etc.) cascade — twelve assertions in Recipe A's two contracts blocks,
nine in Recipe B's. The author cannot tell *which* assertions are
present-in-DR-under-a-different-name vs. genuinely missing without
consulting `contracts.py` directly. This is the largest single
diagnosability gap in the spec.

**Decompose into two sub-gaps:**

**G16a — Naming consistency.** The spec uses `*_equals` (e.g.,
`dtype_equals`) for exact-match kinds and `value_range` for bounded.
DR uses bare verbs (`dtype`, `range`). The naming difference is small
in code but produces a 1:1 author confusion: an author who reads
`record_count` in the docs reasonably writes `record_count_equals` when
they want exact-count semantics. Decide on a canonical naming convention
and apply consistently. Options:

- **`*_equals` + `*_range` + `*_in_set` etc.** — verb-style, reads as a
  predicate sentence. The consumer spec author's natural pull.
- **Bare verbs + struct disambiguation** — current style. `dtype:
  {expected: uint8}` (equals) vs `dtype: {one_of: [uint8, float32]}` (set
  membership). Compact in YAML but requires authors to remember struct
  shapes.

The first option is more discoverable; the second is more compact. Per
DOC, whatever is chosen must be documented in `recipe-authoring.md §
InputContracts` (and section parity for OutputExpectations).

**G16b — Missing kinds.** Beyond renames, these kinds are not
implemented at all:

- `value_in_set` (or `dtype: {one_of: [...]}`) — used in 8 places across
  the spec.
- `shape_equals` — used 4 times on `image` fields; today shape only
  lives in `Output.record_schema` declarations, not as a runtime
  assertion.
- `per_class_count_equals` (single-split) — used 1 time in Recipe A's
  InputContracts.
- The per-split family from G6 (`split_record_counts`,
  `per_class_count_per_split`, `count_by_field`, `count_by_fields`).

Each missing kind needs a v1-style evaluator entry in `contracts.py`,
the `dispatch` table extended, and a `recipe-authoring.md` row in the
Assertion kinds table.

**Workaround in 0.16.0.** Drop all assertions except the five DR
recognizes; rewrite those into the bare-verb shape with the right param
keys (`expected:`, `min:`/`max:`). The consumer spec was authored against a
mental model of what assertions *should* be available; reality is much
sparser.

**Suggested fix direction.**

Two-phase work:

1. **Phase A (naming pass).** Decide canonical naming convention; either
   keep bare verbs and document the struct shapes more visibly, or
   rename to `*_equals` / `*_in_set` / `*_range`. If renaming, bump
   schema and migrate; the assertion `kind` is part of the canonical
   bytes (via the assertion dict serialization), so this is
   cache-invalidating.
2. **Phase B (new kinds).** Implement `value_in_set`, `shape_equals`,
   `per_class_count_equals`, plus the G6 per-split family. Each kind
   gets an evaluator, an entry in the dispatch table, a row in the
   `recipe-authoring.md` assertion-kinds table, and a unit test.

Per DOC: every new kind must land with its `recipe-authoring.md` row.
The current table at [`recipe-authoring.md:452-460`](../guides/recipe-authoring.md#L452-L460)
is the canonical home.

**Tests that would prove the fix.**

- Recipe with one assertion of each new kind validates and evaluates
  cleanly on a fixture.
- Each new kind has a corresponding negative test (assertion fails with
  a precise message identifying the offending records and the assertion
  bound).
- Naming pass: a v1-shape recipe using the bare-verb kinds (e.g.
  `dtype`) materializes identically to a v2-shape recipe using the new
  names (e.g. `dtype_equals`) — round-trip migration test.

---

## G17 — `class_distribution_histogram` lacks `group_by` param

**Severity:** Friction (viz dropped in spec workaround).

**Category:** Plugin op param schema.

**Schema view.** OperationSpec for `class_distribution_histogram` at
[`plugin.py:278`](file) declares no params. The runtime histograms by the
recipe's `Labels.field` implicitly.

**Why this matters for consumer repo.** Recipe B's
`corruption_class_distribution` viz wants to group by the `corruption`
field (not `label`) to confirm each corruption type preserves the
balanced class distribution:

```yaml
- name: corruption_class_distribution
  op: class_distribution_histogram
  params: { group_by: corruption }
  stage: post_transform
  mode: reporting
```

`group_by` isn't a declared param, so validator check 18 rejects it.

**Workaround in 0.16.0.** Drop the viz. The sanity check moves to an
out-of-band notebook cell that reads the materialized JSONL and
recomputes the count.

**Suggested fix direction.**

Extend the OperationSpec:

```python
"class_distribution_histogram": OperationSpec(
    parameters={
        "group_by": ParameterSpec(
            type="str", required=False
        ),  # defaults to Labels.field when absent
    },
    applicable_sections=frozenset({"Visualizations"}),
),
```

Runtime: when `group_by` is present, the viz histograms on the named
field instead of `Labels.field`. The field must exist on every record
in the target stage; validator check 18 alone is not sufficient — also
need a check that `group_by` names a known field per
`Output.record_schema` or a Generation-introduced tag field.

Per DOC: update `recipe-authoring.md § Visualizations` with the
`group_by` param, plus the broader backfill of currently-undocumented
viz ops (FR-VIZ-1..4).

**Tests that would prove the fix.**

- Recipe with `class_distribution_histogram` and no params produces a
  histogram bucketed by `Labels.field` (current behavior).
- Recipe with `group_by: corruption` produces a histogram bucketed by
  the `corruption` field; validator accepts it; rendered PNG groups by
  the named field.
- Recipe with `group_by: nonexistent_field` is rejected at validate
  time, not at viz-render time.

---

## G18 — `Generation` stage extends each target split rather than replacing source records

**Severity:** Blocking for Recipe B (`cifar10c_eval.yaml`) — the phase
plan's "single test split of exactly 12,000 records" is unachievable in
0.16.0. Worked around by accepting 1,000 dead-weight untagged originals
alongside the 12,000 corrupted records in the test split.

**Category:** Pipeline runner.

**Schema view.** `GenerationOp` ([`recipe/models.py:238`](file)) declares
`applies_at: list[str]` (default `["train"]`). The schema implies "this
op runs against records in these splits"; it doesn't say whether the
source records survive or get replaced.

**Current runtime behavior.** `apply_generation`
([`pipeline/stages/generation.py:71`](file)) concatenates the op's output
records onto the source split:

```python
new_records = _invoke_one(op, out[split_name], plugin, label_field)
_validate_against_output_schema(op.name, split_name, new_records, output_fields)
out[split_name].extend(new_records)   # ← extend, not replace
```

`imagecorruptions_apply` ([`generation_imagecorruptions.py:67`](file))
calls this contract out explicitly in its docstring:

> Returned records are the NEW outputs added by Generation; per the stage
> contract they are concatenated onto the input split. The original input
> records remain in the split untouched.

For `imagecorruptions_apply` with `preserve_original: false`, the op
returns just the corrupted variants (no untouched copies). But because
the stage extends, the originals stay in the split anyway. Output is
`<n_original_records> + (n_corruption_types × n_severities × n_records)`,
not the `(n_corruption_types × n_severities × n_records)` the phase plan
expected.

**Why this matters for consumer repo.** Recipe B's phase-plan goal is a
single test split of exactly 12,000 records: 1,000 base test images × 4
corruptions × 3 severities. Under 0.16.0 the test split ends up at
**13,000** = 1,000 untagged originals + 12,000 tagged corruptions.
Downstream Module 11 evaluation code has to filter by presence of the
`corruption` field to isolate the corrupted subset, and `OutputExpectations
record_count=12000` becomes `record_count=15000` (1,700 train + 300 val +
13,000 test) — measurably surprising for any author reading the recipe.

**Workaround in 0.16.0 (Story B.d).** Recipe B sets `preserve_original:
false` and accepts the dead-weight originals in the test split. The
originals are identifiable by absence of the `corruption` field;
downstream consumers filter when needed. `OutputExpectations` asserts the
union total `record_count=15000`.

**Suggested fix direction.**

Add a per-op `replace_input_records: bool = False` field to
`GenerationOp` declaring whether the op's output **augments** (current
behavior, default) or **replaces** the input records. For an op that
materially transforms each input record N ways (corruption × severity),
`replace: true` is the natural ask — the consumer wanted "these records
turned into those records," not "these records *plus* those records."

Implementation sketch in `pipeline/stages/generation.py`:

```python
for op in generation_ops:
    for split_name in op.applies_at:
        new_records = _invoke_one(op, out[split_name], plugin, label_field)
        _validate_against_output_schema(...)
        if op.replace_input_records:
            out[split_name] = list(new_records)
        else:
            out[split_name].extend(new_records)
```

Schema:

```python
class GenerationOp(_Frozen):
    name: str
    inputs: list[str]
    output_schema: dict[str, FieldSpec]
    seed: int
    applies_at: list[str] = ["train"]
    params: dict[str, Any] = {}
    replace_input_records: bool = False   # ← new; backward-compatible default
```

The default `False` preserves current behavior, so this is additive —
**no `schema_version` bump required**. Lands cleanly alongside G12 (the
deeper Generation schema reshape) or independently.

Per DOC: add a "When to use `replace_input_records`" subsection in
`recipe-authoring.md § Generation` covering the corruption-apply use case
explicitly (today's docs don't mention the extend-vs-replace question at
all, so the natural author assumption — "Generation produces N output
records per input" — silently disagrees with the runtime).

**Tests that would prove the fix.**

- Recipe with `imagecorruptions_apply` + `replace_input_records: true`
  produces exactly `(n_corruption_types × n_severities × n_base_records)`
  records in the target split; no untagged originals remain.
- The same recipe with `replace_input_records: false` (or omitted)
  reproduces the current 0.16.0 behavior.
- Regression: a recipe authored against the current 0.16.0 (no
  `replace_input_records` field) loads with the default `False` and
  produces a byte-identical materialized instance to its pre-fix output.

---

## G19 — `resolve_sibling_stats` doesn't strip variants before hashing the sibling recipe

**Severity:** Blocking whenever the sibling recipe declares any
`variants` block — `stats_from_instance` lookups fail with
`SiblingInstanceNotFoundError` even though the sibling is materialized
and `datarefinery status` resolves it correctly.

**Category:** Pipeline runner / sibling resolver.

**Schema view.** `StatsFromInstanceSpec`
([`recipe/models.py:261`](file)) — `recipe: str` + `op_id: str`. Schema
permits any sibling-recipe path.

**Symptom.** A consumer recipe with

```yaml
Transformations:
  - name: normalize_per_channel
    op: normalize
    fit_source: train  # required by validator check 6 even with stats_from_instance
    splits: [train, val, test]
    params:
      stats_from_instance:
        recipe: recipes/cifar10-base.yaml
        op_id: normalize_per_channel
```

raises at materialize time:

```
SiblingInstanceNotFoundError: sibling_stats: no promoted instance for
recipe at recipes/cifar10-base.yaml (expected shard <X> not found)
```

…even though Recipe A is materialized and `datarefinery status
recipes/cifar10-base.yaml` resolves the instance correctly. The shard
`<X>` the resolver looks for is the canonical hash of the loaded sibling
recipe **with variants present**, while the actual cached instance lives
under the canonical hash with variants stripped.

**Why it happens.** The CLI materialize path
([`core/datarefinery.py:92`](file)) calls `apply_variant(recipe, variant)`
to strip variants before computing the cache key — even when
`variant=None`, `apply_variant` clears the `variants` block
([`recipe/variants.py:44`](file): `base["variants"] = {}`). This is the
documented design: variants participate in cache identity through the
*selected overlay*, not by their mere declaration. Two materializations
of the same recipe, one with no variant and one with `--variant
no_augment`, produce different shards; switching variants is a cache
miss the first time and a hit thereafter.

But `resolve_sibling_stats` ([`cache/sibling_stats.py:88`](file)) loads
the sibling recipe and passes it directly to `to_canonical_bytes`
without calling `apply_variant(recipe, None)` first:

```python
sibling_recipe = load_recipe(recipe_path)
sibling_hash = hashlib.sha256(to_canonical_bytes(sibling_recipe)).hexdigest()
```

So when the sibling declares variants, the resolver hashes a "with
variants" canonical form while the materialize path cached under a
"without variants" canonical form. The two diverge.

Concrete example from the consumer repo:

| Path | Hash[:16] |
|---|---|
| `datarefinery materialize recipes/cifar10-base.yaml` actually cached at | `8863ce9031b3f367` |
| `to_canonical_bytes(load("recipes/cifar10-base.yaml"))` | `361d6a24c8572dd9` |

**Why this matters for consumer repo.** Recipe B's whole point is to
inherit Recipe A's normalize statistics via `stats_from_instance` (the
FR-TRANS-1 loose-coupling contract). With G19 unfixed, the lookup fails
for every recipe that declares variants — which Recipe A does, as the
canonical contract for downstream Module 9 / Module 3 work. Any consumer
project following the recipe-authoring guide's reference recipe (which
declares a `no_augment` variant) hits this immediately.

**Workaround in 0.16.0 (Story B.d).** Pin literal `mean` / `std` values
in Recipe B's `normalize` params, copied from Recipe A's
`fitted_statistics/normalize_per_channel/{mean,std}.parquet`. Loses the
FR-TRANS-1 loose-coupling property — re-fitting Recipe A doesn't
propagate automatically; the project must update the pinned values by
hand. Keeps Recipe B materializable.

**Suggested fix direction.**

One-line fix in `resolve_sibling_stats`:

```python
- sibling_recipe = load_recipe(recipe_path)
+ sibling_recipe = apply_variant(load_recipe(recipe_path), None)
```

The `apply_variant(..., None)` call is the same no-op-but-strip-variants
form the materialize path uses. After the fix, the sibling shard matches
the cached shard for any recipe regardless of whether it declares
variants.

A future feature could let `stats_from_instance` name a specific variant
of the sibling:

```yaml
stats_from_instance:
  recipe: recipes/cifar10-base.yaml
  variant: no_augment
  op_id: normalize_per_channel
```

…so an evaluation recipe can import statistics fit under a specific
experimental overlay. That's a v1.1+ enhancement; the minimum fix for
G19 is the no-variant case (one line).

Per DOC: add an "FR-TRANS-1 across variants" subsection to
`recipe-authoring.md § Transformations` documenting that
`stats_from_instance` resolves the sibling's no-variant canonical
instance, with the future variant-selecting form noted as planned.

**Tests that would prove the fix.**

- A "sibling" recipe declaring a `variants` block, materialized once,
  then referenced from a "consumer" recipe via `stats_from_instance`.
  The consumer materializes successfully and the fitted statistics used
  match the sibling's fitted statistics byte-identically.
- `resolve_sibling_stats` continues to work for sibling recipes that
  declare no variants (no regression).
- After future variant-selector landing: a sibling materialized under a
  non-default variant (`--variant no_augment`) is resolvable from a
  consumer recipe with `stats_from_instance.variant: no_augment`,
  separately from the no-variant instance.

---

## Recipe-side workarounds in `recipes/cifar10-base.yaml`

The actual workarounds for each gap above live in the inline header
comments of [`recipes/cifar10-base.yaml`](../../../recipes/cifar10-base.yaml)
and in [`docs/specs/stories.md`](../stories.md) under Story B.b's
checklist deviations. When a gap is fixed upstream, the recipe needs the
corresponding deviation removed:

| Gap | Recipe edit when fixed |
|---|---|
| G1 | Restore the two `sample_per_class` filters with `label: train_pool` / `label: test_pool` + `Splits.applies_to: train_pool, ratios: {train: 0.85, val: 0.15}`. Refactor the `imbalanced*` variants similarly. |
| G2 | Add `cast` Transformation (canonical name; not `cast_dtype`) before `normalize` with `params: { dtype: float32, scale: 0.00392156862745098 }`. Change `Output.record_schema.image.dtype` to `float32`. |
| G3 | Add `categorical_encode` Featurization deriving `label_id`. Add `label_id: { dtype: int32 }` to `Output.record_schema`. |
| G4 | **Closed in v0.16.2 (Story I.c).** Validator check 23 catches the collision at validate time. No recipe edit needed; Recipe A's existing structure (label from loader, no `label_from_path` Featurization) is still correct. The check now ensures any future author who reaches for the conflicting pattern is told before materialize runs. |
| G5 | (No G5-only recipe edit; G5 is subsumed by G7. When G7 lands, restoring the `augmented_sample_grid` viz with `stage: pre_transformations` is the unblocked path.) |
| G6 | Restore per-split + per-class OutputExpectations (paired with G15 for the missing assertion kinds). |
| G7 | Split `sample_grid` into `pre_normalize` + `post_normalize` versions with appropriate `stage:` values. |
| G8 | **Closed in v0.16.1 (Story I.b).** `dtype: uint8` and `range: {min, max}` on tensor fields now work. (`tensor_range` / `tensor_shape` as separate kinds remain G16.) |
| G9 | Restore the `flatten` Featurization in the `mlp_flat` variant. |
| G10 | Restore the `imbalanced_oversample` and `imbalanced_classweight` variants once the resampling design is decided (recipe-side shape depends on the decision). |
| G11 | Restore `seed_derive_from: master` on every filter and on Recipe B's `apply_corruptions` Generation op. |
| G12 | Rewrite Recipe B's `Generation` block in the new shape: top-level `op:`, `splits:` (not `applies_at:`), `output_schema: matches_input`, and `seed_derive_from: master`. |
| G13 | Switch `Recipe B Generation.params.tag_fields` to the dict-rename form: `{ corruption: corruption_type, severity: severity, source_path: original_path }`. |
| G14 | Restore the `SampleData` section in Recipe A: `selector: { kind: per_class, n: 1, splits: [train] }`. |
| G15 | Rewrite every filter from the nested `predicate:` shape to flat `op:` / `params:` shape. |
| G16 | Rewrite every assertion in both recipes to use the new naming + the new kinds (`value_in_set`, `shape_equals`, `per_class_count_equals`, `*_equals` / `*_range` renames). |
| G17 | Restore the `corruption_class_distribution` viz in Recipe B with `params: { group_by: corruption }`. |
| G18 | Add `replace_input_records: true` to Recipe B's `imagecorruptions_apply` Generation op; drop the 1,000 dead-weight untagged originals from the test split. Update Recipe B's `OutputExpectations.record_count` from 15,000 (1,700 + 300 + 13,000) to 14,000 (1,700 + 300 + 12,000). Remove the "downstream consumers filter by presence of `corruption` field" note from the recipe header — every test record will carry the tag fields by construction. |
| G19 | Replace Recipe B's pinned literal `params.mean` / `params.std` with the FR-TRANS-1 form: `params: { stats_from_instance: { recipe: recipes/cifar10-base.yaml, op_id: normalize_per_channel } }`. Remove the G19-workaround comment block from the recipe header. (Bonus: once the future variant-selector form lands, the consumer recipe can pin a specific sibling-variant of Recipe A's normalize stats — relevant for Module 9's imbalance variants whose normalize stats may legitimately differ.) |
| DOC | Every G fix above lands its `recipe-authoring.md` section in the same story. Existing-feature documentation drift (the table in DOC) closes alongside the next op-registration story in each § — no separate doc-sweep story. |

---

## Upstream issue-filing convention

When filing these against the DataRefinery repo, suggested title pattern:

```
[consumer repo dependency-gaps] G<n>: <one-line summary>
```

Body should link back to this doc by stable URL and cite the
specific symptom + repro from the corresponding section here.
