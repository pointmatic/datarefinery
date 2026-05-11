# Recipe authoring guide

A DataRefinery **recipe** is a single YAML file that fully describes a
data-preparation pipeline: where the raw inputs live, what the prepared
dataset should look like, how to split it, what transformations and
augmentations to apply, what to verify before and after, and what to
visualize. Running the same recipe over the same inputs with the same
seed produces a byte-identical materialized **instance** — the recipe
itself, the prepared dataset, the fitted statistics, and a report.

This guide is a section-by-section walk-through of the recipe surface.
For the high-level motivation see [`concept.md`](../specs/concept.md);
for the formal requirements see [`features.md`](../specs/features.md);
for implementation depth see [`tech-spec.md`](../specs/tech-spec.md).

For a working quickstart, see the [project README](../../README.md#quickstart).

## Reference recipe

Every snippet in this guide slots into the reference recipe below. It is
a complete, materializable `image_classification` recipe — the same
shape that `datarefinery init --input <image_folder>` produces, expanded
with a fit-on-train normalize transformation, an `image_classification`
augmentation, an `InputContract`, an `OutputExpectation`, and a `variants`
block. Substitute your own input path under `Input.sources[0].path`.

```yaml
# reference-recipe.yaml
schema_version: 1
plugin: image_classification
seed: 0

Input:
  sources:
    - name: train
      type: image_folder
      path: my-images          # directory of class-named subfolders

Output:
  record_schema:
    image: { dtype: uint8, shape: [8, 8, 3] }
    label: { dtype: str }
    path:  { dtype: str }

Labels:
  field: label
  source:
    kind: derived
    derivation: parent_directory_name

InputContracts:
  - assertion: { kind: record_count, min: 10 }
    severity: error

Splits:
  ratios: { train: 0.7, val: 0.15, test: 0.15 }
  seed: 11
  stratify_by: label

Transformations:
  - name: norm
    op: normalize
    fit_source: train
    splits: [train, val, test]

Augmentations:
  - name: hflip
    op: horizontal_flip
    params: { p: 0.5, seed: 42 }
    splits: [train]
    seed: 42

Featurizations:
  - name: derive_label
    inputs: [path]
    output_field: label
    op: label_from_path
    params: { source: parent_directory_name }
    splits: [train, val, test]

OutputExpectations:
  - field: label
    assertion: { kind: required_field }
    severity: error

Visualizations:
  - name: class_distribution
    op: class_distribution_histogram
    stage: post_pipeline
    mode: reporting
  - name: samples
    op: sample_grid
    params: { n: 16, per_class: true }
    stage: post_pipeline
    mode: reporting

variants:
  no_augment:
    Augmentations: []
```

Materialize it:

```bash
datarefinery validate reference-recipe.yaml
datarefinery --cache-root ./cache materialize reference-recipe.yaml
datarefinery --cache-root ./cache --variant no_augment materialize reference-recipe.yaml
```

`--variant` is a global option, placed before the verb.

The two materializations produce two different instances; the variant
overlay changes the canonical recipe bytes and therefore the cache
identity.

## Top-level keys

| Field | Required | Purpose |
|-------|----------|---------|
| `schema_version` | yes | Recipe schema version; load-time refusal of unknown values (FR-1). |
| `plugin` | yes | Plugin name that supplies the operations referenced in this recipe. |
| `seed` | no (default `0`) | Recipe-level seed. Combined with the canonical recipe hash and the raw-input hash to form the cache identity. |
| `Input` | yes | Raw data sources (FR see-below). |
| `Output` | yes | Record schema the materialized dataset must satisfy. |
| `Labels` | yes | Where labels come from. |
| `Splits` | yes | Train/val/test partitioning. |
| `SampleData`, `InputContracts`, `Filters`, `Generation`, `Transformations`, `Augmentations`, `Featurizations`, `OutputExpectations`, `Visualizations` | no | Optional pipeline stages and assertions, each defaulting to empty. |
| `variants` | no | Named overlays on any section. |

The recipe is the single source of truth for pipeline semantics. CLI
flags and environment variables control only **execution context** —
cache root, log level, plugin path, workers — and never alter what the
pipeline does. The one sanctioned exception is `--seed`, which is the
documented ad-hoc-run knob and changes the cache identity (so a
different instance is produced).

## Section walk-through

### `Input`

Declares the raw sources the pipeline reads.

```yaml
Input:
  sources:
    - name: train
      type: image_folder
      path: my-images
```

Each source has a `name` (referenced from Generation/Featurization
inputs), a `type` (plugin-specific; the `image_classification` plugin
ships `image_folder`), and a `path` to the raw data. Sources are loaded
deterministically — directory iteration is sorted so the input hash is
stable across machines.

### `Output`

Declares the record schema the materialized dataset must satisfy. Field
names, dtypes, and (for tensor fields) shapes form the structural
contract downstream tools bind against.

```yaml
Output:
  record_schema:
    image: { dtype: uint8, shape: [8, 8, 3] }
    label: { dtype: str }
    path:  { dtype: str }
```

`Output` is structural — value-range and distributional checks live in
`OutputExpectations`.

### `Labels`

Declares the label field name and its source.

```yaml
Labels:
  field: label
  source:
    kind: derived            # or "direct"
    derivation: parent_directory_name
```

A **direct** label cites a source field already present in the input. A
**derived** label is produced by a Featurization (FR-22) — the
`derive_label` Featurization in the reference recipe uses the
`label_from_path` op to read the class name from each file's parent
directory.

### `SampleData` (optional)

Declares a selector for a small inline sample of the inputs. Provide
exactly one of `n` (record count, ≥ 1) or `fraction` (in the open
interval `(0, 1)`), with an optional `seed`:

```yaml
SampleData:
  selector: { n: 4, seed: 7 }
```

`SampleData` is a recipe-level declaration; the validator (check 16)
checks the selector is well-formed. It is part of the recipe surface
so downstream tools and future smoke-run flags can resolve a stable,
recipe-declared sample without re-deciding what "a small subset" means
per consumer.

### `InputContracts`

Pre-pipeline assertions on the raw inputs. Failures abort
materialization before any expensive work (FR-23).

```yaml
InputContracts:
  - assertion: { kind: record_count, min: 10, max: 1_000_000 }
    severity: error
  - field: path
    assertion: { kind: required_field }
    severity: error
```

Assertion kinds:

| `kind` | Required keys | Optional keys | What it checks |
|--------|---------------|---------------|-----------------|
| `record_count` | one of `min`/`max` | — | Total record count is in bounds. |
| `required_field` | `field` (on the contract) | — | Field is present and non-`None` in every record. |
| `dtype` | `field`, `expected` (Python dtype tag like `int64`, `float32`, `str`) | — | Field values match the expected Python dtype. |
| `range` | `field`, one of `min`/`max` | — | Numeric field values are within `[min, max]`. |
| `distributional` | `field`, `kind: distributional`, plus distributional params | — | Distribution-shape checks (see `pipeline/contracts.py`). |

`severity: warning` records the violation in the manifest but does not
fail materialization; `severity: error` aborts.

### `Filters` (optional)

Remove records by predicate. Each filter declares the **stages** it
runs at (`pre_split`, `post_split`) and the **splits** it applies to
(when `post_split`):

```yaml
Filters:
  - name: drop_other
    predicate:
      op: filter_by_label
      labels: [other]
      action: exclude
    stages: [pre_split]
  - name: subsample_train
    predicate:
      op: random_sample
      fraction: 0.5
      seed: 13
    stages: [post_split]
    splits: [train]
```

The `predicate.op` field names a plugin operation in the `Filters`
section; the rest of `predicate` becomes operation parameters. Sampling
filters **must declare a seed** — the validator rejects them otherwise.
Filters are also the place to handle class imbalance by *removing*
records — see [Filters vs Splits for class imbalance](#filters-vs-splits-for-class-imbalance).

### `Generation` (optional)

Synthesize new records. Each Generation op declares its inputs, an
output schema (must match the recipe's `Output`), a seed, and the
splits it applies to (default `[train]`):

```yaml
Generation:
  - name: oversample_minority
    inputs: [train]
    output_schema:
      image: { dtype: uint8, shape: [8, 8, 3] }
      label: { dtype: str }
      path:  { dtype: str }
    seed: 99
    applies_at: [train]
```

Generation changes the record count; counts are recorded in the
manifest and the report. Generated records must satisfy
`OutputExpectations`.

### `Splits`

Partition records into train / val / test (FR-7).

```yaml
Splits:
  ratios: { train: 0.7, val: 0.15, test: 0.15 }
  seed: 11
  stratify_by: label
```

- `ratios` sums to ≤ 1.0; any remainder is unassigned (recorded in the
  manifest).
- `stratify_by` keeps a categorical field's per-class distribution
  proportional across splits.
- `seed` defaults to the recipe-level `seed` if omitted.
- For deterministic non-ratio splitting, use `key_assignment` with a
  field-to-split mapping instead of `ratios`.
- `class_balance` lets ModelFoundry honor a sampling strategy at
  training time — that handles class imbalance without removing data.

### `Transformations`

Deterministic per-record operations: resize, normalize, cast dtype,
etc. Each transformation declares the splits it applies to and,
optionally, a **fit source** (the split whose statistics are
persisted):

```yaml
Transformations:
  - name: norm
    op: normalize
    fit_source: train
    splits: [train, val, test]
```

`fit_source: train` means: compute the normalize statistics over the
training split, persist them to `fitted_statistics/norm/`, and apply
them to every split listed under `splits`. This is the
**fit-on-train discipline** that prevents train/inference skew — see
the dedicated section [below](#fit-on-train-discipline).

The validator rejects a fit-on-train op whose `fit_source` is not
`train` (check 6).

### `Augmentations`

Stochastic, train-only operations that expand the *effective* dataset
without changing the record count. Each augmentation declares its
parameters, the splits it applies to (train-only by default, val/test
rejected by validator check 5), and a seed:

```yaml
Augmentations:
  - name: hflip
    op: horizontal_flip
    params: { p: 0.5, seed: 42 }
    splits: [train]
    seed: 42
```

Augmentations are **described** in the recipe; they apply on-the-fly
during training and are not persisted as new records. To disable
augmentation for a comparison run, use a variant — see [Variants](#variants).

### `Featurizations`

Derive new fields from existing inputs. The reference recipe uses one
to derive the label field from the file path:

```yaml
Featurizations:
  - name: derive_label
    inputs: [path]
    output_field: label
    op: label_from_path
    params: { source: parent_directory_name }
    splits: [train, val, test]
```

Featurizations may be deterministic or fit-on-train; fit-on-train
featurizations follow the same `fit_source: train` rules as
Transformations.

### `OutputExpectations`

Post-pipeline assertions on the materialized records. Same assertion
shape as `InputContracts`, run after the final pipeline stage. Failures
abort the run at end-of-pipeline; the partial instance is left in the
cache's `.tmp/<run-id>/` directory under the `FAILED` marker for
diagnosis (FR-5 atomic temp-then-promote).

```yaml
OutputExpectations:
  - field: label
    assertion: { kind: required_field }
    severity: error
  - field: image
    assertion: { kind: dtype, expected: uint8 }
    severity: error
```

### `Visualizations`

Render standard or bespoke views over a pipeline stage. Each
visualization declares the stage it observes and an output **mode**:

- `reporting` — rendered during materialization, persisted to
  `report/visualizations/`. Failures fail the materialization (the
  report is not partial).
- `exploration` — rendered on demand via the library API or
  `datarefinery inspect`; not persisted.

```yaml
Visualizations:
  - name: class_distribution
    op: class_distribution_histogram
    stage: post_pipeline
    mode: reporting
  - name: samples
    op: sample_grid
    params: { n: 16, per_class: true }
    stage: post_pipeline
    mode: reporting
```

### `variants`

Named overlays on any section, applied **before** canonicalization and
hashing so the cache identity reflects the selected variant.

```yaml
variants:
  no_augment:
    Augmentations: []
  big_train:
    Splits:
      ratios: { train: 0.9, val: 0.05, test: 0.05 }
      seed: 11
      stratify_by: label
```

Select at materialize time (`--variant` is a global option, placed
before the verb):

```bash
datarefinery --cache-root ./cache --variant no_augment materialize reference-recipe.yaml
```

Variants are how you express experiment knobs (different augmentation
policies, different split ratios, different class-balance strategies)
without forking the recipe or routing flags around the recipe surface.
See [Variants](#variants-1) below for the design rationale.

## Fit-on-train discipline

The most common source of train/inference skew is fitting normalizers
or encoders on the full dataset (including val/test). DataRefinery
prevents this structurally:

- A Transformation or Featurization that needs to learn parameters
  from data declares `fit_source: train`.
- The validator (check 6) refuses any `fit_source` that is not
  `train`.
- The pipeline fits the operation on the training split only,
  persists the resulting statistics to
  `fitted_statistics/<op_name>/`, then applies the operation to every
  split in `splits` using the persisted statistics.
- Inference-time tools (ModelMachine) replay the same recipe against
  new inputs and read the persisted statistics from
  `fitted_statistics/` — there is no "re-fit at inference" path to
  drift from.

In the reference recipe:

```yaml
Transformations:
  - name: norm
    op: normalize
    fit_source: train
    splits: [train, val, test]
```

After materialization, the cached instance contains:

```text
fitted_statistics/
└── norm/
    ├── mean.parquet
    └── std.parquet
```

These files are written in structured format (parquet for numeric
stats); the v1 contract is "no opaque pickles." Operations that do not
need fitting omit `fit_source` entirely.

## Variants

Variants are named overlays that produce different materializations
from one recipe. A typical recipe has a default behavior and a few
named experiments:

```yaml
variants:
  no_augment:
    Augmentations: []
  light_aug:
    Augmentations:
      - name: hflip
        op: horizontal_flip
        params: { p: 0.5, seed: 42 }
        splits: [train]
        seed: 42
  heavy_aug:
    Augmentations:
      - name: hflip
        op: horizontal_flip
        params: { p: 0.5, seed: 42 }
        splits: [train]
        seed: 42
      - name: crop
        op: random_crop
        params: { size: 8, seed: 43 }
        splits: [train]
        seed: 43
```

Three things follow from this design:

1. **Variants are part of the cache identity.** The overlay is applied
   before canonicalization, so two variant selections produce two
   different cached instances. Re-running with the same variant
   selection is a cache hit; switching variants is a cache miss the
   first time and a hit thereafter.
2. **Variants can override any section.** Use them to vary
   augmentation policy, split ratios, class-balance strategy,
   filters, generation, or any combination — not just `Augmentations`.
3. **Variants are scoped to one recipe.** This keeps experiments
   discoverable inside one file rather than across forked copies. If
   the experiment changes the pipeline semantics in a way that no
   longer makes sense as an overlay (e.g. swapping the plugin), it is
   a different recipe.

The validator (check 12) rejects a variant that references an
undeclared section or key.

## Contracts and expectations

`InputContracts` and `OutputExpectations` are the recipe's correctness
gates around the pipeline. They share the same assertion shape but run
at different stages:

- `InputContracts` runs on the **raw inputs**, before any pipeline
  work. Cheap-to-detect data problems abort early.
- `OutputExpectations` runs on the **materialized records** after the
  final pipeline stage. Used to assert the shape and value ranges of
  what downstream tools will consume.

A combined example:

```yaml
InputContracts:
  - assertion: { kind: record_count, min: 100 }
    severity: error
  - field: path
    assertion: { kind: required_field }
    severity: error

OutputExpectations:
  - field: label
    assertion: { kind: required_field }
    severity: error
  - field: image
    assertion: { kind: dtype, expected: uint8 }
    severity: error
```

Two design notes:

- **`Output` vs. `OutputExpectations`.** `Output` is the structural
  contract — record shape, field names, dtypes — that downstream tools
  bind against. `OutputExpectations` is the *value* contract — things
  you cannot express in a schema (record-count bounds, value ranges,
  distributional checks).
- **`severity: warning`** records the violation in the manifest but
  does not fail the run. Use it for distributional checks that are
  legitimately violated by small inputs (e.g. a fixture too small for
  a meaningful KS test).

## Filters vs Splits for class imbalance

Class imbalance shows up in almost every classification dataset. The
v1 recipe surface splits the response cleanly along a single axis —
*are you removing data, or weighting it at training time?*

- **Remove data → `Filters`.** Filters reduce the raw set by
  predicate; the surviving records flow into Splits. Use Filters when
  the imbalance is severe enough that downstream training would learn
  the prior more than the signal — undersample the majority class,
  drop a too-sparse minority class, subsample to a target ratio.

  ```yaml
  Filters:
    - name: cap_majority
      predicate:
        op: random_sample
        fraction: 0.3
        seed: 13
      stages: [pre_split]
  ```

  Removed records do not appear in any split and do not factor into
  any downstream metric.

- **Weight at training time → `Splits.class_balance`.** When the
  imbalance is not severe enough to warrant data loss, declare a
  sampling strategy on Splits. ModelFoundry honors it during training
  (e.g. a `WeightedRandomSampler`); the train split itself still
  contains every record.

  ```yaml
  Splits:
    ratios: { train: 0.7, val: 0.15, test: 0.15 }
    seed: 11
    stratify_by: label
    class_balance: weighted_sampling
  ```

  No records are dropped; the imbalance is corrected at iteration
  time, not at materialization time.

When in doubt, prefer `Splits.class_balance`. Filters are a heavier
hammer — they delete information from the instance, so the same recipe
cannot be re-used to study the un-balanced distribution without
authoring a variant that disables the filter.

Use a variant if you want to experiment with both:

```yaml
variants:
  no_balance:
    Splits:
      ratios: { train: 0.7, val: 0.15, test: 0.15 }
      seed: 11
      stratify_by: label
```

## Where to go next

- The [project README](../../README.md) covers install, quickstart,
  CLI verbs, and the library API.
- [`features.md`](../specs/features.md) is the canonical reference for
  every recipe section (FR-1 through FR-23) and the validator checks.
- [`tech-spec.md`](../specs/tech-spec.md) covers the cache identity
  algorithm, the canonicalization rules, fitted-statistics layout,
  and the pipeline runner.
- The plugin-authoring guide (forthcoming, Story F.c) covers writing
  your own plugin: declaring `OperationSpec`s, the `Plugin` protocol,
  and the entry-point registration.
