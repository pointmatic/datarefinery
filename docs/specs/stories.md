# stories.md -- datarefinery (python)

This document breaks the `datarefinery` project into an ordered sequence of small, independently completable stories grouped into phases. Each story has a checklist of concrete tasks. Stories are organized by phase and reference modules defined in `tech-spec.md`.

Put **`vX.Y.Z` in the story title only when that story ships the package version bump** for that release. Doc-only or polish stories **omit the version from the title** (they share the release with the preceding code story, or use your project’s doc-release policy). **One semver bump per owning story** — extra tasks on the *same* story share that bump; see `project-essentials.md`. Semantic versioning applies to the package. Stories are marked with `[Planned]` initially and changed to `[Done]` when completed.

For a high-level concept (why), see [`concept.md`](concept.md). For requirements and behavior (what), see [`features.md`](features.md). For implementation details (how), see [`tech-spec.md`](tech-spec.md). For project-specific must-know facts, see [`project-essentials.md`](project-essentials.md) (`plan_phase` appends new facts per phase). For the workflow steps tailored to the current mode (cycle steps, approval gates, conventions), see [`docs/project-guide/go.md`](../project-guide/go.md) — re-read it whenever the mode changes or after context compaction.

---

## Version Cadence

Standard semantic versioning, with these conventions:

- **Every story belongs to a phase.** Bugfix stories included. No orphan stories.
- **Per-story bumping** (when a story owns its own release):
  - Bugfix or trivial change → **patch** (`vX.Y.Z+1`)
  - Feature or improvement → **minor** (`vX.Y+1.0`)
  - Breaking change → **major** (`vX+1.0.0`). Post-1.0 only, and only via the `plan_production_phase` mode, which negotiates with the developer about whether the breakage is substantively user-facing or technically-but-trivially breaking (example: a log-format change is technically breaking, but if logs aren't a core consumer capability, the developer may judge it minor or even patch).
- **Phase-bundling option:** a phase can run unversioned during work and ship a single release/tag at end-of-phase. Stories within the phase carry no version in their title; the phase's last story owns the bump (magnitude determined by the highest-impact change in the bundle).
- **No out-of-order implementation.** Story order in this file is the order of execution. If work order needs to change, **reorganize/renumber here first** — don't skip ahead and create version-number gaps.
- **Pre-1.0:** standard semver applies; version starts at `v0.1.0` (Story A.a).
- **Post-1.0:** every phase must go through `plan_production_phase` (the lighter `plan_phase` is pre-1.0 only). Major bumps only happen through that mode's negotiation step.

This is the authoritative cadence rule. **Do not extrapolate the bump magnitude from `pyproject.toml`'s current version** — re-read this section whenever you're about to assign a version to a story.

---

## Phase H: Feature Refinements and Fixes

Refinements to the v1 feature surface, post-release fixes, and image-classification capability extensions that build on v1's input/featurization/filter/generation primitives. Each story is scoped to one user-visible capability or one focused fix so versions can ship independently.

### Story H.a: v0.7.0 InputSource sidecar labels + flat-image layout for image_classification [Done]

Finish the design that `InputSource.label_from` started in [`src/datarefinery/recipe/models.py:35`](../../src/datarefinery/recipe/models.py): a reserved field declared at the input-source level but never consumed anywhere in `src/`. Wire it up in the image-classification plugin's input loader so a recipe author can point an input source at a sidecar manifest of labels and have records arrive at the pipeline *already labeled*. No featurization detour.

Real-world sidecar-CSV datasets are typically flat — `images/img_*.jpg` plus a separate `labels.csv` — not ImageFolder-style (one class per subdirectory). To answer the original use case truthfully, this story also adds a second source type, `image_flat`, that requires `label_from`. The existing `image_folder` type stays as-is and keeps its class-subdir labels (no `label_from` allowed). Two source types, each with one labeling mechanism — no overlay/override semantics, no heuristic layout detection.

**Why input-side, not featurization-side.** Labels in a sidecar manifest are *provided*, not *computed* — joining against an external file is a load-time concern, not a "compute fields from other fields" concern. Solving it in `Featurizations` means records flow through `InputContracts`, `Filters/pre_split`, and `Splits` without labels, which silently misbehaves: `filter_by_label`, stratified splits, and the v1 `sample_data_strict_subset` validator check (16) all assume labels are present from the start. Solving it at load time means `LabelsSection.source.kind` can stay `"direct"` and downstream stages see labeled records uniformly.

**Promote `label_from` from a path to a structured spec.**

The field exists as `Path | None` today but is unused in `src/` — no recipe authors to break. Replace it with a small Pydantic model that covers the three real-world manifest shapes:

```python
class LabelFromSpec(_Frozen):
    path: Path                                  # resolved relative to the recipe file
    join: Literal["by_id", "by_row_order"]
    header: list[str] | None = None             # column names when the file has no header row
    id_field: str | None = None                 # required iff join == "by_id"
    label_field: str                            # CSV column name to emit as the label
```

**Three example recipe shapes:**

```yaml
# Mode 1: headered CSV (most common third-party shape)
Input:
  sources:
    - name: images
      type: image_folder
      path: ./data/images
      label_from:
        path: ./data/labels.csv
        join: by_id
        id_field: filename
        label_field: class

# Mode 2: headerless CSV — recipe declares the column names
label_from:
  path: ./labels.txt
  join: by_id
  header: [filename, class]
  id_field: filename
  label_field: class

# Mode 3: CIFAR-style — headerless single column, parallel to input listing
label_from:
  path: ./labels.txt
  join: by_row_order
  header: [class]
  label_field: class

Labels:
  field: label                                  # record-field name the loader writes into
  source: { kind: direct }                      # truthful: labels arrive intrinsically
```

**Header semantics — recipe-as-truth, no heuristics.**

- `header` **omitted** → CSV has a header row; loader reads column names from row 0. `id_field` (when `join == "by_id"`) and `label_field` must appear in that header.
- `header` **provided** → file is treated as **headerless**; the recipe-supplied names *are* the column names. If the file actually contains a header line, the loader reads it as a data row — by design. Ingestion definition is a brief, one-time configuration step; we trust the recipe author rather than add heuristic foot-gun-detection that would explode into complexity. (Aligns with the project-essentials "Recipe is authoritative for data-pipeline semantics" rule.)

**Cache-identity note.** Labels feed into record bytes, which already feed the input-hash side of the cache key. Adding sidecar-manifest joining changes the *bytes* the cache stores, not the canonical-form algorithm. Pre-production rules apply (per `project-essentials.md` § "Cache identity"): users re-materialize after upgrade, no migration ceremony required.

**Tasks:**

- [x] **Pydantic model.** Replace `InputSource.label_from: str | None` with `LabelFromSpec | None`. Add the new model in `src/datarefinery/recipe/models.py` with field-level validators: `id_field` required iff `join == "by_id"`; `label_field` always required; `header` (when present) is a non-empty list of strings with unique entries.
- [x] **Add `image_flat` source type.** New supported `InputSource.type` value: a directory of image files, no class subdirectories. Loader walks `*.png/*.jpg/*.jpeg` files (recursive, sorted), generates `record_id = f"{source_name}/{relative_path}"`, joins labels from `label_from`.
- [x] **Source-type vs `label_from` consistency.**
  - `image_folder` + `label_from` set → reject (one source of truth; subdirs already provide labels).
  - `image_flat` + `label_from` unset → reject (no other label source for flat).
  - Enforced at validate time via check 19 and re-checked defensively at load time.
- [x] **Loader wiring.** In `src/datarefinery/pipeline/inputs.py`: factor `_load_image_classification` to dispatch by `src.type`. Add `_load_one_image_flat` and `_hash_image_flat` (hash includes the manifest file's bytes alongside the image files so manifest edits invalidate the cache). For `image_flat`, open the manifest via the stdlib `csv` module (sufficient and stdlib-only; the project also depends on `pyarrow` but it adds no value here), respect the header/join rules, build an in-memory `id → label` dict (for `by_id`) or `label[]` list (for `by_row_order`), and inject the label into each record at load time.
- [x] **Join behavior.**
  - `by_id`: image with **no matching id** in the manifest → `MaterializeError`. Manifest row with **no matching image** → silent (extras are common when manifests are reused across subsets). **Duplicate id** in manifest → `MaterializeError` at load time (deterministic; no last-write-wins). Default join key (the id used to look up in the manifest): the image's **filename stem** (e.g., `img_001.jpg` → `img_001`).
  - `by_row_order`: row count of the manifest must equal the input source's enumerated record count after sorted-paths enumeration; mismatch → `MaterializeError` naming both counts. (Document that `by_row_order` is brittle by nature; recommend `by_id` for new datasets.)
- [x] **Path resolution.** Implementation note: paths are interpreted as written, matching the pre-existing convention for `Input.sources[*].path` (the recipe loader does not plumb a recipe-base directory through to the input loader). Users supply absolute paths or run from the recipe directory. The original strawman said "relative to the recipe file"; that would require new plumbing (no recipe-path on `DataRefinery`) and is out of scope for this story.
- [x] **Validator check 19 — `label_from_spec_resolves`.** Cover:
  - Source-type consistency: `image_folder` + `label_from` set → fail; `image_flat` + `label_from` unset → fail.
  - When `label_from` is set: file at `label_from.path` exists and is readable.
  - When `header` omitted: file is non-empty; `id_field` (if `join == "by_id"`) and `label_field` appear as column names in the file's header row.
  - When `header` provided: count of names in `header` equals the file's actual column count; `id_field` (if `join == "by_id"`) and `label_field` reference entries in `header`.
  - When `join == "by_id"`: no duplicate values in the id column.
  - When `join == "by_row_order"`: manifest row count equals the input source's enumerated record count.
  - Wired into [`src/datarefinery/recipe/validator.py`](../../src/datarefinery/recipe/validator.py) and into the registry tuple at the bottom of that file.
- [x] **Recipe-authoring guide.** Updated `docs/guides/recipe-authoring.md` § Input and § Labels per the spec.
- [x] **README quickstart variant.** Added "Alternative layout: flat directory + sidecar labels" subsection.
- [x] **Tests.**
  - Pydantic-model unit tests: 8 cases covering field-level constraints and cross-field invariants.
  - Loader unit tests in [`tests/unit/test_inputs.py`](../../tests/unit/test_inputs.py) — 11 cases across the three modes and the consistency rules.
  - Validator: 8 new check-19 tests in `tests/unit/test_validator.py` plus updates to existing counts (18 → 19 across `test_validator.py`, `test_tabular_stub_smoke.py`, and the validate-CLI smoke check).
  - Integration: 2 cases in `tests/integration/test_image_flat_label_from.py` (end-to-end materialize + validator rejection of the inconsistent combo).
- [x] Bump version to v0.7.0
- [x] Update CHANGELOG.md
- [x] Verify: a recipe with `type: image_flat` and `label_from: {…}` materializes end-to-end on a CIFAR-shaped fixture in each of the three modes; `datarefinery validate` reports the new check 19 as `pass`; the materialized records carry `label` from the manifest with the expected label distribution.

**Out of Scope**

- Scaffolder (`datarefinery init`) emitting `image_flat` recipes. v1 scaffolder is ImageFolder-only by design (per `concept.md`); users of `image_flat` + `label_from` hand-author the recipe. A follow-up story can extend the scaffolder.
- `label_from` for the tabular and text plugin stubs — those plugins still ship as stubs in v1 (see `Future` section); when they are implemented, they re-use the same loader-level mechanism.
- Non-CSV sidecar formats (JSONL, Parquet, YAML). CSV is the lingua franca for label manifests; richer formats can land in a follow-up story if a user surfaces a real need.
- Multi-label manifests (record carries multiple label fields). v1 image_classification is single-label by design; the `LabelFromSpec.label_field: str` shape extends to a plural form later without breaking single-label users.
- Computed-from-id labels (e.g., a Python expression on the id). That is `Featurizations` territory, not `label_from` territory.
- Header-coexistence heuristics: if `header` is provided AND the file also contains a header line, the loader reads the header line as a data row. By design (recipe-as-truth); no heuristic detection in v1.
- A `label_from_missing: warn|error` knob for `by_id`. v1 errors deterministically on missing-image-row. Add the knob in a follow-up only if a real workflow surfaces the need.
- Heuristic layout detection (auto-select between `image_folder` and `image_flat` based on directory contents). Recipe declares the layout explicitly via `type:`.

### Story H.b: v0.8.0 InputSource partitions — honor pre-existing train/test directories [Done]

Most real-world datasets ship pre-partitioned: a `train/` directory authored by the dataset publisher plus a `test/` directory intended to remain heldout. Today, DataRefinery pools all `Input.sources` into a single record list at load time (`_load_image_classification` concatenates per-source records before any pipeline stage runs); `source.name` survives only as a prefix in `record_id`, not as a record field. That means `Splits.key_assignment` — the existing mechanism for pre-partition-aware splitting — has nothing to key on without a Featurization hack to parse `record_id`.

This story makes pre-partitioned datasets a first-class shape by adding a `partition: str | None` field to `InputSource`. Each source declares which split it belongs to; the loader honors the declaration; the Splits stage either accepts the declared partitioning verbatim or sub-partitions one declared partition (typically `train` → `train`/`val`) while leaving the rest heldout.

**Target recipe shapes:**

```yaml
# Form A — pure honor: declared partitions are final; Splits is omitted.
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
  # omit entirely, OR…
  ratios: {}                            # explicit empty: "honor source partitions"

# Form B — sub-partition: carve val out of train, keep test heldout untouched.
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
  applies_to: train                     # only re-partition the named partition
  stratify_by: label
  seed: 7
```

**Backward-compat is clean.** Recipes without any `partition` declaration keep working unchanged: loader pools as today, Splits partitions globally. The new shapes are additive.

**Cache-identity note.** Adding `partition` to record bytes shifts the input hash; adding `applies_to` to `SplitsSection` shifts the canonical recipe bytes. Pre-production rules apply per `project-essentials.md` § "Cache identity": users re-materialize after upgrade, no migration ceremony required. Post-v1, the canonical-hash pin (`test_canonical_hash_pin`) updates with the schema change.

**Tasks:**

- [x] **Pydantic model.** Add `InputSource.partition: str | None = None`. Add `SplitsSection.applies_to: str | None = None`. Validator on `applies_to`: a non-empty string when set; nothing more at the field level (cross-checks live in validator check 20).
- [x] **Loader wiring.** Stamp a plain `partition` key on each loaded record when the source declares one. This matches the existing `record_id` convention — both are loader-stamped, plain-named fields sharing a single record namespace (no leading-underscore/`_partition` convention). Collision avoidance is enforced via validator check 20 (no user-declared `partition` in `Output.record_schema`).
- [x] **Splits-stage dispatch.** New mode in `apply_splits`:
  - Records carry `partition` → group by it.
  - `Splits` omitted or `Splits.applies_to` unset (and `ratios == {}`) → return the groups verbatim.
  - `Splits.applies_to == <name>` → run the existing ratio-based partitioning on just the records in that group; preserve all other groups verbatim.
  - `Splits.applies_to` set but no record carries `partition` → `MaterializeError` (recipe is internally inconsistent — the validator catches this earlier, but defend at load time).
  - No source declares `partition` → existing global-pool behavior (current code path unchanged).
- [x] **Validator check 8 relaxation.** `splits_partition_correctly` no longer rejects empty `Splits` when any source declares `partition`. Source partitions are a valid partitioning surface.
- [x] **Validator check 20 — `partitions_consistent`.** Cover:
  - All-or-nothing: if any source declares `partition`, every source must declare one.
  - `Output.record_schema` must not declare a `partition` field — reserved for the loader-stamped value.
  - `Splits.applies_to` (when set) must reference a partition declared by some source.
  - `Splits.ratios` keys (when set with `applies_to`) must not collide with sibling partition names.
  - When source partitions are declared but `Splits.applies_to` is unset, `Splits.ratios` must be empty.
  - Plugin-specific: only applies to plugins whose loader stamps `partition` (initially `image_classification`).
- [x] **Stratification interaction.** `Splits.stratify_by` runs inside `_apply_ratios` and therefore stratifies only within the named partition when `applies_to` is set.
- [x] **Record-id prefix unchanged.** `source.name` still encodes into `record_id` as today; the new `partition` field is separate metadata.
- [x] **Recipe-authoring guide.** Added "Pre-partitioned sources" subsection under § Input and "Sub-partitioning via `applies_to`" subsection under § Splits.
- [x] **README quickstart variant.** Added "Pre-partitioned sources (Kaggle-style train/test)" subsection under § Quickstart.
- [x] **Tests.** 4 model + 3 loader + 9 splits-stage + 10 validator + 5 integration = 31 new tests.
- [x] **Canonical-hash pin update.** Recomputed to `a09614a4b59d2fecd20ef19b3e4894e0fdc6313a3818a770f5e96072957b9cc0`. CHANGELOG release notes call out the shift per the pre-prod ceremony.
- [x] Bump version to v0.8.0
- [x] Update CHANGELOG.md
- [x] Verify: end-to-end on a Kaggle-shape fixture, recipe materialises with `test` heldout from `train` in both Form A and Form B; `datarefinery validate` reports `20/20 checks passed`; test split is byte-identical across forms.

**Out of Scope**

- **Unlabeled partitions** (e.g., Kaggle test sets with no labels) — Story H.d addresses this separately. H.b assumes every partition is labeled.
- **Cross-partition shuffling** (e.g., `Splits.ratios` that mixes records from multiple declared partitions back into a single pool). Explicitly rejected — that would re-introduce the very leak `partition` is preventing.
- **Partition-level transformations** (e.g., applying a different normalize to train vs test). The existing per-op `splits: [...]` list already covers this; no new surface needed.
- **Multi-level partitions** (e.g., `partition: train.subset_a`). Single-level only in v1; nest later if a real workload surfaces.
- **Heuristic partition-name → split-name mapping.** Partition names are split names directly; if a source declares `partition: holdout`, the resulting split is named `holdout`. No automatic translation to train/val/test.

**Design decisions resolved during planning** (kept in the story so the rationale stays visible to future readers):

1. **`Splits` omitted entirely is allowed.** When sources declare partitions and `Splits` is omitted (or `Splits.ratios == {}`), the loader honors source partitions verbatim (Form A). No marker required — the partition declaration on the sources is the explicit intent.
2. **Record field is plain `partition`, not `_partition`.** Matches the existing `record_id` precedent (loader-stamped, plain name) instead of introducing a new leading-underscore convention. Collision avoidance is enforced by validator check 20 (no user-declared `partition` in `Output.record_schema`).
3. **`applies_to` is a single string, not a list.** One partition can be sub-partitioned per recipe. Multi-target sub-partitioning would re-introduce cross-partition shuffling ambiguity; defer to a follow-up story if a real workload surfaces.

### Story H.c: v0.8.1 features.md + tech-spec.md alignment with H.a + H.b [Done]

Documentation-only catch-up: `features.md` and `tech-spec.md` describe a pre-H.a/H.b world. The shipped code introduces a structured `LabelFromSpec`, the `image_flat` source type, the `InputSource.partition` field, the `SplitsSection.applies_to` field, validator checks 19 and 20, and a new `pipeline/inputs.py` module — none of which are reflected in the specs. Future LLM sessions that read the specs to understand "what the system does" will produce wrong answers (e.g., "the enumerated checks list has 18 entries") until this is fixed.

This story is a bookkeeping correction. No code changes; tests don't move. The package version bump is a **patch** (v0.8.1) because: the docs go through their own release cycle in this project (per the F.b/F.c precedent of doc-only stories sharing the preceding code release), but H.b has already shipped its v0.8.0, so the cleanest mechanism for "doc fixes after the code is out" is a patch bump. The alternative — leaving the docs unversioned and rolling them into H.d's v0.9.0 — couples a doc fix to a feature ship and delays the correction.

**Tasks:**

- [x] **`features.md` FR-2 — extend the enumerated-checks list.** Add to the numbered list (lines 196–213):
  - **19. `label_from_spec_resolves`** — `InputSource.label_from` is structurally valid; manifest file at `label_from.path` exists; declared header (when present) matches the file's column count; `id_field` / `label_field` reference columns that resolve; no duplicate ids for `by_id`; row count matches enumerated record count for `by_row_order`; source-type consistency (`image_folder` + `label_from` is rejected; `image_flat` without `label_from` is rejected). Plugin-specific: only applies to `image_classification` in v1.
  - **20. `partitions_consistent`** — `InputSource.partition` declarations are all-or-nothing across sources; `partition` is not declared in `Output.record_schema` (reserved name); `Splits.applies_to` (when set) references a declared partition; `Splits.ratios` keys don't collide with sibling partition names when `applies_to` is set; `Splits.ratios` is empty (or unset) when source partitions are declared and `applies_to` is unset.
- [x] **`features.md` FR-7: Splits — document partition-honoring modes.** Add to the Behavior list:
  - **5. When `Input.sources[*].partition` is declared on every source**, the materialized splits honor those declarations (each partition becomes a split). Setting `Splits.applies_to: <partition-name>` with `ratios: {...}` sub-partitions just that partition; sibling partitions are preserved verbatim (so `test` can stay heldout while `train` is carved into train/val).
  
  Update Edge Cases:
  - Some sources declare `partition` and some don't → caught by `validate` (check 20).
  - `Splits.applies_to` set but no source declares `partition` → `MaterializeError` (defensively rechecked at load time even though check 20 catches it earlier).
- [x] **`features.md` Inputs — add a third example for pre-partitioned sources.** After the `image_flat` example, add an `image_folder` × 2 example with `partition: train` and `partition: test` declarations, mirroring the Kaggle-style shape documented in the recipe-authoring guide and README.
- [x] **`features.md` FR-22: Labels — connect the sidecar-manifest direct-label route.** Add a bullet to Behavior:
  - **4. For `image_classification`, the `image_flat` source type accepts a `label_from` spec** (see `Input` examples) that populates labels at load time. From `Labels`'s perspective this is `kind: direct` — the labels arrive intrinsically; no Featurization is involved.
- [x] **`features.md` Inputs prose — tighten the "joined by a declared key" sentence.** Line 78 currently reads: "*Multiple sources may be joined by a declared key (e.g., filename, foreign key column).*" That predates `LabelFromSpec`. Replace with a sentence that's accurate to v1: cross-source joins are out of scope; each source is independent; sidecar-manifest joining for labels is the only join the v1 image plugin supports, via `label_from`.
- [x] **`tech-spec.md` Package Structure — add `pipeline/inputs.py`.** Insert under `pipeline/` with comment: `# disk-backed input loader (FR-3): image_folder + image_flat with label_from join`.
- [x] **`tech-spec.md` Package Structure — bump validator comment.** Change `validator.py # FR-2 enumerated checks 1–18` to `# FR-2 enumerated checks 1–20`.
- [x] **`tech-spec.md` `recipe.validator` (FR-2) section — bump heading prose.** "Each of the 18 enumerated checks from features.md..." → "Each of the 20 enumerated checks from features.md...". Update the function-signature comment accordingly.
- [x] **`tech-spec.md` Data Models — update InputSection / add LabelFromSpec / update SplitsSection.**
  - `InputSection` row: change "(each with `name`, `type`, `path`, type-specific fields like `label_from`)" to "(each with `name`, `type`, `path`, optional `label_from: LabelFromSpec`, optional `partition: str`)".
  - **New `LabelFromSpec` row:** `path: pathlib.Path`, `join: Literal["by_id", "by_row_order"]`, `header: list[str] | None`, `id_field: str | None`, `label_field: str`. With a note that `header` provided means "treat file as headerless; recipe-supplied names are the column names" (recipe-as-truth, no heuristic detection).
  - `SplitsSection` row: append `, applies_to: str | None` and a note that `applies_to` names a single source-declared partition to sub-partition via `ratios`; sibling partitions are preserved verbatim.
- [x] **`tech-spec.md` `scaffolder.init` — note the layout limitation.** Add to the section: "The scaffolder emits `image_folder` recipes only; `image_flat` + `label_from` users hand-author the recipe in v1. Out-of-scope for H.a; a follow-up story can extend the scaffolder if real workloads surface the need."
- [x] **Sweep for stale "18 checks" references.** Grep `docs/specs/` and `docs/guides/` for "18 checks" / "checks 1–18" / similar; update anything stale. (`docs/guides/plugin-authoring.md` already updated by H.a+H.b — confirm.)
- [x] **No `project-essentials.md` update needed.** The shipped behavior is well-described in the H.a + H.b CHANGELOG entries and the recipe-authoring guide; no new project-specific gotcha emerged that would warrant a fact appended there.
- [x] Bump version to v0.8.1
- [x] Update CHANGELOG.md
- [x] Verify: `grep -rn "checks 1.18\|18 enumerated\|FR-2 (1-18)" docs/specs/` returns nothing; `grep -rn "pipeline/inputs.py" docs/specs/` returns the new tech-spec entry; reading `features.md` § FR-2 lists 20 enumerated checks; reading `features.md` § Inputs shows three example shapes (ImageFolder, image_flat+label_from, partitioned train/test); reading `tech-spec.md` Data Models table shows `LabelFromSpec` and `applies_to` and `partition`.

**Out of Scope**

- Concept.md updates. The "why" of DataRefinery hasn't changed; H.a + H.b extend the "what" without shifting the concept.
- Tech-spec coverage of the `partitioned` Splits-stage internals (`_apply_partitioned`, `applies_to` sub-partitioning). The Data Models update covers the recipe-surface change; implementation depth lives in the code itself.
- README / authoring-guide updates. Both were updated alongside H.a and H.b; only `features.md` and `tech-spec.md` are out of date.

### Story H.d: v0.9.0 Unlabeled partition support [Done]

**Depends on H.b.** Adds first-class support for partitions that ship without labels — the Kaggle/inference-set shape where `test/` (or any held-out partition) has no `labels.csv` and exists only for downstream prediction. The pipeline today assumes every record has a label, which makes "ship the unlabeled test partition through the same pipeline as the labeled train partition" unexpressible.

This story adds an `unlabeled: true` flag on `InputSource` and threads it through the stages that touch labels so the unlabeled partition flows through label-independent transformations (resize, normalize, augmentation) and lands in the materialized instance as a usable dataset for downstream inference — while label-dependent stages (stratify_by, `filter_by_label`, drift class-distribution) are skipped for that partition with a clear "skipped: unlabeled" note in the report.

**Target recipe shape:**

```yaml
Input:
  sources:
    - name: train_data
      type: image_folder
      path: ./data/train
      partition: train
    - name: test_data
      type: image_flat                    # flat layout, no label_from
      path: ./data/test
      partition: test
      unlabeled: true                     # NEW
Labels:
  field: label
  source: { kind: direct }                # labels exist for labeled partitions
Splits:
  ratios: { train: 0.85, val: 0.15 }
  applies_to: train
  stratify_by: label                      # stratifies only train (label-dependent)
```

**Cache-identity note.** `unlabeled` participates in canonical recipe bytes — flipping the flag shifts the cache identity. Pre-production rules apply.

**Tasks:**

- [x] **Pydantic model.** `InputSource.unlabeled: bool = False`. Cross-field validators: `unlabeled=true` requires `partition`; `unlabeled=true` forbids `label_from`. The "image_flat only" restriction lives in check 21 (plugin-specific).
- [x] **Loader wiring.** `image_flat` + `unlabeled=true` uses a new `_load_one_image_flat_unlabeled` path: no `label_from` read, records arrive without a `label` field. `image_folder` + `unlabeled=true` rejected at validate time (check 21) and defended at load time.
- [x] **Splits-stage interaction.** Records lacking `label` flow through the existing partition-honoring code unchanged. `stratify_by` + `applies_to=<unlabeled-partition>` rejected via check 21. Sub-partitioning an unlabeled partition produces unlabeled sub-splits (records still lack `label`); check 21 detects this for downstream filter/featurization rules.
- [x] **Drift/reporting interaction.** `SplitDriftRecord.note: str | None` added. `compute_drift_placeholder` accepts an `unlabeled_splits: set[str] | None` kwarg; for matching splits, `class_distribution=None` and `note="skipped: unlabeled"`. `report.md` flags unlabeled splits with `*(unlabeled)*` in the Splits section.
- [x] **Filter interaction.** Check 21 rejects `Filters[*].predicate.op == "filter_by_label"` when `splits` contains an unlabeled split name. Other filters (`random_sample`) are unaffected.
- [x] **Validator check 21 — `unlabeled_consistency`.** Covers: `unlabeled=true` requires `image_flat`; `stratify_by` + unlabeled `applies_to`; `filter_by_label` on unlabeled splits; `label_from_path` (or any featurization whose `inputs` include `Labels.field`) on unlabeled splits. Skips for plugins not in `_PARTITION_PLUGINS`. The model-level validators enforce the `partition` and `label_from` rules.
- [x] **Featurization interaction.** Check 21 rejects featurizations whose `op == "label_from_path"` or whose `inputs` include the recipe's `Labels.field` when targeting an unlabeled split. `image_size_stats` (which doesn't touch the label) is allowed.
- [x] **OutputExpectations skip rule.** `evaluate_output_expectations` accepts `skip_missing_label_field: str | None`; the runner passes `Labels.field` when any source declares `unlabeled=true`. Records lacking the field are skipped for `required_field` assertions; records with `None` still fail.
- [x] **Recipe-authoring guide.** New § "Unlabeled partitions" subsection in `docs/guides/recipe-authoring.md`.
- [x] **README quickstart variant.** New "Unlabeled partitions (Kaggle-style test set with no labels)" subsection.
- [x] **features.md + tech-spec.md updates** (scope expanded by developer per Step 2 announce): FR-2 check 21 added; FR-7 Splits bullet 6; FR-22 Labels bullet 5; new Inputs example; tech-spec validator comment + section + Data Models row updated.
- [x] **Tests.** 4 model + 2 loader + 8 validator (check 21) + 2 drift + 5 integration = 21 new tests, plus updates to existing counts (20 → 21 across `test_validator.py`, `test_validate_cmd.py`, `test_tabular_stub_smoke.py`, `test_partitioned_inputs.py`, `test_image_flat_label_from.py`).
- [x] **Canonical-hash pin update.** Recomputed to `11a6ca0fd15e2995092fe6755ff188c05e9e814344209a9b6926a420fd487731`. CHANGELOG release notes call out the shift per the pre-prod ceremony.
- [x] Bump version to v0.9.0
- [x] Update CHANGELOG.md
- [x] Verify: 719 unit + integration tests pass; ruff clean; mypy --strict clean across 71 source files; integration test materializes a Kaggle-shape fixture and asserts unlabeled test records lack `label`, drift records `null + note`, report flags split with `*(unlabeled)*`.

**Out of Scope**

- **Per-record label-absence** (some records labeled, others not, within the same partition). v1 unlabeled-ness is partition-scoped, not record-scoped. Mixed-labeling within a partition is a different problem — likely belongs to the Featurizations layer or a separate "partial-labels" story post-v1.
- **Auto-inference at materialize time.** Materialize produces datasets; running inference against them is a downstream concern (out of v1 scope per `concept.md` non-goals). The unlabeled partition's job is to *exist* in the materialized instance for downstream tooling to consume.
- **Pseudo-labeling** (deriving labels for unlabeled records via a trained model). That's a model-development workflow, not a data-prep workflow.

**Open questions to resolve before implementation:**

1. **`image_folder` + `unlabeled: true` — allow flat directory or restrict to `image_flat`?** Strawman: restrict to `image_flat` for clarity (one shape per use case). Users with an existing flat-directory ImageFolder layout (no class subdirs) just declare `image_flat`.
2. **Should `Labels.source.kind` change for unlabeled-only recipes?** A recipe whose only partition is unlabeled has no labels anywhere. Strawman: still require `Labels` to be declared (for downstream schema consistency) but treat `kind: direct` as "labels exist on partitions that aren't unlabeled." Alternative: a `kind: absent` discriminator. Strawman avoids adding the discriminator until a real need surfaces.
3. **Behavior when an OutputExpectation references the `label` field.** Strawman: OutputExpectations apply only to labeled splits (skipped for unlabeled with a note); rejecting the recipe is too strict because most recipes will declare label expectations even when one partition is unlabeled.

### Story H.e: v0.9.1 PyPI publish under `ml-datarefinery` [Done]

Reverses the deferred-PyPI decision recorded for Phase G. The unprefixed `datarefinery` name on PyPI was taken before this project began; the developer has elected to publish under the **distribution name `ml-datarefinery`** while keeping the Python package, import name, and CLI script name unchanged (same shape as `scikit-learn` / `import sklearn`). The story bundles the rename, the publish workflow, and the documentation sweep required to make `pip install ml-datarefinery` work from a clean venv against the real index.

**Scope.** Distribution-side change only. The recipe surface, plugin contract, validator, runner, and on-disk cache layout are untouched. Canonical recipe bytes are unaffected (the distribution name is not in `Recipe`); the pinned hash does not move.

**Tasks:**

- [x] **`pyproject.toml`.** Rename `[project].name` from `"datarefinery"` to `"ml-datarefinery"`. Leave `packages = ["src/datarefinery"]` and `[project.scripts] datarefinery = "datarefinery.cli.app:app"` alone — the import and console-script names stay `datarefinery`. Bump `[project].version` to `0.9.1`.
- [x] **`src/datarefinery/__init__.py`.** Bump `__version__` to `0.9.1`.
- [x] **New `.github/workflows/publish.yml`.** Trusted-Publishing (OIDC) workflow that triggers on `v*` tag push, builds sdist + wheel via `python -m build`, then publishes to TestPyPI (env `testpypi`) and PyPI (env `pypi`, gated by environment protection) using `pypa/gh-action-pypi-publish`. `permissions: id-token: write`. No long-lived API tokens.
- [x] **`.github/workflows/release.yml`.** Drop the "PyPI upload is intentionally deferred" comment block; the GitHub Release path still runs in parallel with the publish workflow on the same tag.
- [x] **README.md.** Replace `pip install datarefinery` with `pip install ml-datarefinery`. Same for the `[llm]` extra example. Add one sentence near the install line clarifying that the import name remains `datarefinery`.
- [x] **`docs/guides/releasing.md`.** Replace the "PyPI publishing is intentionally deferred" callout with a § documenting the new flow: trusted-publisher binding setup (one-time, on PyPI), the `testpypi` → `pypi` two-step on each tag push, and the maintainer-approval gate on the `pypi` GitHub environment. Update the "What this workflow does *not* do" section: PyPI upload is now done by `publish.yml`, not deferred.
- [x] **`docs/specs/tech-spec.md`.** § Publishing already prescribes Trusted Publishing; update the line `**PyPI:** datarefinery` → `**PyPI:** ml-datarefinery` and add a one-line note that the import name remains `datarefinery`. § Installation methods: `pip install datarefinery` → `pip install ml-datarefinery`. § Package metadata: the `[project].name` example value moves to `ml-datarefinery`.
- [x] **CHANGELOG.md.** New `## [0.9.1]` section under "Changed" describing the distribution-name change and the publish workflow.
- [x] **Memory update.** Rewrite `project_pypi_deferred.md` (and its `MEMORY.md` index line) from "deferred" → "PyPI distribution name is `ml-datarefinery`; first publish attempt is v0.9.1 via `.github/workflows/publish.yml`." Keep the historical reason in the body so a future LLM understands why the distribution name diverges from the import name.
- [x] **No canonical-hash shift.** `Recipe` does not contain the distribution name. Confirm `test_canonical_hash_pin` still passes without an update.
- [x] **Developer-side setup (out-of-band, before first publish attempt).** Listed here so future readers can verify the workflow's preconditions, not as LLM-executable tasks:
  - PyPI: add a "pending publisher" for `ml-datarefinery` bound to GitHub repo `pointmatic/datarefinery`, workflow `publish.yml`, environment `pypi`.
  - TestPyPI: same binding under environment `testpypi`.
  - GitHub: create Actions environments `pypi` (with required-reviewer protection) and `testpypi` (no protection).
- [x] Bump version to v0.9.1
- [x] Update CHANGELOG.md
- [x] Verify: tests green, ruff + mypy clean, canonical-hash pin still passes, `python -m build` produces `ml_datarefinery-0.9.1-py3-none-any.whl` and `ml_datarefinery-0.9.1.tar.gz` whose installed entry-points still expose `import datarefinery` and `datarefinery --help`.

**Out of Scope**

- **Reserving `datarefinery` on PyPI.** Not ours to take; the existing project owns it.
- **Renaming the Python package or import name.** Distribution-side only.
- **Backporting older versions to PyPI.** Only `v0.9.1` and later are published; pre-v0.9.1 tags remain GitHub-Release-only.

### Story H.f: v0.9.2 Drop TestPyPI from publish workflow [Done]

Bug fix on top of H.e. The `publish.yml` shipped in H.e included a `publish-testpypi` job referencing a GitHub Actions environment `testpypi` that did not exist in the repo, causing the v0.9.1 tag's publish run to fail in CI before reaching the PyPI step. The TestPyPI half was added speculatively from `tech-spec.md`'s pre-shipped recommendation; the developer did not authorise the extra hop and prefers a single `build → publish-pypi` flow.

This story strips the TestPyPI half entirely and bumps to v0.9.2 so the next tag actually publishes.

**Tasks:**

- [x] `.github/workflows/publish.yml`: delete the `publish-testpypi` job; `publish-pypi` depends directly on `build`.
- [x] `docs/guides/releasing.md`: drop the TestPyPI sub-bullet from step 6, drop the TestPyPI binding from § "One-time PyPI Trusted Publisher setup", drop the `testpypi` GitHub environment row. Keep the `pypi` environment + required-reviewer guidance.
- [x] `docs/specs/tech-spec.md` § Publishing: drop the TestPyPI job description; the workflow is `build → publish-pypi` only.
- [x] `CHANGELOG.md`: new `## [0.9.2]` section documenting the revert and the CI failure that prompted it.
- [x] `project_pypi_deferred.md` memory: remove the TestPyPI mention; the publish flow is single-hop.
- [x] `pyproject.toml` and `src/datarefinery/__init__.py`: bump to `0.9.2`.
- [x] Verify: tests green, ruff + ruff format + mypy clean, canonical-hash pin unchanged.

**Out of Scope**

- Re-adding TestPyPI later as a separate workflow. If a future story needs it, it can be added back deliberately with both bindings in place.
- Investigating the v0.9.1 tag's publish-run failure beyond the `testpypi`-env cause. The GH Release for v0.9.1 succeeded (different workflow); only the publish pipeline broke.

### Story H.g: v0.9.3 Drop GitHub Releases workflow [Done]

`release.yml` exists from F.f and creates a GitHub Release (the "Releases" page entries on github.com) on every `v*` tag push, with the matching `CHANGELOG.md` section as the body. It is independent of PyPI — `publish.yml` does the actual package distribution. The developer flagged that other PyPI-publishing repos they own do not maintain a parallel GitHub-Releases surface; the existing `CHANGELOG.md` already serves as the canonical release log inside the repo, and the git tag itself is visible on GitHub without a "Release" object attached.

This story deletes `release.yml` and trims every doc that references it. `publish.yml` becomes the sole tag-triggered workflow. Patch bump (v0.9.3) — no behavior change for users; only removes a duplicate surface.

**Tasks:**

- [x] Delete `.github/workflows/release.yml`.
- [x] `.github/workflows/publish.yml` header comment: drop the "runs in parallel with `release.yml`" line.
- [x] `docs/guides/releasing.md`: drop step 5 (Release workflow watch), renumber 6→5 and 7→6 and 8→7; drop GitHub-Release verification bullets from the new step 6; remove the `release.yml` row from the procedure preamble; rewrite intro to mention only the publish workflow.
- [x] `docs/specs/tech-spec.md` § Package Structure already lists only `ci.yml` + `publish.yml`; no edit needed there. Sweep the rest of the file for any stray `release.yml` reference.
- [x] `CHANGELOG.md`: new `## [0.9.3]` "Removed" section.
- [x] `pyproject.toml` and `src/datarefinery/__init__.py`: bump to `0.9.3`.
- [x] Verify: tests green, ruff + ruff format + mypy clean, canonical-hash pin unchanged, no remaining `release.yml` references outside `CHANGELOG.md` history.

**Out of Scope**

- Re-adding a GitHub-Releases workflow later. Easy to revive (the deleted file remains in git history); deferred until a real need surfaces.
- Backfilling GitHub Releases for v0.7.0 – v0.9.2. Their tags already exist; their CHANGELOG entries are the canonical notes. Not worth the manual `gh release create` per version.

### Story H.h: v0.9.4 README check-count fix + PyPI installability promoted to a requirement [Done]

Doc-only cleanup story. Three drift fixes that surfaced during a post-H.g audit:

1. `README.md`'s CLI verbs table says `validate` runs "18 enumerated static logical checks" — stale since H.b added check 20 and H.d added check 21 (H.a's check 19 also predates this fact going stale).
2. `features.md` has no explicit requirement covering PyPI installability. H.e shipped the PyPI publish workflow and renamed the distribution, but the requirement that motivates that work is not written down — leaving the developer-facing acceptance bar implicit. PyPI installability earns a real Usability Requirement + Acceptance Criterion.
3. `tech-spec.md`'s "First publish" line was written while H.f and H.g were both still in flight and hedges between v0.9.2 and v0.9.3. In practice H.g superseded H.f before any tag push, so v0.9.2 will never be tagged — the line can be simplified.

No code or tests touched. Patch bump (v0.9.4) since no behavior changed.

**Tasks:**

- [x] `README.md` line 361: `Schema + 18 enumerated static logical checks` → `Schema + 21 enumerated static logical checks`.
- [x] `docs/specs/features.md` § Usability Requirements: insert a new bullet between "Co-equal surfaces" and "Recipe legibility":
  > **Discoverable installation.** End users install DataRefinery via `pip install ml-datarefinery` from a clean Python 3.12 venv with no extra configuration. The distribution name (`ml-datarefinery`) diverges from the import name and console script (both `datarefinery`); the install command is the only place users see the prefixed name.
- [x] `docs/specs/features.md` § Acceptance Criteria: add AC 12:
  > `pip install ml-datarefinery==<version>` succeeds in a clean Python 3.12 venv and the installed package exposes `import datarefinery` plus the `datarefinery` console script. Verified manually on each release per `docs/guides/releasing.md` step 6.
- [x] `docs/specs/tech-spec.md` § Publishing: simplify the "First publish" line — drop the v0.9.2/v0.9.3 conditional and state `First publish: v0.9.3 (Story H.g). Pre-v0.9.3 tags exist but were never published to PyPI.`
- [x] `CHANGELOG.md`: new `## [0.9.4]` "Documentation" section.
- [x] `pyproject.toml` and `src/datarefinery/__init__.py`: bump to `0.9.4`.
- [x] Verify: tests green, ruff + ruff format + mypy clean, canonical-hash pin unchanged.

**Out of Scope**

- The `pyve run pip install -e /path/to/datarefinery` placeholders in README's "From source (development)" section. The developer authored those intentionally to make it explicit how to install the locally-cloned package from another codebase; not a defect.
- Promoting any other operational concern (release workflow, CI matrix, codecov) to a features.md requirement. PyPI installability is user-visible and warrants the seat; the others are internal-quality concerns and already live in tech-spec.md.

### Story H.i: Integration spike — `imagecorruptions` extras viability [Done]

Time-boxed integration spike to validate the new third-party dependency boundary introduced by FR-GEN-1 ([phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md)). The spike's deliverable is documented findings (install behavior, vocabulary, determinism, pin guidance) that H.m will consume — not shipping code.

Three uncertainties to resolve before H.m commits to the extras-group approach:

1. Do `imagecorruptions`, `opencv-python-headless`, and `scikit-image` install cleanly into the testenv alongside current `requirements-dev.txt` pins, with no resolver conflicts?
2. Is the H-D corruption vocabulary enumerable at the Python level (so recipe-time validation in H.m can be fail-fast when the extras are installed)?
3. Does a seeded corruption call on a fixed input produce byte-identical output across repeated invocations, as required by the determinism contract in `pipeline.workers`?

No version bump (spike-only; no shipping code). Phase-bundling option applies — this story carries no version in its title per the Version Cadence rules.

**Tasks:**

- [x] In a scratch worktree (or scratch branch), add a temporary `[corruptions]` extras spec to `pyproject.toml` listing `imagecorruptions`, `opencv-python-headless`, `scikit-image`. Install into the testenv (`pyve testenv run pip install -e '.[corruptions]'`) and record resolver behavior.
- [x] Enumerate the corruption vocabulary: `from imagecorruptions import get_corruption_names; get_corruption_names()`. Record the full list.
- [x] Determinism check: apply `gaussian_noise` at severity 3 to a fixed test image twice with the same RNG seed; confirm byte-identical output. Repeat for one weather-family corruption (e.g., `fog`).
- [x] Verify `opencv-python-headless` is what gets installed (not the GUI variant pulled transitively). If the GUI variant sneaks in via a transitive constraint, document the resolution.
- [x] Record findings in this story body before flipping to [x]: install procedure, vocabulary list, determinism result, recommended version pins, any caveats (e.g., platform-specific install gotchas on macOS arm64).
- [x] Decision: is the extras-group approach viable, or are there blocking issues that require an alternative (vendoring, fork, different package)? Record the decision and rationale.
- [x] Tear down the scratch install. Do **not** commit `pyproject.toml` or `requirements-dev.txt` changes in this story — H.m will land those with the production-grade tasks.

**Findings (recorded 2026-05-21 on macOS arm64, Python 3.12.13, NumPy 2.4.4, scikit-image 0.26.0)**

*Install behavior.* `pyve testenv run pip install -e '.[corruptions]'` resolved without version-resolver conflicts against the project's current `requirements-dev.txt`. Pulled wheels: `imagecorruptions-1.1.2`, `opencv-python-headless-4.13.0.92`, `scikit-image-0.26.0`, plus transitive `opencv-python-4.13.0.92`, `imageio-2.37.3`, `lazy-loader-0.5`, `networkx-3.6.1`, `tifffile-2026.5.15`. Three blocking install-time caveats surfaced:

1. **Transitive `opencv-python` (GUI variant)** is pulled by `imagecorruptions`'s `opencv-python>=3.4.5` requirement. Both `opencv-python` and `opencv-python-headless` install into the same `site-packages/cv2/` directory at the same version; the second installer wins by overwrite. The headless-only goal is defeated unless H.m installs `imagecorruptions --no-deps` and re-supplies its other deps explicitly, or runs `pip uninstall -y opencv-python` post-install.
2. **`pkg_resources` ModuleNotFoundError.** `imagecorruptions/corruptions.py:17` imports `pkg_resources` (legacy setuptools API). `setuptools>=81` no longer ships it. Adding `setuptools<81` to the extras restores the import — but the upstream setuptools README warns the API is slated for removal "as early as 2025-11-30" (already past today's date 2026-05-21), so this pin is a fragile floor that may break on next setuptools release.
3. **No `imagecorruptions` source patch will avoid both #1 and #2** without vendoring the package.

*Vocabulary (enumerable as required).* `get_corruption_names('all')` returns 19 names, partitioned `common` (15) / `validation` (4):
- common: `gaussian_noise`, `shot_noise`, `impulse_noise`, `defocus_blur`, `glass_blur`, `motion_blur`, `zoom_blur`, `snow`, `frost`, `fog`, `brightness`, `contrast`, `elastic_transform`, `pixelate`, `jpeg_compression`
- validation: `speckle_noise`, `gaussian_blur`, `spatter`, `saturate`

Recipe-time validation in H.m can be fail-fast via `from imagecorruptions import get_corruption_names; set(get_corruption_names('all'))`.

*Determinism check (severity=3, 64×64 RGB uint8 fixed-seed image, `np.random.seed(0)` + `random.seed(0)` before each call).*
- **15 / 19 byte-identical across repeated invocations:** `gaussian_noise`, `shot_noise`, `defocus_blur`, `motion_blur`, `zoom_blur`, `snow`, `frost`, `brightness`, `contrast`, `elastic_transform`, `pixelate`, `jpeg_compression`, `speckle_noise`, `spatter`, `saturate`.
- **3 fail outright on NumPy 2.x / scikit-image 0.21+:**
  - `fog` — `AttributeError: np.float_ was removed in the NumPy 2.0 release` (`imagecorruptions/corruptions.py:46`, `plasma_fractal`).
  - `glass_blur`, `gaussian_blur` — `TypeError: gaussian() got an unexpected keyword argument 'multichannel'` (scikit-image removed the `multichannel=` kwarg in 0.21; current API is `channel_axis=`).
- **1 non-deterministic:** `impulse_noise` calls `skimage.util.random_noise(..., mode='s&p', ...)` without passing `rng=`. Since skimage 0.21, `random_noise` uses an internal default PCG64 generator independent of `np.random.seed()`. Three calls under identical legacy seeding produced three different hashes. Fixable only by patching `imagecorruptions.corruptions.impulse_noise` to thread `rng=` through.

*Recommended pins (if extras-group is pursued anyway, with caveats accepted):*
```
[project.optional-dependencies]
corruptions = [
    "imagecorruptions==1.1.2",
    "opencv-python-headless",
    "scikit-image",
    "setuptools<81",  # required for pkg_resources import inside imagecorruptions
]
```
…plus a post-install `pip uninstall -y opencv-python` step (or an `--no-deps`-based install recipe documented in H.m).

**Decision (rationale):** the extras-group approach in its current `imagecorruptions==1.1.2` shape is **NOT VIABLE** for FR-GEN-1 / H.m. The upstream package was last released in 2019 and is incompatible with three of the project's current dependency-floor commitments:
- NumPy 2.x (the project ships `numpy` unpinned and resolves to 2.4.4) — breaks `fog`.
- scikit-image 0.21+ (resolves to 0.26.0) — breaks `glass_blur`, `gaussian_blur`.
- setuptools 81+ (default in current Python tooling) — breaks the import of `imagecorruptions` itself.
Additionally, the `opencv-python` transitive constraint defeats the headless-only deployment story.

**Recommended path for H.m (suggest at approval gate):** **Option A — vendored subset.** Vendor `imagecorruptions/corruptions.py` into `src/datarefinery/plugins/image_classification/_corruptions.py` (the upstream package is Apache-2.0 — verify NOTICE attribution requirements at vendor time). Apply four mechanical patches:
1. `np.float_` → `np.float64` (fixes `fog`).
2. `skimage.filters.gaussian(..., multichannel=True)` → `gaussian(..., channel_axis=-1)` (fixes `glass_blur`, `gaussian_blur`).
3. Thread an explicit `rng` through `impulse_noise` → `random_noise(..., rng=rng)` (fixes determinism).
4. Replace `pkg_resources.resource_filename` (loads frost JPEGs) with `importlib.resources` (removes setuptools dep).

Net result: all 19 corruptions work and are deterministic; runtime deps reduce to `opencv-python-headless` + `scikit-image` + `numpy` + `pillow` (no `imagecorruptions`, no `setuptools<81`). The vendored copy lives under the plugin and is covered by the project's existing license header convention. Estimated effort: 1–2 days plus tests.

Alternatives considered and not recommended:
- **Option B (different library — `albumentations` / `kornia`):** active maintenance and NumPy 2.x compatible, but their corruption vocabularies do not align 1:1 with the canonical Hendrycks-Dietterich 19-name set, requiring a translation layer that loses semantic equivalence with the literature.
- **Option C (pin the project floor backward):** `numpy<2`, `scikit-image<0.21`, `setuptools<81`. Drags the entire project's runtime floor back ~2 years for one optional op. Refuse.

**Out of Scope**

- Implementing the `imagecorruptions_apply` op itself. That's H.m.
- Performance benchmarking of the corruption calls. The determinism check is enough for a spike; latency is a non-blocking concern that surfaces only if H.m's integration tests are slow enough to warrant attention.

### Story H.j: v0.10.0 `sample_per_class` filter op with disjoint-pool labeling [Done]

A new `Filters` operation `sample_per_class` that produces a balanced subsample of `n_per_class` records per label, drawn deterministically from incoming records (stratified by label, seeded from the recipe's master seed). Optional `label` param tags surviving records with a partition marker readable by downstream filters; optional `exclude_already_labeled` param removes records already carrying any of the listed tags from the candidate pool, enabling disjoint-pool selection in a single recipe. See FR-FILTER-1 in [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

Disjoint-pool selection is the less obvious use case but matters whenever two non-overlapping balanced sets must be drawn from one labeled source — building a train/test split from a source without a canonical one, evaluating fairness on a balanced holdout drawn from the same pool as training, or constructing any pair of independent balanced sets when canonical splits are unavailable or unusable.

Design decision (from the phase plan): bespoke `label` + `exclude_already_labeled` params on this op rather than a generic record-tagging primitive that multiple filter ops would share. The generic primitive is deferred to Future.

Minor bump (v0.10.0) — new feature. Cache-invalidating: introduces a new op kind. Pre-prod invalidation acceptable per `project-essentials.md` § "Cache identity is the reproducibility contract" pre-production rules; mention in release notes.

**Tasks:**

- [x] Create `src/datarefinery/plugins/image_classification/filters_sample_per_class.py` with the standard Apache-2.0 header (`# Copyright (c) 2026 Pointmatic` / `# SPDX-License-Identifier: Apache-2.0`).
- [x] Add `SamplePerClassParams` pydantic model in `src/datarefinery/recipe/models.py`: `n_per_class: int` (positive), `label: str | None = None`, `exclude_already_labeled: list[str] | None = None`. Frozen.
- [x] Implement op: stratified-by-label deterministic sampling using per-record seeding (`sha256(global_seed.to_bytes(8, 'big') + record_id_bytes).digest()[:8]`), with optional label tagging on surviving records and optional candidate-pool exclusion via `exclude_already_labeled`. **Semantic clarification recorded:** when `label` is set the op is non-destructive (full pass-through with chosen records tagged), enabling the disjoint-pool pattern to work in chained filters; without `label` the op is the destructive balanced subsample. Documented in features.md FR-8.
- [x] Register op in `src/datarefinery/plugins/image_classification/__init__.py`. *(Registered in `plugin.py` — `__init__.py` re-exports `PLUGIN`, which is what consumers and entry points see.)*
- [x] Tests in `tests/plugins/image_classification/test_filters_sample_per_class.py`: balanced subsample without tagging; with `label` tag emitted on surviving records; disjoint-pool case (two `sample_per_class` ops chained, second uses `exclude_already_labeled` to skip the first's selection); deterministic across `workers=1/2/4` byte-identical. Plus selection-invariant-to-input-order, n-per-class-cap, validation paths, and `pydantic ValidationError` on `n_per_class <= 0`.
- [x] `docs/specs/features.md` § FR-8 (Filters): append a paragraph declaring `sample_per_class` as a new plugin-contributed op; document the `n_per_class`, `label`, and `exclude_already_labeled` params; describe the disjoint-pool pattern (chained `sample_per_class` ops with `exclude_already_labeled` referencing the prior `label`) as a worked use case. Add an edge-case bullet covering tagging-without-existing-label (records without the prior tag are not excluded).
- [x] `docs/specs/tech-spec.md` § Package Structure: add `filters_sample_per_class.py` under `plugins/image_classification/` *(directly under the plugin dir, matching the H.k/H.l/H.m per-op-file pattern — the in-line "under operations/" in this task line was an authoring inconsistency; the actual file path matches the explicit `Create` task above).* § Data Models > Recipe model section table: extend the `FilterOp` row to reference the new `SamplePerClassParams` model (params validated via the plugin's `OperationSpec`, check 18). § Cross-Cutting Concerns > Determinism: confirm the new op uses the existing per-record seeding scheme; no new seeding code needed.
- [x] `README.md`: no edit required for this story. The Plugin model section's existing "etc." covers the new op; CLI verb table check-count is unchanged unless this story adds a new validator check (it does not).
- [x] `CHANGELOG.md`: new `## [0.10.0]` "Added" section noting the new op and pre-prod cache invalidation.
- [x] Bump `pyproject.toml` and `src/datarefinery/__init__.py` to `0.10.0`.
- [x] Verify: tests green, ruff + ruff format + mypy clean, canonical-hash pin unchanged (the pinned fixture recipe must not use the new op).

**Out of Scope**

- Generic record-tagging primitive that other filter ops could share. Deferred to Future.
- `sample_per_class_fractional` — separate story (H.k).
- `drop_by_label` — separate story (H.l).

### Story H.k: v0.11.0 `sample_per_class_fractional` filter op [Done]

A new `Filters` operation that produces a per-class subsample where each class is sampled at a different rate. Parameters: `n_per_class_base` (integer reference scale) and `fractions` (dict mapping each label to a float in [0.0, 1.0]; missing labels default to 1.0). Surviving records per class = `floor(n_per_class_base × fractions[label])`. Inherits FR-FILTER-1's `label` and `exclude_already_labeled` tagging params. See FR-FILTER-2 in [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

Controlled-imbalance dataset construction is the recurring need this addresses: studying how class imbalance affects model behavior, comparing mitigation strategies (oversampling, class-weighted loss, focal loss, minority-class augmentation), or stress-testing a mitigation against a known imbalance ratio. The fractional form reads cleanly and matches how imbalance is typically discussed in the literature — as a per-class multiplier on a base rate — rather than as a chain of per-class filters with different absolute counts.

Minor bump (v0.11.0). Cache-invalidating.

**Tasks:**

- [x] Create `src/datarefinery/plugins/image_classification/filters_sample_per_class_fractional.py` with Apache-2.0 header.
- [x] Add `SamplePerClassFractionalParams` pydantic model: `n_per_class_base: int` (positive), `fractions: dict[str, float]` (each value in [0.0, 1.0]), plus inherited `label`/`exclude_already_labeled` params. Frozen. *(Range validation via `model_validator`; `n_per_class_base` via `Field(gt=0)`.)*
- [x] Factor out the shared stratified-by-label seeded sampling and tagging logic into a private helper module shared with H.j's `sample_per_class` (DRY without over-abstracting; one helper, two op call sites). *(Helper: `filters_stratified_sampling.stratified_seeded_sample`; accepts a `n_for_class: Callable[[label], int]` so H.j passes a constant lambda and H.k passes the floor formula. `TAG_FIELD` now lives in the helper module and is re-exported from `filters_sample_per_class` for the existing import path.)*
- [x] Implement op: per-class surviving count = `floor(n_per_class_base × fractions.get(label, 1.0))`.
- [x] Register op.
- [x] Tests in `tests/plugins/image_classification/test_filters_sample_per_class_fractional.py`: per-class counts match the floor formula; missing-class defaults to 1.0; fractions=0.0 drops that class entirely; label tagging consistent with H.j; disjoint pool with `sample_per_class` chained via `exclude_already_labeled`; workers=1/2/4 byte-identical. Plus floor-truncation for non-integer products, range/positive validation, missing-seed and missing-label-field PluginError paths.
- [x] `docs/specs/features.md` § FR-8 (Filters): append a paragraph declaring `sample_per_class_fractional`; document `n_per_class_base`, `fractions`, and inherited `label`/`exclude_already_labeled` params; state the per-class surviving-count formula. Note the op shares the disjoint-pool tagging mechanism with `sample_per_class`.
- [x] `docs/specs/tech-spec.md` § Package Structure: add `filters_sample_per_class_fractional.py` plus the shared sampling-helper module *(`filters_stratified_sampling.py`, placed directly under `plugins/image_classification/` to match the actual H.j/H.k file pattern — same "operations/" path inconsistency in this task line as in H.j)*. § Data Models > Recipe model section table: extend the `FilterOp` row to reference `SamplePerClassFractionalParams`.
- [x] `README.md`: no edit required.
- [x] `CHANGELOG.md`: `## [0.11.0]` "Added" section.
- [x] Bump `pyproject.toml` and `src/datarefinery/__init__.py` to `0.11.0`.
- [x] Verify: tests, lint, mypy, canonical-hash pin.

**Out of Scope**

- Rebasing H.j onto a "generic per-class sampler with optional fraction param" primitive that subsumes both ops. The two-op recipe surface reads more clearly than a single op with conditional parameters; the shared internal helper covers the DRY concern.

### Story H.l: v0.12.0 `drop_by_label` filter op [Done]

A new `Filters` operation that drops records carrying any of the named labels. Parameter: `labels: list[str]` (non-empty). The inverse companion to FR-FILTER-1's `label` tagging mechanism. See FR-FILTER-3 in [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

Canonical use case: two sibling recipes need to select the same subset from a common labeled source, so both replicate an identical filter chain (same ops, same parameters, same seed) — but each recipe then drops the labels not relevant to its purpose, keeping only its share. Without `drop_by_label`, recipes either use a non-deterministic selection mechanism (breaking cross-recipe bit-identity guarantees) or carry unused records through the rest of the pipeline (wasting materialization time and disk space).

Design decision (from the phase plan): distinct `drop_by_label` op rather than a parameter on existing filter primitives. Distinct reads cleaner in the recipe surface.

Minor bump (v0.12.0). Cache-invalidating.

**Tasks:**

- [x] Create `src/datarefinery/plugins/image_classification/filters_drop_by_label.py` with Apache-2.0 header.
- [x] Add `DropByLabelParams` pydantic model: `labels: list[str]` with non-empty validation. Frozen. *(Validated via `Field(min_length=1)`.)*
- [x] Implement op: read the record-tag field written by H.j/H.k, drop any record whose tag is in `labels`. *(Reads `TAG_FIELD` from `filters_stratified_sampling`; records without the tag field pass through unchanged.)*
- [x] Register op.
- [x] Tests in `tests/plugins/image_classification/test_filters_drop_by_label.py`: drop with single label; drop with multiple labels; drop on tagged records but pass through untagged; empty `labels` rejected at validation; cross-recipe bit-identity test (two recipes chain through H.j and H.l with different `labels` values and produce non-overlapping, byte-identical sub-instances). Plus the nonexistent-label no-op edge case and the no-prior-tagging-at-all pass-through.
- [x] `docs/specs/features.md` § FR-8 (Filters): append a paragraph declaring `drop_by_label`, its `labels: list[str]` parameter, and the canonical two-sibling-recipes use case (same chain, different `drop_by_label.labels`, byte-identical sub-instances). Add an edge-case bullet for non-existent label values (skipped as a no-op rather than raising).
- [x] `docs/specs/tech-spec.md` § Package Structure: add `filters_drop_by_label.py` *(placed directly under `plugins/image_classification/` to match the actual H.j/H.k file pattern — same "operations/" path inconsistency in this task line as in H.j/H.k)*. § Data Models > Recipe model section table: extend the `FilterOp` row to reference `DropByLabelParams`.
- [x] `README.md`: no edit required.
- [x] `CHANGELOG.md`: `## [0.12.0]` "Added" section.
- [x] Bump to `0.12.0`.
- [x] Verify.

**Out of Scope**

- A `keep_by_label` companion op. Symmetrically pleasing, but the same effect can be achieved by inverting the `drop_by_label` list; deferred until a real recipe needs it.

### Story H.m: `imagecorruptions_apply` Generation op + `[corruptions]` extras (umbrella) [Done]

A new `Generation` operation that applies Hendrycks-Dietterich image corruptions (ICLR 2019) to incoming records. Parameters: `corruption_types` (list of H-D vocabulary names), `severities` (list of ints in 1–5), `preserve_original` (boolean), `tag_fields` (metadata fields written per output record). Output record count = `input × len(corruption_types) × len(severities)`, ×2 when `preserve_original=True`. Determinism via the per-record seeding contract in `pipeline.workers`. See FR-GEN-1 in [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

Robustness evaluation under known image corruptions is a standard benchmarking practice originating with Hendrycks & Dietterich's "Benchmarking Neural Network Robustness to Common Corruptions and Perturbations" (ICLR 2019). The corruption taxonomy covers noise, blur, weather, and digital artifacts at five severity levels. Wrapping it as a DataRefinery Generation operation keeps the corruption layer seeded, cache-keyed, report-visible, and reproducible — versus the alternative of consuming pre-generated published corruption datasets (per-dataset fetch logic, separate `.npy` source handling, tens of GB of downloads for what is functionally a wrapper around this package).

**Implementation path (binding decision from the H.i spike).** The H.i integration spike established that depending on `imagecorruptions==1.1.2` directly from PyPI is **not viable** on the project's current dependency floor:

- `imagecorruptions==1.1.2` (last released 2019) uses `np.float_` (removed in NumPy 2.0) → `fog` corruption fails outright.
- Calls `skimage.filters.gaussian(multichannel=True)` (removed in scikit-image 0.21+) → `glass_blur` and `gaussian_blur` fail outright.
- Calls `skimage.util.random_noise` without `rng=` (skimage 0.21+ uses an internal PCG64 not bound to legacy `np.random.seed()`) → `impulse_noise` is non-deterministic.
- Imports `pkg_resources` (removed from `setuptools>=81`) → entire package fails to import on a current testenv unless `setuptools<81` is pinned.
- Transitive `opencv-python>=3.4.5` defeats the `opencv-python-headless` isolation goal.

Therefore H.m's work follows the spike's **Option A — vendored subset**: vendor `imagecorruptions/corruptions.py` into the plugin (Apache-2.0, attribution preserved) with four mechanical patches (`np.float_`→`np.float64`; `multichannel=`→`channel_axis=`; thread `rng` through `impulse_noise`'s `random_noise` call; replace `pkg_resources.resource_filename` with `importlib.resources`). The `[corruptions]` extras group ships only `scikit-image` + `opencv-python-headless` (no `imagecorruptions`, no `setuptools<81` pin).

**Child stories.** This work is split for incremental review:

- **H.m.1 — Vendor `imagecorruptions/corruptions.py` with NumPy 2.x / scikit-image / RNG patches.** Extras group + vendored `_corruptions.py` + frost texture data + tests for vocabulary and determinism. Unversioned (phase-bundled).
- **H.m.2 — `imagecorruptions_apply` Generation op + recipe-validation hook.** Op module + pydantic params + per-record seeding + output emission + plugin registration + op-level unit tests. Unversioned (phase-bundled).
- **H.m.3 — v0.13.0 `imagecorruptions_apply` integration test + docs + release.** End-to-end materialization test + features.md/tech-spec.md/README.md updates + CHANGELOG + version bump. Ships the v0.13.0 release.

Cache-invalidating (new op kind). Pre-prod invalidation acceptable per `project-essentials.md` § "Cache identity is the reproducibility contract" pre-production rules.

**Out of Scope** *(applies across H.m.1 / H.m.2 / H.m.3)*

- FR-VIZ-3 / FR-VIZ-4 corruption visualizations. Deferred to Future.
- Pre-generated corruption-dataset source types (e.g., `.npy` distributions of CIFAR-10-C). Out of bundle scope.

### Story H.m.1: Vendor `imagecorruptions/corruptions.py` with NumPy 2.x / scikit-image / RNG patches [Done]

First of three H.m child stories. Establishes the `[corruptions]` extras group and vendors the corruption implementation as `src/datarefinery/plugins/image_classification/_corruptions.py` with the four patches identified in the H.i spike. No shipping op yet — that's H.m.2.

Unversioned (phase-bundled per the Version Cadence rule; H.m.3 carries the v0.13.0 release bump).

**Tasks:**

- [x] Add `[project.optional-dependencies] corruptions = ["scikit-image", "opencv-python-headless"]` to `pyproject.toml`. Do **not** include `imagecorruptions` or `setuptools<81` — the vendored module replaces both.
- [x] Install the extras in the testenv: `pyve testenv run pip install -e '.[corruptions]'`.
- [x] Vendor the corruption implementation into `src/datarefinery/plugins/image_classification/_corruptions.py`. Apache-2.0 file header carrying both Pointmatic copyright and the upstream attribution ("Originally derived from `imagecorruptions` v1.1.2 by Claudio Michaelis, Apache-2.0; modifications by Pointmatic 2026"). Apply the four mechanical patches *(plus a fifth defensive one for the scipy.ndimage.interpolation deprecation; documented in the file header)*:
  1. `np.float_` → `np.float64` (fixes `fog`'s `plasma_fractal`).
  2. `skimage.filters.gaussian(..., multichannel=True)` → `gaussian(..., channel_axis=-1)`; `multichannel=False` → `channel_axis=None` (fixes `glass_blur` and `gaussian_blur`).
  3. Thread an explicit `rng: numpy.random.Generator` parameter through `impulse_noise` → `skimage.util.random_noise(..., rng=rng)` *(extended scope: ALL randomness in the vendored module is now threaded through `rng`, not just `impulse_noise`. Upstream used global `np.random.X` calls throughout — gaussian_noise, shot_noise, speckle_noise, glass_blur swap deltas, motion_blur angle, snow noise/angle, frost texture-idx + crop, fog plasma_fractal, spatter liquid_layer, elastic_transform displacement. Determinism for the op now means a single `rng` passed to `corrupt(...)`; the upstream call surface is otherwise preserved.)*
  4. Replace `pkg_resources.resource_filename` (used by `frost` to locate the frost JPEG textures) with `importlib.resources.files(...).joinpath(...)` (removes the `pkg_resources` / `setuptools<81` dependency).
- [x] Vendor the frost JPEG textures into `src/datarefinery/plugins/image_classification/_corruption_data/frost/` (copy `frost1.png`...`frost6.jpg` from the upstream `imagecorruptions/frost/`). Loaded via `importlib.resources.as_file` in the patched `frost()`. Upstream Apache-2.0 license text preserved in `_corruption_data/NOTICE.md` along with author attribution.
- [x] Define the public API: `get_corruption_names(subset: str = "all") -> list[str]` returning the same 19 / 15 / 4 partitions as upstream (plus the four `noise`/`blur`/`weather`/`digital` category subsets); `corrupt(image, *, corruption_name: str, severity: int, rng: numpy.random.Generator) -> numpy.ndarray` matching upstream's call surface but accepting an explicit `rng` parameter rather than relying on global `np.random` state. Validation paths (non-ndarray, non-uint8, dims, severity range, unknown name) preserved.
- [x] Tear down any installed `imagecorruptions` from the testenv. *(Temporarily re-installed `imagecorruptions==1.1.2` + `setuptools<81` while extracting the upstream source for vendoring; both uninstalled afterward. The testenv state matches what a fresh consumer would see.)*
- [x] Tests in `tests/plugins/image_classification/test_corruptions_vendored.py`:
  - `get_corruption_names("all")` returns 19 names; `"common"` returns 15; `"validation"` returns 4; union of `common` + `validation` equals `all` with no overlap.
  - For each of the 19 corruption names at severity 3, `corrupt(image, corruption_name=name, severity=3, rng=np.random.default_rng(0))` returns a `(H, W, 3)` `uint8` array; two calls with the same seed produce byte-identical output. *(Parametrized — 19 tests confirm determinism per corruption.)*
  - Patch-specific regression tests named explicitly: `fog` no longer raises `AttributeError`; `glass_blur` and `gaussian_blur` no longer raise `TypeError`; `impulse_noise` is byte-identical across two seeded calls.
  - `frost` successfully loads a vendored texture file via `importlib.resources` (smoke test that the data path works).
  - Validation surface (non-ndarray, non-uint8, small-image, unknown name, out-of-range severity) covered.
- [x] `docs/specs/tech-spec.md` § Package Structure: add `_corruptions.py` and `_corruption_data/` under `plugins/image_classification/`. § Dependencies > Optional extras table: add a `[corruptions]` row pulling `scikit-image`, `opencv-python-headless`.
- [x] `CHANGELOG.md` Unreleased / phase-bundled — no entry yet; H.m.3 writes the consolidated 0.13.0 entry.
- [x] No version bump (phase-bundled with H.m.3).
- [x] Verify: tests green for the new file (34 tests, including 19 parametrized determinism cases), ruff + ruff format + mypy clean (vendored module carries a file-level `# mypy: ignore-errors` directive — standard for vendored scientific code; the Pointmatic-authored `corrupt` / `get_corruption_names` surface is small and type-checks fine; only the upstream-derived numerical body is exempted), full suite still green (794 vs. 760 before H.m.1).

**Out of Scope (H.m.1 specifically)**

- Recipe-level integration — no `imagecorruptions_apply` op, no `ImageCorruptionsApplyParams`, no plugin registration. That's H.m.2.
- `docs/specs/features.md` updates — wait for the user-visible op to land in H.m.2/H.m.3.
- `README.md` updates — wait for H.m.3.

### Story H.m.2: `imagecorruptions_apply` Generation op + recipe-validation hook [Done]

Second of three H.m child stories. Builds the Generation op on top of H.m.1's vendored module. Unversioned (phase-bundled).

**Tasks:**

- [x] Create `src/datarefinery/plugins/image_classification/generation_imagecorruptions.py` with Apache-2.0 header. Lazy-import the `_corruptions` backend (which transitively imports `scikit-image` and `cv2`) at op-call time, via a `_load_backend()` helper that catches `ImportError` and re-raises with a friendly `pip install 'ml-datarefinery[corruptions]'` pointer.
- [x] Add `ImageCorruptionsApplyParams` pydantic model in `recipe/models.py`: `corruption_types: list[str]` (non-empty), `severities: list[int]` (each in 1..5, non-empty), `preserve_original: bool = False`, `tag_fields: list[str] = ["corruption", "severity", "source_path"]`. Frozen, with `model_validator` rejecting empty lists, out-of-range severities, duplicate names, and unknown corruption names. *(Vocabulary check reads from the new dependency-free `_corruption_names.CORRUPTION_NAMES_ALL` so it works without the extras installed.)*
- [x] **Foundational schema change (out-of-band addition).** Generation ops in this codebase previously had no `params` surface — `GenerationOp` exposed only `name` / `inputs` / `output_schema` / `seed` / `applies_at`. Building `imagecorruptions_apply` requires user-supplied params. Added `params: dict[str, Any] = Field(default_factory=dict)` to `GenerationOp`; threaded through `pipeline/stages/generation.py:_invoke_one`; existing `duplicate_minority_class` op signature extended to accept-and-discard `params`. The op's `OperationSpec.parameters` was simultaneously truthified — the old declaration listed `label_field` / `target_count` / `seed` as required params but those values come from `op.seed` / `Labels.field` / hard-coded majority count, not from a `params` dict. Set to empty parameters in all three plugins (image_classification, tabular, text). Extended `recipe.validator.check_18` to validate Generation params as well (consistent with other op kinds). Inline `_DropFieldPlugin` test plugin in `test_generation_stage.py` updated to accept the new param.
- [x] Created dependency-free `_corruption_names.py` module with `CORRUPTION_NAMES_COMMON` / `CORRUPTION_NAMES_VALIDATION` / `CORRUPTION_NAMES_ALL` tuples. Cross-check test in `test_corruptions_vendored.py` asserts the static names match `_corruptions.get_corruption_names(...)` so drift is caught.
- [x] Recipe-validation hook: validate `corruption_types` against `CORRUPTION_NAMES_ALL` at `ImageCorruptionsApplyParams` validate-time (always works without extras — the names module is dependency-free). Materialization-time lazy import surfaces the friendly extras-install pointer if cv2/scikit-image are missing.
- [x] Per-record seeding: derive each input record's corruption seed from `(global_seed, record_id)` via `pipeline.workers.per_record_seed`; convert to a `numpy.random.default_rng(prs)` and pass to `_corruptions.corrupt(..., rng=...)`. One `rng` per input record, advanced across the per-corruption-name × per-severity sweep.
- [x] Output emission: one output record per `(input × corruption_type × severity)`; when `preserve_original=True` an untouched copy is emitted first per input with `corruption="none"`, `severity=0`. Each output `record_id` derived from `sha256(input_record_id|corruption_name|severity)[:8]` to preserve uniqueness.
- [x] Tag-field writes: `corruption`, `severity`, `source_path` written onto each output when listed in `tag_fields`. `source_path` falls back to `record_id` when the record has no `path` field.
- [x] Register op in `plugin.py` under `_GENERATION_OPS` and declare its `OperationSpec` with `applicable_sections=frozenset({"Generation"})`.
- [x] Update `tests/plugin_contract/test_image_classification.py`'s `EXPECTED_OPERATIONS` to include `imagecorruptions_apply`.
- [x] Tests in `tests/plugins/image_classification/test_generation_imagecorruptions.py` (19 tests):
  - Determinism: same input + seed → byte-identical output across two invocations.
  - Workers byte-identical at 1/2/4 via `run_parallel` (the `@pytest.mark.slow` integration check).
  - Output count formula: `len(out) == len(inputs) * len(corruption_types) * len(severities)` (plus `len(inputs)` extra when `preserve_original=True`).
  - `preserve_original=True` emits the untouched record with `corruption="none"`, `severity=0`.
  - Tag-field writes: each output record carries the named `corruption`, `severity`, `source_path` fields with correct values. Subset `tag_fields=["corruption"]` only writes `corruption`.
  - Output record IDs are unique across the cross-product sweep.
  - End-to-end: `apply_generation` concatenates corrupted records onto the input split (counts_before=3 → counts_after=6 for 3 inputs × 1 type × 1 severity).
  - Recipe-validation rejects unknown corruption names, duplicate corruption_types, severities outside 1..5, duplicate severities, empty lists.
  - Op-call-time input validation: record missing `image` field → `MaterializeError`; non-uint8 `image` → `MaterializeError`.
  - Friendly extras-install `ImportError` when `_corruptions` cannot be imported (mock-based; testenv has the extras after H.m.1).
- [x] No version bump (phase-bundled with H.m.3).
- [x] Verify: tests green (815 vs. 794 before H.m.2; +20 tests + 1 from the static-names cross-check in `test_corruptions_vendored.py`), ruff + ruff format + mypy clean.

**Out of Scope (H.m.2 specifically)**

- End-to-end materialization integration test (full pipeline through manifest + report). That's H.m.3.
- `docs/specs/features.md` / `tech-spec.md` (beyond Package Structure already added in H.m.1) / `README.md` updates. H.m.3.

### Story H.m.3: v0.13.0 `imagecorruptions_apply` integration test + docs + release [Done]

Third of three H.m child stories. End-to-end verification + user-visible documentation + the version bump that ships FR-GEN-1.

Minor bump (v0.13.0). Cache-invalidating: introduces the `imagecorruptions_apply` op kind. Pre-prod invalidation acceptable per `project-essentials.md` § "Cache identity is the reproducibility contract" pre-production rules.

**Tasks:**

- [x] Integration test in `tests/integration/test_imagecorruptions_apply.py`: 12-input record set (32×32 images) → recipe with a 2×2 (`corruption_types=[gaussian_noise, fog]` × `severities=[1, 3]`) `imagecorruptions_apply` op → full materialization through `PipelineRunner` → asserts instance directory layout (manifest, train/val/test JSONL shards, report.md), per-split record counts (train = `n_train_pre_generation × 5` from the 2×2 sweep + originals), and per-record tag-field writes in train.jsonl (`corruption`, `severity`, `source_path`). Plus a second test asserting cross-run cache-key determinism (same recipe + same input hashes + same seed → same `recipe_hash` / `input_hash` / `record_counts`).
- [x] `docs/specs/features.md` § FR-9 (Generation): new paragraph documenting the op, parameters, output-count formula, determinism contract, and Hendrycks-Dietterich provenance + vendored-module note. § Quality Requirements > Minimal runtime deps: updated to list both `[llm]` and `[corruptions]` extras with the in-tree vocabulary note. § FR-2 Edge Cases: new bullet on the deferred-validation case for optional-extras-gated ops.
- [x] `docs/specs/tech-spec.md` § Optional extras table: extends H.m.1's `[corruptions]` row description to mention the runtime-only execution boundary. § Package Structure: added `_corruption_names.py` + `generation_imagecorruptions.py`. § Data Models > Recipe model table: `GenerationOp` row extended with the new `params` field and `ImageCorruptionsApplyParams`. § Installation methods table: new "End user with corruption-robustness extras" row.
- [x] `README.md` § Installation: parallel `[corruptions]` snippet added after the `[llm]` one, with a Hendrycks-Dietterich reference.
- [x] `CHANGELOG.md`: `## [0.13.0] - 2026-05-22` block with Added (op + vendored module + extras group), Changed (the `GenerationOp.params` schema field carried over from H.m.2 + the `duplicate_minority_class` OperationSpec truthification), and a Notes section on pre-prod cache invalidation.
- [x] Bump `pyproject.toml` and `src/datarefinery/__init__.py` to `0.13.0`.
- [x] Verify: tests (incl. extras-installed run), lint, mypy, canonical-hash pin (the pinned fixture recipe does not use the new op and is unchanged).
- [x] **Wheel-pack verification** (out-of-band defensive check): built a wheel via `python -m build --wheel` and confirmed the vendored frost JPEGs + `NOTICE.md` + `_corruption_data/` directory all ship in the wheel. Hatchling's default `packages = ["src/datarefinery"]` config handled the non-Python assets without needing `force-include`.

**Out of Scope (H.m.3 specifically)**

- Same as H.m's umbrella out-of-scope: FR-VIZ-3 / FR-VIZ-4 corruption visualizations; pre-generated corruption-dataset source types.

### Story H.n: `stats_from_instance` on `normalize` + FR-ARCH-1 loose-coupling decision documented (umbrella) [Done]

A new parameter on `Transformations` operations that have a `fit` phase (today: `normalize`; extensible to future fit-phase ops). When set, the operation imports its fitted statistics from a sibling materialized DataRefinery instance rather than fitting locally. Parameter shape:

```yaml
stats_from_instance:
  recipe: <path-or-name>
  op_id: <name-of-the-op-in-the-sibling-recipe>
```

The op resolves the sibling instance from the cache, reads `fitted_statistics/<op_id>/`, and uses those statistics for the apply phase. No local fit is performed. Three failure modes must produce clear errors at validation or materialization time: sibling instance not found in cache, named `op_id` not present in sibling, sibling's statistics format incompatible with this op. See FR-TRANS-1 in [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

Train/inference normalization parity is a correctness invariant: evaluation data must be normalized with the same statistics the model was trained against. When training and evaluation data are materialized in the same recipe, `fit_source: train` already handles this; the gap appears when they live in separate recipes (distribution-shift evaluation, A/B evaluation, cross-team workflows, longitudinal evaluation). In all of these, re-fitting statistics on the evaluation data is a correctness bug, not an optimization. `stats_from_instance` makes the correct behavior expressible at the recipe surface.

**FR-ARCH-1 decision (documented here, not implemented as a separate change):** **loose coupling**. The sibling is referenced by recipe path/name; no `recipe_hash` is recorded as a component of this recipe's cache identity. Re-materializing the upstream recipe does not automatically invalidate downstream caches — the user is responsible for re-materializing downstream when upstream changes. Loose-coupling failure modes are detectable in small-scale single-author workflows, which is the workflow this sub-bundle enables. Tight coupling (sibling `recipe_hash` participates in cache identity, so upstream changes auto-invalidate downstream) is deferred to Future as a follow-up upgrade — needed for multi-team or longitudinal workflows where the loose-coupling failure mode is harder to catch by inspection.

Cache-invalidating (new field on `normalize`). Pre-prod invalidation acceptable per `project-essentials.md` § "Cache identity is the reproducibility contract" pre-production rules.

**Child stories.** This work is split for incremental review:

- **H.n.1 — Sibling-instance fitted-stats resolver.** Standalone utility module that takes `(cache_root, recipe_path, op_id)` and returns the parsed fitted statistics, with three explicit failure modes. Unit-tested against a hand-built cache directory; no recipe-model changes; no `normalize` integration. Unversioned (phase-bundled).
- **H.n.2 — `StatsFromInstanceSpec` + `normalize` apply-path integration.** `StatsFromInstanceSpec` pydantic model, mutual-exclusion validator check, `normalize` apply branch that calls the resolver. Cross-recipe integration tests via `PipelineRunner`. Unversioned (phase-bundled).
- **H.n.3 — v0.14.0 docs + project-essentials + release.** `features.md` / `tech-spec.md` / `project-essentials.md` updates, `CHANGELOG`, version bump. Ships v0.14.0.

**Out of Scope** *(applies across H.n.1 / H.n.2 / H.n.3)*

- Tight coupling (sibling `recipe_hash` participating in cache identity). Deferred to Future per the FR-ARCH-1 decision.
- Extending `stats_from_instance` to other fit-phase ops beyond `normalize`. The parameter is designed to be reusable, but no other fit-phase op exists today; extending happens when a second fit-phase op lands.
- Tooling to detect or warn about stale downstream caches when upstream changes. The loose-coupling decision accepts this as user-managed; a "detect-stale" linter is a Future enhancement, not a v0.14.0 requirement.

### Story H.n.1: Sibling-instance fitted-stats resolver [Done]

First of three H.n child stories. Stands alone as a utility module that knows how to walk the cache layout, find the most-recent matching instance for a given recipe, and read its `fitted_statistics/<op_id>/`. No recipe-model changes, no `normalize` integration yet (that's H.n.2).

Unversioned (phase-bundled; H.n.3 carries the v0.14.0 release).

**Tasks:**

- [x] Create `src/datarefinery/cache/sibling_stats.py` with Apache-2.0 header. Public function `resolve_sibling_stats(cache_root: Path, recipe_path: Path, op_id: str, *, required_vectors: tuple[str, ...] = (), required_scalars: tuple[str, ...] = ()) -> FittedStatistics`. *(Returns a `FittedStatistics` handle pointed at the sibling's `fitted_statistics/` rather than an eagerly-loaded dict — matches the existing in-process API for fitted statistics access, lets the caller read named vectors/scalars via the standard `get_vector(op_id, name)` / `get_scalar(op_id, name)` interface, and lets the resolver pre-validate that any caller-declared required statistics are present at resolve time.)* Resolution path: read & parse the recipe at `recipe_path` via `recipe.loader.load`; compute its canonical SHA-256 hash via `recipe.canonical.to_canonical_bytes`; look up promoted instances under `<cache_root>/instances/<recipe16>/`; among candidates whose `manifest.json` is readable, pick the most-recent by `Manifest.created_at` (path-lexicographic tiebreak); read `fitted_statistics/<op_id>/` and verify the op directory exists.
- [x] Three explicit failure modes via dedicated exception types (`SiblingInstanceNotFoundError`, `SiblingOpNotFoundError`, `SiblingStatsIncompatibleError`) extending `MaterializeError`. Each carries a clear message naming the lookup path / op_id / file that failed.
- [x] Prominent module-docstring comment captures the intentional-loose-coupling decision (sibling `recipe_hash` does NOT enter the consumer's cache identity; tight coupling tracked in Future).
- [x] Unit tests in `tests/unit/test_sibling_stats.py` *(placed under `tests/unit/` rather than the task's suggested `tests/cache/` to match the established convention for cache-layer tests in this repo — see `test_cache_identity.py`, `test_cache_layout.py`)*: hand-build a synthetic cache-layout directory tree with a known recipe + a `fitted_statistics/norm/{mean.parquet,std.parquet}` pair via real `FittedStatistics.put_vector` calls. 10 tests: happy path (returns the handle, vectors read correctly); most-recent-by-`created_at` selection across two instances sharing a recipe; `SiblingInstanceNotFoundError` when the shard directory is missing; `SiblingInstanceNotFoundError` when the shard exists but contains no valid manifest; `SiblingOpNotFoundError` when no `op_id` directory; `SiblingOpNotFoundError` when only a different `op_id` is present; `SiblingStatsIncompatibleError` for missing required vector / missing required scalar / corrupt parquet that pyarrow can't read; loose-coupling invariant test confirming the resolver locates instances by recipe_hash only (input_hash and seed irrelevant to lookup).
- [x] No recipe-model changes. No `normalize` op modification. No `Recipe` validator changes.
- [x] No version bump (phase-bundled with H.n.3).
- [x] Verify: tests green for the new file (10 tests), full suite still green (827 vs. 817 before H.n.1), ruff + ruff format + mypy clean.

**Out of Scope (H.n.1 specifically)**

- Pydantic model / `normalize` schema / mutual-exclusion validator — H.n.2.
- End-to-end cross-recipe materialization tests — H.n.2.
- Documentation updates (features.md / tech-spec.md / project-essentials.md / CHANGELOG) — H.n.3.

### Story H.n.2: `StatsFromInstanceSpec` + `normalize` apply-path integration [Done]

Second of three H.n child stories. Builds the recipe-surface and apply-path integration on top of H.n.1's resolver. Unversioned (phase-bundled).

**Tasks:**

- [x] Add `StatsFromInstanceSpec` pydantic model in `src/datarefinery/recipe/models.py`: `recipe: str` (path-or-name; v1 accepts a filesystem path string), `op_id: str`. Frozen.
- [x] Validator check (new or extension of an existing one): a `normalize` op's `params["stats_from_instance"]` and the op's `fit_source` field are mutually exclusive; exactly one must be set when the op is `normalize`. Added as numbered check 22 (`check_22_stats_from_instance_mutually_exclusive_with_fit_source`) and check 6 now short-circuits when `stats_from_instance` is set. *(Wired through to call sites: `tests/unit/test_validator.py`, `tests/integration/test_tabular_stub_smoke.py`, `tests/cli/test_validate_cmd.py`, and the three CLI-output integration tests bumped 21 → 22.)*
- [x] Modify the apply path so `params["stats_from_instance"]` skips the local fit. *(Implemented in `src/datarefinery/pipeline/stages/transformations.py::apply_transformations` rather than inside `NormalizeOp` itself — keeps the dispatch generic so any future fit-on-train op picks it up automatically; threaded `cache_root` in from `PipelineRunner` and added `_load_sibling_fitted` to materialize the sibling's `fitted_statistics/<op_id>/` as a `FittedValues` for the op's apply phase. The op handle stays unchanged.)*
- [x] Tests in `tests/plugins/image_classification/test_normalize_stats_from_instance.py` (7 tests): end-to-end eval recipe via `PipelineRunner` (sibling fit_stats persisted, no local fit on eval); byte-identical eval output across repeated runs; cross-recipe parity (imported-stats apply output matches a direct `normalize` apply with sibling-recorded mean/std); three resolver failure modes through the apply path (`SiblingInstanceNotFoundError`, `SiblingOpNotFoundError`, `SiblingStatsIncompatibleError`); mutual-exclusion validator rejects fit_source + stats_from_instance.
- [x] No version bump (phase-bundled with H.n.3).
- [x] Verify: 834/834 tests green (827 before H.n.2 + 7 new), ruff + ruff format + mypy clean.

**Out of Scope (H.n.2 specifically)**

- Documentation updates beyond the validator's new check number — H.n.3.

### Story H.n.3: v0.14.0 `stats_from_instance` docs + project-essentials + release [Done]

Third and final H.n child story. Ships v0.14.0 and documents the loose-coupling decision in three doc files.

Minor bump (v0.14.0). **Not cache-invalidating after all** — H.n.2's implementation chose an opaque-`params` shape rather than a new pydantic field on `TransformationOp`, so recipes that do not use `stats_from_instance` have identical canonical bytes pre- and post-upgrade. The H.n umbrella header's preemptive "cache-invalidating" label was overcautious; the canonical-hash pin at `tests/unit/test_canonical_hash_pin.py` holds without modification. CHANGELOG calls this out under "Notes."

**Tasks:**

- [x] `docs/specs/features.md` § FR-10 (Transformations) Behavior: new sub-section on `stats_from_instance` documenting the parameter shape, the four-scenario motivation (distribution-shift / A-B / cross-team / longitudinal evaluation), the resolver's most-recent-by-`created_at` lookup, and the loose-coupling pointer. § FR-10 Edge Cases: three failure-mode bullets (sibling-not-found, op_id-not-in-sibling, statistics-format-incompatible) plus a mutual-exclusion bullet (check 22). § FR-2 enumerated checks: count bumped 21 → 22 with check 22 description added. § FR-4 Edge Cases: bullet documenting the FR-ARCH-1 loose-coupling decision. § FR-6 Behavior: sub-point #5 (producer side: instance's library API exposes fitted stats for *other* recipes via `stats_from_instance`) and #6 (consumer side: imported stats are **read-through, not copied** — the materialized output of a consuming recipe has no `fitted_statistics/<op_id>/` for ops that import their stats). § FR-6 Edge Cases: bullet on materialize-time "sibling instance not found" error.
- [x] `docs/specs/tech-spec.md` § Key Component Design: new `cache.sibling_stats` sub-heading with resolver signature, lookup rules, three exception types, **dispatcher-vs-op-handle decision** (the `stats_from_instance` branch lives in `apply_transformations` so any future fit-on-train op picks it up by declaring the param in its `OperationSpec`), and the **read-through-not-copy** note. § Cross-Cutting Concerns > Caching: loose-coupling paragraph (sibling `recipe_hash` does NOT participate in consumer cache identity; tight coupling is a planned `schema_version`-bumped upgrade). § Data Models `TransformationOp` row: extended with `StatsFromInstanceSpec` reference + mutual-exclusion note. § Schema versioning: sentence acknowledging tight coupling as a future `schema_version` bump. § Package Structure: validator.py comment bumped 21 → 22. § `recipe.validator`: prose bumped 21 → 22.
- [x] `docs/specs/project-essentials.md`: new `### Sibling-instance dependencies are loose-coupled in v1` subsection — framed as **LLM-blunder reinforcement** (per the developer's clarification that essentials is LLM-context guidance, not the place to memorialize architecture decisions). Lists three tempting-but-wrong moves the LLM should refuse: don't mix sibling `recipe_hash` into consumer cache identity, don't add stale-warning, don't copy sibling stats locally. Architecture rationale lives in tech-spec.md / features.md.
- [x] `README.md`: no edit required (per the story).
- [x] `CHANGELOG.md`: `## [0.14.0]` "Added" section covering the H.n.1 resolver, the H.n.2 model + validator + apply-path integration, the dispatcher-vs-op-handle design choice, and the read-through-not-copy note. A "Loose-coupling semantics — read carefully" subsection spells out the user-managed-recompute consequence concretely (including the gotcha that downstream `clean` is required to force a re-materialize after upstream changes — because the consumer's own cache identity hasn't shifted). A "Notes" subsection records that the release is not cache-invalidating despite touching `recipe/`.
- [x] Bumped `pyproject.toml` and `src/datarefinery/__init__.py` to `0.14.0`.
- [x] Verify: 834/834 tests green, ruff + ruff format + mypy clean, canonical-hash pin holds unmodified.

**Out of Scope (H.n.3 specifically)**

- Same as H.n's umbrella out-of-scope: tight coupling, extending `stats_from_instance` to other fit-phase ops, stale-downstream linter.

### Story H.n.4: v0.14.1 CI bugfix — `[corruptions]` extras availability in tests [Done]

Patch release. Bug surfaced by CI for the v0.14.0 release (not introduced by H.n): `tests/plugins/image_classification/test_corruptions_vendored.py` does a module-top-level `from datarefinery.plugins.image_classification import _corruptions`, which transitively does `import cv2` / `import skimage`. CI's install step (`pip install -e .` + `pip install -r requirements-dev.txt`) never installs the `[corruptions]` extras, so pytest aborts at *collection time* with `ModuleNotFoundError: No module named 'cv2'` and no tests run. `test_generation_imagecorruptions.py` has the same problem one step deferred (the lazy import inside `imagecorruptions_apply` fires at *test execution* time) and would have failed identically if collection had reached it.

Latent since Story H.m.1; masked locally by an opportunistically-installed `opencv-python-headless` in the dev venv. The `[corruptions]` extras are an **end-user** optional install ("only execution requires them" per `features.md` FR-GEN-1 / H.m.3 release notes); but CI's job is to exercise every code path, so CI needs them installed.

Plan C (belt-and-suspenders): install `[corruptions]` extras in CI **and** add `pytest.importorskip("cv2")` at the top of both test modules so dev environments without the extras get clean skips rather than failures. The CI install ensures the corruption codepaths are actually exercised; the `importorskip` guard makes future regressions of this exact failure mode impossible without explicit removal.

Patch bump (v0.14.1) per Version Cadence (bugfix → patch).

**Tasks:**

- [x] Added `pytest.importorskip("cv2", reason=...)` after the `import pytest` line in `tests/plugins/image_classification/test_corruptions_vendored.py`. Gates the collection-time eager import of `_corruptions`.
- [x] Added the same `pytest.importorskip("cv2")` guard to `tests/plugins/image_classification/test_generation_imagecorruptions.py`. *(Sub-finding: ruff doesn't fire E402 after `pytest.importorskip`, so no `# noqa: E402` needed on the subsequent imports — ruff treats `importorskip` as init-like. The initial commit included unnecessary `# noqa` comments which ruff auto-fixed.)*
- [x] `.github/workflows/ci.yml`: install step changed from `pip install -e .` to `pip install -e ".[corruptions]"`; comment explains the exercise-every-codepath rationale and points at Story H.n.4.
- [x] `CHANGELOG.md`: `## [0.14.1]` "Fixed" section landed. Names the failure mode, the latent-since-H.m.1 framing, the two-part fix, and notes that the "friendly-error" mocked test still gets coverage in CI.
- [x] Bumped `pyproject.toml` and `src/datarefinery/__init__.py` to `0.14.1`.
- [x] Verified locally: 834/834 tests green, ruff + ruff format + mypy clean, canonical-hash pin holds unmodified.

**Out of Scope (H.n.4 specifically)**

- Reshaping the `[corruptions]` extras' optionality (e.g., promoting them to core dependencies) — they remain optional for end users; CI installs them as a CI policy, not a project policy.
- A separate "no-extras smoke" CI job that confirms `pip install ml-datarefinery` (no extras) still imports cleanly. Worth doing eventually as a release-gate guard; out of scope for a one-line CI bugfix.
- Adding `importorskip` to other files that may transitively pull cv2/skimage. The two failing files are the only ones that exercise the corruption codepath; other tests do not import `_corruptions` (directly or via the lazy path in `generation_imagecorruptions.py`).

### Story H.o: Architectural spike — aggressive-mode augmentation realization viability [Done]

Time-boxed architectural spike validating the design choices in the proposed FR-11 extension before H.p commits to them. Per-record-variant seeding under multi-worker execution and the Option A on-disk representation (record multiplication) are the two design choices the spike must confirm before the framework story (H.p) builds on them. Deliverable is documented findings, not shipping code. `horizontal_flip` is the exemplar — simplest realization, fewest variables. See the phase plan for the full design context: [phase-h-image-classification-extensions-2-plan.md](phase-h-image-classification-extensions-2-plan.md).

Three uncertainties to resolve:

1. **Per-record-variant seeding determinism.** Does the proposed `sha256(global_seed || op_id || record_id || variant_index)` scheme produce byte-identical augmented variants across `workers=1`, `workers=2`, and `workers=4`?
2. **On-disk representation (Option A: record multiplication).** Do `N × expansion` augmented records integrate cleanly with the existing dataset materialization layer? Do downstream consumers (validator, report, manifest) handle the multiplied record count without bespoke special cases?
3. **Pillow + numpy seeding composition.** Does Pillow's stochastic surface compose cleanly with explicit per-call seeded `numpy.random.default_rng`? Are there Pillow-internal randomness sources that bypass our seed?

No version bump (spike-only; bundled under the AUG release in H.s).

**Tasks:**

- [x] In a scratch worktree (or scratch branch), write a minimal stub `horizontal_flip` realizer that takes `(image_record, seed)` and emits N variants. Use Pillow + `numpy.random.default_rng(seed)`.
- [x] Implement per-record-variant seed derivation: `seed_for_variant = sha256(global_seed.to_bytes(8, 'big') + op_id.encode() + record_id_bytes + variant_index.to_bytes(4, 'big')).digest()[:8]`. Verify byte-identical seeds for the same `(global_seed, op_id, record_id, variant_index)` across repeated invocations.
- [x] Run a small end-to-end test: 10 input image records × `expansion=4` → 40 output records. Run under `workers=1/2/4`. Assert byte-identical instance directories across worker counts.
- [x] Sketch the on-disk record schema for aggressive mode: each augmented record carries `source_record_id: str` and `variant_index: int` metadata fields. Verify round-trip through the existing image-plugin dataset writer.
- [x] Verify Pillow's `Image.transpose(Image.FLIP_LEFT_RIGHT)` is fully deterministic (no Pillow-internal RNG); the only randomness is the per-variant coin flip we control.
- [x] Document findings inline in this story body: confirmed/refuted per uncertainty; recommended implementation patterns for H.p (RNG library choice; seed-derivation helper signature; metadata-field naming); blockers or open questions H.p must handle.
- [x] Decision: proceed with Option A + per-record-variant seeding as proposed, or identify the blocking issue and propose an alternative.
- [x] Tear down the scratch worktree. Do **not** commit any code in this story — H.p lands the production-grade implementation.

**Out of Scope**

- Implementing any of the four augmentation ops or the FR-11 framework changes. Those are H.p, H.q, H.r.
- Performance benchmarking. The determinism check is the spike's deliverable.
- Lazy-mode path. The current FR-11 passthrough is unchanged and doesn't need spike coverage.

**Findings** (recorded 2026-05-22; scratch script at `/tmp/dr-spike-ho/spike_realizer.py`, removed after the run)

1. **Per-record-variant seeding determinism — CONFIRMED.** The proposed formula `sha256(global_seed.to_bytes(8,"big") + op_id.encode() + record_id_bytes + variant_index.to_bytes(4,"big")).digest()[:8]` produced byte-identical materialized output (sha256 = `74bd0ade358bd40135ebd9af3fa5739439fc57fdbe4fb7e6f1260eaffd965fe7`) across `workers=1`, `workers=2`, `workers=4`, AND across a separate Python process invocation. Worker scheduling does not perturb the per-variant seed (depends only on `(global_seed, op_id, record_id, variant_index)`), and the fan-out → sort-by-`(source_record_id, variant_index)` → emit pattern yields a deterministic order independent of `ProcessPoolExecutor` completion order. The pure-function check `derive_variant_seed(42, "random_crop", "img_007", 2)` returned `16774609658038245661` on both invocations and a different value (`9695138196995935303`) for `variant_index=3` — pure and variant-discriminating.

2. **Option A on-disk representation (record multiplication) — CONFIRMED.** A 10-record × `expansion=4` run produced exactly 40 augmented records and round-tripped cleanly through `pipeline.runner._write_dataset` with **zero modifications to the writer**. `source_record_id: str` and `variant_index: int` are JSON-native and pass through `_coerce` unchanged; `variant_index` round-trips as `int`, not `str`. **Open question surfaced for H.p:** `_write_dataset._coerce` silently drops numpy `image` arrays (the writer was designed under the "image bytes resolve via source `path`" model — see `pipeline/runner.py:448-491`). Aggressively-augmented records have no meaningful source path. `generation_imagecorruptions.py` has the same constraint and currently lives with it. H.p must decide image-bytes persistence: write a sidecar (e.g. `dataset/<split>/<record_id>.png`) and add an `image_path` field, or persist image bytes inline via a new branch in `_coerce`. **This is not a blocker for the spike's recommendation but needs an explicit task in H.p.**

3. **Pillow + numpy seeding composition — CONFIRMED for `horizontal_flip`.** `Image.transpose(Image.FLIP_LEFT_RIGHT)` produced identical bytes across 100 repeated calls — no Pillow-internal RNG. The pattern that worked: derive seed → `numpy.random.default_rng(seed)` → draw the parameter (here, the coin-flip via `rng.integers(0, 2)`) → call Pillow with explicit parameters. Pillow never gets to choose anything stochastically. **Generalization caveat:** ops with stochastic Pillow surfaces must be verified case-by-case at implementation time. The H.q/H.r ops (`random_crop`, `horizontal_flip`, `color_jitter`, `random_erasing`) all admit this pattern — none requires a stochastic Pillow call. `imagecorruptions_apply` already established the same precedent (`generation_imagecorruptions.py:98-99`).

**Recommended implementation patterns for H.p**

- **Seed-derivation helper** — place in `augmentations/_realizer.py`, mirror the shape of existing `pipeline.workers.per_record_seed` so plugin authors recognize the contract:

  ```python
  def per_variant_seed(global_seed: int, op_id: str, record_id: str, variant_index: int) -> int:
      payload = (int(global_seed).to_bytes(8, "big") + op_id.encode("utf-8")
                 + str(record_id).encode("utf-8") + int(variant_index).to_bytes(4, "big"))
      return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
  ```

- **RNG library** — `numpy.random.default_rng(seed)`. Reuses the precedent set by `imagecorruptions_apply`. Plugin authors call `rng.integers(...)`, `rng.uniform(...)`, etc. to draw Pillow-call parameters; they never call Pillow's stochastic surfaces directly.
- **Metadata field naming** — `source_record_id: str` and `variant_index: int` at the **top level** of the record dict (not nested under a "metadata" sub-dict). Top-level placement is what makes the existing JSONL writer capture them without modification.
- **Variant `record_id`** — `f"{source_record_id}__v{variant_index}"` (or `_derive_output_record_id`-style hash analogous to `generation_imagecorruptions.py:50-53`). Variant record_ids are already unique and sortable, which means the reorder-by-record-id invariant in `pipeline.workers.run_parallel` extends naturally without code changes.

**Design simplification recommended for H.p's task list**

The story's current task says: *"Extend `src/datarefinery/pipeline/workers.py`: per-record seed derivation generalizes to per-record-variant. Reorder-invariant becomes `(record_id, variant_index)` tuples for aggressive expansion."*

The spike demonstrated this generalization is **not necessary**. The cleaner shape: keep `pipeline.workers.run_parallel` unchanged — it still reorders by parent `record_id`. The augmentations stage runs the per-record worker (which emits a *variant pack*), then performs a single fan-out + sort-by-`(source_record_id, variant_index)` inside `stages/augmentations.py`. The seed derivation lives in `augmentations/_realizer.py`, not in `pipeline.workers`. H.p should update its task list to scope `pipeline.workers` out of the change set; the stage-local fan-out preserves determinism with strictly less surface area touched.

**Decision: PROCEED with Option A + per-record-variant seeding as proposed.** All three uncertainties resolved positively. Two refinements recommended for H.p before it begins: (a) add an explicit task for image-bytes persistence (sidecar vs. inline) — the dataset writer was not designed for self-contained augmented records; (b) remove the `pipeline/workers.py` change from the H.p task list and locate the per-variant logic in `augmentations/_realizer.py` + the augmentations stage instead.

### Story H.p: FR-11 extension — `materialization: lazy \| aggressive` framework [Done]

Extends `AugmentationOp` to support two materialization modes per-op, building the framework H.q and H.r populate with concrete ops. The current FR-11 framing ("augmentations apply on-the-fly during training; they do not produce additional persisted records") becomes the **lazy** mode; the new **aggressive** mode lets DataRefinery materialize augmented records into the cached dataset deterministically. See FR-11 reframing in the phase plan: [phase-h-image-classification-extensions-2-plan.md](phase-h-image-classification-extensions-2-plan.md).

Recipe surface:

```yaml
Augmentations:
  - name: random_crop
    op: random_crop
    params: { size: 32, padding: 4, padding_mode: reflect }
    materialization: aggressive      # default: lazy
    expansion: 4                     # aggressive only; N variants per original record
    splits: [train]
    seed: 42
```

In lazy mode, behavior is unchanged from current FR-11: policy declared and persisted into the recipe + manifest + report, dataset unaugmented, ModelFoundry realizes per epoch. In aggressive mode, `pipeline/stages/augmentations.py` realizes `expansion` variants per record at materialization time; augmented records become peer records in the materialized dataset.

Design decisions (informed by H.o spike):
- **Materialization is per-op** (not per-section). A single `Augmentations` block can mix lazy and aggressive ops.
- **Option A on-disk representation:** record multiplication; augmented records are peer records carrying `source_record_id` and `variant_index` metadata.
- **Per-record-variant seeding:** existing determinism contract extends one level.

No version bump (bundled in H.s). Cache-invalidating: adds two new fields with defaults to `AugmentationOp`, perturbing canonical bytes of any recipe with `Augmentations`. Pre-prod invalidation acceptable per `project-essentials.md`; H.s release notes call it out.

**Tasks:**

- [x] Extend `AugmentationOp` in `src/datarefinery/recipe/models.py`: add `materialization: Literal["lazy", "aggressive"] = "lazy"` and `expansion: int = 1`. Frozen. Model-level validation: `expansion < 1` rejected; `expansion > 1` requires `materialization == "aggressive"`.
- [x] Create `src/datarefinery/plugins/image_classification/augmentations/__init__.py` (submodule init) and `src/datarefinery/plugins/image_classification/augmentations/_realizer.py` with Apache-2.0 headers. `_realizer.py` exposes shared aggressive-mode helpers: per-record-variant seed derivation, variant-emission loop, metadata tagging (`source_record_id`, `variant_index`).
- [x] Extend `src/datarefinery/pipeline/workers.py`: per-record seed derivation generalizes to per-record-variant. Reorder-invariant becomes `(record_id, variant_index)` tuples for aggressive expansion. Lazy mode unchanged.
- [x] Extend `src/datarefinery/pipeline/stages/augmentations.py`: lazy-mode preserves the current passthrough; aggressive-mode dispatches per-record to the op's realizer via `_realizer.py`, emitting `expansion` variant records per input.
- [x] Extend `src/datarefinery/reporting/report.py`: render augmentation policy mode-aware. Lazy declares the policy; aggressive also reports the expansion-multiplied record count in the per-split statistics summary.
- [x] Validator coverage: existing FR-2 check 5 (train-only) still applies; check 18 covers the new fields via plugin schemas. Surface the `expansion > 1 + lazy` rejection through the validator (relies on pydantic model-level validator).
- [x] Tests in `tests/recipe/test_augmentation_op_model.py`: model validation accepts both modes; rejects `expansion < 1`; rejects `expansion > 1` + `lazy`.
- [x] Tests in `tests/pipeline/test_augmentations_aggressive.py`: stub realizer (no real op yet); aggressive-mode produces `N x expansion` records with `source_record_id` and `variant_index` metadata; lazy-mode unchanged; workers=1/2/4 byte-identical.
- [x] Scoped doc updates:
  - [x] `docs/specs/features.md` § FR-11 (Augmentations): rewrite to document both lazy and aggressive modes; document `materialization` and `expansion` behavior; document the train-only invariant still applies (check 5); add edge-case bullets for `expansion < 1` and `expansion > 1 + lazy` rejection.
  - [x] `docs/specs/tech-spec.md` § Package Structure: add `augmentations/__init__.py` and `augmentations/_realizer.py`. § Cross-Cutting Concerns > Determinism: extend per-record seeding scheme description to include `variant_index`. § Data Models > Recipe model section table: extend the `AugmentationOp` row to include `materialization` and `expansion`.
- [x] Verify: tests green, ruff + ruff format + mypy clean. **Do not bump the version** — release lands in H.s.

**Out of Scope**

- The four concrete augmentation ops. Those are H.q and H.r.
- ModelFoundry dependency spec doc. H.s.
- Visualizations of augmented samples. H.u.

### Story H.q: Spatial augmentations — `random_crop` + `horizontal_flip` (lazy + aggressive) [Done]

Two image_classification augmentation ops sharing the spatial-transform pattern. Build on the FR-11 framework from H.p; emit augmented variants via the shared `_realizer.py` scaffolding.

- **`random_crop` (FR-AUG-1):** random spatial crop with optional pre-crop padding. Params: `size` (int or tuple), `padding` (default 0), `padding_mode` (`reflect`/`replicate`/`zero`/`constant`, default `reflect`).
- **`horizontal_flip` (FR-AUG-2):** random horizontal flip. Param: `p` (probability per sample, default 0.5).

Both implement both materialization modes. Lazy: op declared, no realization. Aggressive: realizer emits `expansion` variants per record, each seeded by `(global_seed, op_id, record_id, variant_index)`.

No version bump (bundled in H.s).

**Tasks:**

- [x] Create `src/datarefinery/plugins/image_classification/augmentations/random_crop.py` with Apache-2.0 header. Pydantic `RandomCropParams`: `size: int | tuple[int, int]`, `padding: int = 0`, `padding_mode: Literal["reflect", "replicate", "zero", "constant"] = "reflect"`. Frozen. Validation: positive size, non-negative padding.
- [x] Implement aggressive realizer: pad per `padding_mode`, then random crop to `size` using `numpy.random.default_rng(seed_for_variant)` for crop coordinates.
- [x] Create `src/datarefinery/plugins/image_classification/augmentations/horizontal_flip.py` with header. Pydantic `HorizontalFlipParams`: `p: float = 0.5` in `[0.0, 1.0]`. Frozen.
- [x] Implement aggressive realizer: per-variant `rng.random() < p` coin flip; `Image.transpose(Image.FLIP_LEFT_RIGHT)` when true.
- [x] Register both ops in `src/datarefinery/plugins/image_classification/__init__.py`.
- [x] Tests in `tests/plugins/image_classification/test_augmentations_random_crop.py`: lazy declares without realizing; aggressive emits `expansion` variants with correct shapes; padding modes apply; deterministic under workers=1/2/4 byte-identical.
- [x] Tests in `tests/plugins/image_classification/test_augmentations_horizontal_flip.py`: lazy declares; aggressive realizes; deterministic; probability convergence with large `expansion`.
- [x] Cross-recipe bit-identity test: identical recipe + inputs + seed produces byte-identical aggressive-mode instances.
- [x] Scoped doc updates:
  - [x] `docs/specs/features.md` § FR-11: list `random_crop` and `horizontal_flip` as available `image_classification` augmentation ops with their param schemas.
  - [x] `docs/specs/tech-spec.md` § Package Structure: add `random_crop.py` and `horizontal_flip.py`. § Data Models > Recipe model section table: reference `RandomCropParams` and `HorizontalFlipParams`.
- [x] Verify.

**Out of Scope**

- `color_jitter` and `random_erasing` — H.r.
- Visualizations of augmented variants — H.u.

### Story H.r: Appearance augmentations — `color_jitter` + `random_erasing` (lazy + aggressive) [Done]

Two augmentation ops sharing the appearance-perturbation pattern.

- **`color_jitter` (FR-AUG-3):** random color-space perturbations. Params: `brightness`, `contrast`, `saturation`, `hue` — each a float magnitude. Each enabled dimension applies a uniformly-random offset within `[-magnitude, +magnitude]`.
- **`random_erasing` (FR-AUG-4):** random rectangular region erasing (Zhong et al. 2020). Params: `p` (probability), `scale` (range of masked area as fraction of image), `ratio` (range of aspect ratio of the mask).

Both implement both materialization modes via the FR-11 framework.

No version bump (bundled in H.s).

**Tasks:**

- [x] Create `src/datarefinery/plugins/image_classification/augmentations/color_jitter.py` with Apache-2.0 header. Pydantic `ColorJitterParams`: `brightness: float = 0.0`, `contrast: float = 0.0`, `saturation: float = 0.0`, `hue: float = 0.0`. Frozen. Validation: each in `[0.0, 1.0]` except `hue` in `[0.0, 0.5]`.
- [x] Implement aggressive realizer: per-variant RNG samples each enabled dimension within `[-magnitude, +magnitude]`; apply via Pillow `ImageEnhance` (brightness/contrast/saturation) and HSV-space rotation (hue). Document the grayscale edge case (hue is a no-op on `< 3` channel images).
- [x] Create `src/datarefinery/plugins/image_classification/augmentations/random_erasing.py` with header. Pydantic `RandomErasingParams`: `p: float = 0.5`, `scale: tuple[float, float] = (0.02, 0.33)`, `ratio: tuple[float, float] = (0.3, 3.3)`. Frozen. Validation: `0 <= p <= 1`; sane `scale` and `ratio` ranges.
- [x] Implement aggressive realizer: per-variant `rng.random() < p` decides whether to erase; sample area fraction from `scale` and aspect ratio from `ratio`, compute rectangle bounds, fill with mean pixel value.
- [x] Register both ops.
- [x] Tests in `tests/plugins/image_classification/test_augmentations_color_jitter.py`: lazy declares; aggressive realizes; deterministic; per-channel magnitudes within bounds.
- [x] Tests in `tests/plugins/image_classification/test_augmentations_random_erasing.py`: lazy declares; aggressive realizes; erased rectangles fall within image bounds and respect `scale`/`ratio`.
- [x] Scoped doc updates:
  - [x] `docs/specs/features.md` § FR-11: list `color_jitter` and `random_erasing` with their param schemas. Add an edge-case bullet for `color_jitter` on grayscale images.
  - [x] `docs/specs/tech-spec.md` § Package Structure: add `color_jitter.py` and `random_erasing.py`. § Data Models > Recipe model section table: reference `ColorJitterParams` and `RandomErasingParams`.
- [x] Verify.

**Out of Scope**

- Visualizations of augmented variants — H.u.

### Story H.r.1: Aggressive-mode runner wiring + temporary fail-loud guard [Done]

Wires `pipeline.stages.augmentations.realize_aggressive_split` into the runner so aggressive ops actually fan out the train split during materialization. The H.p framework story added the realizer scaffolding and H.q/H.r added concrete ops, but the runner currently calls only `collect_augmentation_policies` — a recipe declaring `materialization: aggressive` produces a manifest claiming aggressive expansion while the dataset remains unchanged (silent semantic failure).

H.r.1 lands the wiring AND a defensive guard so a user declaring aggressive in a real recipe discovers the persistence gap loudly rather than silently producing metadata-only records. H.r.2 closes the persistence gap and removes the guard.

This is the first of two cleanup stories closing the gaps the H.o spike surfaced and the H.p/H.q/H.r framework intentionally left for later. Originally raised at the H.p approval gate; tracked here per the developer's "add as H.r.1/H.r.2" direction.

No version bump (bundled in H.s).

**Tasks:**

- [x] In `src/datarefinery/pipeline/runner.py`, locate the augmentations-stage call site (currently invokes only `collect_augmentation_policies`). Call `realize_aggressive_split` for the train split immediately BEFORE policy capture, so the manifest still records the declared policy verbatim while the dataset receives the multiplied record set. Ops apply in recipe-declared order. The realizer registry is plugin-supplied (see H.q registration).
- [x] Plumb the resulting record list back into the per-split records dict so `_write_dataset` receives the multiplied train records. `manifest.record_counts["train"]` reflects the post-augmentation count via the existing count-records path.
- [x] Add a defensive guard at materialize time: if any `AugmentationOp` declares `materialization=aggressive`, the runner raises `MaterializeError("aggressive-mode augmentation persistence pending Story H.r.2; the recipe is accepted but cannot materialize until persistence lands")` BEFORE invoking `realize_aggressive_split`. The wiring is still exercised by unit tests that bypass the guard so the runner integration is covered, but real recipes fail loud.
- [x] Validator surface: `recipe.validator` adds a check (warning, not fail) that surfaces the same "pending H.r.2" condition so `validate` callers see the limitation before reaching `materialize`. Both the warning and the runner guard are removed in H.r.2.
- [x] Tests:
  - [x] `tests/integration/test_runner.py`: runner integration — train split with one aggressive op produces the multiplied record count when the guard is patched out (validates the wiring directly).
  - [x] Runner raises `MaterializeError` containing "pending Story H.r.2" when an aggressive op is declared and the guard is in place.
  - [x] `tests/unit/test_validator.py`: warning surfaced for aggressive recipes; lazy-only recipes get no warning.
- [x] Scoped doc updates:
  - [x] `docs/specs/features.md` § FR-11: append a short "Status" subsection noting aggressive wiring lands in H.r.1 with a temporary guard; persistence + ungating lands in H.r.2. Remove the subsection in H.r.2.
- [x] Verify: tests green, ruff + ruff format + mypy clean. **Do not bump the version** — release lands in H.s.

**Out of Scope**

- Image-bytes persistence — H.r.2.
- ModelFoundry consumption of aggressive variants — H.s.

### Story H.r.2: Image-bytes persistence for aggressive variants + ungating [Done]

Closes the loop on aggressive-mode augmentation: each variant's image bytes are persisted as a per-record sidecar PNG under `dataset/<split>/images/<record_id>.png`, and the JSONL record carries `image_path: str` pointing at the sidecar. Removes the H.r.1 runner guard and validator warning so aggressive recipes materialize end-to-end into a complete, self-contained instance ModelFoundry (or any consumer) can read without referring back to the source images.

Resolves the H.o spike's open question about Option A persistence — chosen path is sidecar PNGs over inline base64 because (a) Pillow is already a dependency and handles PNG encode natively, (b) JSONL stays human-readable for debugging, (c) the on-disk layout matches how the image plugin already handles writes elsewhere.

This is the second of two cleanup stories closing the H.p/H.q/H.r gaps.

No version bump (bundled in H.s).

**Tasks:**

- [x] Extend `pipeline.runner._write_dataset` (or add a sibling `_write_image_sidecars` helper invoked from the runner) to detect records carrying aggressive-mode metadata (`source_record_id` + `variant_index` + a numpy `uint8` `image` array). For those records, encode the image as PNG via Pillow and write to `dataset/<split>/images/<record_id>.png`. The runner replaces the `image` field with `image_path: str` (relative to the dataset dir) BEFORE the JSONL serialization runs, so `_coerce` no longer needs to drop the bytes.
- [x] Non-aggressive records keep the existing "image bytes resolve via source `path`" behavior. Sidecars are aggressive-only — document the distinction in the writer's docstring.
- [x] Cache layout: sidecars live under the materialized instance's dataset dir, so they're naturally covered by the existing cache-identity contract (the materialized output IS the cached output). No separate cache key surface; no `cache.layout` change required unless we want a helper for the new `images/` subdirectory.
- [x] Remove the H.r.1 runner guard (`MaterializeError "pending Story H.r.2"`). Remove the validator warning. Both surfaces flip to fully-supported.
- [x] Tests:
  - [x] `tests/integration/test_runner.py`: end-to-end materialize with an aggressive `horizontal_flip` recipe produces sidecar PNGs at the expected paths; `train.jsonl` lines carry `image_path` not `image`.
  - [x] Round-trip: read a sidecar PNG back, assert byte-equality with the in-memory variant produced by the realizer.
  - [x] Determinism: re-running with the same recipe + seed produces byte-identical sidecar PNGs (FR-3 + FR-4 contract still holds).
  - [x] Lazy-only recipe: no sidecars written; existing behavior preserved.
- [x] Scoped doc updates:
  - [x] `docs/specs/features.md` § FR-11: remove the "Status: pending H.r.2" subsection added in H.r.1. Document the sidecar PNG output, the `image_path` field, and the aggressive-vs-non-aggressive persistence distinction.
  - [x] `docs/specs/tech-spec.md` § Data layout (instance directory tree): document `dataset/<split>/images/<record_id>.png` for aggressive-mode instances.
- [x] Verify.

**Out of Scope**

- Compression/quality tuning of PNGs. Default Pillow settings.
- A "preserve original" tag for aggressive records — currently aggressive replaces originals. If needed, separate story.
- ModelFoundry consumption tests — H.s.

### Story H.s: v0.15.0 AUG release — ModelFoundry dependency spec + cross-cutting docs sweep + release [Planned]

Release story for the AUG bundle. Three deliverables: (a) create `docs/specs/modelfoundry/dependency-spec.md` (the cross-repo contract document ModelFoundry consumers bind against); (b) cross-cutting docs sweep across `features.md`, `tech-spec.md`, `README.md` for drift accumulated during H.p–H.r; (c) CHANGELOG, version bump to v0.15.0, Future-section cleanup.

Minor bump (v0.15.0) — new features (FR-11 framework + four augmentation ops). Cache-invalidating for any recipe declaring `Augmentations` ops (new `materialization` and `expansion` defaults perturb canonical bytes). Pre-prod invalidation acceptable per `project-essentials.md` § "Cache identity is the reproducibility contract" pre-production rules; user re-materializes once after upgrade.

**Tasks:**

- [ ] Create `docs/specs/modelfoundry/` directory.
- [ ] Create `docs/specs/modelfoundry/dependency-spec.md`. Sections:
  - **Overview** — documented cross-repo contract surface for ModelFoundry and other downstream consumers.
  - **Recipe-side contract** — `Augmentations` section schema with all four ops + param schemas; `materialization` and `expansion` semantics.
  - **Materialized dataset on-disk layout** — directory structure; aggressive-mode record-multiplication shape with `source_record_id` and `variant_index` metadata.
  - **Manifest fields** ModelFoundry binds against — `schema_version`, `plugin`, `plugin_version`, `record_counts`, `variant`, `seed`.
  - **Report subsections** — augmentation policy summary; `drift.json` schema (pointer to FR-15).
  - **Cache-identity contract** — canonical bytes include all recipe fields with defaults; bumping `schema_version` is the deliberate-invalidation lever; non-bumped releases preserve cache.
  - **Schema-version coordination policy** — ModelFoundry tracks DataRefinery's `SUPPORTED_SCHEMA_VERSIONS`; consuming a recipe with a future schema version is a hard error on ModelFoundry's side.
  - **Forward-compatibility expectations** — ModelFoundry should detect recipes declaring unknown ops and fail with a clear "unknown op" error.
  - **Failure modes ModelFoundry should detect** — stale fitted statistics; missing required fields; schema-version mismatch.
  - **Versioning and adoption** — DataRefinery ships forward-declared contracts; ModelFoundry adopts on its own schedule; not a precondition.
- [ ] Cross-cutting docs sweep:
  - [ ] `docs/specs/features.md`: verify all four new augmentation ops are documented in § FR-11; cross-reference `dependency-spec.md` from § FR-11 and § FR-15.
  - [ ] `docs/specs/tech-spec.md`: verify all new augmentation files appear in § Package Structure; § Data Models consistent with the new `AugmentationOp` shape.
  - [ ] `README.md` § Plugin model: existing "etc." covers the new ops; no edit needed there. § CLI verbs table: **verify the validate row's "Schema + N enumerated static logical checks" count matches features.md's actual enumerated check count** (this sub-bundle adds no new top-level checks, but the count is currently drifted — features.md ends at check 22 while README still says 21 from H.n's release; fix to whatever features.md actually enumerates at v0.15.0). Other CLI-verb table rows: unchanged.
  - [ ] `docs/guides/recipe-authoring.md` (if present and current): add a short section on the lazy vs aggressive trade-off; mention `dependency-spec.md`.
- [ ] `docs/specs/project-essentials.md`: append a new `###` subsection (placed after § "Sibling-instance dependencies are loose-coupled in v1") titled "Recipe / manifest / report shape changes need a cross-repo coordination check." Content: name the three external contract surfaces (recipe model in `src/datarefinery/recipe/models.py`; manifest schema; report subsections `report.md` + `drift.json`); name `docs/specs/modelfoundry/dependency-spec.md` as the authoritative cross-repo contract doc; specify the "before changing field name / dropping field / changing emitted-bytes default / renaming manifest key / restructuring report subsection, check `dependency-spec.md` first" rule; list three tempting-LLM-mistakes-to-refuse (silent field removal "because no internal callers"; recipe field rename without `schema_version` bump + dependency-spec.md update; treating drift.json's "unstable until production release" framing as license to skip dependency-spec.md updates pre-prod). Append-only — do not rewrite or reorder existing project-essentials sections.
- [ ] `CHANGELOG.md`: new `## [0.15.0]` "Added" section. Sub-sections: FR-11 framework (lazy/aggressive), four augmentation ops, ModelFoundry dependency spec. **Prominent callout:** pre-prod cache invalidation — recipes with `Augmentations` ops will re-materialize on first run after upgrade.
- [ ] Remove the `FR-AUG-1..4 augmentation policies` sub-bullet from the `## Future` entry "Image-classification plugin: additional capabilities deferred from Phase H sub-bundle." Other sub-bullets remain.
- [ ] Bump `pyproject.toml` and `src/datarefinery/__init__.py` to `0.15.0`.
- [ ] Verify: full test suite green; ruff + ruff format + mypy clean. Canonical-hash pin: update if the pinned fixture recipe uses `Augmentations`.
- [ ] Release-prep: verify `pip install ml-datarefinery==0.15.0` succeeds in a clean Python 3.12 venv per Acceptance Criterion 12; manual check per `docs/guides/releasing.md`.

**Out of Scope**

- VIZ bundle work — H.t–H.x.
- ModelFoundry adoption coordination. Forward-declared; ModelFoundry adopts on its own schedule.
- Promoting `dependency-spec.md` to an immutable stability contract. Pre-prod the spec may evolve as ModelFoundry adoption surfaces gaps; post-prod, it becomes a stability contract.

### Story H.t: FR-VIZ-1 `pixel_distribution` [Planned]

Per-channel pixel-value histograms across a named split, rendered as a PNG. Reporting-mode visualization persisted to `report/visualizations/`. See FR-VIZ-1 in [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

Pixel-value distributions surface the effect of normalization, casting, and pixel-space transformations in a way that record-count or class-distribution histograms cannot. Comparing pre- and post-normalize distributions makes the centering-and-scaling effect numerically visible — useful for debugging normalization parameters, documentation, and reviewing what a pipeline did to its inputs.

No version bump (bundled in H.x).

**Tasks:**

- [ ] Create `src/datarefinery/plugins/image_classification/visualizations/__init__.py` (submodule init).
- [ ] Create `src/datarefinery/plugins/image_classification/visualizations/_render.py` with Apache-2.0 header. Shared Matplotlib helpers: figure setup with deterministic DPI; PNG output to `report/visualizations/`; deterministic file naming.
- [ ] Create `src/datarefinery/plugins/image_classification/visualizations/pixel_distribution.py` with header. Pydantic `PixelDistributionParams`: `bins: int = 64`, `splits: list[str]` (non-empty; which splits to render).
- [ ] Implement: per requested split, compute per-channel histograms (R/G/B) and render 3 subplots in a single figure. Output: `pixel_distribution_<split>.png` per split.
- [ ] Register op in `src/datarefinery/plugins/image_classification/__init__.py`.
- [ ] Tests in `tests/plugins/image_classification/test_visualizations_pixel_distribution.py`: render against a synthesized fixture image set; assert PNG exists per split; figure has 3 subplots.
- [ ] Scoped doc updates:
  - [ ] `docs/specs/features.md` § FR-13 (Visualizations): list the new op with param schema and reporting-mode behavior.
  - [ ] `docs/specs/tech-spec.md` § Package Structure: add `visualizations/__init__.py`, `_render.py`, and `pixel_distribution.py` under `plugins/image_classification/`.
- [ ] Verify.

**Out of Scope**

- `augmented_sample_grid` (H.u), `corruption_severity_grid` (H.v), `severity_ladder` (H.w).
- Exploration-mode rendering. This op is reporting-only.

### Story H.u: FR-VIZ-2 `augmented_sample_grid` (depends on H.r) [Planned]

A grid showing `n_base` held-out base images, each rendered `n_variants` times with the recipe's declared augmentation policy applied with `n_variants` different seeds. See FR-VIZ-2 in [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

Augmentation policies are non-materialized in lazy mode; without a visualization, the policy exists only as text and params, and nobody reading the recipe or report sees what the augmentations actually do to images. `augmented_sample_grid` realizes a small deterministic, seeded sample into the report so the policy is visible as concrete output.

**Mode-aware implementation:**
- **Aggressive mode:** augmented variants are already in the materialized dataset. The viz samples `n_base × n_variants` records by `(source_record_id, variant_index)`.
- **Lazy mode:** dataset is unaugmented. The viz picks `n_base` base records, realizes `n_variants` augmented variants inline using the same `_realizer.py` code paths. The realized variants are rendered into the visualization only — not persisted into the dataset.

Depends on H.r (aggressive-mode realizers).

No version bump (bundled in H.x).

**Tasks:**

- [ ] Create `src/datarefinery/plugins/image_classification/visualizations/augmented_sample_grid.py` with Apache-2.0 header. Pydantic `AugmentedSampleGridParams`: `n_base: int` (positive), `n_variants: int` (positive), `seed: int | None = None`.
- [ ] Implement: detect each declared `Augmentations` op's materialization mode. For aggressive ops, query the materialized dataset for `n_base` `source_record_id` values and their first `n_variants` variants. For lazy ops, realize `n_variants` variants inline via `_realizer.py` seeded with the op's seed + this viz's `seed`.
- [ ] Render: `n_base` rows × `n_variants` columns grid. Output: `augmented_sample_grid_<op_name>.png` per declared augmentation op.
- [ ] Register op.
- [ ] Tests in `tests/plugins/image_classification/test_visualizations_augmented_sample_grid.py`: render against an aggressive-mode recipe; render against a lazy-mode recipe; assert grid layout matches `n_base × n_variants`; deterministic against fixed seed.
- [ ] Scoped doc updates:
  - [ ] `docs/specs/features.md` § FR-13: list this op; document the mode-aware behavior.
  - [ ] `docs/specs/tech-spec.md` § Package Structure: add `augmented_sample_grid.py`.
- [ ] Verify.

**Out of Scope**

- Variant-by-variant exploration UI. The grid is a snapshot.
- Cross-op grids (e.g., `random_crop` and `color_jitter` chained on the same record). Each op gets its own grid; chained-augmentation visualization is a Future enhancement.

### Story H.v: FR-VIZ-3 `corruption_severity_grid` [Planned]

A K-corruption × L-severity grid showing the same set of base images under each (corruption, severity) combination. See FR-VIZ-3 in [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

The output of a corruption-generation pipeline (FR-GEN-1) is otherwise a flat collection of records tagged with corruption and severity metadata. A 2-D grid laying out the two metadata dimensions makes the corruption space visible at a glance — sanity-checking that each corruption type produces visually distinct output, documenting the robustness evaluation's coverage.

Depends on the `[corruptions]` extras shipped in H.m. Uses the same lazy-import pattern as `generation_imagecorruptions.py` so the viz remains importable only when extras are installed.

No version bump (bundled in H.x).

**Tasks:**

- [ ] Create `src/datarefinery/plugins/image_classification/visualizations/corruption_severity_grid.py` with Apache-2.0 header. Module-level guard raises `ImportError` with install-pointer (`pip install 'ml-datarefinery[corruptions]'`) when `cv2` or `imagecorruptions` is missing.
- [ ] Pydantic `CorruptionSeverityGridParams`: `n_images: int` (positive), `corruption_types: list[str]` (non-empty), `severities: list[int]` (each in 1..5).
- [ ] Implement: select `n_images` base records; apply each `(corruption_type, severity)` combination; render as `len(corruption_types)` × `len(severities)` grid. Output: `corruption_severity_grid.png`.
- [ ] Recipe-validation hook: when extras importable, validate `corruption_types` against `imagecorruptions.get_corruption_names()`; defer with clear error at materialize time when extras absent.
- [ ] Register op.
- [ ] Tests with `pytest.importorskip("cv2", reason="...")` per the H.n.4 pattern: render with 2 corruptions × 3 severities × 4 images; verify grid layout.
- [ ] Scoped doc updates:
  - [ ] `docs/specs/features.md` § FR-13: list this op; note `[corruptions]` extras requirement.
  - [ ] `docs/specs/tech-spec.md` § Package Structure: add `corruption_severity_grid.py`.
- [ ] Verify.

**Out of Scope**

- `severity_ladder` (H.w).
- Combined grids spanning multiple base images and multiple corruption types as a single tiled figure.

### Story H.w: FR-VIZ-4 `severity_ladder` [Planned]

`n_examples` example images, each rendered at every severity of a single corruption type, arranged as a ladder (one row per image, one column per severity). See FR-VIZ-4 in [phase-h-datarefinery-feature-recommendation.md](phase-h-datarefinery-feature-recommendation.md).

Complements `corruption_severity_grid` by isolating the severity dimension. Useful when documenting a single corruption type's behavior across severity levels without the visual noise of other corruption types in the same figure.

Depends on the `[corruptions]` extras (same as H.v).

No version bump (bundled in H.x).

**Tasks:**

- [ ] Create `src/datarefinery/plugins/image_classification/visualizations/severity_ladder.py` with Apache-2.0 header. Same extras-guard pattern as H.v.
- [ ] Pydantic `SeverityLadderParams`: `n_examples: int` (positive), `corruption_type: str` (non-empty).
- [ ] Implement: select `n_examples` base records; apply `corruption_type` at all 5 severities to each; render as `n_examples` rows × 5 columns. Output: `severity_ladder_<corruption_type>.png`.
- [ ] Recipe-validation: validate `corruption_type` against the H-D vocabulary when extras installed; defer with clear error otherwise.
- [ ] Register op.
- [ ] Tests with `pytest.importorskip("cv2", reason="...")`: render with 4 example images × 5 severities of `gaussian_noise`.
- [ ] Scoped doc updates:
  - [ ] `docs/specs/features.md` § FR-13: list this op; note `[corruptions]` extras requirement.
  - [ ] `docs/specs/tech-spec.md` § Package Structure: add `severity_ladder.py`.
- [ ] Verify.

**Out of Scope**

- Multi-corruption ladders. Use `corruption_severity_grid` for that.

### Story H.x: v0.16.0 VIZ release — cross-cutting docs sweep + release [Planned]

Release story for the VIZ bundle. Two deliverables: cross-cutting docs sweep + CHANGELOG section + version bump + Future-section cleanup.

Minor bump (v0.16.0) — new features (four reporting-mode visualization ops). Cache-invalidating only for recipes that declare one of the four new viz ops; recipes that don't are unaffected. Pre-prod invalidation acceptable.

**Tasks:**

- [ ] Cross-cutting docs sweep:
  - [ ] `docs/specs/features.md` § FR-13: verify all four new viz ops are documented; cross-reference the new files in tech-spec.md.
  - [ ] `docs/specs/tech-spec.md` § Package Structure: verify the four new viz files plus `_render.py` and the submodule `__init__.py` appear. § Data Models > Recipe model section table: extend the `VisualizationOp` row to reference the four new param models.
  - [ ] `README.md`: no edit needed (Plugin model "etc." covers the new ops; CLI verb table unchanged).
- [ ] `CHANGELOG.md`: new `## [0.16.0]` "Added" section listing the four new viz ops; note `corruption_severity_grid` and `severity_ladder` require the `[corruptions]` extras shipped in H.m.
- [ ] Remove the `FR-VIZ-1..4 reporting visualizations` sub-bullet from the `## Future` entry. Other sub-bullets remain.
- [ ] Bump `pyproject.toml` and `src/datarefinery/__init__.py` to `0.16.0`.
- [ ] Verify: tests green, ruff + ruff format + mypy clean. Canonical-hash pin unchanged (pinned fixture should not use the new viz ops).
- [ ] Release-prep: verify `pip install ml-datarefinery==0.16.0` succeeds in a clean venv.

**Out of Scope**

- ModelFoundry-related work — already shipped in H.s.
- Further visualization ops beyond FR-VIZ-1..4.

---

## Future

<!--
This section captures items intentionally deferred from the active phases above:
- Stories not yet planned in detail
- Phases beyond the current scope
- Project-level out-of-scope items
The `archive_stories` mode preserves this section verbatim when archiving stories.md.
-->

- **Image plugin tasks beyond classification** (detection, segmentation) — accommodated by the plugin interface, no v1 implementation per concept.md/features.md.
- **Tabular plugin: full operation implementations** — v1 ships a stub only; full implementation is post-v1.
- **Text plugin: full operation implementations** — v1 ships a stub only; full implementation is post-v1.
- **Recipe inheritance and multi-file composition** — variants suffice for v1; deferred per concept.md non-goals.
- **Resume-from-stage during materialization** — atomic temp-then-promote is the v1 failure model; resume support is post-v1.
- **`init` for non-image categories** — deterministic scaffolder is image-only in v1.
- **Inter-run concurrency: file-lock-based protocol** — pre-production serializes externally; the post-production protocol designed-for in cache layout is implemented post-v1.
- **Cache layout migration tooling (`clean --upgrade`)** — post-production cache-layout versioning + migration guide; v1 documents pre-prod invalidation semantics only.
- **Hard performance targets and benchmarking suite** — v1 is reactive; stories set targets when representative workloads expose problems.
- **Native Windows first-class support** — WSL2 is the recommended Windows path in v1.
- **Plugin sandboxing** — plugins run in-process, unsandboxed in v1; sandboxing is a post-v1 trust-boundary upgrade.
- **Image-classification plugin: additional capabilities deferred from Phase H sub-bundle** — see [`phase-h-datarefinery-feature-recommendation.md`](phase-h-datarefinery-feature-recommendation.md) for full specifications:
  - FR-AUG-1..4 augmentation policies (`random_crop`, `horizontal_flip`, `color_jitter`, `random_erasing`) — non-materialized policies forwarded to ModelFoundry's framework adapter.
  - FR-VIZ-1..4 reporting visualizations (`pixel_distribution`, `augmented_sample_grid`, `corruption_severity_grid`, `severity_ladder`).
  - FR-ARCH-1 tight coupling — sibling `recipe_hash` participating in the current recipe's cache identity, so re-materializing upstream auto-invalidates downstream. The Phase H sub-bundle shipped FR-TRANS-1 with loose coupling; tight coupling is the follow-up needed for multi-team or longitudinal workflows.
  - Generic record-tagging primitive — factor FR-FILTER-1's bespoke `label` / `exclude_already_labeled` params into a shared mechanism multiple filter ops can use.
- **Default-change discipline tooling for cache-identity stability** — expand the canonical-hash pinning test suite to cover multiple fixture recipes with different default-coverage profiles, so any change to a pydantic field default (anywhere in the recipe model graph) trips at least one pin and forces the developer to either revert or bump `schema_version`. Add an optional pre-commit / CI hook that diffs pydantic field defaults against `main` and requires a `schema_version` bump or an explicit "non-semantic default change" acknowledgement in the commit message. End-state invariant: cache invalidations are always deliberate (acknowledged at change time, announced in release notes); never silent. Plan as production-readiness work.
