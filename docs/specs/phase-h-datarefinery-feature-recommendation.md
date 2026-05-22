# DataRefinery Feature Spec — Image Classification Plugin Additions

This spec covers gaps and improvements to DataRefinery's image_classification
plugin and a small number of cross-cutting concerns. It answers **what**
each new feature does and **why** it's needed. Implementation details
(the **how**) belong in a follow-on tech-spec.

This is a delta document: existing features are not restated. Feature IDs
use descriptive prefixes (FR-FILTER-N, FR-GEN-N, etc.) and should be
renumbered into the project's main FR-N sequence when filed.

---

## Scope

In scope:

- New Filter operations (balanced subsample, fractional subsample, drop by label)
- New Generation operation (image corruptions)
- New Transformation parameter (import fitted statistics from a sibling instance)
- New Augmentation policy operations (crop, flip, jitter, erasing)
- New Visualization operations (pixel distribution, augmented samples, corruption grids)
- One architectural change (multi-instance cache identity)

Out of scope (mentioned for boundary clarity):

- New source types beyond the existing `image_folder` and `image_flat`
- New plugins beyond image_classification
- ModelFoundry-facing concerns (training-time augmentation realization,
  framework adapters) — those belong in ModelFoundry's spec, not here
- Materialization performance, parallelism, caching internals — implementation,
  not spec

---

## Triage Summary

| ID | Feature | Tier | Primary use case |
| --- | --- | --- | --- |
| FR-FILTER-1 | `sample_per_class` | Hard required | Balanced subsampling and disjoint-pool selection from a single labeled source |
| FR-FILTER-2 | `sample_per_class_fractional` | Strongly desired | Controlled-imbalance dataset construction |
| FR-FILTER-3 | `drop_by_label` | Hard required | Removing filter-tagged subsets after they've served their selection role |
| FR-GEN-1 | `imagecorruptions_apply` | Hard required | Robustness evaluation under known image corruptions |
| FR-TRANS-1 | `stats_from_instance` | Hard required | Train/inference normalization parity across separately materialized instances |
| FR-AUG-1..4 | Augmentation policies | Strongly desired | Canonical image-classification augmentation declared at the recipe surface |
| FR-VIZ-1..4 | Reporting visualizations | Nice to have | Operation-specific "what did this do" figures persisted into the report |
| FR-ARCH-1 | Multi-instance cache identity | Architectural | Correctness for any feature that imports state from a sibling instance |

"Hard required" means a pipeline using the relevant primitive cannot
materialize without the feature. "Strongly desired" means a hand-rolled
workaround exists but materially degrades recipe readability or report
quality. "Nice to have" means the workaround is fine.

---

## Filter Operations

### FR-FILTER-1: `sample_per_class`

**What.** A `Filters` operation that produces a balanced subsample
containing `n_per_class` records of each label, drawn from the records
flowing into the filter. Records not selected are dropped from the
pipeline. Selection is stratified by label and deterministic given a seed.

The operation accepts an optional `label` parameter (a string). When set,
surviving records are tagged with that label as a partition marker readable
by downstream filters and Splits operations. When unset, the operation acts
as a plain balanced subsample with no tagging.

The operation accepts an optional `exclude_already_labeled` parameter (a
list of strings). When set, records already carrying any of the listed
labels (from a prior `sample_per_class` invocation in the same recipe) are
excluded from the candidate pool before sampling. This enables disjoint
pool selection in a single pass.

**Why.** Balanced subsampling is a recurring need in any classification
pipeline: when a labeled source is large or skewed, training and
evaluation benefit from a deterministic balanced view of it. The
disjoint-pool selection is the less obvious use case but matters whenever
two non-overlapping balanced sets must be drawn from a single labeled
source — for example, constructing a train/test split from a source that
ships without a canonical split, evaluating fairness on a balanced holdout
drawn from the same pool as training, or building any pair of independent
balanced sets where canonical splits are unavailable, unusable, or
inappropriate for the experimental setup.

The `label` + `exclude_already_labeled` mechanism expresses this
disjoint-pool selection declaratively in the recipe. Without it, the only
ways to express disjoint balanced pools are (a) materializing the
partitioning in a pre-pipeline script, which leaks the most pedagogically
important decisions out of the recipe and weakens the cache-identity
contract, or (b) hand-coding the disjoint-pool logic in custom Python and
losing the validation and report benefits of a declared filter.

**Open question.** Whether `label` and `exclude_already_labeled` are
single-feature additions to `sample_per_class` or a separate generic
record-tagging mechanism that multiple filter ops can use. The latter is
more general but larger in scope; the former is the minimum needed for
disjoint-pool selection.

### FR-FILTER-2: `sample_per_class_fractional`

**What.** A `Filters` operation that produces a per-class subsample where
each class can be sampled at a different rate. Parameters: `n_per_class_base`
(an integer reference scale) and `fractions` (a dict mapping each label to
a float in [0.0, 1.0]; missing labels default to 1.0). Surviving records
per class = `floor(n_per_class_base × fractions[label])`. Inherits the
`label` and `exclude_already_labeled` parameters from FR-FILTER-1.

**Why.** Controlled-imbalance dataset construction is a recurring need in
any work that studies how class imbalance affects model behavior or
compares mitigation techniques (oversampling, class-weighted loss, focal
loss, augmentation of minority classes). Researchers and instructors
routinely need to deliberately skew class frequencies — e.g., reducing
some classes to 25% or 50% of others — to observe the effect on per-class
metrics or to stress-test a mitigation strategy against a known imbalance
ratio. The fractional form reads more cleanly than equivalent per-class
filter chains and matches how imbalance is typically discussed in the
literature (as a per-class multiplier on a base rate).

**Alternative if rejected.** Express the same imbalance as a chain of N
class-filtered `sample_per_class` calls, one per class, each with a
different `n_per_class` value. Verbose but functional.

### FR-FILTER-3: `drop_by_label`

**What.** A `Filters` operation that drops records carrying any of the
named labels. Parameter: `labels` (a list of strings). The inverse
companion to FR-FILTER-1's `label` parameter.

**Why.** Whenever filter-tagging (FR-FILTER-1's `label` parameter) is used
to track selection state across multiple filter operations, a companion
mechanism to drop tagged records becomes necessary. The canonical case:
two sibling recipes need to select the same subset from a common labeled
source, so both replicate an identical filter chain (same operations,
same parameters, same seed) — but each recipe then keeps only the portion
relevant to its purpose and drops the rest. `drop_by_label` is the
drop-the-rest step.

Without `drop_by_label`, recipes either use a non-deterministic selection
mechanism (breaking cross-recipe bit-identity guarantees) or carry
unused records through the rest of the pipeline (wasting materialization
time and disk space).

**Open question.** Whether `drop_by_label` is a distinct operation or a
parameter on existing filter primitives. Distinct reads cleaner in the
recipe; parameter is more compact. Either satisfies the use case.

---

## Generation Operations

### FR-GEN-1: `imagecorruptions_apply`

**What.** A `Generation` operation that applies image corruptions from the
`imagecorruptions` PyPI package (Hendrycks-Dietterich reference
implementation) to incoming records. Parameters: `corruption_types` (a list
of names from the package's vocabulary: `gaussian_noise`, `motion_blur`,
`fog`, `jpeg_compression`, and the rest of the H-D set), `severities` (a
list of integers in 1-5), and `preserve_original` (boolean: when true,
clean input records are also emitted, tagged with `corruption=none,
severity=0`).

For each input record, the operation emits one output record per
(corruption_type, severity) combination, with the corrupted image in the
`image` field and metadata fields written per the `tag_fields` parameter
(typically `corruption`, `severity`, and `source_path` for provenance).
Output record count = input count × len(corruption_types) × len(severities)
(× 2 if `preserve_original`).

Determinism: the operation seeds the underlying `imagecorruptions` calls
from the recipe's master seed. Re-running with the same seed produces
byte-identical output.

**Why.** Robustness evaluation under known image corruptions is a
standard benchmarking practice in image classification work, originating
with Hendrycks & Dietterich's "Benchmarking Neural Network Robustness to
Common Corruptions and Perturbations" (ICLR 2019). The corruption taxonomy
covers noise, blur, weather, and digital artifacts at five severity
levels, and the canonical reference implementation ships as the
`imagecorruptions` PyPI package.

Wrapping `imagecorruptions` as a DataRefinery Generation operation lets
robustness evaluation sets be constructed declaratively from a recipe,
keeping the corruption layer seeded, cache-keyed, report-visible, and
reproducible. The alternative — consuming the various published
pre-generated corruption datasets — requires per-dataset fetch logic,
separate source-type handling for the `.npy` distributions those sets
typically ship as, and tens of gigabytes of downloads for datasets that
are functionally wrappers around the same package's corruption functions.

Use cases: benchmarking model robustness against a controlled corruption
suite; comparing augmentation strategies by their downstream effect on
corruption robustness; generating stress-test datasets for safety or
deployment analysis; constructing evaluation sets that probe a model's
behavior under specific perturbation types relevant to a deployment
environment (e.g., motion blur for vehicle cameras, fog for outdoor
sensors, JPEG compression for web/mobile pipelines).

**Dependency.** Adds `imagecorruptions` (and its transitive dependencies:
`opencv-python` or `opencv-python-headless`, `scikit-image`) to the
image_classification plugin's requirements, or to a new
`image_classification[corruptions]` extras group. These are non-trivial
dependencies; the extras-group approach keeps the base plugin lean.

**Open questions.**

1. Is the `imagecorruptions` dependency acceptable in the image plugin's
   base requirements, or should it live in an extras group that recipes
   opt into?
2. How should the operation behave on unsupported corruption names?
   Fail-fast at recipe validation time is the obvious answer, but the
   validation needs the dependency available to check the vocabulary.

---

## Transformation Parameters

### FR-TRANS-1: `stats_from_instance`

**What.** A new parameter on Transformation operations that have a `fit`
phase (today: `normalize`; future: any operation that derives statistics
from training data and replays them on val/test). When set, the operation
imports its fitted statistics from a sibling materialized DataRefinery
instance rather than fitting locally.

Parameter shape:

```yaml
stats_from_instance:
  recipe: <path-or-name>
  op_id: <name-of-the-op-in-the-sibling-recipe>
```

The operation resolves the sibling instance from the cache, reads
`fitted_statistics/<op_id>/`, and uses those statistics for the apply
phase. No local fit is performed; the operation has no `fit_source` field
when `stats_from_instance` is set.

Failure modes that must produce clear errors at validation or
materialization time:

- Sibling instance not found in cache (the referenced recipe has never
  been materialized).
- The named `op_id` does not exist in the sibling instance.
- The sibling instance's statistics format is incompatible with this
  operation's expected format (different op, different version).

**Why.** Train/inference normalization parity is a correctness invariant
in any model evaluation: the statistics used to normalize evaluation data
must match the statistics the model was trained against, otherwise the
model sees data outside the distribution it learned to interpret. When
training data and evaluation data are materialized in the same recipe,
DataRefinery's `fit_source: train` mechanism already handles this. The
gap appears when evaluation data is materialized in a *separate* recipe
from training data — a common pattern in several scenarios:

- Distribution-shift or robustness evaluation, where the evaluation set
  is constructed by transforming or augmenting a holdout in ways the
  training pipeline doesn't (e.g., adding corruptions, applying domain
  shifts). The evaluation recipe is logically downstream of the training
  recipe.
- A/B evaluation, where multiple evaluation sets are built independently
  to compare a model against varied conditions, all sharing the
  training-time normalization.
- Cross-team or cross-organization workflows where one party prepares
  training data and another prepares evaluation data; the evaluation
  recipe needs the training recipe's statistics without re-running the
  training data pipeline.
- Continual or longitudinal evaluation, where new evaluation sets are
  prepared periodically against a fixed historical training-time
  normalization.

In all of these, re-fitting statistics on the evaluation data is a
correctness bug, not an optimization. `stats_from_instance` makes the
correct behavior expressible in the recipe surface.

**Dependency.** Touches the cache-identity model (see FR-ARCH-1).

---

## Augmentation Policies

Four augmentation operations declared as recipe-level **policy** that
propagates to ModelFoundry's framework adapter (PyTorch / Keras), realized
on-the-fly during training. None of these augmentations is materialized
into the prepared dataset.

This matches DataRefinery's existing FR-11 framing ("the recipe declares
augmentation policies, not concrete augmented examples"). The four
operations below extend that framing with the canonical image-classification
augmentation set used in essentially every modern training pipeline.

### FR-AUG-1: `random_crop`

**What.** Policy declaring random spatial crop with optional pre-crop
padding. Parameters: `size` (output spatial dimensions), `padding`
(pre-crop pad pixels per side), `padding_mode` (`reflect`, `replicate`,
`zero`, `constant`).

**Why.** The canonical image-classification augmentation since Krizhevsky
et al. 2012. Pre-crop padding plus random crop is the standard form;
without it, recipes either omit one of the most important augmentations
or push the augmentation declaration outside the recipe surface (into
framework-specific training code) and lose the visibility and
reproducibility benefits.

### FR-AUG-2: `horizontal_flip`

**What.** Policy declaring random horizontal flip with parameter `p`
(probability per sample, default 0.5).

**Why.** Near-universal in image classification — cheap, low-risk, broadly
effective. Recipes that don't declare it explicitly typically inherit it
from framework defaults, which leaves it invisible to anyone reading the
recipe.

### FR-AUG-3: `color_jitter`

**What.** Policy declaring random color-space perturbations. Parameters:
`brightness`, `contrast`, `saturation`, `hue` (each a float describing the
maximum perturbation magnitude per dimension).

**Why.** Color-space regularization improves generalization in
classification tasks where color co-occurrence statistics could be learned
as spurious features. Hue jitter specifically is task-dependent — for
classes where hue is class-discriminative (e.g., distinguishing red and
blue objects of the same shape) it should be set conservatively or to
zero; for other tasks it can be increased. Exposing each dimension as a
separate parameter lets recipes tune the policy to the dataset.

### FR-AUG-4: `random_erasing`

**What.** Policy declaring random rectangular masking of image regions
during training. Parameters: `p`, `scale` (range of masked area as
fraction of image area), `ratio` (range of aspect ratio of the mask).

**Why.** A modern regularization technique (Zhong et al. 2020) commonly
used as a contrast or complement to dropout and weight decay. Useful in
ablation studies comparing regularization strategies and in any setting
where occlusion robustness matters.

**Open question for all four.** Whether DataRefinery declares these as
opaque policy strings (passed verbatim to ModelFoundry) or with schema-
validated parameter dicts. Schema-validated is better for report quality
and recipe error messages; opaque is easier to implement and forwards
changes downstream automatically.

---

## Visualization Operations

All four are reporting-mode visualizations: rendered once during
materialization, persisted into the instance's report directory, and never
re-rendered. Pure Matplotlib + Pillow; no framework or model dependency.

### FR-VIZ-1: `pixel_distribution`

**What.** Per-channel pixel-value histograms across a named split, output
as a PNG figure with three subplots (R, G, B). Parameters: `bins`, `splits`.

**Why.** Pixel-value distributions surface the effect of normalization,
casting, and pixel-space transformations in a way that record-count or
class-distribution histograms cannot. Comparing pre- and post-normalize
distributions makes the centering-and-scaling effect of normalization
numerically visible, which is useful for debugging normalization
parameters, for documentation, and for any audience (technical reviewer,
collaborator, student) trying to understand what a pipeline did to its
input. The existing `class_distribution_histogram` and `sample_grid`
visualizations don't address pixel-value distribution.

### FR-VIZ-2: `augmented_sample_grid`

**What.** A grid showing N held-out images, each rendered K times with
the recipe's declared augmentation policy applied with K different seeds.
Parameters: `n_base`, `n_variants`, `seed`.

**Why.** Augmentation policies (FR-AUG-* and existing FR-11) are
non-materialized — they're declared in the recipe and realized at
training time by ModelFoundry. Without a visualization step, the policy
exists only as text and parameters; nobody reading the recipe or the
report sees what the augmentations actually do to images. The
`augmented_sample_grid` materializes a few deterministic, seeded examples
into the report so the policy is visible as concrete output, not just as
declared intent.

### FR-VIZ-3: `corruption_severity_grid`

**What.** A K-corruption × L-severity grid showing the same set of base
images under each (corruption, severity) combination. Parameters:
`n_images`, `corruption_types`, `severities`.

**Why.** The output of a corruption-generation pipeline (FR-GEN-1) is
otherwise just a flat collection of records tagged with corruption and
severity metadata. A 2-D grid laying out the two metadata dimensions
makes the corruption space visible at a glance — useful for sanity-
checking that each corruption type produces visually distinct output, for
documentation in reports, and for any audience trying to understand the
robustness evaluation's coverage.

### FR-VIZ-4: `severity_ladder`

**What.** N example images, each rendered at every severity of a single
corruption type, arranged as a ladder (one row per image, one column per
severity). Parameters: `n_examples`, `corruption_type`.

**Why.** Complements `corruption_severity_grid` by isolating the severity
dimension. Useful when explaining or documenting a single corruption
type's behavior across severity levels without the visual noise of other
corruption types in the same figure.

---

## Architectural

### FR-ARCH-1: Multi-instance cache identity

**What.** When a recipe declares `stats_from_instance` (FR-TRANS-1), the
referenced sibling instance's `recipe_hash` becomes a component of the
current recipe's cache identity. If the referenced recipe changes (and so
its hash changes), the current recipe's cache entry is invalidated.

Two implementation directions exist; the choice affects spec semantics:

- **Loose coupling.** The recipe declares the sibling by name or path; no
  hash dependency is recorded. Cache identity does not track the sibling.
  Re-materializing the upstream recipe does not automatically invalidate
  the downstream recipe's cache. The user is responsible for
  re-materializing downstream when upstream changes.
- **Tight coupling.** The recipe declares the sibling and DataRefinery
  records the sibling's `recipe_hash` as part of the current recipe's
  cache key. Re-materializing upstream automatically invalidates
  downstream caches.

**Why.** Any feature that imports computed state from a sibling instance —
fitted normalization statistics (FR-TRANS-1), and any future analogue
(fitted vocabularies, learned embeddings, indices, calibration tables) —
has the same dependency-tracking question. If the upstream instance is
re-materialized with different inputs or parameters, downstream cached
instances become silently stale: their imported state no longer matches
any actual upstream instance. Tight coupling closes this hole
automatically; loose coupling requires the user to remember the
dependency.

**Open question.** Loose for an initial release (cheaper, faster to ship,
less risk of cache-thrashing bugs) and tight for a follow-up? Or commit
to tight from the start? Loose-coupling failure modes are detectable in
small-scale single-author workflows; in multi-team or longitudinal
workflows the failure mode is much harder to catch.

---

## Dependencies and Suggested Order

Read top-to-bottom; later items depend on earlier ones being decided
(not necessarily implemented).

1. **FR-FILTER-1, FR-FILTER-3.** No dependencies on other features in
   this spec. Build first.
2. **FR-GEN-1.** Independent of filter work. Builds in parallel with #1.
3. **FR-TRANS-1.** Depends on a cache-identity decision (FR-ARCH-1) — at
   minimum the loose-coupling variant.
4. **FR-ARCH-1 (decision).** Decide loose vs. tight coupling before
   implementing FR-TRANS-1. Recommendation: ship loose, file tight as a
   follow-up.
5. **FR-FILTER-2.** Builds after #1 since it shares the labeling
   mechanism. Can be deferred if downstream consumers can chain
   individual filters instead.
6. **FR-AUG-1 through FR-AUG-4.** Build as one feature set. Schema-
   validated vs. opaque-string is the one open question.
7. **FR-VIZ-1 through FR-VIZ-4.** Can be implemented independently and
   in any order. Lowest priority; non-blocking.

A "minimum viable" feature set sufficient for the most demanding pattern
this spec addresses (two sibling recipes where one consumes the other's
fitted statistics, plus on-the-fly corruption generation downstream) is:
FR-FILTER-1, FR-FILTER-3, FR-GEN-1, FR-TRANS-1, and FR-ARCH-1 (loose).
FR-AUG-1 and FR-AUG-2 are recommended additions for any image-
classification recipe that declares augmentation policy. Everything else
improves recipe readability or report quality but isn't strictly required
for materialization.
