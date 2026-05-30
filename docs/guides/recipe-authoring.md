# Recipe authoring guide

A DataRefinery **recipe** is a single YAML file that fully describes a data-preparation pipeline: where the raw inputs live, what the prepared dataset should look like, how to split it, what transformations and augmentations to apply, what to verify before and after, and what to visualize. Running the same recipe over the same inputs with the same seed produces a byte-identical materialized **instance** — the recipe itself, the prepared dataset, the fitted statistics, and a report.

This guide is a section-by-section walk-through of the recipe surface.
For the high-level motivation see [`concept.md`](../specs/concept.md);
for the formal requirements see [`features.md`](../specs/features.md);
for implementation depth see [`tech-spec.md`](../specs/tech-spec.md).

For a working quickstart, see the [project README](../../README.md#quickstart).

## Reference recipe

Every snippet in this guide slots into the reference recipe below. It is a complete, materializable `image_classification` recipe — the same shape that `datarefinery init --input <image_folder>` produces, expanded with a fit-on-train normalize transformation, an `image_classification` augmentation, an `InputContract`, an `OutputExpectation`, and a `variants` block. Substitute your own input path under `Input.sources[0].path`.

```yaml
# reference-recipe.yaml
schema_version: 2
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
  - assertion: { kind: record_count_in_range, min: 10 }
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

The two materializations produce two different instances; the variant overlay changes the canonical recipe bytes and therefore the cache identity.

## Top-level keys

| Field | Required | Purpose |
|-------|----------|---------|
| `schema_version` | yes | Recipe schema version. Supported values: `1` (auto-migrated to v2 at load time) and `2` (current). New recipes should write `2`. The loader rejects unknown values (FR-1). |
| `plugin` | yes | Plugin name that supplies the operations referenced in this recipe. |
| `seed` | no (default `0`) | Recipe-level seed. Combined with the canonical recipe hash and the raw-input hash to form the cache identity. |
| `Input` | yes | Raw data sources (FR see-below). |
| `Output` | yes | Record schema the materialized dataset must satisfy. |
| `Labels` | yes | Where labels come from. |
| `Splits` | yes | Train/val/test partitioning. |
| `SampleData`, `InputContracts`, `Filters`, `Generation`, `Transformations`, `Augmentations`, `Featurizations`, `OutputExpectations`, `Visualizations` | no | Optional pipeline stages and assertions, each defaulting to empty. |
| `variants` | no | Named overlays on any section. |

The recipe is the single source of truth for pipeline semantics. CLI flags and environment variables control only **execution context** — cache root, log level, plugin path, workers — and never alter what the pipeline does. The one sanctioned exception is `--seed`, which is the documented ad-hoc-run knob and changes the cache identity (so a different instance is produced).

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

Each source has a `name` (referenced from Generation/Featurization inputs), a `type` (plugin-specific), and a `path` to the raw data. Sources are loaded deterministically — directory iteration is sorted so the input hash is stable across machines.

The `image_classification` plugin ships two source types:

- `image_folder` — ImageFolder layout (`<root>/<class>/<file>.{png,jpg}`). Class names come from the subdirectory names. Labels are intrinsic to the directory structure; no manifest is needed (and `label_from` must not be set — validator check 19 rejects it).
- `image_flat` — flat directory of images (subdirs allowed but the path is opaque). Requires a sidecar manifest declared via `label_from`. The manifest provides the labels; there is no class-from-subdir fallback.

```yaml
# image_flat + by_id (most common third-party shape)
Input:
  sources:
    - name: images
      type: image_flat
      path: ./data/images
      label_from:
        path: ./data/labels.csv
        join: by_id          # match each image to a manifest row by id
        id_field: id         # CSV column containing the join key
        label_field: class   # CSV column to emit as the label

# image_flat + by_id, headerless manifest (recipe declares column names)
Input:
  sources:
    - name: images
      type: image_flat
      path: ./data/images
      label_from:
        path: ./data/labels.txt
        join: by_id
        header: [id, class]   # treat file as headerless; use these names
        id_field: id
        label_field: class

# image_flat + by_row_order (CIFAR-style: one label per line, parallel to inputs)
Input:
  sources:
    - name: images
      type: image_flat
      path: ./data/images
      label_from:
        path: ./data/labels.txt
        join: by_row_order
        header: [class]
        label_field: class
```

**`label_from` rules and semantics:**

- **Join key for `by_id`:** the image's filename **stem** (e.g., `img_001.jpg` → `img_001`). The id column in the manifest must match the stem. Manifest rows with no matching image are silently ignored; images with no matching manifest row are a `MaterializeError`.
- **`by_row_order`:** the manifest's row count must equal the source directory's enumerated image count (sorted-paths order). Brittle by nature — prefer `by_id` for new datasets; `by_row_order` exists for legacy formats like CIFAR-10's `labels.txt`.
- **`header` (recipe-as-truth):** when present, the file is treated as headerless and the recipe-supplied names *are* the column names. If the file actually contains a header line, it is read as a data row 
  — by design. Ingestion is a one-time configuration step; we trust the recipe author rather than add heuristic detection.
- **Duplicate ids in the manifest** → `MaterializeError` at load time.
- **Path resolution** is the same as `Input.sources[*].path` (interpreted as the user wrote it; use absolute paths or run from the recipe's directory).
- **Cache identity:** the manifest's bytes feed the input hash for `image_flat` sources, so edits to `labels.csv` invalidate the cache without re-touching any image.

#### Pre-partitioned sources

Many third-party datasets ship pre-partitioned: `train/` is authored by the publisher and `test/` is intended to remain heldout from training. DataRefinery honors this directly via `InputSource.partition`: each source declares which split it belongs to, the loader stamps the declared value onto every record from that source, and the Splits stage either accepts the source partitions verbatim (Form A) or sub-partitions one of them (Form B — typically to carve `val` out of `train`).

```yaml
# Form A — declared partitions are final; Splits is omitted.
Input:
  sources:
    - name: train_data
      type: image_folder
      path: ./data/train
      partition: train
    - name: test_data
      type: image_folder
      path: ./data/test
      partition: test
Splits: {}                              # honor source partitions verbatim
```

```yaml
# Form B — carve val out of train, keep test heldout.
Input:
  sources:
    - name: train_data
      type: image_folder
      path: ./data/train
      partition: train
    - name: test_data
      type: image_folder
      path: ./data/test
      partition: test
Splits:
  ratios: { train: 0.85, val: 0.15 }
  applies_to: train                     # only sub-partition this partition
  stratify_by: label
  seed: 7
```

**Rules:**

- **All-or-nothing.** If any source declares `partition`, every source must. (Mixed mode is rejected by validator check 20.)
- **`partition` is a reserved record-field name.** The loader stamps it on every record, analogous to `record_id`. Don't declare `partition` in `Output.record_schema` — check 20 rejects that too.
- **`applies_to` is a single string.** One partition can be sub-partitioned per recipe. Multi-target sub-partitioning is out of scope for v1.
- **Sub-partition names must not collide with sibling partitions.** If you declare `partition: test` on a source and then write `ratios: { train: 0.5, test: 0.5 }` under `applies_to: train`, check 20 fails — the `test` from ratios would shadow the heldout `test` partition.
- **No `partition` declared anywhere** → existing global-pool behavior: loader concatenates per-source records and `Splits` partitions the whole stream as before. Backward-compatible.

#### Unlabeled partitions

Some pre-partitioned datasets ship a labeled training set together with an unlabeled heldout partition intended for downstream inference (the classic Kaggle shape: `train.csv` with labels + `test.csv` with no labels). Declare such a source with `unlabeled: true`:

```yaml
Input:
  sources:
    - name: train_data
      type: image_folder
      path: ./data/train
      partition: train
    - name: test_data
      type: image_flat                 # flat layout, no label_from
      path: ./data/test
      partition: test
      unlabeled: true                  # NEW
Labels:
  field: label
  source: { kind: direct }             # labels exist for labeled partitions
Splits:
  ratios: { train: 0.85, val: 0.15 }
  applies_to: train                    # sub-partition only the labeled side
  stratify_by: label                   # stratifies within train; safe because
                                       # applies_to is the labeled partition
```

**What happens:**

- The loader walks `test_data` like any `image_flat` source but does not read a manifest and does not attach a `label` field to records. Records flow through label-independent stages (resize, normalize, augmentation) normally.
- Label-dependent stages refuse to operate on unlabeled splits at **validate time** (check 21):
  - `Splits.stratify_by` with `applies_to: <unlabeled-partition>` → rejected.
  - Filters using `filter_by_label` whose `splits:` list contains an unlabeled split → rejected.
  - Featurizations using `label_from_path` (or whose `inputs` reference the label field) targeting an unlabeled split → rejected.
- `drift.json` reports `class_distribution: null` for unlabeled splits with a `"skipped: unlabeled"` note; `report.md` flags those splits with `*(unlabeled)*` in the Splits section.
- `OutputExpectations` whose `field` equals `Labels.field` treat records lacking the label as "skipped" rather than failures when any source declares `unlabeled: true`. Records where the label is present but `None` still fail. This lets `required_field: label` coexist with an unlabeled partition.

**Rules:**

- `unlabeled: true` requires `partition: <name>` on the same source (model-level validation; no recipe can mix unlabeled records into a global pool).
- `unlabeled: true` is incompatible with `label_from` (a sidecar manifest provides labels, contradicting unlabeled-ness).
- `unlabeled: true` requires `type: image_flat` in v1 (check 21). `image_folder` derives labels from class subdirectories, which would contradict the declaration. Users with an existing flat-directory `image_folder` layout just rewrite it as `image_flat`.
- Sub-partitioning an unlabeled partition is allowed. The resulting sub-splits are also unlabeled.

**Downstream inference pattern.** The materialized instance contains labeled `train`/`val` splits and an unlabeled `test` split as `dataset/test.jsonl`. Train a model on `train`+`val`; run it against the records in `test.jsonl` to produce predictions. That last step is external to DataRefinery (per `concept.md` non-goals); the unlabeled partition's job is to *exist* in the materialized instance for downstream tooling to consume.

### `Output`

Declares the record schema the materialized dataset must satisfy. Field names, dtypes, and (for tensor fields) shapes form the structural contract downstream tools bind against.

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

Declares the label field name and where it comes from.

```yaml
# Form A: direct — labels arrive on the record at load time.
Labels:
  field: label
  source:
    kind: direct

# Form B: derived — labels are produced by a Featurization.
Labels:
  field: label
  source:
    kind: derived
    derivation: parent_directory_name   # identifier the Featurization keys off
```

| Field | Required | Purpose |
|-------|----------|---------|
| `field` | yes | Record-field name the label is written into (`record["label"]`). |
| `source.kind` | yes | `direct` or `derived`. |
| `source.derivation` | only when `kind == "derived"` | Identifier the responsible Featurization keys off; the reference recipe pairs `derivation: parent_directory_name` with a `label_from_path` Featurization that has `params: { source: parent_directory_name }`. |

**Direct** labels are populated by the input loader; two routes for `image_classification`:

- `image_folder` source — the loader reads the class name from each   image's parent directory.
- `image_flat` source with `label_from` (see `Input`) — the loader joins against a sidecar manifest at load time.

**Derived** labels are produced by a Featurization (FR-22), letting you compute labels from path components, joined sidecar data, or any other
record field. Use this when neither of the direct routes fits — for example, when the label has to be parsed out of the image filename itself rather than the folder structure.

### `SampleData` (optional)

Declares a selector for a small representative sample. Provide exactly one of `n` (record count, ≥ 1) or `fraction` (in the open interval `(0, 1)`), with an optional `seed`. Two further selector fields shape *what* is sampled:

- `kind` — `uniform` (default) samples without regard to class; `per_class` samples `n` records per label class (and therefore requires a label source — a recipe whose every Input source is `unlabeled` is rejected by the validator).
- `splits` — an optional list of split names to sample from (e.g. `[train]`); each entry must name a defined split. Omitted means "all".

```yaml
SampleData:
  selector:
    kind: per_class
    n: 1
    splits: [train]
    seed: 7
```

`SampleData` is a recipe-level declaration; the validator (check 16) checks the selector is well-formed (exactly one of `n`/`fraction`; `per_class` has a label source; `splits` entries are defined). The selector is part of the recipe surface and **participates in cache identity**.

> **Runtime status (v0.18.0).** The SampleData selector is **not yet honored at materialize time** — declaring it shapes cache identity and is validated, but it does not currently produce a sampled subset. The runtime (and the decision of whether the sample replaces the instance or is emitted as a sidecar artifact, and where in the pipeline it runs) is tracked as a separate, to-be-planned story. Authoring a `SampleData` block today is forward-looking, not a working subset.

### `InputContracts`

Pre-pipeline assertions on the raw inputs. Failures abort materialization before any expensive work (FR-23).

```yaml
InputContracts:
  - assertion: { kind: record_count_in_range, min: 10, max: 1_000_000 }
    severity: error
  - field: path
    assertion: { kind: required_field }
    severity: error
```

Assertion kinds:

| `kind` | Required keys | Optional keys | What it checks |
|--------|---------------|---------------|-----------------|
| `record_count_in_range` | one of `min`/`max` | — | Total record count is in bounds. |
| `required_field` | `field` (on the contract) | — | Field is present and non-`None` in every record. |
| `dtype_equals` | `field`, `expected` (dtype tag like `int64`, `float32`, `uint8`, `str`) | — | Field values match the expected dtype. Scalar fields are checked via Python `isinstance`; **ndarray fields** are checked via `v.dtype.name == expected`. |
| `value_range` | `field`, one of `min`/`max` | — | Numeric field values are within `[min, max]`. Scalar fields are compared directly; **ndarray fields** pass when every element is in `[min, max]` (checked via `v.min()` / `v.max()` reductions). |
| `distributional` | `field`, `kind: distributional`, plus distributional params | — | Distribution-shape checks (see `pipeline/contracts.py`). Placeholder in v1; always passes. |

`severity: warning` records the violation in the manifest but does not
fail materialization; `severity: error` aborts.

> **Schema v2 naming pass (Story I.x.3 / G16a).** v1 used bare-verb names — `record_count`, `dtype`, `range` — which collided with the recipe's structural vocabulary (`FieldSpec.dtype`, value ranges) and read awkwardly inside `assertion: { kind: ... }`. v2 lifts the three to predicate-sentence form. Recipes authored as `schema_version: 1` are auto-migrated by the loader; the v1 names are removed (not aliased), so any post-migration recipe using bare `dtype:` / `range:` / `record_count:` will fail dispatch with an "unknown assertion kind" error pointing at the v2 names. `required_field` and `distributional` already read as sentences and are unchanged.

**Tensor fields example.** When the recipe's `Output.record_schema`
declares a tensor field (e.g., `image: { dtype: uint8, shape: [32, 32, 3] }`),
`dtype_equals` and `value_range` assertions on that field apply element-wise:

```yaml
OutputExpectations:
  - field: image
    assertion: { kind: dtype_equals, expected: uint8 }   # ndarray dtype, not element type
    severity: error
  - field: image
    assertion: { kind: value_range, min: 0, max: 255 }   # every pixel in [0, 255]
    severity: error
```

### `Filters` (optional)

Remove or tag records by op. Each filter declares the **stages** it runs at (`pre_split`, `post_split`) and the **splits** it applies to (when `post_split`):

```yaml
Filters:
  - name: drop_other
    op: filter_by_label
    params: { labels: [other], action: exclude }
    stages: [pre_split]
  - name: subsample_train
    op: random_sample
    params: { fraction: 0.5 }
    seed: 13
    stages: [post_split]
    splits: [train]
```

A `FilterOp` carries:

- `name` — unique identifier; also the op-name in derived seeds (see [Seeds and determinism](#seeds-and-determinism)).
- `op` — the plugin operation in the `Filters` section (image plugin: `filter_by_label`, `random_sample`, `sample_per_class`, `sample_per_class_fractional`, `drop_by_label`; tabular stub: `drop_nulls`).
- `params` — the operation's parameters (no `op` or `seed` here in v2).
- `stages` — `[pre_split]` (default) or `[post_split]` or both. Pre-split filters apply to the raw record stream before splitting; post-split filters apply to the named `splits`.
- `splits` — required for `post_split`; the splits the filter targets.
- `seed` — top-level seed source for stochastic filters: either an integer or the master-derivation form `{ from: master }` (see [Seeds and determinism](#seeds-and-determinism)). Sampling filters **must** declare a seed — the runtime rejects them otherwise.

> **Schema v2 reshape (Story I.x.1 / G15).** In schema_version 1, `FilterOp` carried a single `predicate` dict that nested `op`, the params, and the seed all together. v2 lifts `op` and `seed` to top-level fields and renames the remaining keys to `params`, matching every other section. Recipes authored as `schema_version: 1` are migrated automatically by the loader — see [Top-level keys](#top-level-keys) for the migration ceremony.

**Image-classification Filters.**

`filter_by_label` (no fit, no seed) — keep or drop records whose label is in `labels`. `action: include` keeps matches; `action: exclude` drops them (default: `include`). Requires `Labels.field` to be set.

```yaml
Filters:
  - name: keep_two_classes
    op: filter_by_label
    params: { labels: [cat, dog], action: include }
    stages: [pre_split]
```

`random_sample` (seeded) — keep a fraction (`fraction`) or a fixed count (`n`) of records; exactly one is required. The seed is on `FilterOp`, not on `params`.

```yaml
Filters:
  - name: subsample
    op: random_sample
    params: { fraction: 0.1 }
    seed: 42
    stages: [pre_split]
```

`sample_per_class` (FR-FILTER-1, seeded) — balanced subsample: keep `n_per_class` records of each label, capped by availability. Optionally **tag** the surviving records via `label: <tag>` (does not drop the rest — the tag rides on the `sample_per_class_tags` field), and **exclude** records already carrying any of `exclude_already_labeled` from the candidate pool to compose disjoint-pool flows.

```yaml
Filters:
  - name: pick_train
    op: sample_per_class
    params: { n_per_class: 200, label: train_pool }
    seed: 1
    stages: [pre_split]
  - name: pick_holdout
    op: sample_per_class
    params: { n_per_class: 50, label: holdout, exclude_already_labeled: [train_pool] }
    seed: 1
    stages: [pre_split]
```

`sample_per_class_fractional` (FR-FILTER-2, seeded) — like `sample_per_class` but the per-class target is `floor(n_per_class_base * fractions[label])`. Each fraction must be in `[0.0, 1.0]`; missing labels default to `1.0`. Inherits the `label` / `exclude_already_labeled` tagging semantics.

```yaml
Filters:
  - name: fractional_pool
    op: sample_per_class_fractional
    params:
      n_per_class_base: 100
      fractions: { cat: 0.5, dog: 1.0 }
      label: pool
    seed: 7
    stages: [pre_split]
```

`drop_by_label` (FR-FILTER-3, no seed) — destructive complement to the tag ops: drop every record carrying any of the named tags in `sample_per_class_tags`. Use after a tagging filter to peel off a disjoint subset.

```yaml
Filters:
  - name: remove_pool
    op: drop_by_label
    params: { labels: [holdout] }
    stages: [pre_split]
```

Filters are also the place to handle class imbalance by *removing* records — see [Filters vs Splits for class imbalance](#filters-vs-splits-for-class-imbalance).

### `Generation` (optional)

Synthesize new records. Each Generation op declares an `op` (the plugin operation), its `inputs`, an output schema (must match the recipe's `Output`), a seed, and the splits it applies to (default `[train]`):

```yaml
Generation:
  - name: oversample_minority
    op: duplicate_minority_class
    inputs: [image, label]
    output_schema:
      image: { dtype: uint8, shape: [8, 8, 3] }
      label: { dtype: str }
      path:  { dtype: str }
    seed: 99
    splits: [train]
```

A `GenerationOp` carries:

- `name` — unique identifier; also the op-name in derived seeds (see [Seeds and determinism](#seeds-and-determinism)) and the prefix of any persisted per-record seed (`<name>_seed`).
- `op` — the plugin operation in the `Generation` section (image plugin: `duplicate_minority_class`, `imagecorruptions_apply`).
- `inputs` — record fields the op consumes.
- `output_schema` — either an explicit `dict[str, FieldSpec]` declaring every field the op writes, or the shorthand `"matches_input"` (see below).
- `seed` — integer literal or the master-derivation form `{ from: master }` (G11 / Story I.n).
- `splits` — splits the op runs against (default `[train]`).
- `params` — the operation's parameters.
- `replace_input_records` — see below.

> **Schema v2 reshape (Story I.x.2 / G12).** In schema_version 1, `GenerationOp` left the op-name implicit (the recipe's `name` doubled as both the recipe-author identifier and the operation lookup key), and called the splits field `applies_at`. v2 makes `op` explicit (matching every other section) and renames `applies_at` → `splits`. Recipes authored as `schema_version: 1` are auto-migrated by the loader — see [Top-level keys](#top-level-keys) for the migration ceremony.

#### `output_schema: matches_input` shorthand

When a Generation op preserves the input record shape and only adds tag fields (the canonical `imagecorruptions_apply` case), re-stating the full `output_schema` is busywork. The shorthand `output_schema: "matches_input"` resolves at materialize time to `Output.record_schema` plus any fields named in the op's `tag_fields` param. The runtime expansion looks up each tag field's `FieldSpec` from `Output.record_schema` (so you still declare `corruption`, `severity`, `source_path` there) and adds them to the per-op output schema.

```yaml
Generation:
  - name: corrupt
    op: imagecorruptions_apply
    inputs: [image]
    output_schema: matches_input        # expanded from Output.record_schema + tag_fields
    seed: 42
    splits: [train]
    params:
      corruption_types: [gaussian_noise, fog]
      severities: [1, 3]
      tag_fields: [corruption, severity, source_path]
```

Explicit dicts always work — use the shorthand when the op preserves the input shape and only adds declared tag fields; use the dict when the op writes new non-tag fields or omits any of the input fields.

Generation changes the record count; counts are recorded in the manifest and the report. Generated records must satisfy `OutputExpectations`.

#### When to use `replace_input_records`

By default a Generation op **augments** the split: its output records are appended to the existing records (the input records stay). Set `replace_input_records: true` to **replace** the split with only the generated records instead:

```yaml
Generation:
  - name: corrupt
    op: imagecorruptions_apply
    inputs: [image]
    output_schema:
      record_id: { dtype: str }
      image:     { dtype: uint8, shape: [64, 64, 3] }
      path:      { dtype: str }
    seed: 42
    splits: [train]
    replace_input_records: true       # output replaces the originals
    params:
      corruption_types: [gaussian_noise, fog]
      severities: [1, 3]
```

This is the transformation-style case: `imagecorruptions_apply` emits `n_corruptions × n_severities` records per input, and with `replace_input_records: true` the resulting split holds exactly `n_corruptions × n_severities × n_inputs` records — the pristine originals are dropped. Reach for it when the corrupted (or otherwise generated) records *are* the dataset, not an addition to it. Leave it at the default (`false`) for oversampling-style generation like `duplicate_minority_class`, where the originals must remain.

`replace_input_records` is part of the recipe's canonical bytes — toggling it produces a different cache instance.

#### `tag_fields` on `imagecorruptions_apply`

`tag_fields` controls which metadata the op stamps onto each output record. The canonical metadata names are **`corruption`**, **`severity`**, and **`source_path`**. Two authoring forms are accepted:

- **List form (legacy / default).** A subset of the canonical names; each named tag is written under its canonical key. Omit a name to suppress its tag.

  ```yaml
  Generation:
    - name: corrupt
      params:
        corruption_types: [gaussian_noise]
        severities: [3]
        tag_fields: [corruption, severity]    # source_path suppressed
  ```

- **Dict form (rename map, Story I.u / G13).** A `{authored_field_name: canonical_name}` mapping. Each output record receives the canonical tag's value under the *authored* key. Canonicals not listed are suppressed. Useful when downstream code expects a different column name (e.g. `corruption_kind` instead of `corruption`), or when avoiding a clash with another field on the record.

  ```yaml
  Generation:
    - name: corrupt
      params:
        corruption_types: [gaussian_noise]
        severities: [3]
        tag_fields:
          corruption_kind: corruption          # rename
          lvl: severity                        # rename
          # source_path omitted → not written
  ```

The model validator rejects a dict value that is not in `{corruption, severity, source_path}` and rejects duplicate canonical values (the rename map must be one-to-one). The list form is unchanged.

**Per-record-seed persistence (Story I.e).** Each Generation op that uses the per-record-seed contract (today: `imagecorruptions_apply`) stamps `<GenerationOp.name>_seed` (8-byte int) onto every output record. The field rides through to the cached JSONL and is captured automatically by any Sink targeting `post_Generation`. Downstream tools — including the forthcoming `datarefinery export` verb (Story I.f) — use this seed to reconstruct the op's stochastic output from the cached state, without re-running the full pipeline. Ops whose stochasticity is op-level (not per-record) — like `duplicate_minority_class` — do not stamp; the op-level seed already lives in `recipe.json` and the duplicated record's `record_id` points back at the source.

### `Splits`

Partition records into train / val / test (FR-7).

```yaml
Splits:
  ratios: { train: 0.7, val: 0.15, test: 0.15 }
  seed: 11
  stratify_by: label
```

- `ratios` sums to ≤ 1.0; any remainder is unassigned (recorded in the manifest).
- `stratify_by` keeps a categorical field's per-class distribution proportional across splits.
- `seed` defaults to the recipe-level `seed` if omitted.
- For deterministic non-ratio splitting, use `key_assignment` with a field-to-split mapping instead of `ratios`.
- `class_balance` lets ModelFoundry honor a sampling strategy at training time — that handles class imbalance without removing data.

#### Sub-partitioning via `applies_to`

When `Input.sources[*].partition` declares a pre-existing partitioning (see § Input → Pre-partitioned sources), `Splits.applies_to` lets you sub-partition just one of those partitions — typically carving `val` out of `train` while keeping `test` heldout: 

```yaml
Splits:
  ratios: { train: 0.85, val: 0.15 }
  applies_to: train                     # only re-partition records in this partition
  stratify_by: label                    # stratifies only within the named partition
  seed: 7
```

The result of materialize is three splits: `train` and `val` (carved out of the source's `train` partition by the ratios above) and `test` (passed through verbatim from the source's `test` partition).

Omitting `Splits` entirely (or writing `Splits: {}`) under declared partitions yields **Form A** — source partitions are the final splits. Setting `applies_to` *and* `ratios` yields **Form B** as above. Validator check 20 enforces consistency between source partitions and `Splits`; see § Input for the rules.

#### Sub-partitioning via tag

`Splits.applies_to` can also name a **tag** emitted by a `sample_per_class` / `sample_per_class_fractional` filter (its `label` parameter), not just a source partition. This is the *disjoint-pool* pattern: a pre-split filter deterministically tags a balanced subset (e.g. `train_pool`), a second filter tags a disjoint subset under another tag (e.g. `test`), and `Splits` then sub-partitions only the named pool:

```yaml
Filters:
  - name: pick_train_pool
    op: sample_per_class
    params: { n_per_class: 200, label: train_pool }
    seed: 1
    stages: [pre_split]
  - name: pick_test
    op: sample_per_class
    params:
      n_per_class: 100
      label: test                       # tag name becomes the pass-through split name
      exclude_already_labeled: [train_pool]
    seed: 1
    stages: [pre_split]
Splits:
  ratios: { train: 0.85, val: 0.15 }
  applies_to: train_pool                 # sub-partition only the train_pool-tagged records
  stratify_by: label
  seed: 11
```

The result is three splits: `train` + `val` (carved from the `train_pool`-tagged records by the ratios) and `test` (the `test`-tagged records, passed through **verbatim** under their tag name). Records carrying no tag land in `unassigned` (surfaced as a materialize warning), so the destructive subset intent of the sampling filters is honored.

Because the pool membership is fixed by the filter's deterministic per-record ranking — not by the Splits RNG — the `test` split is **byte-identical across runs and independent of the Splits `seed`**. A sibling recipe can replay the identical filters and `drop_by_label` to peel off the same disjoint subset bit-for-bit. Validator check 20 accepts `applies_to` when it matches either a source partition *or* a `sample_per_class*` filter label. (A record carrying two non-`applies_to` tags is rejected at materialize time, since the pass-through split would be ambiguous; the disjoint-pool `exclude_already_labeled` chain keeps tags disjoint.)

### `Transformations`

Deterministic per-record operations: resize, normalize, cast dtype, etc. Each transformation declares the splits it applies to and, optionally, a **fit source** (the split whose statistics are persisted):

```yaml
Transformations:
  - name: norm
    op: normalize
    fit_source: train
    splits: [train, val, test]
```

`fit_source: train` means: compute the normalize statistics over the training split, persist them to `fitted_statistics/norm/`, and apply them to every split listed under `splits`. This is the **fit-on-train discipline** that prevents train/inference skew — see the dedicated section [below](#fit-on-train-discipline).

The validator rejects a fit-on-train op whose `fit_source` is not `train` (check 6).

**FR-TRANS-1 across variants.** A fit-on-train Transformation may import its fitted statistics from a sibling materialized instance via `stats_from_instance: { recipe: <path>, op_id: <op_name> }` instead of fitting locally. The resolver locates the sibling by hashing its **no-variant canonical form** — i.e., the recipe with its `variants:` block stripped, matching what the materialize path itself uses to compute cache identity. As a result, `stats_from_instance` always resolves to the sibling's no-variant canonical instance regardless of which variants the sibling declares. Pinning a specific sibling variant's statistics is not supported in v1 (tracked in `stories.md § Future`).

**Image-classification Transformations.**

`resize` (no fit) — resample each image to a square of the declared size.

```yaml
Transformations:
  - name: r
    op: resize
    params: { size: 32, method: bilinear }   # method: nearest | bilinear | bicubic | lanczos
    splits: [train, val, test]
```

`cast` (no fit) — convert each image to the declared NumPy dtype, optionally multiplying by `scale` in one pass. The common uint8 → float32 in `[0, 1]` pre-normalize pattern is a single op:

```yaml
Transformations:
  - name: c
    op: cast
    params: { dtype: float32, scale: 0.00392156862745098 }   # 1/255
    splits: [train, val, test]
```

With `scale` omitted (default `1.0`), `cast` is a pure dtype conversion — values are reinterpreted in the target dtype with no rescaling. A `cast` whose input is already the target dtype is effectively a no-op.

`mean_subtract` (fit-on-train) — compute the per-channel mean over the training split, persist it to `fitted_statistics/<name>/mean.parquet`, and subtract the mean per record on every split listed under `splits`. Returns float64 records.

```yaml
Transformations:
  - name: ms
    op: mean_subtract
    fit_source: train
    splits: [train, val, test]
```

`normalize` (fit-on-train) — full z-score: subtract per-channel mean, divide by per-channel std. Persists `{mean,std}.parquet`. Supports recipe-pinned `params: { mean: [...], std: [...] }` for direct overrides (skips the fit), and `params: { stats_from_instance: ... }` per FR-TRANS-1 above.

### `Augmentations`

Stochastic, train-only operations that expand the *effective* dataset. Each augmentation declares its parameters, the splits it applies to (train-only by default, val/test rejected by validator check 5), a seed, and a **materialization mode** (`lazy` by default; `aggressive` opt-in). Lazy and aggressive ops can be mixed in a single `Augmentations:` block.

```yaml
Augmentations:
  - name: hflip
    op: horizontal_flip
    params: { p: 0.5 }
    splits: [train]
    seed: 42
  - name: crop
    op: random_crop
    params: { size: 32, padding: 4, padding_mode: reflect }
    splits: [train]
    seed: 43
    materialization: aggressive    # default: lazy
    expansion: 4                   # aggressive only; N variants per input record
```

**Lazy vs. aggressive trade-off:**

- **`lazy` (default).** The recipe declares the policy; the materialized dataset is unchanged. ModelFoundry's framework adapter realizes augmented examples on-the-fly during training, drawing fresh samples each epoch. Pro: small on-disk footprint, unbounded effective dataset size. Con: requires a framework adapter that honors the policy at training time.
- **`aggressive`.** DataRefinery realizes `expansion` augmented variants per train record at materialize time. Variants become peer records in the dataset with sidecar PNG image bytes. Pro: dataset is framework-agnostic — any consumer that reads the JSONL + sidecar PNGs sees augmented variants without any adapter. Con: on-disk size grows by `expansion` per aggressive op; the variant space is fixed at materialize time (not redrawn each epoch).

To disable augmentation for a comparison run, use a variant — see [Variants](#variants).

The four image-classification augmentation ops — `random_crop`, `horizontal_flip`, `color_jitter`, `random_erasing` — are documented under § FR-11 of `features.md`, and the full cross-repo contract is in [`docs/specs/modelfoundry/dependency-spec.md`](../specs/modelfoundry/dependency-spec.md).

**Per-record-seed persistence (Story I.e, aggressive mode).** Every realized variant record carries `<AugmentationOp.name>_seed` — the per-variant seed used by the realizer's RNG, keyed on the recipe-defined op name. The field rides through to the cached JSONL and is captured by any Sink targeting `post_Augmentations`. Lazy-mode ops do not stamp (variants are realized at training time, outside the pipeline).

### `Featurizations`

Derive new fields from existing inputs. The reference recipe uses one to derive the label field from the file path:

```yaml
Featurizations:
  - name: derive_label
    inputs: [path]
    output_field: label
    op: label_from_path
    params: { source: parent_directory_name }
    splits: [train, val, test]
```

Featurizations may be deterministic or fit-on-train; fit-on-train featurizations follow the same `fit_source: train` rules as Transformations.

**Image-classification Featurizations.**

`label_from_path` (no fit) — derive a label from a path field; the example above shows the standard `image_folder` parent-directory convention. Alternative `source` values: `filename`, `stem`.

`image_size_stats` (no fit) — featurize each record with its image's spatial dimensions, producing a list `[H, W, C]` (or `[H, W]` for 2-D images) under `output_field`. Useful for downstream filtering or as a sanity-check featurizer.

```yaml
Featurizations:
  - name: img_dims
    inputs: [image]
    output_field: image_shape
    op: image_size_stats
    splits: [train, val, test]
```

`categorical_encode` (fit-on-train) — derive an integer-encoded field from a string-valued categorical source. Two modes:

```yaml
# Mode 1 — recipe-declared vocabulary (deterministic).
Featurizations:
  - name: lbl_id
    inputs: [label]
    output_field: label_id
    op: categorical_encode
    params:
      vocabulary: [airplane, automobile, bird, cat, deer, dog, frog, horse, ship, truck]
      output_dtype: int32
    fit_source: train
    splits: [train, val, test]
```

```yaml
# Mode 2 — vocabulary fit on train, persisted, replayed on val/test.
Featurizations:
  - name: lbl_id
    inputs: [label]
    output_field: label_id
    op: categorical_encode
    params: { ordering: alphabetical, output_dtype: int32 }   # ordering: alphabetical | first_seen
    fit_source: train
    splits: [train, val, test]
```

Mode 2 persists the derived vocabulary to `fitted_statistics/<name>/vocabulary.parquet`. The persisted vocab can be imported by a downstream recipe via FR-TRANS-1 (`params.stats_from_instance`), exactly the same way `normalize` imports per-channel mean/std across recipes. An apply-time label that isn't in the vocabulary fails with a clear `PluginError` naming the missing label.

`flatten` (no fit) — reshape a multi-dimensional input field to a 1-D vector. Requires exactly one entry in `inputs`. The source field stays in the record so a downstream consumer can still observe the multi-dimensional view (useful pattern: a variant adds `flatten` to give an MLP-shaped consumer view of the same data a CNN-shaped consumer sees in the base recipe).

```yaml
Featurizations:
  - name: img_flat
    inputs: [image]
    output_field: image_flat
    op: flatten
    splits: [train, val, test]
```

**Reserved `output_field` names.** A Featurization's `output_field` must not collide with a field the input loader stamps on every record. Validator check 23 (`featurization_output_field_loader_collision`) catches these at validate time. For the `image_classification` plugin the reserved set is:

- `record_id`, `image`, `path` — always.
- `label` — when `Labels.source.kind` is `direct` and a label source is
  available (`image_folder` parent directory, or `image_flat` +
  `label_from` sidecar manifest).
- `partition` — when any `InputSource` declares `partition`.

So **if your recipe loads labels via `image_flat` + `label_from` (or `image_folder` with `Labels.kind: direct`), do not also declare a `label_from_path` Featurization writing to `label`**: the loader already produced the label, and the Featurization would be a duplicate write. The two patterns are mutually exclusive:

- **Loader-stamped label.** `Input.sources[*].label_from` (or `image_folder` parent directory) + `Labels.source.kind: direct`. The loader writes `label` at load time; no Featurization needed.
- **Derived label.** Set `Labels.source.kind: derived` and declare a `label_from_path` Featurization with `output_field: label`. The loader does not stamp `label`; the Featurization is the sole writer.

### `OutputExpectations`

Post-pipeline assertions on the materialized records. Run after the final pipeline stage. Failures abort the run at end-of-pipeline; the partial instance is left in the cache's `.tmp/<run-id>/` directory under the `FAILED` marker for diagnosis (FR-5 atomic temp-then-promote).

```yaml
OutputExpectations:
  - field: label
    assertion: { kind: required_field }
    severity: error
  - field: image
    assertion: { kind: dtype_equals, expected: uint8 }
    severity: error
```

`OutputExpectations` support every `InputContracts` assertion kind above, plus the per-split / per-class / structural kinds below (these run after Splits, so they have access to the split structure that pre-pipeline `InputContracts` do not).

| `kind` | Required keys | Optional keys | What it checks |
|--------|---------------|---------------|-----------------|
| `split_record_counts` | `counts: {<split>: <int>, …}` | — | Each named split's record count equals the declared value. A named split that is absent fails. Extra splits are ignored. |
| `per_class_count_per_split` | `field`, `per_class: <int>` | `tolerance` (default `1`) | For every split, every distinct value of `field` has `per_class ± tolerance` records. The default tolerance absorbs stratification rounding; declare at `severity: warning` for a soft check. |
| `count_by_field` | `field`, `value_per_key: <int>` | — | Across all records, every distinct value of `field` has exactly `value_per_key` records. |
| `count_by_fields` | `fields: [<name>, …]`, `value_per_combination: <int>` | — | Across all records, every distinct combination of `fields` values has exactly `value_per_combination` records (e.g. every `(corruption, severity)` pair). |
| `shape_equals` | `field`, `value: [<dim>, …]` | — | Every record's `field` is an ndarray whose `.shape` equals `value`. Non-ndarray values fail. |
| `value_in_set` | `field`, `value: [<v>, …]` | — | Every record's `field` value is one of the listed values. `None` values are skipped (use `required_field` to forbid them). |
| `per_class_count_equals` | `field`, `value: <int>` | — | Across all records (single-split form), every distinct value of `field` has exactly `value` records. |

**Cross-split assertions.** `split_record_counts` and `per_class_count_per_split` are the only kinds that consult the split structure; the rest evaluate against the flattened set of all records across splits. The per-split kinds are valid **only** in `OutputExpectations` — declaring one in `InputContracts` (which runs pre-Splits) fails with a clear "requires per-split context" message. Failure messages name the offending split / class / key precisely (e.g. `split 'val' expected 300, got 350`).

```yaml
OutputExpectations:
  - assertion:
      kind: split_record_counts
      counts: { train: 1700, val: 300, test: 1000 }
    severity: error
  - field: label
    assertion: { kind: per_class_count_per_split, per_class: 170 }
    severity: warning      # tolerant of stratification rounding
  - field: image
    assertion: { kind: shape_equals, value: [32, 32, 3] }
    severity: error
  - field: label
    assertion: { kind: value_in_set, value: [airplane, automobile, bird, cat, deer, dog, frog, horse, ship, truck] }
    severity: error
```

### `Visualizations`

Render standard or bespoke views over a pipeline stage. Each visualization declares the stage it observes and an output **mode**:

- `reporting` — rendered during materialization, persisted to `report/visualizations/`. Failures fail the materialization (the report is not partial).
- `exploration` — rendered on demand via the library API or `datarefinery inspect`; not persisted.

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

**Available visualization ops:**

| `op` | Params | Renders |
|------|--------|---------|
| `class_distribution_histogram` | `group_by` (optional) | Bar chart of per-record counts bucketed by a field. Buckets on `group_by` when set, else `Labels.field`. |
| `sample_grid` | `n` (default 16), `per_class` (default false) | Grid of sample images; `per_class: true` draws one row per class. |
| `mean_image_per_class` | — | Per-class mean image tile (one column per class). |
| `pixel_distribution` | `bins` (default 64), `splits` (required) | Per-channel pixel-value histogram across the named splits. |
| `augmented_sample_grid` | `n_base` (required), `n_variants` (required), `seed` (optional) | Grid showing augmentation variants of base records (FR-VIZ-1). |
| `corruption_severity_grid` | `n_images` (required), `corruption_types` (required), `severities` (required) | Grid of corruption × severity examples (FR-VIZ-2). |
| `severity_ladder` | `n_examples` (required), `corruption_type` (required) | One corruption type laddered across severities (FR-VIZ-3). |

#### Stage-aware dispatch (G7)

Each visualization op declares which **stage snapshot** of the split records it renders against. `VisualizationOp.stage` is a closed vocabulary:

| `stage` | Snapshot rendered against |
|---------|---------------------------|
| `post_InputContracts` | Records after the input loader runs and contracts pass; **pre-Splits** flat stream, wrapped as `{"_records": [...]}`. |
| `post_Filters` | Splits after both pre-split and post-split filters have run. |
| `post_Splits` | Splits immediately after the splitter, before post-split filters. |
| `post_Generation` | Splits after Generation. Validator rejects when `Generation` is empty. |
| `post_Transformations` | Splits after Transformations. Validator rejects when `Transformations` is empty. |
| `post_Augmentations` | Splits after Augmentations. Validator rejects when `Augmentations` is empty. |
| `post_Featurizations` | Splits after Featurizations. Validator rejects when `Featurizations` is empty. |
| `post_pipeline` | The final snapshot (the existing default, what the scaffolder emits). |

The pipeline runner snapshots `split_map` at the END of each named stage (references, not deep copies — the runner constructs fresh per-stage `split_map` lists so the snapshots are stable). At report-render time each op dispatches against its declared snapshot. **Validator check 11** rejects a viz whose stage's recipe section is empty (e.g. `stage: post_Generation` with no `Generation:` ops), since the snapshot would be identical to a prior stage and the author's intent is unclear. `post_InputContracts`, `post_Filters`, `post_Splits`, and `post_pipeline` are always valid targets.

**The pre-vs-post-normalize pattern.** Two `augmented_sample_grid` ops, one at `post_Filters` (uint8 records, recognizable images) and one at `post_Transformations` (the model-facing normalized representation), produce two distinct PNGs in `report/visualizations/`:

```yaml
Visualizations:
  - name: pre_norm_augmented_grid
    op: augmented_sample_grid
    params: { n_base: 4, n_variants: 4 }
    stage: post_Filters             # uint8 records, "what the data looks like"
    mode: reporting
  - name: post_norm_augmented_grid
    op: augmented_sample_grid
    params: { n_base: 4, n_variants: 4 }
    stage: post_Transformations     # normalized records, "what the model sees"
    mode: reporting
```

This is also the G5 close-out: a recipe with `normalize` Transformation can declare `augmented_sample_grid` at `stage: post_Filters` and render against uint8 inputs, side-stepping the float-image `TypeError` that plagued the post-pipeline-only runtime.

**Re-render limitation.** `datarefinery report` (and the `re_render_report` library API) only have the final dataset on disk, so they expose only the `post_pipeline` snapshot. Viz ops declared at intermediate stages cannot be re-rendered; they require re-materialization. The re-render path raises `MaterializeError` with the list of available snapshots when a viz's declared stage isn't present.

**`group_by` (G17).** `class_distribution_histogram` accepts an optional `group_by: <field>` param to bucket on a field other than the label — e.g. a Generation-introduced tag like `corruption` or `severity`:

```yaml
Visualizations:
  - name: corruption_distribution
    op: class_distribution_histogram
    params: { group_by: corruption }   # default: Labels.field
    stage: post_pipeline
    mode: reporting
```

The `group_by` value must resolve to a known recipe field — `Output.record_schema`, a Generation output / `tag_fields` entry, or a Featurization output. Validator check 25 rejects an unknown-field `group_by` at validate time.

### `Sinks` (optional)

Disk-output declarations captured at materialize time. Each sink observes one named pipeline stage's record output and writes per-record artifacts (today: PNGs) under a path template, rooted in the cache instance directory. Sinks let downstream consumers (e.g. a training tool, a submission package, a manual sanity check) read bit-identical bytes from the stage at which they were produced — not a denormalized or otherwise reconstructed version.

```yaml
Sinks:
  - name: corruption_pngs
    stage: post_Generation       # after the Generation stage emits records
    splits: [test]               # optional; defaults to all splits at the stage
    field: image                 # record field to serialize
    format: png_per_record       # v1: one PNG per record
    path_template: "exports/cifar-10-c/{corruption}/sev{severity|str}/{label}/{source_path|stem}__sev{severity|str}.png"
```

**Fields:**

- `name` — sink identifier; on-disk root segment and manifest key. Must be unique within a recipe.
- `stage` — closed vocabulary: `post_InputContracts`, `post_Filters`, `post_Splits`, `post_Generation`, `post_Transformations`, `post_Featurizations`, `post_Augmentations`, `post_OutputExpectations`, `post_Visualizations`. Each value names the stage whose *output* the sink observes.
- `splits` — optional list of split names to restrict capture to. Omit (or leave `null`) to capture every split known at the chosen stage.
- `field` — record field whose value gets serialized. For `png_per_record` this must carry a uint8 H×W×C (or H×W) numpy array.
- `format` — serialization format. v1 ships `png_per_record`.
- `path_template` — per-record output path, interpreted relative to the cache instance directory.

**Path template grammar:**

- `{field}` substitutes the record's value of `field` as a string.
- `{field|filter}` applies one of `stem`, `lower`, `upper`, `str`.
  - `|stem` — `Path.stem` of a string value (e.g. `data/train/1234.png` → `1234`).
  - `|lower`, `|upper` — case transforms.
  - `|str` — explicit string coercion for integer fields.
- `{split}` is a special variable resolved from the current split name.
- Templates that escape the instance directory (`..` segments or absolute paths) are rejected at validate time.

**Format vocabulary (v1):**

| `format` | Required field shape | Output |
|---|---|---|
| `png_per_record` | uint8 H×W×C (or H×W for grayscale) on `field` | One PNG per record via `PIL.Image.fromarray`. |

**Cache identity participation.** Sinks are part of canonical recipe bytes. Adding, removing, or modifying any sink field — including `path_template` alone — invalidates the cache. Downstream tools that bind against the path layout deserve the invalidation.

**Atomicity.** Sink output lives under the same temp-then-promote contract as the cached JSONL, `fitted_statistics/`, and `report/`. Pipeline failure leaves the temp dir flagged `FAILED`; no partial sink output ever appears under the promoted instance path.

**Manifest.** Each sink writes one entry to `manifest.sinks.<name>`: `stage`, `format`, `files_written`, `bytes_total`, `path_template_resolved_root` (the longest fixed prefix of the template). See the dependency contract for downstream consumers in [`modelfoundry/dependency-spec.md`](../specs/modelfoundry/dependency-spec.md).

**Tip: where to put the sink.** For uint8 image exports, target the earliest stage at which the record carries the uint8 representation you want (typically `post_Filters` or `post_Generation`) — **before** any normalize-style Transformation rewrites `image` in place to float bytes. A sink at `post_Transformations` against a normalized `image` field will fail at materialize time with an actionable dtype error.

**Re-running sinks after the fact: `datarefinery export` (Story I.f).** A recipe author who added a sink to an already-materialized recipe can produce the sink output without re-running the full pipeline:

```bash
datarefinery export <recipe>                  # re-run every sink on the recipe
datarefinery export <recipe> --sink corrupted # re-run only the named sink
```

The verb locates the bound cache instance via a *sinks-stripped* cache key — adding a sink to a recipe perturbs canonical bytes, but the instance you already materialized (without the sink) is still the one the export reads from. Output bytes are byte-identical to what a materialize-with-the-sink would have produced.

**v1 reconstructability table.** The export verb walks back from each sink's stage to the cached state by re-running the minimum stage logic needed. The supported stages:

| Sink `stage` | Reconstruction strategy |
|---|---|
| `post_OutputExpectations` / `post_Visualizations` | Reads cached JSONL directly (records are already at this state in the cache). Sinks targeting `image` on image-classification recipes will fail because the numpy `image` field is dropped at JSONL serialization for non-aggressive records — target an earlier stage instead. |
| `post_Generation` | Re-loads source images (via the recipe's `Input` sources) and re-runs the recipe's `Generation` ops against the subset that produced the cached records. Per-record-seed stamps (Story I.e) make this byte-identical to the original materialize. |
| `post_InputContracts`, `post_Filters`, `post_Splits`, `post_Transformations`, `post_Featurizations`, `post_Augmentations` | **Not reconstructable in v1.** Refuse with a pointer to re-materialize (`datarefinery materialize`) — the cached state has moved past these intermediate forms and v1 doesn't carry enough metadata to replay them. |

The dispatch table will expand as more ops adopt the per-record-seed contract.

**When to prefer `materialize` over `export`.** When the recipe is *new* (no cached instance yet), or when the cached recipe and the new recipe differ in anything other than the `Sinks` section, or when a sink targets a non-reconstructable stage. Materialize is the safe default; export is an optimization for the "add a sink, keep the cache" workflow.

### `variants`

Named overlays on any section, applied **before** canonicalization and hashing so the cache identity reflects the selected variant.

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

Select at materialize time (`--variant` is a global option, placed before the verb):

```bash
datarefinery --cache-root ./cache --variant no_augment materialize reference-recipe.yaml
```

Variants are how you express experiment knobs (different augmentation policies, different split ratios, different class-balance strategies) without forking the recipe or routing flags around the recipe surface. See [Variants](#variants-1) below for the design rationale.

## Fit-on-train discipline

The most common source of train/inference skew is fitting normalizers or encoders on the full dataset (including val/test). DataRefinery prevents this structurally:

- A Transformation or Featurization that needs to learn parameters from data declares `fit_source: train`.
- The validator (check 6) refuses any `fit_source` that is not `train`.
- The pipeline fits the operation on the training split only, persists the resulting statistics to `fitted_statistics/<op_name>/`, then applies the operation to every split in `splits` using the persisted statistics.
- Inference-time tools (ModelMachine) replay the same recipe against new inputs and read the persisted statistics from `fitted_statistics/` — there is no "re-fit at inference" path to drift from.

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

These files are written in structured format (parquet for numeric stats); the v1 contract is "no opaque pickles." Operations that do not need fitting omit `fit_source` entirely.

## Variants

Variants are named overlays that produce different materializations from one recipe. A typical recipe has a default behavior and a few named experiments:

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

1. **Variants are part of the cache identity.** The overlay is applied before canonicalization, so two variant selections produce two different cached instances. Re-running with the same variant selection is a cache hit; switching variants is a cache miss the first time and a hit thereafter.
2. **Variants can override any section.** Use them to vary augmentation policy, split ratios, class-balance strategy, filters, generation, or any combination — not just `Augmentations`.
3. **Variants are scoped to one recipe.** This keeps experiments discoverable inside one file rather than across forked copies. If the experiment changes the pipeline semantics in a way that no longer makes sense as an overlay (e.g. swapping the plugin), it is a different recipe.

The validator (check 12) rejects a variant that references an undeclared section or key.

## Contracts and expectations

`InputContracts` and `OutputExpectations` are the recipe's correctness gates around the pipeline. They share the same assertion shape but run at different stages:

- `InputContracts` runs on the **raw inputs**, before any pipeline work. Cheap-to-detect data problems abort early.
- `OutputExpectations` runs on the **materialized records** after the final pipeline stage. Used to assert the shape and value ranges of what downstream tools will consume.

A combined example:

```yaml
InputContracts:
  - assertion: { kind: record_count_in_range, min: 100 }
    severity: error
  - field: path
    assertion: { kind: required_field }
    severity: error

OutputExpectations:
  - field: label
    assertion: { kind: required_field }
    severity: error
  - field: image
    assertion: { kind: dtype_equals, expected: uint8 }
    severity: error
```

Two design notes:

- **`Output` vs. `OutputExpectations`.** `Output` is the structural contract — record shape, field names, dtypes — that downstream tools bind against. `OutputExpectations` is the *value* contract — things you cannot express in a schema (record-count bounds, value ranges, distributional checks).
- **`severity: warning`** records the violation in the manifest but does not fail the run. Use it for distributional checks that are legitimately violated by small inputs (e.g. a fixture too small for a meaningful KS test).

## Seeds and determinism

Every seeded op in a recipe — Filters that sample, Splits, Generation, Augmentations, SampleData — accepts a seed in one of two forms:

1. **Literal integer.** `seed: 42`. The op uses that integer directly.
2. **`seed_derive_from: master` (G11).** Per-op seeds derived from the recipe's master seed at materialize time:

   ```yaml
   seed: 20260509   # the recipe's master seed

   Filters:
     - name: subsample
       op: random_sample
       params: { fraction: 0.5 }
       seed: { from: master }     # derived from the master seed
     - name: train_pool
       op: sample_per_class
       params: { n_per_class: 200 }
       seed: { from: master }

   Splits:
     ratios: { train: 0.85, val: 0.15 }
     seed: { from: master }
   ```

   At materialize time each `seed: { from: master }` is resolved to

   `sha256(master_seed.to_bytes(8, "big") + op_name.encode("utf-8")).digest()[:8]`

   interpreted as a 64-bit unsigned integer. The op-name input is the surrounding op's `name` field (or the literal string `"Splits"` for the Splits section).

**Cache identity.** The master seed is part of the recipe's canonical bytes, so it participates in cache identity. The `seed_derive_from` form itself is also preserved in canonical bytes — the cached `recipe.json` records your YAML intent rather than the resolved integers. Changing the master seed produces new cache identity for every op that derived from it; changing a single op's `name` changes only that op's derived seed.

**Per-op-seed escape hatch.** If you need one op pinned to a specific integer while others derive — for example, to keep a Splits seed stable across master-seed experiments — declare a literal `seed:` on that one op and `seed: { from: master }` everywhere else.

**The derivation function is a pinned contract.** Changing it would invalidate every cached instance for every recipe that uses the derivation form. A unit test pins the canonical value; bumping it is a deliberate, ceremonious cache-invalidation per the rules in `project-essentials.md` § "Cache identity is the reproducibility contract."

## Filters vs Splits for class imbalance

Class imbalance shows up in almost every classification dataset. The v1 recipe surface splits the response cleanly along a single axis — *are you removing data, or weighting it at training time?*

- **Remove data → `Filters`.** Filters reduce the raw set by predicate; the surviving records flow into Splits. Use Filters when the imbalance is severe enough that downstream training would learn the prior more than the signal — undersample the majority class, drop a too-sparse minority class, subsample to a target ratio.

  ```yaml
  Filters:
    - name: cap_majority
      op: random_sample
      params: { fraction: 0.3 }
      seed: 13
      stages: [pre_split]
  ```

  Removed records do not appear in any split and do not factor into any downstream metric.

- **Weight at training time → `Splits.class_balance`.** When the imbalance is not severe enough to warrant data loss, declare a strategy on Splits. **DataRefinery does not act on it** — `class_balance` is a *forward-declared hint* that rides through to `manifest.class_balance` verbatim. The consumer (ModelFoundry) honors it at training time via framework primitives (e.g. PyTorch `WeightedRandomSampler`, Keras `class_weight=`). The materialized train split still contains every record at its natural frequency; **no resampling and no weight column happen at materialize time.**

  Two forms are accepted. A bare string (strategy name, no scoping):

  ```yaml
  Splits:
    ratios: { train: 0.7, val: 0.15, test: 0.15 }
    seed: 11
    stratify_by: label
    class_balance: weighted_sampling
  ```

  Or a dict that names the strategy and the splits it applies to:

  ```yaml
  Splits:
    ratios: { train: 0.7, val: 0.15, test: 0.15 }
    seed: 11
    stratify_by: label
    class_balance:
      strategy: oversample_minority_to_majority   # passed through verbatim; the consumer owns its meaning
      applies_to: [train]                          # which splits the strategy targets
  ```

  The validator checks only the dict *shape* (`strategy` is a non-empty string; `applies_to` is a list of defined split names). It does not enforce a fixed strategy vocabulary — the strategy name is the consumer's contract. The supported strategy names and ModelFoundry's training-time responsibility are documented in [`modelfoundry/dependency-spec.md` § `manifest.class_balance`](../specs/modelfoundry/dependency-spec.md). No records are dropped; the imbalance is corrected at iteration time, not at materialization time.

When in doubt, prefer `Splits.class_balance`. Filters are a heavier hammer — they delete information from the instance, so the same recipe cannot be re-used to study the un-balanced distribution without authoring a variant that disables the filter.

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

- The [project README](../../README.md) covers install, quickstart, CLI verbs, and the library API.
- [`features.md`](../specs/features.md) is the canonical reference for every recipe section (FR-1 through FR-23) and the validator checks.
- [`tech-spec.md`](../specs/tech-spec.md) covers the cache identity algorithm, the canonicalization rules, fitted-statistics layout, and the pipeline runner.
- The [plugin authoring guide](plugin-authoring.md) covers writing your own plugin: declaring `OperationSpec`s, the `Plugin` protocol, and the entry-point registration.
