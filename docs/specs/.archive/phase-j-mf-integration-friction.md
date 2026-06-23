# Phase J — ModelFoundry integration spike friction list

> **Status:** spike deliverable for Story J.d (Phase J), authored
> 2026-06-12 against DataRefinery v0.20.0 (in-progress; v0.19.0 + the
> v0.20.0 work on `main`). Throwaway artifact — each item below is a
> candidate for a separate Phase J follow-up story (or a contract-doc
> clarification absorbed into the next
> [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md)
> ratification pass), to be triaged by the developer at the J.d
> approval gate.

## Spike setup

- **Scratch dir:** `/tmp/dr-mf-spike/` (synthetic 3-class × 8-image
  ImageFolder; two recipes: an aggressive-augmentation recipe
  exercising sidecar PNG resolution, and a normalize recipe exercising
  fitted-statistics persistence; isolated `.cache/` per recipe).
- **MF harness:** `/tmp/dr-mf-spike/mf_harness.py` — pure stdlib +
  `numpy` + `Pillow` + `pyarrow`, **no `from datarefinery import`**.
  Mimics a clean cross-repo consumer reading the on-disk artifacts.
- **Coverage:** every documented bind surface in
  [`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md):
  manifest fields, recipe-side contract (schema_v2 names), JSONL
  records (lazy + aggressive), sidecar PNG resolution, fitted
  statistics (normalize), report.md augmentation rendering,
  drift.json, cache-identity path shape.

## What worked end-to-end (positive confirmations)

Recording these so the next contract-doc ratification round can move
them from "documented" to "verified by Story J.d spike":

- **Manifest field set is exact.** Every one of the 18 fields the spec
  enumerates is present on a fresh v0.20.0 manifest; zero extras
  beyond the spec.
- **Recipe canonical-hash round-trips consumer-side.** A consumer
  using only stdlib (`json.dumps(sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)` + `hashlib.sha256`) reproduces
  `manifest.recipe_hash` exactly from the persisted `recipe.json`. The
  algorithm documented in
  [`project-essentials.md` § "Cache identity is the reproducibility
  contract"](project-essentials.md) is consumer-implementable without
  importing DataRefinery — the "stale fitted statistics" failure-mode
  check in the MF spec works as advertised.
- **Schema-v1 → v2 loader migration is transparent.** Recipe authored
  with `schema_version: 1`; persisted `recipe.json` reflects
  `schema_version: 2` and v2 field names (FilterOp flat shape,
  GenerationOp explicit `op:` + `splits:`, predicate-sentence
  assertion `kind`). MF consumers binding against v2 names see only
  the migrated shape.
- **Aggressive-mode JSONL contract holds.** Variant records carry
  `source_record_id`, `variant_index`, `image_path`, and the per-record
  seed stamp (`<aug-name>_seed: int`). `image_path` resolves to the
  sidecar PNG; PNG decode yields uint8 `(H, W, 3)` per the spec.
- **report.md augmentation rendering matches the spec verbatim**:
  `hflip (\`horizontal_flip\`, materialization=aggressive, expansion=2)`.
- **drift.json has documented fields** (`plugin`, `schema_version`,
  `splits`, `feature_summary`, `notes`) and `drift.json.recipe_hash`
  could be added (it's not present today — see F8 below) to make the
  MF "stale fitted statistics" check load-bearing without cross-
  reading manifest.json.
- **`normalize` fitted-statistics shape matches the spec exactly.**
  `mean.parquet` and `std.parquet` each have a single `value` column
  with C rows (3 for RGB); MF can read them with `pyarrow.parquet`
  and not import DataRefinery.
- **Cache-identity path shape**: instance directory is
  `<recipe-hash16>/<input-hash16>/<seed>/`; each 16-char shard matches
  the first 16 chars of the corresponding 64-hex digest in the
  manifest.
- **`manifest.label_classes` correctly absent** (forward-declared for
  Story J.f, target v0.20.0). The MF spec's forward-declaration is
  honest about the current state.
- **`manifest.sample` correctly `None`** when the recipe declares no
  `SampleData:` section. The forward-declaration in the MF spec for
  Story J.a is now satisfied by the J.a runtime that shipped earlier
  in Phase J.

### Schema-v1 ↔ schema-v2 input transparency (Story J.e verification, 2026-06-12)

Story J.e (FR-J-5) re-ran the harness against both a v1-authored and
a v2-authored fixture recipe exercising the assertion-naming reshape
(`kind: dtype` vs `kind: dtype_equals`):

- `datarefinery.recipe.loader.SUPPORTED_SCHEMA_VERSIONS` is
  `frozenset({1, 2})`; `LATEST_SCHEMA_VERSION` is `2`.
- v1-authored and v2-authored recipes produce **byte-identical
  persisted `recipe.json`** (same SHA-256, same `manifest.recipe_hash`
  full 64-hex digest).
- The migration's assertion-naming reshape renames the dispatch key
  (`kind: dtype` → `kind: dtype_equals`) and leaves assertion parameters
  unchanged — `expected:` is the parameter on both sides, per
  [`recipe.migrations.assertion_naming_v1_to_v2`](../../src/datarefinery/recipe/migrations.py)
  docstring.
- F5 (the `schema_version` field-name overload from this friction list)
  empirically confirmed on the same fresh instance:
  `manifest.schema_version=1` (manifest format counter) and
  `recipe.schema_version=2` (recipe schema counter) coexist; Story J.k
  pins this disambiguation in the MF spec.
- NbF-side coverage is satisfied by the same loader-level
  confirmation — the v1→v2 migration runs inside
  `DataRefinery.from_recipe` upstream of caller shape, so a Marimo
  cell sees the same migrated bytes the MF harness does. No NbF-
  specific code path can break v1/v2 transparency.

**Net:** MF consumers binding against v2 names exclusively are safe;
no v1-handling shim required on the consumer side. The loader is the
single migration point.

## Categorization

Each finding is tagged with one or more of:

- **CONTRACT** — the cross-repo contract doc should pin or clarify a
  behavior; no DR code change required.
- **CODE** — a DR-side code change is the right fix.
- **VALIDATOR** — a new FR-2 check would refuse the broken combination
  at validate time (preventing the runtime crash).
- **DOC** — recipe-authoring / README clarification is the right fix.

---

## Findings

### F1. ImageFolder + aggressive Augmentations crashes at sidecar PNG write. **CODE | VALIDATOR**

**High severity.** End-to-end materialization of a recipe declaring
`Input.type: image_folder` + `Augmentations: [{materialization:
aggressive, ...}]` fails with `FileNotFoundError` at the dataset-write
stage. Reproducer (`pyve env run python -m datarefinery materialize
.../recipe.yaml`):

```
FileNotFoundError: [Errno 2] No such file or directory:
'.../dataset/train/images/train/bird/img_00.png__v000.png'
```

**Cause.** The `image_classification` ImageFolder loader stamps
`record_id` as `"<source-name>/<class>/<filename>"` (with forward
slashes). The runner's
[`_prepare_record_for_persistence`](../../src/datarefinery/pipeline/runner.py)
computes the sidecar PNG path as `sidecar_dir / f"{record_id}.png"`,
which produces a nested-directory path
(`.../images/train/bird/img_00.png__v000.png`) without
`mkdir(parents=True)` on the intermediate `train/bird/` directories.
`PIL.Image.save` then fails to open the file for writing.

**Why no existing test caught it.** The Story H.r.2 integration tests
([`test_runner.py:519`](../../tests/integration/test_runner.py#L519))
use the library API with manually constructed flat record_ids
(`rec_0001`), which sidesteps both the slashes and the nested-dir
problem. The disk-loader path has never been exercised end-to-end with
aggressive variants in the test suite.

**Recommendation.** Two paths, not mutually exclusive:
1. (preferred) Sanitize the per-variant sidecar filename — replace `/`
   (and other path separators) with a safe character, or `mkdir(parents=True,
   exist_ok=True)` on `sidecar_path.parent` before `Image.save`. Update
   the JSONL `image_path` field to use the same sanitized form so
   consumers resolve correctly. This is a local fix in the runner's
   `_prepare_record_for_persistence`.
2. (validator) Add an FR-2 check that refuses an `image_folder` input
   declaration combined with any aggressive `AugmentationOp` until the
   sanitization lands. Cheap insurance; sheds the crash now.

**MF-spec implication.** The current MF spec § "Sidecar PNG encoding"
implies sidecar PNGs are byte-stable across runs. That guarantee
*holds when the run completes*, but today the run cannot complete for
the most common DR use case (ImageFolder). Once the fix lands, the
spec's "byte-identical sidecar files" claim is honest end-to-end.

### F2. Normalize + aggressive Augmentations crashes in the realizer. **CODE | VALIDATOR**

**High severity.** A recipe declaring `Transformations: [{op:
normalize, ...}]` alongside `Augmentations: [{materialization:
aggressive, ...}]` crashes mid-pipeline with:

```
TypeError: Cannot handle this data type: (1, 1, 3), <f8
  in PIL.Image.fromarray  (called from realize_horizontal_flip)
```

**Cause.** Runner stage order is
`InputContracts → Filters/pre_split → Splits → Filters/post_split → Generation
→ Transformations → Featurizations → Augmentations → OutputExpectations →
Visualizations`
([`runner.py:STAGE_NAMES`](../../src/datarefinery/pipeline/runner.py)).
By the time aggressive Augmentations realizers run, train-split images
have been normalized to `float64` z-scores. The
[`horizontal_flip` realizer](../../src/datarefinery/plugins/image_classification/augmentations/horizontal_flip.py)
calls `PIL.Image.fromarray(img_arr)` which only accepts `uint8` for the
`(H, W, 3)` shape — float images fail hard.

**Cross-cutting:** likely affects every pixel-altering aggressive
augmentation (`horizontal_flip`, `random_crop`, `color_jitter`,
`random_erasing`) any time it's chained after `normalize` or
`mean_subtract`. This isn't realizer-specific; it's a stage-order
contract gap.

**Recommendation.** Three paths, increasingly invasive:
1. (validator, minimal) Add an FR-2 check that refuses
   `Transformations` pixel-altering ops + any aggressive
   `AugmentationOp` targeting the same split. The same closed set of
   pixel-altering ops Story J.g is already scoping for the lazy-mode
   `path` rewrite applies here. Cheap; sheds the crash; documents the
   author-facing constraint.
2. (realizer) Make each realizer accept float-typed input via cast
   (`(img * 255).clip(0, 255).astype(np.uint8)`). Lossy and changes the
   contract; not recommended.
3. (stage order) Reverse Augmentations and Transformations so realizers
   see uint8 always. This is a *much* bigger change — it inverts the
   "fit on train, apply everywhere" discipline for normalize because
   then fit would run on augmented records. Defer.

(1) is the right pick; Story J.g already touches the pixel-altering
op enumeration so this is a natural fold-in.

**MF-spec implication.** The current MF spec § "Aggressive-mode
variants" doesn't note this restriction. Once the validator check
lands, the spec should call out that aggressive Augmentations are
incompatible with pixel-altering Transformations on the same split,
referencing the validator-check ID.

### F3. Lazy-mode `path` field is host-bound; spec hints at this only via Story J.g forward-decl. **CONTRACT**

Lazy-mode JSONL records (val/test, and lazy train records) carry
`path` pointing at the **source image filesystem path** (the path the
loader saw, e.g. `/inputs/img_02.png`). The MF spec § "Source-
resolution path" documents this as authoritative for lazy records.

**Friction.** A cross-machine MF consumer reading a DR instance that
was materialized on a different host has no guarantee the source
filesystem path resolves. Today the only path that gives the consumer
host-portable bytes is the **aggressive** path (sidecar PNG via
`image_path`) or **Sinks** (via the path-rewrite forward-declared in
Story J.g). The lazy-mode case is host-bound and silently so.

The MF spec § "Consumer-applied transformations vs. baked
transformations" § "Unresolved boundary — lazy-mode geometry /
pixel-altering Transformations" anticipates Story J.g's `path` rewrite
for the pixel-altering case. The host-portability case is adjacent but
distinct — even with a `normalize`-only recipe (not pixel-altering),
`path` is host-bound.

**Recommendation.** **CONTRACT** — extend the MF spec § "Source-
resolution path" with an explicit "Host portability" subsection: the
`path` field is host-bound; consumers operating across hosts SHOULD
either (a) require a Sink writing per-record images so `path` is
rewritten under the instance directory, or (b) ship the source
ImageFolder alongside the instance. The Story J.g `path`-rewrite
mechanism is the long-term fix for the pixel-altering subset; the
host-portability framing is broader.

### F4. Disk-loader path and library-records path have asymmetric Featurization collision behavior. **CONTRACT | DOC**

When `Input.type: image_folder` + `Labels.source.kind: derived` + a
`Featurizations` op like `derive_label` with `output_field: label`:

- **Disk path:** the loader pre-stamps `label`, then
  `Featurizations.derive_label` re-derives — both code paths produce
  the same value, so the
  [check 23 collision guard](../../src/datarefinery/recipe/validator.py)
  intentionally exempts loader-stamped fields, and the run succeeds.
- **Library path (manually constructed records):** if those records
  arrive with `label` pre-stamped (typical pattern), the runtime
  collision check in
  [`featurizations.py`](../../src/datarefinery/pipeline/stages/featurizations.py)
  refuses with `MaterializeError: Featurizations['derive_label'].output_field
  'label' collides with an existing field in split 'train'`. The
  validator can't predict this asymmetry because manually constructed
  records are by definition outside its scope.

**Cross-repo implication.** MF *itself* doesn't construct records, so
the runtime asymmetry doesn't affect it directly. But MF consumers
who build harnesses (or who run DR via the library API inside their
own test rigs — the same pattern this spike used) will hit it. The
fix is editorial.

**Recommendation.** **CONTRACT** — add a short subsection under the
NbF spec § "Library entry points" (which already documents the
library-records path) flagging this asymmetry. Or **DOC** in
[`recipe-authoring.md`](../guides/recipe-authoring.md) § Featurizations
naming the constraint explicitly: "manually constructed records
arriving with `<Featurization.output_field>` already populated will
fail the runtime collision check; rely on the loader to stamp the
field, or remove the Featurization op."

### F5. `schema_version` field name is overloaded — manifest's is the *manifest* schema; recipe.json's is the *recipe* schema. **CONTRACT**

Both `manifest.json` and `recipe.json` have a top-level
`"schema_version"` key. They mean different things and version
independently:

- `manifest.schema_version` — the manifest format version (currently
  `1`; see `pipeline.manifest.MANIFEST_SCHEMA_VERSION`).
- `recipe.schema_version` — the recipe schema version (currently `2`
  post-loader-migration; see
  `recipe.loader.SUPPORTED_SCHEMA_VERSIONS`).

The MF spec § "Manifest fields ModelFoundry binds against" documents
`manifest.schema_version` as "separate from recipe `schema_version`",
but the field-name overlap is easy for a consumer to miss. A consumer
binding against the wrong one (e.g. reading `manifest.schema_version`
and treating its value as the recipe-schema bound) silently misroutes
schema-version coordination logic.

**Recommendation.** **CONTRACT** — the MF spec § "Schema-version
coordination policy" should call out explicitly that
**`manifest.schema_version` and `recipe.schema_version` are independent
counters** with different rules. Optionally also rename one of them
internally (e.g. `manifest_format_version`) in a future schema bump to
remove the ambiguity, but the cheap fix is editorial.

### F6. `recipe.json` contains every section key even when the author declared none. **CONTRACT**

A recipe author who declared only `Input`, `Output`, `Labels`,
`Splits`, `Augmentations`, and `Visualizations` ends up with a
persisted `recipe.json` whose top-level keys include `Filters`,
`Generation`, `Featurizations`, `Transformations`, `InputContracts`,
`OutputExpectations`, `SampleData`, `Sinks`, and `variants` — all
defaulted to `[]` or `null`. The MF spec § "Recipe-side contract"
doesn't enumerate these as guaranteed-present; an MF consumer
iterating `recipe.keys()` and assuming "only what the author declared
appears" gets surprised.

This is the documented consequence of "every pydantic field default
participates in canonical bytes" (which is *why* canonical hashing
works), but the consumer-facing surface for that consequence isn't
explicitly pinned in the contract.

**Recommendation.** **CONTRACT** — one paragraph in the MF spec §
"Recipe-side contract" pinning the rule: "All top-level recipe
sections are present in `recipe.json` whether or not the author
declared them; absent / empty sections appear as the section type's
default (`[]` for list sections, `null` for optional object sections,
empty list / `{}` where applicable). Consumers SHOULD treat empty /
null sections as 'not declared'."

### F7. `drift.json` does not carry `recipe_hash`; MF stale-instance check has to cross-read manifest. **CONTRACT | CODE (small)**

The MF spec § "Failure modes ModelFoundry SHOULD detect" lists "Stale
fitted statistics" as:

> `manifest.recipe_hash` does not match the on-disk recipe's canonical
> hash → the instance was rendered against an older recipe shape; do
> not train on it. (`drift.json`'s `recipe_hash` field aligns with
> `manifest.recipe_hash`; mismatch is ipso facto a stale instance.)

But on a fresh v0.20.0 instance, `drift.json` does **not** contain a
`recipe_hash` key. Its top-level keys are `feature_summary`, `notes`,
`plugin`, `schema_version`, `splits`. So the spec's parenthetical
about `drift.json.recipe_hash` doesn't describe current behavior;
either the field should be added, or the parenthetical should be
removed.

**Recommendation.** Two paths:
1. (CODE, preferred) Add `recipe_hash` to `drift.json` at the runner's
   `compute_drift_placeholder` call site
   ([`runner.py:524`](../../src/datarefinery/pipeline/runner.py#L524)).
   One line; trivial; aligns spec with code; gives MF the redundant
   cross-check it expects without forcing cross-read of
   manifest.json.
2. (CONTRACT) Remove the parenthetical from the spec. Honest but
   strictly less useful.

(1) is the right pick; this is a documented contract that doesn't
currently exist in code.

### F8. `Pillow` dependency is implicit; MF consumer needs to know it. **DOC**

A pure-stdlib MF harness can read `manifest.json`, `recipe.json`,
`<split>.jsonl`, and `drift.json` without importing anything. But
reading aggressive sidecar PNGs (and most fitted_statistics workflows
in practice) requires `Pillow` and `pyarrow`. The MF spec doesn't
enumerate these consumer-side dependencies explicitly.

**Recommendation.** **DOC** — one sentence in the MF spec § "Overview"
naming the consumer-side runtime deps: `numpy`, `Pillow` (PNG decode
for aggressive variants and any image-bytes reads), `pyarrow`
(parquet decode for fitted statistics). All three are common; just
worth pinning so a freshly-installed MF consumer knows what to install.

## Triage suggestion at the J.d approval gate

| Item | Severity | Path |
| --- | --- | --- |
| F1 sidecar PNG path crashes on ImageFolder | **High** | New code story (and/or validator check); blocks production aggressive-augment use |
| F2 normalize + aggressive crashes | **High** | Fold into Story J.g's pixel-altering-op validator-check work, OR new dedicated check |
| F7 drift.json missing `recipe_hash` | Medium | One-line code change; align spec promise with reality |
| F3 lazy-mode `path` host-portability | Medium | Contract-doc clarification; subsumed by J.g eventually |
| F5 `schema_version` field overload | Low | Contract-doc clarification |
| F6 every recipe section persists | Low | Contract-doc clarification |
| F4 disk/library Featurization asymmetry | Low | Contract-doc or recipe-authoring clarification |
| F8 implicit consumer-side deps | Low | One-sentence spec note |

The two **High** items (F1, F2) are real crash-on-realistic-recipe
bugs that escaped the test suite because both code paths used in
existing integration tests sidestep them (manual flat record_ids for
F1; no Transformations + Aggressive combos for F2). They should
become Phase J stories before any future MF integration story leans
on the MF spec's current aggressive-augment claims.

F7 is small but high-leverage: aligning the spec promise with code
gives MF a "single field to check" stale-instance detector.

F3–F6 + F8 are contract-doc-only and fold cleanly into the next
[`modelfoundry/vendor-dependency-spec.md`](modelfoundry/vendor-dependency-spec.md)
ratification pass.
