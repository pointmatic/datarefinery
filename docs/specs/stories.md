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
