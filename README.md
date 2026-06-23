# DataRefinery

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![CI](https://github.com/pointmatic/datarefinery/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/pointmatic/datarefinery/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/pointmatic/datarefinery/branch/main/graph/badge.svg)](https://codecov.io/gh/pointmatic/datarefinery)

> Recipe-driven data preparation and caching for machine learning.

DataRefinery compiles a single YAML **recipe** into a materialized
**instance**: the recipe, the prepared dataset, the fitted statistics
produced during preparation, and a report describing both. Re-running an
unchanged recipe over unchanged inputs returns the cached instance
unchanged; any semantic edit invalidates and rebuilds.

Two categories ship as **fully-real plugins** — **image classification**
and **audio classification** — with tabular and text plugin stubs to keep
the abstractions honest. The audio plugin is the proof that the
category-agnostic abstractions are not "image with extra steps": its
windowing, log-mel featurization, and fit-on-train normalization all land
on the same recipe sections image uses. See the
[concept](docs/specs/concept.md), [features](docs/specs/features.md),
and [tech-spec](docs/specs/tech-spec.md) documents for design depth.

## Why DataRefinery

Data prep for ML training usually lives in throwaway notebooks: steps
decay between projects, train/inference skew creeps in, splits leak,
and reproducibility relies on muscle memory. DataRefinery replaces that
with one declarative artifact (the recipe) and a deterministic
materialization path. Highlights:

- **Reproducibility contract.** Same recipe + same inputs + same seed
  produces a byte-identical instance. Every stochastic operation is
  seeded; fitted statistics from the training split are persisted so
  inference replays the exact transformations.
- **Semantic cache identity.** Cache addressing combines a canonical
  hash of the recipe (whitespace- and key-order-insensitive) with a
  hash of the raw inputs and the seed. Cosmetic edits don't rebuild;
  meaningful edits do. The recipe hash is **segmented** into four
  independently-versioned identity parts (`core` / `plugin` /
  `overlays` / `extensions`), so an edit confined to one segment
  invalidates only that segment's scope — e.g. an audio-plugin change
  never rebuilds an image recipe's cache.
- **Atomic temp-then-promote.** Materialization writes into a temp
  directory and promotes only after success — partial instances never
  appear in the cache.
- **Recipe is authoritative.** The recipe is the single source of
  truth for pipeline semantics. CLI flags and env vars only control
  execution context (cache root, log level, workers, plugin path).
  The one sanctioned override is `--seed` for ad-hoc runs.
- **Library + CLI as co-equal surfaces.** Same recipe, same operations,
  no second code path to drift from at serving time.

## Installation

DataRefinery requires Python 3.12.

```bash
pip install ml-datarefinery
```

The PyPI distribution name is `ml-datarefinery`; the Python import name
and console script remain `datarefinery` (e.g. `import datarefinery` and
`datarefinery --help`). Same shape as `scikit-learn` / `import sklearn`.

For the optional LLM-enhancement layer (FR-17), install with the
`[llm]` extra:

```bash
pip install 'ml-datarefinery[llm]'
```

For the robustness-evaluation `imagecorruptions_apply` Generation op
(FR-GEN-1), which applies Hendrycks-Dietterich (ICLR 2019) image
corruptions, install with the `[corruptions]` extra:

```bash
pip install 'ml-datarefinery[corruptions]'
```

For the **`audio_classification`** plugin (clip decode, windowing,
log-mel featurization), install with the `[audio]` extra, which pulls in
`librosa` (and its transitive `soundfile`):

```bash
pip install 'ml-datarefinery[audio]'
```

The default install stays lean; the audio plugin imports `librosa`
lazily, so the package remains importable without the extra.

### From source (development)

DataRefinery uses [`pyve`](https://pointmatic.github.io/pyve/) to
manage two isolated environments: one for the runtime package and one
for dev tooling (ruff, mypy, pytest).

```bash
git clone https://github.com/pointmatic/datarefinery.git
cd datarefinery

# Runtime env
pyve init
pyve run pip install -e /path/to/datarefinery

# Dev tooling env (one-time)
pyve testenv init
pyve testenv install -r requirements-dev.txt
pyve testenv run pip install -e /path/to/datarefinery

# Run the test suite
pyve test
```

## Quickstart

DataRefinery's documented user journey is `init → validate →
materialize → status`. The example below uses an
`image_classification` layout: a directory of class-named
subdirectories, each holding image files.

```text
my-images/
  cat/
    cat_001.png
    cat_002.png
    ...
  dog/
    dog_001.png
    ...
```

```bash
# 1. Scaffold a starter recipe from raw images (deterministic, offline).
datarefinery init --input my-images --output recipe.yaml

# 2. (Optional) Review the recipe and uncomment any suggested
#    Transformations (e.g. resize, normalize).

# 3. Validate the recipe against the schema and FR-2 static checks.
datarefinery validate recipe.yaml

# 4. Materialize the pipeline end-to-end. The first run is a cache
#    miss; the cached instance is promoted atomically on success.
datarefinery --cache-root ./cache materialize recipe.yaml

# 5. Inspect the instance summary (cache hit on a re-run).
datarefinery --cache-root ./cache status recipe.yaml
```

After a successful `materialize`, the cache layout looks like:

```text
cache/instances/<recipe-hash>/<input-hash>/<seed>/
├── recipe.json              # canonical post-loader recipe (the bytes hashed for the cache key)
├── manifest.json            # full hashes, record counts, schema version
├── dataset/                 # prepared dataset (e.g. <split>.jsonl)
├── fitted_statistics/       # statistics fitted on the training split
└── report/
    ├── report.md            # human-readable summary
    ├── drift.json           # stable contract for downstream drift tooling
    └── visualizations/      # PNGs declared in the recipe
```

The `<recipe-hash>` and `<input-hash>` directory names use the first
16 hex characters of each SHA-256; the full hashes are recorded in
`manifest.json`.

### Alternative layout: flat directory + sidecar labels

If your dataset is a flat directory of images plus a separate manifest
of labels (the common third-party shape — Kaggle CSVs, re-labeled
datasets, etc.), declare the source as `image_flat` and point its
`label_from` at the manifest:

```text
my-dataset/
  images/
    img_001.png
    img_002.png
    ...
  labels.csv         # id,class
```

```yaml
Input:
  sources:
    - name: images
      type: image_flat
      path: ./my-dataset/images
      label_from:
        path: ./my-dataset/labels.csv
        join: by_id
        id_field: id
        label_field: label
Labels:
  field: label
  source: { kind: direct }
```

The loader joins each image's filename stem against the manifest's
`id` column and writes the matching `label` value into the
record's `label` field at load time. `validate` enforces the join
(check 19): missing ids, duplicate ids, and column-name typos are
caught before `materialize` runs. See `docs/guides/recipe-authoring.md`
for headerless manifests and `by_row_order` (CIFAR-style) variants.

### Pre-partitioned sources (Kaggle-style train/test)

Most third-party datasets ship pre-partitioned: a `train/` directory
authored by the publisher and a `test/` directory intended to remain
heldout from training. Declare each source's role with `partition`:

```text
my-dataset/
  train/cat/, train/dog/, …            # ImageFolder layout per partition
  test/cat/,  test/dog/,  …
```

```yaml
Input:
  sources:
    - name: train_data
      type: image_folder
      path: ./my-dataset/train
      partition: train
    - name: test_data
      type: image_folder
      path: ./my-dataset/test
      partition: test
Splits:
  ratios: { train: 0.85, val: 0.15 }
  applies_to: train                     # carve val from train; test stays heldout
  stratify_by: label
  seed: 7
```

The materialized instance contains three splits: `train` and `val`
(sub-partitioned from the source's `train` directory) and `test`
(passed through verbatim from the source's `test` directory). Omitting
`Splits` (or writing `Splits: {}`) honors the source partitions as the
final splits without sub-partitioning. Validator check 20 enforces
consistency — every record's partition declaration is honored end-to-end.

### Unlabeled partitions (Kaggle-style test set with no labels)

The classic Kaggle shape ships a labeled training set together with an
unlabeled heldout test partition. Declare the unlabeled source with
`type: image_flat` (the heldout side has no class subdirectories) and
`unlabeled: true`:

```yaml
Input:
  sources:
    - name: train_data
      type: image_folder
      path: ./my-dataset/train
      partition: train
    - name: test_data
      type: image_flat                  # flat layout, no labels
      path: ./my-dataset/test
      partition: test
      unlabeled: true
Labels:
  field: label
  source: { kind: direct }              # labels exist for labeled partitions
Splits:
  ratios: { train: 0.85, val: 0.15 }
  applies_to: train                     # only sub-partition the labeled side
  stratify_by: label
```

Records loaded from `test_data` land without a `label` field. They
flow through label-independent stages (resize, normalize) normally;
label-dependent stages (`stratify_by` on an unlabeled partition,
`filter_by_label`, label-reading featurizations) are rejected at
validate time (check 21). `report.md` flags the unlabeled split with
`*(unlabeled)*`; `drift.json` reports `class_distribution: null` with
a `"skipped: unlabeled"` note. The materialized `dataset/test.jsonl`
is ready for downstream inference — train a model on `train`+`val`,
predict against `test`, and submit. (Inference itself is external to
DataRefinery.)

### Audio classification

The `audio_classification` plugin (install with `pip install
'ml-datarefinery[audio]'`) follows the same `init → validate →
materialize → status` journey on the same recipe sections — only the
plugin name, source types, and ops differ. Sources mirror the image
ones: `audio_folder` (class-subdirectory labels) and `audio_flat`
(`label_from` sidecar or `unlabeled: true`). Each source declares a
required `target_sample_rate`; the loader decodes every clip with
`librosa` and resamples to it (mono float32).

The pipeline is: **decode → window → log-mel → fit-on-train normalize.**
Windowing is a `Generation` op that fans each clip into fixed-length
window records (so `manifest.record_counts` reflects the expansion);
featurization is a two-op `Featurizations` chain — `log_mel_spectrogram`
writes the raw spectrogram to `mel`, then fit-on-train `audio_normalize`
reads `mel` and writes per-mel-bin-standardized `feature`.

```yaml
schema_version: 3
plugin: audio_classification
seed: 0

Input:
  sources:
    - name: clips
      type: audio_folder        # class-named subdirectories of audio files
      path: ./my-audio/train
      target_sample_rate: 16000 # required — clips decode + resample to this

Output:
  record_schema:
    sample_array: { dtype: float32 }   # decoded waveform (in-pipeline; not serialized)
    label: { dtype: str }

Labels:
  field: label
  source: { kind: direct }

Splits:
  ratios: { train: 0.8, val: 0.2 }
  stratify_by: label            # clip-level stratification; a clip's windows stay together
  seed: 7

Generation:
  - name: win
    op: window
    inputs: [sample_array]
    output_schema: matches_input
    seed: 0
    splits: [train, val]
    replace_input_records: true # each clip -> N window records
    params:
      window_length_samples: 1600   # 0.1s @ 16 kHz
      hop_samples: 1600             # non-overlapping
      remainder: drop               # or pad_zero for the trailing partial window

Featurizations:
  - name: logmel
    op: log_mel_spectrogram
    inputs: [sample_array]
    output_field: mel             # raw log-mel spectrogram (n_mels x n_frames)
    params: { n_fft: 512, hop_length: 256, n_mels: 32, f_min: 0.0, power: 2.0 }
    splits: [train, val]
  - name: norm
    op: audio_normalize
    inputs: [mel]
    output_field: feature         # fit-on-train per-mel-bin normalized
    fit_source: train             # stats fit on train, applied to val/test
    splits: [train, val]
```

Each window record carries `source_record_id` (the parent clip's
`record_id`) and `window_index` — the documented grouping key downstream
tools use to aggregate window predictions back to a clip-level decision.

## Recipe anatomy

A recipe is a single YAML file. Field names match the section set
used by the validator and runner; each operation declares the stages
and splits it applies to so train-only behavior is explicit.

```yaml
schema_version: 3
plugin: image_classification
seed: 0

Input:
  sources:
    - name: train
      type: image_folder
      path: my-images

Output:
  record_schema:
    image: { dtype: uint8, shape: [32, 32, 3] }
    label: { dtype: str }
    path:  { dtype: str }

Labels:
  field: label
  source: { kind: derived, derivation: parent_directory_name }

Splits:
  ratios: { train: 0.7, val: 0.15, test: 0.15 }
  seed: 11
  stratify_by: label

Transformations:
  - name: resize
    op: resize
    params: { size: 32, method: bilinear }
    splits: [train, val, test]
  - name: normalize
    op: normalize
    fit_source: train          # statistics fit on train, applied everywhere
    splits: [train, val, test]

Featurizations:
  - name: derive_label
    inputs: [path]
    output_field: label
    op: label_from_path
    params: { source: parent_directory_name }
    splits: [train, val, test]

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

overlays:
  no_augment:
    Augmentations: []
```

Section roles at a glance:

| Section | Purpose |
|---------|---------|
| `Input` | Declared raw sources (files, directories, parquet, etc.) |
| `Output` | Record schema the materialized dataset must satisfy |
| `Labels` | Where labels come from (column, derivation, sidecar) |
| `SampleData` | A small inlined sample for documentation/testing |
| `InputContracts` | Pre-pipeline assertions on raw input shape/values |
| `Filters` | Row-removal policy (e.g. class-imbalance via subsetting) |
| `Generation` | Synthetic record generation |
| `Splits` | Train/val/test ratios, stratification, seed |
| `Transformations` | Deterministic ops; `fit_source: train` persists stats |
| `Augmentations` | Stochastic, train-only by default |
| `Featurizations` | Derive new fields from existing ones |
| `OutputExpectations` | Post-pipeline assertions on materialized data |
| `Visualizations` | Exploration (on-demand) or reporting (persisted) views |
| `Sinks` | Per-record disk exports captured at a named stage (e.g. PNGs) |
| `overlays` | Named overrides on any section (experiment knobs) |
| `extensions` | Sanctioned namespace for plugin-consumed experimental keys |

Select one or more overlays at materialize time with repeatable
`--overlay no_augment` (applied in order, last-writer-wins per section).
Overlays change the canonical hash (and therefore the cache identity).
(`overlays` is the v0.22.0 generalization of the former `variants` /
`--variant` surface.)

The optional `Sinks` section captures per-record artifacts (v1:
`png_per_record`) from a named pipeline stage under a path template,
rooted in the instance directory — so downstream consumers read
bit-identical bytes from the stage that produced them:

```yaml
Sinks:
  - name: transformed
    stage: post_Transformations    # observes this stage's record output
    field: image                   # uint8 H×W×C array to serialize
    format: png_per_record
    path_template: "transformed/{split}/{record_id}.png"
```

Sinks are part of canonical recipe bytes. Add a sink to an
already-materialized recipe and re-run it without rebuilding the
pipeline via the `export` verb.

For a section-by-section walk-through — including fit-on-train
discipline, overlays, contracts/expectations, and the Filters-vs-Splits
choice for class imbalance — see the
[Recipe authoring guide](docs/guides/recipe-authoring.md).

## CLI verbs

```bash
datarefinery --help
```

| Verb | Purpose | FR |
|------|---------|----|
| `check` | Report environment soundness (Python, deps, plugins discovered). | FR-18 |
| `init` | Scaffold a starter recipe deterministically from raw inputs. | FR-17 |
| `validate` | Schema + 31 enumerated static logical checks. | FR-2 |
| `materialize` | Run the pipeline end-to-end against the recipe's inputs. | FR-3 |
| `status` | Summarize a materialized instance or resolve a recipe to one. | FR-19 |
| `report` | Re-render `report.md`, `drift.json`, and reporting visualizations. | FR-15 |
| `inspect` | Read-only views of a materialized instance. | FR-20 |
| `export` | Re-run `Sinks` against an existing instance without re-materializing. | FR-3 |
| `clean` | Remove cached instances and orphan temp directories. | FR-21 |

Execution-context flags (never alter pipeline semantics):

| Flag | Env var | Effect |
|------|---------|--------|
| `--cache-root` | `DATAREFINERY_CACHE_ROOT` | Root directory for the cache. |
| `--log-level` | `DATAREFINERY_LOG_LEVEL` | Operational log level. |
| `--log-target` | `DATAREFINERY_LOG_TARGET` | Log routing target (reserved). |
| `--plugin-path` | `DATAREFINERY_PLUGIN_PATH` | Extra plugin discovery paths. |
| `--workers` | `DATAREFINERY_WORKERS` | Process-pool worker count. |
| `--overlay` | — | Recipe overlay to apply before canonicalization (repeatable). |
| `--seed` | — | Override the recipe seed (changes cache identity). |

## Plugin model

A **plugin** contributes the operations that make sense for one data
category. Plugins register through the `datarefinery.plugins`
entry-point group and are discovered automatically.

v1 ships:

- `image_classification` — fully-real, full operation set (resize,
  normalize, class-distribution and sample-grid visualizations,
  label-from-path featurization, aggressive augmentations, etc.).
- `audio_classification` — fully-real (requires the `[audio]` extra):
  `audio_folder` / `audio_flat` sources with clip decode + resample,
  the `window` Generation op, and the `log_mel_spectrogram` +
  fit-on-train `audio_normalize` Featurization chain. Validates the
  category-agnostic abstractions on a second real category.
- `tabular` — stub plugin exercising the abstractions; no working ops.
- `text` — stub plugin exercising the abstractions; no working ops.

A plugin declares, for each operation, an `OperationSpec` covering
parameter schema, `fit_on_train` flag, applicable splits, and
applicable recipe sections. The validator cross-checks recipe
operations against these specs (FR-2 check 18). See
[`src/datarefinery/plugins/base.py`](src/datarefinery/plugins/base.py)
for the protocol, and the [plugin authoring guide](docs/guides/plugin-authoring.md)
for a walk-through of writing your own.

## Library API

Library and CLI are co-equal surfaces driven by the same recipe.

```python
from pathlib import Path

from datarefinery import DataRefinery, materialize
from datarefinery.core.config import RuntimeConfig

config = RuntimeConfig(cache_root=Path("./cache"))

# High-level: one-shot materialize a recipe path.
instance = materialize("recipe.yaml", config=config)
print(instance.manifest.record_counts)

# Lower-level: load once, then call verbs against the loaded recipe.
dr = DataRefinery.from_recipe("recipe.yaml", config=config)
report = dr.validate()
instance = dr.materialize()
```

## v1 scope and non-goals

**In scope for v1:**

- Recipe-driven pipeline with the section set above; explicit
  per-operation stage/split applicability.
- Schema-versioned YAML recipes; load-time refusal of unknown
  versions; documented migration path between versions.
- Materialized instance = recipe + dataset + fitted statistics +
  report. No statistical artifacts persisted outside the report.
- Segmented semantic cache identity (per-segment canonical recipe hash
  ⊕ raw-input hash ⊕ seed). Whitespace/key-order edits do not trigger
  rebuilds; a single-segment edit invalidates only that segment's scope.
- Atomic temp-then-promote materialization; no partial instances in
  cache.
- Named overlays within a recipe; experiment knobs are overlays, not
  separate recipes.
- Two fully-real plugins — `image_classification` and
  `audio_classification`, both scoped to **classification** — plus
  tabular and text stubs.
- Deterministic `init` scaffolder (image only); optional LLM
  enhancement layer via `lmentry` as an extra.
- Stable drift-relevant report subsection for downstream tooling.

**Non-goals for v1:**

- Image and audio tasks beyond classification (detection,
  segmentation; audio event detection / source separation).
- Model framework abstraction, training, evaluation, inference.
- Production streaming and drift-detection logic.
- Persisted statistical artifacts beyond the report (no sidecar
  pickles, no separate stats files).
- Recipe inheritance or multi-file recipe composition (overlays
  suffice).
- Resume-from-stage during materialization.
- Hard LLM dependency (DataRefinery must work fully offline).
- Tabular and text plugin implementations (stubs only).
- Hard performance targets (reactive performance work only).
- `init` for non-image categories (audio recipes are written by hand).

For the full requirements, see
[`docs/specs/features.md`](docs/specs/features.md). For implementation
details, see [`docs/specs/tech-spec.md`](docs/specs/tech-spec.md).

## License

Licensed under the [Apache License, Version 2.0](LICENSE).

Copyright (c) 2026 Pointmatic.
