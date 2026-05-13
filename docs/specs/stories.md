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

Small, contained refinements to the v1 feature surface and post-release fixes. Each story is scoped to one user-visible capability or one focused fix so versions can ship independently.

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
- [x] **Memory update.** Rewrite `project_pypi_deferred.md` (and its `MEMORY.md` index line) from "deferred" → "PyPI distribution name is `ml-datarefinery`; first publish is v0.9.1 via `.github/workflows/publish.yml`." Keep the historical reason in the body so a future LLM understands why the distribution name diverges from the import name.
- [x] **No canonical-hash shift.** `Recipe` does not contain the distribution name. Confirm `test_canonical_hash_pin` still passes without an update.
- [x] **Developer-side setup (out-of-band, before first publish).** Listed here so future readers can verify the workflow's preconditions, not as LLM-executable tasks:
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
