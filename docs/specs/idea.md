# DataRefinery — recipe-driven data preparation for machine learning

Preparing data for machine learning training is a recurring chore: setting up tooling, navigating hardware and software friction, exploring raw data, cleaning it, transforming it, splitting it into train/val/test, generating features, and keeping all of that reproducible across experiments and consistent between training and inference. The work requires specialized knowledge and tools, and unless someone does it daily, the steps and gotchas decay between projects.

DataRefinery is a Python tool that wraps the standard scientific Python stack (NumPy, Pandas, SciPy, Scikit-learn, etc.) behind a recipe-driven interface. The user writes a single recipe (YAML config) describing the data and the desired preparation pipeline; DataRefinery executes it reliably and produces a training-ready dataset. The tool runs in the background — downstream artifacts (notebooks, coursework deliverables) reference DataRefinery outputs but don't expose its recipe DSL.

A DataRefinery instance is a recipe combined with the materialized dataset and the fitted statistics produced by running it. All three are required: the combination is what makes the instance wholly reproducible and what gives downstream tools something concrete to consume. Re-running an unchanged recipe over unchanged inputs returns the cached instance; any change invalidates and rebuilds.

## Recipe sections

A recipe describes the data category, raw inputs, expected outputs, and the operations applied along the way. Each operation declares which pipeline stages and splits it applies to, so train-only behavior (e.g. augmentation) is explicit rather than implicit. The pipeline order across sections is configurable and explicit; DataRefinery doesn't impose a fixed order beyond what's logically required. Each recipe declares a schema version, and DataRefinery refuses to load a recipe whose version it doesn't understand.

- **Input** — shape and schema of raw data to ingest, including any per-record metadata available alongside the primary content (e.g. filenames, directory paths, sidecar files). Multiple raw sources may be declared and joined by a declared key.
- **Output** — shape and schema of the prepared dataset.
- **Labels** — declaration of what the label is and how it's obtained: present in the raw input, or derived. Derived labels are produced by the same machinery as featurizations and may draw on any declared input source, including filenames and other metadata.
- **SampleData** — a small representative dataset for fast iteration, exploration, and tests.
- **Contracts** — assertions the data must satisfy; protects downstream stages from malformed inputs.
- **Filters** — rules for reducing the raw set (sampling, inclusion/exclusion by value or range).
- **Generation** — production of new records added to the dataset (e.g. SMOTE, naive minority-class oversampling, externally synthesized data). Generation changes record count and is distinct from Augmentation, which perturbs records on the fly during training without changing dataset size.
- **Splits** — train/validation/test strategy, including stratification, class-balance handling, and seed.
- **Transformations** — deterministic modifications applied to one or more splits (e.g. rounding, Winsorization, image resize/normalize).
- **Augmentations** — stochastic operations that expand the effective dataset, typically train-only (e.g. random crop, flip, color jitter).
- **Featurizations** — derivation of new features from one or more existing inputs.
- **Visualizations** — standard or bespoke views over any stage of the pipeline. Each visualization declares whether it is an exploration view (rendered on demand, not persisted) or a reporting view (rendered as part of the materialized instance).

Reproducibility is a first-class concern: every stochastic operation is seeded, and any fitted statistics (e.g. normalization parameters) computed on the training split are persisted with the recipe so the same preparation can be replayed at inference time.

## Data categories and plugins

A data category is defined by its native record shape and the operations that make sense on it — for example, image (2D arrays of pixels), text (token sequences), tabular (feature vectors with mixed types), and time-series (ordered tabular with temporal semantics). A plugin specializes DataRefinery for a single category and contributes the operations relevant to that type. Subdivisions within a category live as plugin-internal options, not separate plugins.

The first plugin shipped is Image, scoped to classification, supporting a consumer's machine learning curriculum. To keep the plugin interface honest, at least one additional category is sketched as a stub — minimally a recipe section list and operation outline for tabular, and ideally also for text — without implementation. The stubs exist to validate that category-agnostic abstractions are not "Image with extra steps" and to frame how future plugins would slot in.

## Reporting

Each materialized DataRefinery instance emits a report describing the prepared dataset and the operations that produced it. The report is the only persisted summary of the instance's data characteristics; statistical persistence in any other form is out of scope for DataRefinery itself. The drift-relevant content of the report is a defined subsection that downstream tools can consume against a stable contract.

## Surfaces

DataRefinery is exposed as both a Python library and a CLI. CLI verbs cover lifecycle (`status`), recipe correctness (`validate`), and environment soundness (`check`), alongside the verbs that drive the pipeline itself.

## Related tools

- **ModelFoundry** — consumes a DataRefinery instance and abstracts the model framework (PyTorch, TensorFlow, Keras, Scikit-learn) and host platform (OS, hardware acceleration: CUDA, Metal, CPU).
- **ModelMetrics** — evaluation framework for supervised learning models.
- **ModelMachine** — runs inference using a paired ModelFoundry and DataRefinery instance.
- **DataMachine** — extends a DataRefinery instance for production: abstracts the infrastructure needed to operate on an endless data stream or a sequence of batches, and detects data drift relative to the original DataRefinery instance's report.
