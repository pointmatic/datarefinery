# DataRefinery — Supplementary Context Brief

Companion to the DataRefinery idea brief. Captures decisions, rationale, and constraints settled during ideation that fall outside the scope of the brief itself but are needed to produce concept, features, tech-spec, and stories documents downstream.

---

## Source context

DataRefinery originated as a tool to support producing artifacts for data preparation. This system will integrate with `LearningFoundry`, a curriculum presentation tool.

## Scope discipline / out of scope

The following were considered and explicitly deferred or excluded:

- **Image plugin tasks beyond classification** — detection and segmentation are out for v1. The plugin interface should accommodate them later without recipe-schema breakage, but no implementation work happens now.
- **Full encoder/model concerns** — DataRefinery does not own model framework abstraction, training, evaluation, or inference. Those belong to ModelFoundry, ModelMetrics, and ModelMachine respectively.
- **Production streaming and drift detection logic** — those belong to DataMachine. DataRefinery's contribution is emitting a report whose drift-relevant subsection DataMachine consumes.
- **Persisted statistical artifacts beyond the report** — DataRefinery uses a report structure as the persistence mechanism for evaluation summaries. No separate stats files, pickled distributions, or sidecar manifests holding statistics outside the report.
- **Recipe inheritance / multi-file composition** — deferred. Variants within a single recipe are sufficient for v1.
- **Resume-from-stage during materialization** — deferred. Atomic temp-then-promote is the v1 failure model.
- **Hard LLM dependency** — DataRefinery must work fully offline. LLM assistance in `init` is an optional enhancement layer only.

## Naming conventions and rationale

- **DataRefinery** chosen over DataDriver and DataCooker. Refining raw inputs into a usable form fits the operation; sits cleanly alongside ModelFoundry/ModelMachine/DataMachine; avoids the "cooking the books" connotation in a coursework context.
- **Recipe** is the configuration metaphor. Appliance metaphors (microwave, crockpot, self-driving car) were dropped — recipe carries the metaphor on its own.
- **Section names** were chosen to avoid collision with standard ML terminology:
  - `Contracts` → `InputContracts` (avoids collision with the validation set)
  - `Examples` → `SampleData` (avoids collision with training examples)
  - `Expectations` → `OutputExpectations` (paired with InputContracts; clarifies stage)
- **Augmentation vs. Generation vs. Transformation** — three distinct concepts:
  - *Transformations*: deterministic, applied across splits as configured (e.g. resize, normalize).
  - *Augmentations*: stochastic, train-only, on-the-fly, do not change dataset record count.
  - *Generation*: produces new records added to the dataset (e.g. SMOTE, oversampling, externally synthesized data); changes dataset record count.

## Decisions beyond the brief's prose

These are settled but don't belong in the idea brief itself.

**Recipe granularity.** One recipe per dataset, not per experiment. Experiment-specific knobs (e.g. augmentation policy, filter variants for imbalance experiments) are *named variants* within the recipe, selectable at materialization time. A new instance is materialized per variant.

**Variants scope.** Variants apply to any recipe section in v1 (including Filters), not just augmentation. Recipe inheritance is deferred.

**Class-imbalance handling locus.** Imbalance produced by *removing* data lives in `Filters`. Imbalance handled by *weighting or resampling during training* lives in `Splits` as a sampling strategy that ModelFoundry honors. Same outcome class, two distinct recipe surfaces, no overlap.

**Output vs. OutputExpectations split.** `Output` is the structural contract — record shape, field names, dtypes — that downstream tools (ModelFoundry) bind against. `OutputExpectations` covers value-range and distributional assertions evaluated against the materialized dataset. They are peers, not nested.

**Failure semantics during materialization.** Write to a temporary location; atomically promote to the cached instance only on success. On failure, leave the temp directory in place with a clear marker for inspection. No partial instances ever appear in the cache.

**Cache identity model.** Cache key derives from the recipe's *normalized semantic form* (parsed, key-sorted, comments stripped) plus raw input hash plus seed — not from raw recipe file bytes. Whitespace or key-order edits don't trigger rebuilds; semantic edits do.

**Recipe schema versioning.** Each recipe declares a schema version. DataRefinery refuses to load a recipe whose version it doesn't understand. A documented migration path between versions ships with the tool.

**Visualization output modes.** Each visualization in the recipe declares whether it is an *exploration view* (rendered on demand, not persisted) or a *reporting view* (rendered into the materialized instance's report). Both modes are supported.

**`validate` scope.** `validate` covers schema correctness *and* a defined, enumerated set of static logical checks (e.g. transformations referencing dropped columns, augmentations declared on validation/test). The check list is enumerated in the spec, not open-ended. Anything requiring data flows through materialization, not `validate`.

**Plugin design honesty.** Image is the only plugin shipped, but at least one additional category — tabular at minimum, ideally text as well — is sketched as a stub (recipe section list and operation outline only, no implementation) to validate that category-agnostic abstractions are not "Image with extra steps."

## `init` (recipe bootstrapping) design

Layered:

1. **Deterministic scaffolder (always available, offline)** — inspects file types, dimensions, dtypes, directory structure, and basic stats, then emits a starter recipe with `Input` populated, common `Transformations` stubbed in (commented out), `Splits` seeded with sensible defaults, and the chosen plugin's standard sections present. Sufficient for CIFAR-10 unaided.
2. **Optional LLM enhancement layer (activates only when configured)** — adds interpretive judgments the deterministic layer can't make: column-name semantics, label-source inference when ambiguous, suggested augmentation policies, plain-English comments. Routed through `lmentry` so the user is not locked to a single provider.

DataRefinery does not depend on `lmentry` at the package level; it's an optional extra. The deterministic path remains the contract.

## Surface conventions

CLI verbs settled so far:

- `init` — recipe bootstrapping (deterministic, optional LLM enhancement)
- `validate` — recipe correctness (schema + enumerated static logical checks)
- `check` — environment/installation soundness
- `status` — instance lifecycle/configuration summary

Pipeline-driving verbs (e.g. for materialization, reporting) are not yet named; other model-focused verbs (`score`, `train`, `tune`, `report`) are intentionally *not* used because those are ModelFoundry concerns. Verb naming for DataRefinery's pipeline operations is open and should be settled in the features spec.

Library API and CLI are co-equal surfaces.

## Conventions inherited from related projects

These should be assumed unless explicitly overridden:

- **Environment management** — `pyve` with micromamba backend; Python 3.12.x pinned; `pyproject.toml` + `environment.yml`; `hatchling` build backend.
- **Tooling** — `ruff` (lint + format), `mypy --strict`, `pytest` with `pytest-cov`.
- **Packaging** — installed editable in dev (`pip install -e .`); CLI installed via `pyproject.toml` entry points.
- **Caching** — parquet for tabular caches, content-addressed paths; cache directories under a `data/` tree (`data/raw/`, `data/preprocessed/`, etc., as appropriate per stage).
- **Configuration** — YAML, single file per recipe. Schema-versioned.
- **Reproducibility** — every stochastic operation seeded; same recipe + same inputs + same seed → identical instance.
- **CLI ergonomics** — `rich`-based output, per-stage progress, structured tables.
- **Health-check pattern** — A `check` command is the model is a sanity check for DataRefinery's environment (installation, dependencies, etc.).

## Author working preferences

These shape the downstream documents.

- **Plan first, execute in moderate chunks.** No oversized step that can't be reviewed.
- **Strong recommendations over menus.** When options are presented, one is recommended with rationale; the others are documented but the author should not have to break the tie.
- **Concise and precise.** No hedging or padding. Pushback and editorial judgment are welcomed.
- **Verification discipline.** Factual claims and citations are web-verified before being committed to documents.
- **Document chain.** concept → features → tech-spec → stories. Each document is the input to the next; revisions stay scoped to the document being worked on.

## Open items to settle in `concept.md` or later

Carried forward, not yet resolved:

- Naming for pipeline-driving CLI verbs (materialize, report, etc.) — open.
- Exact contents of the report's drift-relevant subsection (the contract DataMachine reads against) — open; should be specified by the time DataMachine work begins, but a placeholder is acceptable in DataRefinery's first concept doc.
- Enumerated list of static logical checks performed by `validate` — to be defined in the features or tech spec.
- Whether the second plugin stub is tabular only or tabular + text — author leaning toward "agreed" on the broader sketch; final scope can be set in the features spec.