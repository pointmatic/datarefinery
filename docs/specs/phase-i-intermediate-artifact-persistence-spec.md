# DataRefinery — intermediate-artifact persistence (Sinks)

**Status:** Proposal. Filed against datarefinery 0.16.0 as a feature
specification. Authoring story: d802-deep-learning Story B.f. Implementation
in DataRefinery is a separate downstream change; this document is the
canonical proposal-of-record.

**Companion docs:**
- [`dependency-gaps-v0.16.0.md`](dependency-gaps-v0.16.0.md) (gap G18
  documents the surface symptom this spec resolves).
- [`../phase-b-task2-data-preparation-plan.md`](../phase-b-task2-data-preparation-plan.md)
  § 7 (initial sketch).

---

## 1. Problem statement

DataRefinery's reproducibility contract — **same recipe + same inputs +
same seed produces a byte-identical materialized instance** — applies to
the cache's JSONL records, `manifest.json`, `recipe.json`,
`fitted_statistics/`, and `report/`. Within that contract,
intermediate-stage artifacts are **transient**: each pipeline stage runs
in memory and the next stage mutates its output in place. By the time
the cache is written, only the post-pipeline representation survives.

For the `image_classification` plugin this manifests concretely. Walking
a Recipe B-style pipeline:

| Stage | What's in memory | What's persisted |
|---|---|---|
| Loader | uint8 RGB array per record (read from source PNG) | (transient) |
| Filters (`sample_per_class`) | uint8 RGB array, tagged | (transient) |
| Splits | uint8 RGB array, in `train`/`val`/`test` | (transient) |
| **Generation (`imagecorruptions_apply`)** | **uint8 corrupted RGB array** — the export-deliverable representation | (transient) |
| Transformations (`normalize`) | float64 normalized array (the uint8 corrupted bytes are mutated in place here) | this becomes the cached `image` field |
| OutputExpectations | post-normalize records | (no record output) |
| Visualizations | post-normalize records | `report/visualizations/*.png` |
| Cache write | float64 records → JSONL | `dataset/<split>.jsonl` |

The uint8 corrupted RGB representation exists for one stage, then
becomes inaccessible. Any consumer wanting that representation — for
example, the d802-deep-learning Task 2 submission deliverable, which
ships uint8 PNGs in a directory tree for downstream readability —
cannot recover it bit-identically from the cache. Two workaround paths
exist; neither preserves DataRefinery's reproducibility contract:

1. **Re-derive from `source_path` + DR's internal `per_record_seed`.**
   `datarefinery.pipeline.workers.per_record_seed` is importable but
   not formally a public contract; relying on it puts every downstream
   consumer at risk of a DR-internal rename. Even if the symbol is
   stable, the consumer must re-implement the corruption-apply
   pipeline, which couples the consumer to the plugin's backend
   library.
2. **Denormalize from cache + clip-cast to uint8.** Lossy: the uint8
   round-trip through float64 normalization loses quantization
   precision.

Neither path is bit-identical to "what the Generation stage produced."
This is a structural gap in DataRefinery's persistence contract, not a
plugin defect.

---

## 2. Design positions considered

Two coherent architectures address the gap:

### Position A — Cache stores fully-realized artifacts; Sinks capture stage snapshots

The cache stores the post-pipeline JSONL records as today, plus
**stage-snapshot artifacts** written to disk at materialize time per
recipe-declared sinks. Consumers read whichever representation they
need. Storage-heavy; consumer-light.

### Position B — JSONL-as-index, consumers re-derive

The cache stores only **metadata** (label, path, record_id, generation
tags, per-record seeds) plus fitted statistics. The `image` field is
stripped from JSONL. Consumers re-derive any image representation on
demand by composing source PNG + recorded seeds + fitted stats.
Storage-light; consumer-pays-per-read.

### Recommendation: Position A with Sinks

Position A is recommended for v1 of this feature:

- **Storage is cheap; compute amortization matters.** A Recipe B cache
  instance is ~320 MB JSONL today (13K records × 32×32×3 × 8 bytes).
  Adding uint8 PNG sidecars costs ~40 MB (~10–13% overhead). Total
  ~360 MB per instance. Trivial on modern disk; multiplies favorably
  vs. forcing every consumer to re-derive.
- **Consumer-light is a UX win.** Training loops, eval scripts,
  visualizations, and exports all read pre-baked arrays. Position B
  would force each consumer to re-implement the pipeline composition;
  every team owns the same boilerplate.
- **Position A is closer to current DR behavior.** The JSONL `image`
  field already exists. Sinks are an additive feature; Position B
  would be a backward-incompatible removal of the field.
- **Configurability is overengineering.** Making A/B selectable per
  recipe would multiply the matrix DR has to test (`mode × variants ×
  sinks`), require authors to make a choice they shouldn't have to,
  and create two consumer codepaths to maintain. YAGNI for v1.

Position B is recorded here for future consideration. If a use case
emerges where Position-A storage cost becomes prohibitive (e.g.,
million-record recipes, multi-modal records with large per-record
payloads), DataRefinery can introduce a JSONL-as-index mode at that
time. The Sinks mechanism specified below is independent of any future
A/B mode choice.

---

## 3. The Sinks mechanism

Add a new top-level recipe section, `Sinks`, listing one or more
disk-output declarations. Each declaration writes one or more files
into the cache instance directory at materialize time, captured from
a named pipeline stage and a named record field, organized under a
recipe-author-supplied path template.

### 3.1 Recipe section

```yaml
Sinks:
  - name: corruption_pngs
    stage: post_Generation
    splits: [test]
    field: image
    format: png_per_record
    path_template: "exports/cifar-10-c/{corruption}/sev{severity}/{label}/{source_path|stem}__sev{severity}.png"

  - name: base_pngs_uint8
    stage: post_Filters    # before normalize stomps the uint8 image
    splits: [train, val, test]
    field: image
    format: png_per_record
    path_template: "exports/cifar-10/{split}/{label}/{record_id}.png"
```

### 3.2 Field-by-field semantics

| Field | Type | Required | Purpose |
|---|---|---|---|
| `name` | `str` | yes | Sink identifier. Used as the on-disk root segment and as the sink's manifest key. Must be unique within a recipe. |
| `stage` | `str` | yes | Pipeline stage whose output the sink observes. Constrained to a closed vocabulary (see § 3.3). |
| `splits` | `list[str]` | no | Which splits to capture. Defaults to all splits known at the chosen stage. |
| `field` | `str` | yes | Record field whose value gets serialized. Must satisfy the chosen `format` (e.g., `png_per_record` requires the field to carry a uint8 H×W×C numpy array). |
| `format` | `str` | yes | Serialization format. v1: `png_per_record`. Forward-compatible: `npy_per_record`, `parquet`, `tar`, etc. (see § 3.4). |
| `path_template` | `str` | yes | Per-record output path, with field-substitution placeholders (see § 3.5). Path is interpreted relative to the cache instance directory. |

### 3.3 Stage vocabulary

The `stage` value is a closed enum mirroring
`datarefinery.pipeline.runner.STAGE_NAMES`. Sinks observe a stage's
**output** (i.e., the records as they leave the named stage, before
the next stage runs):

- `post_InputContracts`
- `post_Filters` (= post `Filters/post_split`)
- `post_Splits`
- `post_Generation`
- `post_Transformations`
- `post_Featurizations`
- `post_Augmentations` (lazy-mode: records are unchanged; aggressive-mode: see § 3.6)
- `post_OutputExpectations` (= post-pipeline, equivalent to the
  current cache write state)
- `post_Visualizations` (no-op for record sinks; reserved for future
  report-sink extensions)

Cross-link with G7: visualization-stage selection and sink-stage
selection share this vocabulary. Both should constrain `stage` via a
`Literal[...]` on the recipe model.

### 3.4 Format vocabulary

v1 ships one format. The grammar is extensible; future formats slot in
without recipe-schema churn.

| `format` | Required field shape | Output |
|---|---|---|
| `png_per_record` | uint8 H×W×C ndarray (or H×W for grayscale) on the named `field` | One PNG file per record under `path_template`. PIL's `Image.fromarray` writes the bytes. |

Future-compatible candidates (not in v1; listed for spec stability):

- `npy_per_record` — any numpy-serializable ndarray on `field`. One
  `.npy` per record.
- `parquet` — flat tabular sink for scalar / 1-D record fields. One
  parquet table per sink; `path_template` produces the single output
  path (no per-record substitution). Useful for "dump record_id +
  label + corruption + severity columns as a CSV alternative."
- `tar` — bundles per-record artifacts into a single `.tar.gz`.
  Composes with `png_per_record` etc.

### 3.5 Path template grammar

The simplest grammar that covers known use cases:

- `{field_name}` — substitute the record's value of `field_name` as a
  string. Required field must exist on every record at the chosen
  stage; missing field is a `MaterializeError`.
- `{field_name|filter}` — apply a named filter. v1 filters:
  - `|stem` — Path.stem of a string value (e.g., `path|stem` turns
    `"data/raw/cifar-10/train/1234.png"` into `"1234"`).
  - `|lower`, `|upper` — case transforms.
  - `|str` — explicit string coercion for integer fields (e.g.,
    `severity|str`).
- `{split}` — the current split name (special variable, always
  available).

Path is **interpreted relative to the cache instance directory**.
After materialization, the sink's output files live at
`<cache_root>/instances/<recipe_hash>/<input_hash>/<seed>/<path_template_resolved>`.

A worked example for the Recipe B sink above:

| Record (post-Generation) | Resolved path |
|---|---|
| `{record_id: "1234_gaussian_noise_s1_a1b2c3d4", label: "airplane", source_path: "data/raw/cifar-10/train/1234.png", corruption: "gaussian_noise", severity: 1, ...}` | `exports/cifar-10-c/gaussian_noise/sev1/airplane/1234__sev1.png` |

### 3.6 Augmentation interaction (lazy vs aggressive)

For lazy-mode Augmentations, `post_Augmentations` is identical to
`post_Featurizations`: records are unchanged. For aggressive-mode
Augmentations, `post_Augmentations` includes the realized
variant records (which have their own `record_id` values per
Story H.r.2). A sink at `post_Augmentations` captures one PNG per
variant.

Authors who want pre-augmentation snapshots should target
`post_Featurizations` (or earlier).

---

## 4. Cache identity and atomicity

### 4.1 Cache-identity participation

Sink configuration **participates in canonical recipe bytes**, so
editing a sink (adding, removing, or modifying any field) invalidates
the cache instance and forces a re-materialize. This is consistent
with how every other recipe section behaves under
`datarefinery.recipe.canonical.to_canonical_bytes`.

Rationale: a recipe with sink X and a recipe with sink Y produce
*different materialized instances* — the on-disk layout differs. Cache
identity must reflect that.

Naming subtlety: changing only a sink's `path_template` (with all
other fields equal) also invalidates. This is intentional —
downstream tools that bind against the path layout deserve the
invalidation.

### 4.2 Atomic write semantics

Sinks integrate into the existing temp-then-promote atomicity (FR-5).
At materialize time:

1. Each sink writes its output files under
   `<cache_root>/instances/.tmp/<run_id>/<path_template_resolved>`.
2. On successful pipeline completion, the entire `.tmp/<run_id>/`
   directory atomically renames to the final
   `<cache_root>/instances/<recipe_hash>/<input_hash>/<seed>/`.
3. On pipeline failure (any stage raises), the `.tmp/<run_id>/` dir
   is marked `FAILED` and left in place for diagnosis; no partial
   sink output ever appears under the promoted cache path.

This matches how `fitted_statistics/` and `report/` already work; the
sink output is just another set of files under the same instance
directory.

### 4.3 Manifest record

Each sink declaration produces a manifest entry:

```json
{
  "sinks": {
    "corruption_pngs": {
      "stage": "post_Generation",
      "format": "png_per_record",
      "files_written": 12000,
      "bytes_total": 38400000,
      "path_template_resolved_root": "exports/cifar-10-c"
    },
    "base_pngs_uint8": {
      "stage": "post_Filters",
      "format": "png_per_record",
      "files_written": 3000,
      "bytes_total": 9600000,
      "path_template_resolved_root": "exports/cifar-10"
    }
  }
}
```

Consumers query the manifest to discover which sinks ran and how many
files they wrote. The `files_written` count is asserted against the
expected per-split / per-record cardinality at runtime; a mismatch
fails the materialize (`SinkCardinalityError`).

---

## 5. The `datarefinery export` verb

For cases where a recipe author adds a sink to an already-materialized
recipe and doesn't want to burn the cache, a new CLI verb (and library
method) re-runs sinks against an existing instance:

```bash
datarefinery export recipes/cifar10c-eval.yaml --sink corruption_pngs
```

Semantics:

1. Load the recipe and the bound instance (via the same path
   `datarefinery status` uses).
2. Verify the requested sink is declared in the recipe.
3. **Re-execute only the pipeline stages between the sink's `stage`
   and the cache state.** For sinks targeting late stages
   (`post_OutputExpectations`), this is a no-op read from JSONL. For
   sinks targeting earlier stages, this may require re-running
   stage-internal logic against the cached records.
4. Write sink output into the existing instance directory.

**Restriction in v1:** the `export` verb only handles sinks targeting
stages whose output is **reconstructable from the cached state +
fitted statistics + recorded per-record seeds**. For
`post_Generation` sinks against `imagecorruptions_apply` outputs, the
record's `source_path` + `corruption` + `severity` + a recorded
per-record corruption seed suffice. Recipes that move the sink to a
pre-Generation stage where the cached state has been further
transformed (e.g., normalized) require re-materialize, not `export`.

Adding the `export` verb introduces a soft dependency: every
`Generation` op must record per-record seeds into a manifest sidecar
or into the records themselves, so the `export` verb can reconstruct
the op's RNG state without re-deriving from the recipe seed alone.
This is a small piece of metadata to capture per generated record
(8 bytes) and unblocks an arbitrarily large family of post-hoc
exports.

---

## 6. Worked example — Recipe B sink for d802 Task 2

Recipe B (`cifar10c-eval.yaml`) with the sink declaration that
replaces the d802 project-local export script:

```yaml
# (existing recipe sections elided)

Sinks:
  - name: corruption_pngs
    stage: post_Generation
    splits: [test]
    field: image
    format: png_per_record
    path_template: "exports/cifar-10-c/{corruption}/sev{severity|str}/{label}/{source_path|stem}__sev{severity|str}.png"

  - name: corruption_index
    stage: post_OutputExpectations
    format: parquet     # future format; v1 falls back to JSONL re-emit
    path_template: "exports/cifar-10-c/index.parquet"
```

After `datarefinery materialize recipes/cifar10c-eval.yaml`, the cache
instance directory contains:

```
cache/instances/<hash>/<inputs>/<seed>/
├── dataset/
│   ├── test.jsonl       (13,000 records)
│   ├── train.jsonl
│   └── val.jsonl
├── exports/
│   └── cifar-10-c/
│       ├── gaussian_noise/
│       │   ├── sev1/
│       │   │   ├── airplane/  (100 PNGs)
│       │   │   ├── automobile/
│       │   │   └── ... (10 classes)
│       │   ├── sev3/
│       │   └── sev5/
│       ├── motion_blur/...
│       ├── fog/...
│       ├── jpeg_compression/...
│       └── index.parquet      (12,000 rows of metadata)
├── fitted_statistics/
├── manifest.json
├── recipe.json
└── report/
```

The d802 export step becomes a thin orchestration:

```bash
datarefinery materialize recipes/cifar10c-eval.yaml
# Sink runs at materialize time; PNGs are already in <cache>/exports/.

# Copy the cache-resident export tree into the submission staging dir:
rsync -a "$(datarefinery status recipes/cifar10c-eval.yaml --print path)/exports/cifar-10-c/" \
        data/materialized/cifar-10-c-seed11/

tar czf cifar10-task2-submission.tar.gz -C data/materialized cifar-10-c-seed11
```

No project-side re-corruption code. No `per_record_seed` import. No
denormalization. The submission is bit-identical to what the
Generation stage produced, by DataRefinery's existing reproducibility
contract.

---

## 7. Implementation phasing

Suggested rollout sequence for the DR side:

### Phase 1 — Schema + materialize-time sinks (closes G18)

- Add `Sinks` section to the `Recipe` pydantic model.
- Add `SinkOp` model with fields per § 3.2.
- Add the `Literal[...]` enum for `stage` per § 3.3 (this also lets
  G7 land for visualizations, since both use the same vocabulary).
- Add validator checks: sink names unique; `stage` valid; `field`
  exists at the chosen stage; `path_template` parses cleanly; path
  templates don't escape the instance directory; `format` is one of
  the v1 set.
- Add a sink-execution stage to the pipeline runner that runs after
  each named stage emits its records.
- Add the `png_per_record` writer implementation.
- Add manifest entries per § 4.3.
- Cache-identity participation: `Sinks` enters
  `to_canonical_bytes(recipe)`.

**G18 closes once Phase 1 ships.** The d802 Recipe B can declare a
sink and bit-identical export becomes structural.

### Phase 2 — `datarefinery export` verb

- Add `datarefinery export <recipe> [--sink <name> ...]` CLI verb.
- Add `DataRefinery.export(sink_name=None)` library method.
- Persist per-record `<op_name>_seed` fields for every stochastic op
  whose output a sink could capture (so the export verb can
  reconstruct stage outputs without re-materialize).
- Add a `recipe-authoring.md § Sinks` subsection (per the DOC rule in
  `dependency-gaps-v0.16.0.md`).

### Phase 3 — Additional formats

- Add `npy_per_record`, `parquet`, `tar` formats as separate stories
  per FR.
- Each format lands with its `recipe-authoring.md` row.

### Cross-repo coordination

Sinks add a manifest field (`manifest.sinks`). Per
`project-essentials.md` § "Recipe / manifest / report shape changes
need a cross-repo coordination check", the implementing story must:

- Update [`docs/specs/modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md)
  with the new manifest field shape so ModelFoundry's manifest
  reader doesn't break.
- Confirm the dataset-foundry / nbfoundry side has no manifest-shape
  consumers (per current state — they read JSONL only).
- No `schema_version` bump (additive recipe section; no
  back-incompat).

---

## 8. Out of scope (v1)

- **Position B (JSONL-as-index).** Recorded in § 2; deferred until a
  forcing function exists.
- **Cross-record sink formats** (e.g., `tar` of the whole split as
  one archive). v1 is per-record; cross-record formats are listed
  under Phase 3.
- **Sink dependencies / ordering.** v1 sinks all run after the
  pipeline stage they target, in declaration order. Sinks-depending-
  on-other-sinks is not in scope.
- **Sink validation against `Output.record_schema`.** v1 trusts the
  recipe author to declare a `field` that exists at the chosen
  `stage`. A stricter "sink fields must appear in
  Output.record_schema" check is not in scope (it's actually wrong
  in the common case — `post_Filters` sinks capture pre-normalize
  uint8 which isn't the final cached representation).
- **Conditional sinks** (e.g., "write PNG only if `record.severity >
  0`"). v1 captures every record at the chosen stage that matches
  the `splits` filter. Conditional capture is a future feature.
- **Sink output validation** beyond the cardinality check. A
  hypothetical "every written PNG must decode cleanly" check is
  expensive and not in v1.

---

## 9. Acceptance criteria

- [ ] `Sinks` recipe section accepted by the pydantic model and the
      validator.
- [ ] A recipe declaring a `png_per_record` sink at `post_Generation`
      writes the expected file count to the cache instance directory
      at materialize time, with each file's bytes matching the
      `Image.fromarray(record["image"])` PNG encoding.
- [ ] Editing the sink's `path_template` (with all other fields equal)
      invalidates the cache.
- [ ] Manifest carries `sinks.<name>` entries per § 4.3.
- [ ] Sink writes participate in atomic temp-then-promote (FR-5):
      pipeline failure leaves no sink output under the promoted path.
- [ ] G18 (Generation extends, not replaces) interaction: a sink at
      `post_Generation` captures both the originals (untagged) and
      the corrupted variants (tagged), per the current extend-not-
      replace semantics. When G18 closes and Generation switches to
      replace-by-opt-in, the sink output respects the recipe's
      `replace_input_records` setting automatically.
- [ ] `recipe-authoring.md § Sinks` is authored alongside the
      implementation (per the DOC rule in
      `dependency-gaps-v0.16.0.md`).
- [ ] Cross-repo: `modelfoundry/dependency-spec.md` updated with the
      new `manifest.sinks` field.

---

## 10. Q&A (was Open Questions)

1. **Field-derived nested directories.** Should the path template
   accept arbitrary nesting via `{field/subfield}` for records with
   nested mappings? **Resolved (declined for v1+).** Path templates
   require flat field names. Today every loader-, Generation-,
   Featurization-, and Augmentation-stamped record field is a flat
   scalar, and `Output.record_schema` is `dict[str, FieldSpec]` — flat
   by design. Adding `{a/b}` access would create a mismatch where the
   record shape declared in the schema is flat but the template
   grammar imagines structured access, and would open follow-ons
   (list indexing, missing-subfield behavior, leaf-type coercion).
   Recipes that want grouped metadata in sink paths should expose
   the relevant leaf as a top-level field via a Featurization,
   keeping `Output.record_schema` and the validator's field-universe
   check consistent. Revisit only if a downstream consumer surfaces a
   real case (e.g. multi-modal records) where the Featurization
   escape hatch is unworkable.
2. **Conflict resolution under variants.** A recipe variant overlay
   may override `Sinks: []` to disable sinks. Should the empty
   override clear sinks entirely, or should variants merge?
   **Resolved (confirmed for v1+).** Variant overlays apply to
   `Sinks` with the same wholesale-replacement semantics as every
   other list-valued section. `Sinks: []` in a variant clears the
   section; `Sinks: [<new>]` replaces the base list. Authors who want
   to add a sink to a variant duplicate the base entries. The cost is
   recipe verbosity in one scenario (base-plus-one-extra); the benefit
   is architectural uniformity with the eight peer list sections
   (`Filters`, `Generation`, `Transformations`, `Augmentations`,
   `Featurizations`, `OutputExpectations`, `Visualizations`,
   `InputContracts`) and a simple clear idiom that mirrors the
   already-in-use `Augmentations: []`. Revisit only if real-world
   recipe corpora make the duplication friction load-bearing; a
   non-breaking opt-in merge mode (e.g. `Sinks_extend: [...]`) is the
   expansion path.
3. **Sink output under partial / `stop_after` runs.** When materialize
   is invoked with `stop_after=<stage>`, do sinks targeting later
   stages silently skip, or do they fail? **Resolved (confirmed for
   v1+, announced-skip variant).** Sinks targeting stages later than
   the `--stage` stop point are *announced-skipped*: their host
   stage doesn't execute, the sink doesn't fire, and the partial
   manifest records the skip under a new
   `manifest.sinks_skipped: dict[str, str]` field (sink name →
   declared stage). Sinks at stages at or before the stop point fire
   normally and appear in `manifest.sinks` as in a full run, with
   the partial-manifest path now threading the in-progress
   `sink_results` through `_partial_finish` so the inspection story
   is complete. The `--stage` flag remains a debugging surface
   (`is_partial=True` flags the instance as non-authoritative
   regardless); failing the run for a sink-vs-stop-point mismatch
   would be surprise, not safety. The skip is transparent: the user
   sees in the partial summary that more sinks would run without
   `--stage`, without it being framed as an error.

---

## 11. References

- [`dependency-gaps-v0.16.0.md`](dependency-gaps-v0.16.0.md) — G18 (Generation
  extends not replaces); G19 (`resolve_sibling_stats` doesn't strip
  variants).
- [`../phase-b-task2-data-preparation-plan.md`](../phase-b-task2-data-preparation-plan.md)
  § 7 — initial sketch (this doc supersedes it).
- `pipeline/runner.py:96` — `STAGE_NAMES` (the canonical stage
  vocabulary this spec extends).
- `pipeline/stages/generation.py` — current `apply_generation`
  implementation (the source of the extend-not-replace semantics this
  spec interacts with).

---

## Upstream filing convention

When filing this as an upstream issue against the DataRefinery repo:

```
[feature spec] intermediate-artifact persistence (Sinks)
```

Body should link this doc by stable URL and cite § 1 (problem
statement) + § 6 (worked example) as the load-bearing sections.
