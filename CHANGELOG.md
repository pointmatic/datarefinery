# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Subphase J-1 — Audio classification (phase-bundle; ships at the Story J.w release)

- **Audio input sources + decode (Story J.p).** New `audio_classification` input
  loader behind the `[audio]` optional extra (`pip install
  'ml-datarefinery[audio]'`; librosa + transitive soundfile). Two source kinds
  mirror the image ones — `audio_folder` (class-subdir labels) and `audio_flat`
  (+`label_from` `by_id`/`by_row_order`, or `unlabeled: true`) — and the loader
  **decodes** each clip with librosa, resampling to the source's required
  `target_sample_rate`, emitting `{record_id, sample_array, sample_rate,
  path[, label]}` (mono float32). Decode is deterministic; the source content
  hash covers audio bytes (+ manifest bytes for `audio_flat`). `target_sample_rate`
  stays **required** (no default — the canonical rate is an explicit
  author-written value per the no-implicit-defaults rule; superseding the J.p
  draft's "default 16000"). librosa is imported lazily so the plugin stays
  importable without the extra. CI installs `[corruptions,audio]` to exercise the
  decode path. `recipe-authoring.md` § Input gains an Audio sources subsection.


re-founds DataRefinery's cache identity on a **segmented** model with
**per-segment versioning**, and lands the **no-implicit-defaults** discipline,
the **`overlays`** generalization of `variants`, and the sanctioned
**`extensions`** namespace. Segmentation is an *internal* partition — the recipe
stays **flat on disk**, so no recipe edits are required.

> **⚠️ One-time pre-1.0 mass cache invalidation.** This release changes the
> canonical-bytes algorithm (flat → segmented hash) and, for recipes that
> relied on an op-parameter default, the canonical bytes themselves. **Every
> existing materialized instance is now stale and re-materializes once** —
> potentially hours of recompute per recipe×input, multiplied across every
> user. This is acceptable *now* (pre-1.0) and deliberately prohibitive
> post-1.0 (spike memo § 8 / design memo § 8). It is the **single planned
> invalidation** that buys per-segment *scoped* invalidation thereafter: after
> this, an audio-plugin change can never invalidate an image recipe's cache.
> Action: re-run `materialize`; no recipe edits needed.

### Breaking

- **Cache invalidation (one-time, pre-1.0).** Segmented identity (J.n.3) +
  no-implicit-defaults (J.n.4) shift `recipe_hash` / canonical bytes; every
  instance re-materializes once. Rides a single `schema_version` 2 → 3 bump
  (loader `(2, 3)` bootstrap migration); no release sits between the two
  stories. See the detail bullets below.

### Added

- **Segmented canonical recipe identity** — four identity segments
  (`core` / `plugin:<name>` / `overlays` / `extensions`); per-segment SHA-256
  digests combined with `join_stable` (J.n.3).
- **Per-segment versioning + migration registry** — independent per-segment
  version axes, a `(segment, from, to)`-keyed `SEGMENT_MIGRATIONS` registry
  replayed on the loader read path, and structural era-detection keyed off the
  flat `schema_version` (J.n.7).
- **Per-segment canonical-hash pin-test discipline** — `test_segment_pin_hashes.py`
  pins each segment's digest; an unexpected move is a blocking CI failure that
  forces a conscious per-segment bump + migration (J.n.7).
- **Sanctioned `extensions` namespace** — `extensions: {<namespace>: {<key>:
  <value>}}` for experimental, plugin-consumed parameters; `extra="forbid"`
  relaxed only inside; validator check 28 refuses undeclared keys; additive to
  identity (J.n.6).

### Changed

- **Recipe model refactored into segments** (internal partition; recipe stays
  flat on disk — J.n.3).
- **`variants` → first-class `overlays`** — repeatable `--overlay`,
  last-writer-wins; `manifest.variant` → `manifest.overlays: list[str]`
  (manifest schema → v2); hash-neutral (J.n.5).
- **`ParameterSpec` drops implicit defaults** — op params are `required` or
  mode-selecting optional; recommended values move to
  `Plugin.recommended_params`, emitted into recipe text by the scaffolder
  (J.n.4).
- **`Plugin` protocol** gains required `recommended_params` (J.n.4) and
  `extension_keys` (J.n.6) members.

### Cross-repo coordination

- Segmented identity + per-segment versioning + no-implicit-defaults adopted as
  the **cross-tool-family standard** (spike memo § 10). The MF/NbF
  vendor-dependency-specs and `project-essentials.md` are updated to pin it
  (J.n.8). ModelFoundry/NbFoundry adopt in their own repos (developer-owned).

### Removed

- **The global-umbrella recipe versioning model** — replaced by per-segment
  versions (J.n.7). *Note:* the flat `recipe.schema_version` field **remains on
  disk** as the era marker and the consumer-facing coordination counter; what is
  gone is the single global counter as the *only* invalidation axis.
- **`ParameterSpec(default=…)`** — the implicit-default field is removed; a CI
  guard fails if it is reintroduced (J.n.4).
- **Future entry "Default-change discipline tooling for cache-identity
  stability"** — subsumed by J.n.7's per-segment pins + the no-defaults guard.
  *(The Future "plugin-pluggable validator reserved-set hook" entry is **not**
  removed — J.n.1 Q6 folded the decision into the bundle, but the implementation
  was not built in J.n.7; it remains a tracked follow-up.)*

### Fixed

- **Coverage config** — bare `...` stub bodies (Protocol / abstract / overload
  placeholders) are now excluded from coverage (`[tool.coverage.report]
  exclude_lines`), so adding a multi-line `Plugin` protocol method no longer
  drops `plugins/base.py` below the core-invariant 95% gate. (Build/test config
  only; no runtime impact.)

### Notes

- Subphase J-1 audio (Stories J.o–J.w) was paused through this release and
  resumes on the segmented foundation.
- The Q8 vertical stage-reuse axis was declined for this bundle; `prefix_hash`
  keeps it adoptable later without a combiner redesign.

### Per-story detail

- **⚠️ One-time pre-1.0 cache invalidation — segmented recipe identity
  (Story J.n.3).** The authoritative cache identity moved from the flat
  `sha256(to_canonical_bytes(recipe))` to the **segmented** hash
  `sha256(to_canonical_bytes(recipe))` to the **segmented** hash
  `recipe.segments.recipe_identity_hash` — the recipe is partitioned into
  four identity segments (`core`/`plugin`/`overlays`/`extensions`) whose
  per-segment SHA-256 digests are combined with `join_stable`. Because this
  is a canonical-form algorithm change, it rides a **`schema_version` 2 → 3**
  bump (loader `(2, 3)` bootstrap migration; v3 = the segmented-canonical
  era). **Blast radius:** every existing recipe hashes to a new
  `recipe_hash`, so **every materialized instance is now stale and
  re-materializes once** — potentially hours of recompute per recipe×input,
  across every user. This is acceptable *now* (pre-1.0) and deliberately
  prohibitive post-1.0 (design memo § 8); it is the single planned
  invalidation that buys per-segment scoped invalidation thereafter. The
  recipe stays **flat** on disk — segmentation is an internal partition
  (Option 1), not an author-facing reshape — so no recipe edits are
  required; re-run `materialize` to rebuild instances.
- **Overlays — `variants` reborn as composable overlays (Story J.n.5).** The
  FR-14 `variants:` recipe section is renamed to **`overlays:`**, and selection
  generalizes from a single `--variant` to a repeatable **`--overlay`** (applied
  in order, last-writer-wins per section). Identity still hashes the *resolved*
  recipe with overlay definitions stripped, so the rename is **hash-neutral** —
  it rides the J.n.3 `schema_version` 2→3 bootstrap (which now also performs the
  `variants`→`overlays` key rename) with no additional invalidation. Library:
  `DataRefinery.from_recipe(overlays=[...])`, `resolve_instance(overlays=[...])`,
  `materialize(overlays=[...])`, and the `DataRefinery.overlays` property replace
  their `variant` forms. **Manifest schema → v2:** `manifest.variant: str | None`
  becomes `manifest.overlays: list[str]` (the ordered applied names; empty when
  none). Cross-repo contract updated in the MF/NbF vendor-dependency-specs.
- **⚠️ No-implicit-defaults rollout (Story J.n.4).** Op parameters no longer
  carry code-supplied defaults: `ParameterSpec.default` is removed, the ~25
  default-value params across the bundled plugins became **`required`**, and
  the interpreting code substitutes nothing for an omitted param. Canonical
  bytes now contain *exactly what the author wrote*; a recipe omitting a
  now-required param is a hard validation error (check 18). Recommended
  starting values moved to a new `Plugin.recommended_params(section, op)` hook
  (the scaffolder emits them into recipe text). Only `normalize.mean`/`std`
  remain optional — mode-selecting (absent ⇒ fit-from-train). This **changes
  canonical bytes** for recipes that relied on a default, so it rides the same
  one-time pre-1.0 invalidation window as J.n.3 (a single re-materialization
  event across the v0.22.0 release; no release sits between the two stories).
  A CI guard (`tests/unit/test_no_implicit_defaults.py`) fails if any
  `ParameterSpec` reintroduces a `default`. `Plugin.recommended_params` is now
  part of the protocol's required-attribute set.
- **Extensions namespace — sanctioned experimental-parameter escape hatch
  (Story J.n.6).** New optional top-level `extensions: {<namespace>: {<key>:
  <value>}}` recipe block where pydantic's `extra="forbid"` is relaxed *only
  inside* a namespace; every other recipe surface stays strict. Plugins
  enumerate the keys they consume via a new `Plugin.extension_keys() ->
  dict[str, set[str]]` hook, and the validator's **new check 28** refuses any
  `extensions` namespace/key the bound plugin does not declare (naming the
  offender). **Additive — no invalidation:** an empty/absent `extensions`
  block collapses to the empty-segment marker and contributes nothing to the
  cache identity, so existing recipes hash exactly as before; only a non-empty
  block enters canonical bytes. Extensions carry *declarative parameters* read
  by installed code only — recipe-activated code is explicitly out of scope
  (spike memo § 6 trust boundary). `Plugin.extension_keys` joins the protocol's
  required-attribute set. Recipe guides updated (`recipe-authoring.md` §
  Extensions, `plugin-authoring.md` § Declaring consumed extension keys).
- **Per-segment versions + migration registry + pin-test discipline
  (Story J.n.7).** Each identity segment now evolves on its own version axis —
  no global umbrella counter. The flat `schema_version` stays the on-disk era
  marker (Option 1 keeps recipes flat), so per-segment versioning adds **no new
  cache invalidation**. `recipe.segments` gains `SEGMENT_VERSION_KEYS`, a
  `SCHEMA_ERA_SEGMENT_VERSIONS` era-detection table, `current_segment_versions()`,
  and `apply_segment_migrations()`, which the loader replays on the read path to
  bring each segment up to the current build version via the
  `(segment, from, to)`-keyed `SEGMENT_MIGRATIONS` registry. While every segment
  sits at the current era (the steady state today) the dispatch is an exact
  pass-through; a segment-version bump without a registered migration is a hard
  load-time error. New `tests/unit/test_segment_pin_hashes.py` pins each
  segment's digest for representative image/audio fixtures — an unexpected move
  of any single segment's digest is a blocking CI failure that forces a
  conscious per-segment bump + migration, and the empty-`overlays`/`extensions`
  digests are pinned to the empty-segment marker (the J.n.5/J.n.6 additivity
  gate). Subsumes the former Future "Default-change discipline tooling" item.
  `tech-spec.md` § Cache Identity updated.
- **Cross-repo contract: segmented identity adopted as the cross-tool-family
  standard (Story J.n.8, doc-only).** The vendor-dependency-specs and
  `project-essentials.md` now pin the Phase J Recipe Architecture bundle —
  segmented cache identity, per-segment versioning + migration registry, the
  `extensions` namespace, and the no-implicit-defaults discipline — as the
  shared standard ModelFoundry adopts wholesale (NbFoundry mirrors per its
  CLI/library binding). `modelfoundry/vendor-dependency-spec.md` gains a
  segment-scoped recipe-shape table and per-segment versioning/coordination
  subsections; `nbfoundry/vendor-dependency-spec.md` expands its v2→v3 entry;
  `project-essentials.md` replaces the flat-`model_dump` cache-identity framing
  with the segmented model, adds a "No implicit defaults" entry, and names the
  four segments as separately-bumping cross-repo contract surfaces. No code or
  recipe/manifest shape change.
- **Plugin source subclasses — `AudioSource` (Story J.n.3).** `InputSource`
  is now the open base of a narrow discriminated union; `AudioSource` adds
  `target_sample_rate`. Selection is presence-based and `type` stays a free
  `str`. The base's `extra="forbid"` structurally enforces *Finding A*:
  audio-only source fields can never enter an image recipe's canonical bytes
  (pinned by `tests/integration/test_segmented_identity.py`). Cross-repo
  contract updated in
  [`docs/specs/modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md)
  and the NbFoundry mirror.

## [0.21.0] - 2026-06-16

### Fixed

- **Single source of truth for the package version (Story J.m).** The
  version was hand-maintained in two places that had drifted —
  `pyproject.toml` (`0.20.0`) and `src/datarefinery/__init__.py`
  (`0.19.0`) — so `datarefinery --version` (which reads
  `datarefinery.__version__`) reported `0.19.0` while the built wheel's
  package metadata reported `0.20.0`. `pyproject.toml` now declares
  `version` as `dynamic` and sources it from the `__version__` literal in
  `src/datarefinery/__init__.py` via Hatchling's `[tool.hatch.version]`;
  that literal is the only place the version is edited. A new
  `tests/unit/test_version_single_source.py` guard trips if a static
  `[project].version` is re-introduced or if installed metadata diverges
  from source. No `schema_version` / canonical-bytes impact (build-config
  + version-string change only).

## [0.20.0] - in progress (Phase J phase-bundle)

Phase J: ModelFoundry + NbFoundry consumer-integration phase. Stories
phase-bundle a single end-of-phase release; per-story version bumps
are deferred to the bundle's release ceremony.

### Added

- **FR-J-1: SampleData runtime (Story J.a).** The `SampleData:` recipe
  section is now honored at materialize time via the **P-postpipeline +
  M-sidecar** placement chosen by the Story I.r.0 spike: after the final
  pipeline stage, DataRefinery subsets the prepared per-split records and
  writes a sidecar under `<instance>/sample/` alongside the full
  (unchanged) `dataset/`. Two `SampleSelector.kind` paths land:
  - `uniform` — `n` (or `floor(fraction × len(split))`) records per
    selected split.
  - `per_class` — `n` (or `floor(fraction × len(class_bucket))`) records
    *per class label* per selected split; runtime refusal naming the
    split + missing-field count when records lack `Labels.field`.
  - `splits:` honoring — only listed splits are sampled (default: all).

  Determinism: per-record-seed ranking via
  `pipeline.workers.per_record_seed(seed, record)` makes selection
  invariant to input ordering, worker count, and process scheduling
  (same contract as `sample_per_class`). Same recipe + seed + inputs
  ⇒ byte-identical `sample/*.jsonl` across runs.

- **`manifest.sample`.** New `SampleManifestEntry | None` field on the
  manifest echoing the resolved selector and per-split sampled record
  counts; `None` when the recipe declares no `SampleData:` section.
  Cross-repo contract for downstream consumers is pinned in
  [`docs/specs/modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md).

- **FR-J-2: `manifest.label_classes` (Story J.f).** New
  `list[Any] | None` field on the manifest enumerating the canonical
  class set used by all labeled records in the materialized instance —
  distinct label values across every labeled split, sorted ascending
  via Python `sorted(...)`. Unlabeled splits (FR-22) are excluded;
  `None` when no labeled records exist. The field lives in the manifest
  (not the recipe), so it does not perturb canonical recipe bytes or
  cache identity — re-materializing the same recipe over the same
  inputs produces an identical list. Closes the class-enumeration gap
  surfaced during the [`modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md)
  2026-06-11 ratification round 2: downstream consumers (ModelFoundry
  today; other training tools tomorrow) bind against this list for
  label→logit-index mapping, confusion-matrix axis ordering, and
  per-class column naming instead of independently sort-by-convention-
  ing JSONL records (which can silently disagree on ordering across
  consumers when sparse classes live only in val/test).

- **`cache.layout.sample_dir`.** New layout helper for the sidecar
  directory.

- **Story J.g: consumer-applied transformations boundary.** Closes the
  silent `path`-vs-transformed-pixels divergence: a non-aggressive recipe
  declaring a *pixel-altering* Transformation (today: `resize`) emitted
  JSONL whose `path` pointed at pre-transform source pixels while the
  transformed `image` was dropped at serialization. Now:
  - **`OperationSpec.pixel_altering`** — new declarative flag classifying
    Transformation ops as pixel-altering (changes image bytes in a way
    NOT recoverable from persisted fitted statistics). `resize` is
    flagged; `normalize` / `mean_subtract` / `cast` are not.
  - **FR-2 check 26** (`pixel_altering_transform_requires_sink`) — refuses
    a recipe with a pixel-altering Transformation on any lazily-serialized
    split unless a qualifying image sink (`format: png_per_record`,
    `field: image`, a post-Transformations stage) covers those splits.
    The validator now runs **26** checks.
  - **`path` rewrite** — when the qualifying sink is present, each
    affected record's JSONL `path` is rewritten to the sink's per-record
    output (instance-relative), so consumers reading `path` decode the
    transformed pixels. Applies to the `sample/` sidecar JSONL too.
    Splits realized as aggressive variants are exempt (pixels already
    baked via `image_path`).

- **`datarefinery.resolve_instance(...)` (Story J.l).** New top-level
  facade for locating a materialized instance:
  `resolve_instance(recipe_path, *, cache_root=None, seed=None,
  variant=None) -> StatusReport`. Delegates to
  `DataRefinery.from_recipe(...).status()` (one resolution
  implementation, two ergonomic entry points — same relationship the
  top-level `materialize()` has to the handle). `StatusReport` and
  `resolve_status` are now re-exported from the top-level `datarefinery`
  package. Closes the ergonomics/discoverability gap that led a consumer
  to **reimplement** the cache-key/instance-ID math — a hand-rolled key
  silently breaks after any canonical-bytes change. Additive library
  surface; no recipe/manifest/on-disk shape change, no `schema_version`
  bump.

- **`drift.json.recipe_hash` (Story J.j).** `report/drift.json` now
  carries `recipe_hash` — the full 64-hex SHA-256 of the canonical recipe
  bytes, equal to `manifest.recipe_hash` on every fresh instance. Aligns
  the code with the long-standing `modelfoundry/vendor-dependency-spec.md`
  promise that consumers can detect a stale fitted-statistics block from
  `drift.json` alone, without a second `manifest.json` read (surfaced as
  J.d friction F7). Additive `report/` field; lives outside the recipe so
  it perturbs no canonical bytes and no `schema_version` bump. Pre-J.j
  instances omit the key (read as `null` and fall back to
  `manifest.recipe_hash`); pre-prod re-materialization populates it.

- **Story J.i: dtype-altering Transformation + aggressive Augmentation
  guard.** A recipe combining a float-emitting Transformation
  (`normalize` / `mean_subtract`) with an aggressive Augmentation on the
  same split previously crashed mid-materialize (`TypeError: Cannot
  handle this data type` — the aggressive realizer's
  `PIL.Image.fromarray` requires uint8). Now:
  - **`OperationSpec.dtype_altering`** — new declarative flag (sibling to
    `pixel_altering`) marking ops that leave the image non-uint8;
    `normalize` / `mean_subtract` are flagged.
  - **FR-2 check 27** (`dtype_altering_transform_incompatible_with_aggressive`)
    — refuses a dtype-altering Transformation that shares a split with an
    aggressive Augmentation, naming the op pair and the split. The
    validator now runs **27** checks. `resize` (pixel-altering but
    uint8-preserving) is **not** refused — `resize` + aggressive
    materializes fine. Previously-author-able recipes that hit the crash
    now fail fast at validate time; existing instances are unaffected
    (the combination could not materialize before).

### Changed

- **FR-2 check 16** (`sample_data_strict_subset`) wording flips from
  "subset of the declared **input**" to "subset of the **prepared
  dataset**" — the P-postpipeline placement makes the subset reference
  the final materialized records, not the raw input. Selector-coherence
  enforcement is unchanged.

### Fixed

- **Story J.h: ImageFolder + aggressive Augmentations sidecar PNG crash.**
  End-to-end materialization of a recipe with `Input.type: image_folder`
  plus aggressive `Augmentations` crashed with `FileNotFoundError` at the
  dataset-write stage: the ImageFolder loader stamps `record_id` as
  `<source>/<class>/<file>` (forward slashes) and the aggressive realizer
  appends `__v<NNN>`, so the sidecar filename implied nested directories
  the writer never created. [`_prepare_record_for_persistence`](src/datarefinery/pipeline/runner.py)
  now creates the sidecar's leaf parent (`sidecar_path.parent.mkdir(parents=True)`),
  preserving the nested layout. `record_id` is not mutated; `image_path`
  mirrors it verbatim. The disk-loader aggressive path now has end-to-end
  coverage ([`tests/integration/test_imagefolder_aggressive.py`](tests/integration/test_imagefolder_aggressive.py))
  that the prior library-API (flat-record_id) tests never exercised.

### Materialization-bytes notes

- Recipes that declare a `SampleData:` section now produce a sibling
  `sample/` directory inside the instance. **The full `dataset/` is
  unchanged.** `manifest.sample` becomes a non-null `SampleManifestEntry`
  on the same recipes. Recipes without `SampleData:` are byte-identical
  to v0.19.0 outputs (apart from `created_at` / `elapsed_seconds`).
- No `schema_version` bump: canonical recipe bytes are unchanged; this
  is a materialization-behavior change. Pre-prod re-materialize event
  for recipes declaring `SampleData:` only.
- **Story J.g `path` rewrite.** Recipes with a pixel-altering
  Transformation (today: `resize`) now emit instance-relative `path`
  values (pointing at the qualifying sink's per-record PNG) for affected
  splits, instead of the source-image path. No `schema_version` bump
  (canonical recipe bytes unchanged); the on-disk `path` value changes
  → pre-prod re-materialize event for any such recipe. Recipes without
  pixel-altering Transformations are byte-identical to prior output.
- **Story J.h ImageFolder aggressive sidecars.** ImageFolder recipes with
  aggressive `Augmentations` previously could not materialize at all
  (crash); they now produce sidecar PNGs under a nested
  `dataset/<split>/images/<source>/<class>/...` subtree, with `image_path`
  mirroring the `/`-bearing `record_id`. No `schema_version` bump
  (canonical recipe bytes unchanged); pre-prod re-materialize event for
  any `image_folder` + aggressive recipe (which could not have a cached
  instance before this fix). Library-API recipes with flat record_ids are
  byte-identical to prior output.

### Cross-repo coordination

- [`modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md):
  added `manifest.sample` row + `manifest.sample` shape subsection +
  `sample/` on-disk-layout block. Additive.
- [`modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md):
  ratified `manifest.label_classes` row + `manifest.label_classes` shape
  subsection (Story J.f). Removed the "forward-declared" / "Pre-J.f
  consumer guidance" framing; the field is now live. The
  pre-v0.20.0-instance adoption migration note (consumers continue to
  scan-and-sort when reading older instances) replaces the prior
  forward-declaration guidance.
- [`modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md):
  ratified the § "Consumer-applied transformations vs. baked
  transformations" boundary (Story J.g). The lazy-mode geometry-transform
  gap is documented as **closed**: the closed pixel-altering-op set
  (`{resize}`, plugin-declared), validator check 26, and the
  instance-relative `path`-rewrite mechanism are now the stable contract.
  Removed the "Pre-J.g caveat" / "Unresolved boundary" framing.
- [`modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md):
  pinned the sidecar `image_path` resolution rule for ImageFolder +
  aggressive recipes (Story J.h) — `image_path` is exactly
  `"<split>/images/<record_id>.png"` and may be **nested** when
  `record_id` carries `/` separators; consumers join it as a relative
  POSIX path, not a flat `images/` lookup.
- [`modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md):
  documented the dtype-altering-Transformation + aggressive-Augmentation
  incompatibility under § "Materialization modes" (Story J.i), referencing
  validator check 27.
- [`modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md):
  enumerated `drift.json.recipe_hash` as a stable field under § "Report
  subsections" and made the § "Failure modes" parenthetical load-bearing
  (Story J.j).
- [`modelfoundry/vendor-dependency-spec.md`](docs/specs/modelfoundry/vendor-dependency-spec.md)
  + [`nbfoundry/vendor-dependency-spec.md`](docs/specs/nbfoundry/vendor-dependency-spec.md):
  added the "Resolving a materialized instance" contract (Story J.l) —
  names `resolve_instance(...)` / `status()` as the one blessed resolver,
  documents the `StatusReport` shape, and forbids consumers recomputing
  the cache key / instance path.
- **Vendor-dependency-spec ratification Round 3 (Story J.k).**
  Documentation-only round absorbing five J.d-spike friction items (no
  code, manifest, or recipe shape change). MF spec:
  **F8** consumer-side runtime deps (`numpy`/`Pillow`/`pyarrow`) in
  § Overview; **F6** every top-level recipe section persists in
  `recipe.json` as its model default in § Recipe-side contract; **F3**
  host-bound `path` + portability workarounds in § Source-resolution
  path; **F5** `recipe.schema_version` (2) vs `manifest.schema_version`
  (1) disambiguation table in § Schema-version coordination policy.
  NbF spec: **F4** disk-loader vs. library-records Featurization
  collision asymmetry under § Library entry points. Both spec status
  blocks gain a "Round 3" note; each absorption site carries an inline
  provenance marker.

## [0.19.0] - 2026-05-30

Phase I Bundle 4. Closes Story I.y and Phase I overall. **Recipe
`schema_version` bumped from 1 to 2** — the cluster of three reshape
stories (I.x.1 / I.x.2 / I.x.3) ships together as one deliberate
cache-invalidation event, per the ceremony documented in
[`project-essentials.md` § "Cache identity is the reproducibility
contract — invalidations are ceremonious"](docs/specs/project-essentials.md).
v1 recipes are auto-migrated by the loader (`recipe.migrations.v1_to_v2`);
authors do not need to manually rewrite anything, but cached materialized
instances built against v1-shape canonical bytes are now stale and must
be re-materialized once at upgrade. This is a one-time event per
installation. Pre-production rules apply: the recompute cost is
recipe-dependent (single-input dev recipes are seconds; large production
recipes are minutes-to-hours), no schema_version re-pinning is required
beyond the v1→v2 bump itself.

The migration handles three reshapes in one composed chain
(`recipe/migrations.py`): G15 / Story I.x.1 (Filters flat shape), G12 /
Story I.x.2 (Generation reshape + `output_schema: "matches_input"`
shorthand), G16a / Story I.x.3 (assertion `kind` naming pass).

### Schema

- **`schema_version: 2`** is the canonical recipe version going forward.
  v1 recipes still load (auto-migrated); the cached `recipe.json` always
  reflects the v2 canonical shape. The loader's
  `SUPPORTED_SCHEMA_VERSIONS` is `{1, 2}` and `LATEST_SCHEMA_VERSION = 2`.
  Cross-repo consumers binding directly against the recipe model
  (ModelFoundry today; future tools) should track the v2 names; see
  [`dependency-spec.md` § Cache-identity contract → Schema v1 → v2](docs/specs/modelfoundry/dependency-spec.md)
  for the per-field migration rules.

### Changed

- **G15 — `FilterOp` flat shape (Story I.x.1).** v1's nested
  `predicate: {op, ...rest, seed?}` reshapes to top-level
  `{op, params, seed?}`, matching every other section. Auto-migrated by
  `filters_reshape_v1_to_v2`. Documented in
  [`recipe-authoring.md` § Filters](docs/guides/recipe-authoring.md).
  `tests/unit/test_filters_stage.py` and the eight other filter-touching
  test files were swept to the v2 shape; `FilterOp.predicate` is no
  longer a model field.

- **G12 — `GenerationOp` reshape (Story I.x.2).** v1's implicit op (the
  recipe's `name` doubled as the op-name) becomes explicit
  `op: str` at top level; `applies_at` renames to `splits`;
  `output_schema` widens to accept the literal `"matches_input"`
  shorthand (resolved at materialize time to `Output.record_schema` +
  declared `tag_fields`). Auto-migrated by `generation_reshape_v1_to_v2`,
  which also handles the documented v1 workaround patterns of stashing
  `op:` inside `params:` and `output_schema_matches_input: true` at the
  op level. Documented in
  [`recipe-authoring.md` § Generation](docs/guides/recipe-authoring.md).

- **G16a — Assertion `kind` naming pass (Story I.x.3).** Three v1
  bare-verb names rename to predicate-sentence form:
  `dtype` → `dtype_equals`, `range` → `value_range`,
  `record_count` → `record_count_in_range`. `required_field` and the
  `distributional` placeholder are unchanged. v1 names are removed
  (not aliased); post-migration recipes still using bare `dtype:` /
  `range:` / `record_count:` hit the evaluator's "unknown assertion
  kind" branch. Auto-migrated by `assertion_naming_v1_to_v2`.
  Documented in
  [`recipe-authoring.md` § InputContracts](docs/guides/recipe-authoring.md).

### Added

- **End-to-end migration integration test
  ([`tests/integration/test_v1_v2_migration_end_to_end.py`](tests/integration/test_v1_v2_migration_end_to_end.py)).**
  A single v1 YAML exercising all three reshapes (Filters + Generation +
  assertion-naming) loads through `recipe.loader.load`, the migration
  chain runs implicitly, and `PipelineRunner` materializes a complete
  instance against the migrated shape. A second `load + run` produces a
  cache hit — the migrated `recipe_hash` is stable. Bundle-level
  complement to the unit-level migration round-trip tests in
  `tests/unit/test_migrations.py`.

### Notes

- **Cache invalidation (pre-production).** Every cached materialized
  instance built against a v1-shape recipe is stale after upgrade.
  Re-materialize once. Recipes that do not declare any of the three
  reshaped sections (no Filters, no Generation, and no Contracts/
  Expectations using the three renamed kinds) see no canonical-bytes
  perturbation and their caches survive. The pinned canonical-hash test
  fixture (`tests/unit/test_canonical_hash_pin.py`) falls into this
  category and its digest (`146b2059…`) held unchanged across all three
  bundle stories. The fixture is authored as `schema_version: 1`, so it
  also exercises the loader's migration path through the pinned digest.

- **Cross-repo coordination.**
  [`dependency-spec.md` § Cache-identity contract → Schema v1 → v2](docs/specs/modelfoundry/dependency-spec.md)
  documents the v1↔v2 shape diffs for FilterOp, GenerationOp, and
  assertion `kind` names. ModelFoundry consumers should rely on
  loader-emitted v2 shape; binding against v1 names directly is no
  longer supported.

## [0.18.0] - 2026-05-28

Phase I Bundle 3. Closes Story I.w with twelve work stories (I.k–I.v)
plus the I.r.0 design spike. Minor bump: every feature is additive or
opt-in for *existing* recipes, though two model changes do perturb
canonical bytes for recipes that declare the affected sections
(see **Cache-identity notes** below). No `schema_version` bump — that's
deferred to Bundle 4 / v0.19.0. Cross-repo contract surface
(`modelfoundry/dependency-spec.md`) gains the `manifest.class_balance`
shape (I.s) plus a clarifying note that stage-aware visualization
dispatch is internal (I.v).

### Added

- **G2 — `cast` Transformation op (Story I.k).** Single-pass dtype
  conversion plus optional `scale` multiplier, covering the canonical
  `uint8 → float32 / 255` pre-normalize pattern as one op. Replaces the
  declared-but-unimplemented `cast_dtype` `OperationSpec` entry; the
  old name now fails validator check 18 cleanly. Documented in
  [`recipe-authoring.md` § Transformations](docs/guides/recipe-authoring.md).

- **G3 — `categorical_encode` Featurization op (Story I.l).** Encodes a
  categorical input field to integers. Two modes: recipe-declared
  `vocabulary` (persisted verbatim) and fit-on-train (vocabulary derived
  from train labels with `ordering: alphabetical | first_seen`,
  persisted to `fitted_statistics/<op_name>/vocabulary.parquet`,
  replayed identically on val/test). Carries an `output_dtype` (default
  `int32`) and accepts FR-TRANS-1 `stats_from_instance` like
  `normalize`. The Featurizations stage runner gained a `cache_root`
  parameter and a `stats_from_instance` branch so any fit-on-train
  Featurization can import sibling-instance statistics.

- **G9 — `flatten` Featurization op (Story I.m).** Deterministic
  reshape of a multi-dimensional input field to a 1-D vector, preserving
  the source field alongside the new `output_field`. Unblocks variants
  that want both the original tensor and a flattened view (e.g.
  MLP-shaped vs. CNN-shaped consumption from one recipe).

- **G11 — `seed_derive_from: master` on every seeded op (Story I.n).**
  New `SeedDerivationSpec` pydantic model accepts
  `seed: { from: master }` as an alternative to a literal integer at
  every seeded-op site: `FilterOp.predicate.seed`, `SplitsSection.seed`,
  `GenerationOp.seed`, `AugmentationOp.seed`, `SampleSelector.seed`.
  Resolution at materialize time via
  `recipe.seeds.derive_seed(master, op_name) = SHA-256(master_u64 + op_name)[:8]`
  — pinned by `tests/unit/test_seeds.py`. Master-seed changes propagate
  to every derived op without per-site edits. `SeedDerivationSpec` is
  preserved in canonical bytes so the cached `recipe.json` records the
  YAML intent.

- **G6 + G16b — Per-split / per-class / structural assertion kinds
  (Story I.o).** Seven new `OutputExpectations` assertion kinds:
  `split_record_counts`, `per_class_count_per_split` (rounding-tolerant
  via `tolerance`, default 1), `count_by_field`, `count_by_fields`,
  `shape_equals`, `value_in_set`, `per_class_count_equals`. The
  `evaluate_output_expectations` signature widens from
  `Iterable[Record]` to `Mapping[str, Sequence[Record]]`; a flat
  iterable is still accepted for backward compatibility (routed as one
  implicit split). Per-split kinds reject use in `InputContracts`
  (which runs pre-Splits). The G16a naming-rename pass for existing
  kinds is deferred to Bundle 4 (Story I.x.3).

- **G17 — `class_distribution_histogram` accepts `group_by` (Story I.p).**
  Optional `group_by: <field>` selects the bucketing field; default
  remains `Labels.field`. A new validator **check 25**
  (`visualization_group_by_resolvable`) rejects a `group_by` that
  doesn't resolve to a known recipe field
  (`Output.record_schema`, Generation `tag_fields`, or Featurization
  output). Test-count assertions across the integration suite bumped
  24 → 25.

- **G18 — `GenerationOp.replace_input_records` (Story I.q).** New
  `replace_input_records: bool = False` field declares whether a
  Generation op's output *augments* the input records (current
  behavior, default) or *replaces* them. Covers the transformation-style
  case (e.g. on-the-fly `imagecorruptions_apply`) that emits N records
  per input and doesn't want the originals along.

- **G14 — `SampleData.selector` gains `kind` + `splits` (Story I.r, schema-only).**
  `SampleSelector` widened with `kind: Literal["uniform", "per_class"] = "uniform"`
  and `splits: list[str] | None = None`. Validator check 16 extended to
  reject `per_class` on a fully-unlabeled recipe and to reject `splits`
  entries that don't name a defined split. **No SampleData runtime in
  this release** — the original story's runtime task was reframed by
  the **Story I.r.0 spike** after the spike found `SampleData` has never
  been honored at materialize time. The runtime (which needs a product
  decision on placement and replace-vs-sidecar artifact semantics) is
  carved out to be planned via `plan_phase`. `recipe-authoring.md §
  SampleData` carries an explicit "Runtime status (v0.18.0)" callout.

- **G10 — `Splits.class_balance` dict shape + `manifest.class_balance`
  emission (Story I.s).** `SplitsSection.class_balance` widened to
  `str | dict[str, Any] | None`; the dict shape is
  `{ strategy: <str>, applies_to: [<split>, …] }`. Check 10 was
  extended to validate the dict shape (no new check). The forward-
  declared hint now reaches the consumer through a new
  **`manifest.class_balance`** field (the original `SplitResult.class_balance`
  never made it into the manifest; this latent gap is also closed).
  DataRefinery still performs no resampling / no weight emission —
  ModelFoundry honors the strategy at training time per the cross-repo
  contract in
  [`dependency-spec.md` § `manifest.class_balance`](docs/specs/modelfoundry/dependency-spec.md).

- **G1 — Tag-driven `Splits.applies_to` (Story I.t).** Validator
  check 20 (`partitions_consistent`) broadened to accept `applies_to`
  matching either a source partition **or** a `sample_per_class` /
  `sample_per_class_fractional` filter `label`. The Splits stage
  learned a tag-driven route: records carrying the named tag in
  `sample_per_class_tags` are ratio-sub-split (honoring `stratify_by` /
  `seed`); records carrying a different tag pass through verbatim under
  a split named after their tag; untagged records land in `unassigned`.
  Pass-through split membership is filter-tag-determined, so the heldout
  split is byte-identical across runs and independent of the Splits
  `seed`. Multi-tag ambiguity and ratio/other-tag name collisions raise
  `MaterializeError`. Restores the disjoint-pool bit-identity guarantee.

- **G13 — `tag_fields` dict-rename form on `imagecorruptions_apply`
  (Story I.u).** `ImageCorruptionsApplyParams.tag_fields` widened to
  `list[str] | dict[str, str]`. The dict form is a
  `{ authored_field_name: canonical_name }` rename map; the canonical
  set `{corruption, severity, source_path}` is now a module-level
  constant. The model `_validate` rejects unknown canonical values and
  duplicate canonical mappings (the rename map must be one-to-one).
  The list form (canonical names verbatim) is unchanged.

- **G7 — Stage-aware visualization dispatch (Story I.v, closes G5).**
  `VisualizationOp.stage` is now a closed `VizStage` Literal:
  `{ post_InputContracts, post_Filters, post_Splits, post_Generation,
  post_Transformations, post_Augmentations, post_Featurizations,
  post_pipeline }` — mirrors `SinkStage`'s grammar but drops the
  entries that don't change records, and keeps `post_pipeline` as the
  alias for the final snapshot (the scaffolder default). The pipeline
  runner snapshots `split_map` at the END of each named stage into a
  `viz_snapshots` dict; `apply_reporting_visualizations` dispatches
  each viz op against `snapshots[op.stage]` and accepts either the
  full snapshots map or a flat splits dict (auto-wrapped as
  `post_pipeline`, for backward compatibility with `re_render_report`
  and pre-existing tests). **G5 is closed structurally:**
  `augmented_sample_grid` declared at `stage: post_Filters` renders
  against the uint8 snapshot and never sees the post-normalize floats.
  The `_tile` clip-cast at `augmented_sample_grid.py:144` is kept as
  defense-in-depth (documented) for non-canonical-but-valid stage
  placements like `post_Featurizations` after a cast.

### Changed

- **Validator check 11 renamed** `visualization_mode_declared` →
  `visualization_well_formed` and extended with the empty-stage rule
  (Story I.v). The check id stays 11 to avoid churning the
  `N/N checks passed` assertions across the integration suite.

- **`evaluate_output_expectations` signature widened** to
  `Mapping[str, Sequence[Record]]` keyed by split (Story I.o). A flat
  iterable is still accepted and routed as one implicit `__all__`
  split; existing call sites and recipes are unaffected.

### Removed

- **`cast_dtype` and `to_grayscale` `OperationSpec` entries (Story I.k).**
  Both were declared-but-unimplemented stubs that raised
  `NotImplementedError` at materialize time. Recipes using `op:
  cast_dtype` are migrated to the new `op: cast` (which adds a `scale`
  parameter). `to_grayscale` is tracked as a future enhancement in
  `stories.md § Future` until a real implementation is needed.

### Cache-identity notes

Two model changes in this bundle perturb canonical bytes — *only for
recipes that declare the affected sections.* Recipes without those
sections are byte-identical and re-use their existing cache instances.

- **Recipes declaring a `Generation:` block** now serialize an
  additional `replace_input_records: false` default per op (Story I.q).
- **Recipes declaring a `SampleData:` block** now serialize the
  additional `kind: "uniform"` and `splits: null` defaults on the
  selector (Story I.r).

Both are pre-production cache invalidation events per
[`project-essentials.md` § "Cache identity is the reproducibility
contract — invalidations are ceremonious"](docs/specs/project-essentials.md):
re-materialize the affected recipes once at upgrade. The
canonical-hash pinning fixture in
`tests/unit/test_canonical_hash_pin.py` declares neither section and
stays green. No `schema_version` bump (the v1 → v2 reshape ships
together with the deliberate Filters / Generation / assertion-name
reshapes in Bundle 4 / v0.19.0).

### Cross-repo coordination

- `manifest.class_balance` field row + dict-shape subsection added to
  [`dependency-spec.md`](docs/specs/modelfoundry/dependency-spec.md)
  (Story I.s). Documents the v1 strategy vocabulary
  (`oversample_minority_to_majority`,
  `emit_inverse_frequency_weights`) and ModelFoundry's training-time
  responsibility (`WeightedRandomSampler`, `class_weight=`).
- Report-subsection note in `dependency-spec.md` clarifies that
  stage-aware visualization dispatch is **internal**: the on-disk
  surface (`report/visualizations/<viz_name>.png`, single `report.md`
  section) is unchanged regardless of how many pipeline stages a
  recipe spans (Story I.v).
- No `dependency-spec.md` change for I.r.0 / I.r (the SampleData
  selector shape isn't bound by the spec), I.t (recipe-side semantics
  only), or I.u (per-recipe op authoring).

### Documentation

DOC-rule backfill across [`recipe-authoring.md`](docs/guides/recipe-authoring.md):

- **§ Transformations** — `cast` worked example with the
  `uint8 → float32 / 255` pattern, plus backfill summaries for
  `resize`, `mean_subtract`, `normalize`; "FR-TRANS-1 across variants"
  remains from v0.17.1.
- **§ Featurizations** — `categorical_encode` (both modes), `flatten`,
  plus backfill of `image_size_stats` and `label_from_path`
  alternative sources.
- **§ Filters** — referenced from the new "Sub-partitioning via tag"
  block under § Splits; full Filters rewrite is deferred to Bundle 4
  (Story I.x.1).
- **§ Generation** — "When to use `replace_input_records`",
  "`tag_fields` on `imagecorruptions_apply`" (list + dict forms),
  per-record-seed persistence remains from v0.17.0.
- **§ Splits** — "Sub-partitioning via tag" subsection paralleling the
  existing source-partition one; "Filters vs Splits for class imbalance"
  rewritten to spell out the DR-doesn't-resample / MF-honors-at-training
  separation and document the `class_balance` dict form.
- **§ Visualizations** — "Stage-aware dispatch (G7)" subsection with
  the closed `VizStage` table, the pre-vs-post-normalize worked
  example, the validator empty-stage rule, the re-render limitation,
  plus `group_by` carried over from I.p.
- **§ SampleData** — `kind` / `splits` documented with an explicit
  "Runtime status (v0.18.0)" callout that the selector is validated
  and cache-participating but **not yet honored at materialize time**;
  runtime carved to a plan_phase story per Story I.r.0.
- **§ InputContracts** and **§ OutputExpectations** — the seven new
  per-split / per-class / structural assertion kinds (Story I.o),
  cross-split assertion notes, and per-split rejection in
  `InputContracts`.
- **§ Seeds and determinism** — `seed_derive_from: master` documented
  alongside literal-int seeds (Story I.n).

`tech-spec.md` updated alongside (`recipe.seeds`, the
`apply_reporting_visualizations` snapshot mapping, the widened
`evaluate_output_expectations` signature).

### Notes

- The **G14 SampleData runtime** is the most visible carved-out item:
  the schema landed in this release; the runtime story (placement,
  artifact semantics) is intended for `plan_phase` framing in
  Phase J. See Story I.r.0 for the design axes already documented.
- The **broad consumer-context rewrite of internal specs** (Recipe A/B
  framing, Module N references, consumer recipe filenames in
  `phase-i-*.md`) remains deferred to a post-course Future story.
- The validator check count is now **25** (unchanged this release;
  every new validation in this bundle was folded into an existing
  check by design, so the integration `N/N checks passed` assertions
  did not need to move).

## [0.17.1] - 2026-05-27

Phase I Bundle 2. Closes Story I.j. Patch release bundling one bug fix
(Story I.i) and one documentation-only sanitize (Story I.h). No
cross-repo contract changes; no `schema_version` bump.

### Fixed

- **G19 — `resolve_sibling_stats` strips sibling variants before hashing
  (Story I.i).** The resolver now wraps `load_recipe(recipe_path)` with
  `apply_variant(..., None)` before computing the canonical hash,
  mirroring the materialize path at
  [`core/datarefinery.py:92`](src/datarefinery/core/datarefinery.py).
  Before the fix, any sibling recipe declaring a `variants:` block
  produced a hash mismatch and `stats_from_instance` lookups failed with
  `SiblingInstanceNotFoundError`, even though the sibling was
  materialized and `datarefinery status` resolved it correctly. A
  no-variant regression test pins the invariant that
  `apply_variant(recipe, None)` preserves canonical bytes when no
  variants are declared, so the fix does not invalidate existing
  sibling-stats lookups. Adds an "FR-TRANS-1 across variants" subsection
  to [`recipe-authoring.md` § Transformations](docs/guides/recipe-authoring.md)
  documenting that `stats_from_instance` resolves the sibling's
  no-variant canonical instance (pinning a specific sibling-variant's
  statistics is tracked in `stories.md § Future`).

### Documentation

- **Narrow-scope sanitize of residual consumer-context identifiers
  (Story I.h).** Scrubbed hard-blacklisted course identifiers from
  [`phase-i-intermediate-artifact-persistence-spec.md`](docs/specs/phase-i-intermediate-artifact-persistence-spec.md)
  (six occurrences in §§ 1, 6, 7 rephrased to generic equivalents).
  [`phase-i-dependency-gaps-v0.16.0.md`](docs/specs/phase-i-dependency-gaps-v0.16.0.md)
  was clean for the narrow scope; the deeper consumer-perspective
  framing in both specs is intentionally left in place for a deliberate
  post-course rewrite captured as a new entry under
  [`stories.md § Future`](docs/specs/stories.md): "Broad consumer-context
  rewrite of internal specs." Also added the previously-planned Phase I
  deferred items to `stories.md § Future` (`stats_from_instance.variant`
  selector, `to_grayscale` op, plugin-pluggable validator reserved-set
  hook, per-stage report subsections, scaffolder v2 grand sweep, real
  `distributional` assertion kind, DR-side `class_balance` resampling).
  Renumbered the existing G7 placeholder Story I.h → Story I.v within
  Bundle 3.

## [0.17.0] - 2026-05-26

Phase I Bundle 1 (Sinks). Closes Story I.g. Additive cross-repo
contract changes only — no `schema_version` bump. Brings the Sinks
recipe section, the per-record-seed persistence contract, and the
`datarefinery export` verb (Stories I.d, I.e, I.f, I.f.1).

### Added

- **Announced-skip semantics for partial-run sinks (Story I.f.1).**
  Resolves spec open question § 10 #3 in
  [`phase-i-intermediate-artifact-persistence-spec.md`](docs/specs/phase-i-intermediate-artifact-persistence-spec.md).
  When `materialize --stage <stop>` halts early, sinks targeting
  stages later than `<stop>` are now *announced-skipped*: the
  partial manifest records them under a new
  `manifest.sinks_skipped: dict[str, str]` field (sink name →
  declared stage), and `datarefinery status` renders a "Sinks
  skipped" table when that field is non-empty. Closes a small
  inconsistency in the partial-finish path: sinks that DID fire
  before the stop point now also appear in `manifest.sinks` (the
  prior path silently dropped them). The CLI behaviour for
  `--stage` is unchanged otherwise — no run is failed because of a
  sink declaration mismatch. **Cross-repo coordination:** added
  the `sinks_skipped` row to
  [`docs/specs/modelfoundry/dependency-spec.md`](docs/specs/modelfoundry/dependency-spec.md).

- **`datarefinery export` verb — re-run sinks against an existing
  instance (Story I.f).** New CLI verb and `DataRefinery.export()`
  library method that re-runs recipe-declared sinks against an
  already-materialized cache instance, without re-running the full
  pipeline. The bound instance is located via a sinks-stripped
  cache-key lookup so a user who adds a sink to an existing recipe
  still resolves to the original cache. Output bytes are
  byte-identical to a materialize-with-the-sink (pinned by the
  parity test in `tests/integration/test_export_verb.py`).

  **v1 reconstructability table:**
  - `post_OutputExpectations` / `post_Visualizations` — read cached
    JSONL directly.
  - `post_Generation` — re-load input subset from disk, re-run the
    recipe's Generation ops over it, match outputs to cached records
    by `record_id`. Byte-identical reconstruction relies on the
    per-record-seed stamps from Story I.e.
  - Every other stage — refuses cleanly with a pointer to
    `datarefinery materialize`. The table will expand as more ops
    adopt the per-record-seed contract.

  **Per-file atomicity.** Each sink file is staged in
  `.export_tmp_<uuid>/` and `os.replace`-d onto its final path; an
  interrupted export never leaves a half-written file under the
  promoted instance directory.

  **Latent issues closed alongside.** `Sinks` is now registered in
  `recipe.loader.KNOWN_TOP_LEVEL_KEYS` (the loader was silently
  warning on recipes that declared the section). A `[[tool.mypy.overrides]]`
  entry suppresses the click missing-stub error in `cli/app.py`
  (click v8+ ships its own typing; the override silences mypy on
  CI environments running older click).

- **Per-record-seed persistence on stochastic ops (Story I.e).**
  Every stochastic Generation / Augmentation op now stamps
  `<op_name>_seed` (8-byte unsigned int) onto each record it
  produces. The stamp value equals the seed actually consumed by the
  op's RNG — `per_record_seed(GenerationOp.seed, input_record)` for
  `imagecorruptions_apply`; `per_record_variant_seed(global_seed,
  input_record, variant_index, op_id=AugmentationOp.op)` for every
  variant emitted by `aggressive`-materialization Augmentations. The
  stamp rides through to cached JSONL and is captured automatically
  by any Sink targeting `post_<stage>`. Prerequisite for the future
  `datarefinery export` verb (Story I.f): consumers can replay the op
  with the recorded seed to reconstruct stage outputs bit-identically
  without re-materializing. Ops whose stochasticity is op-level
  (`duplicate_minority_class`) do not stamp; the op-level seed
  already lives in `recipe.json` and the duplicate's `record_id`
  points back at the source. Lazy-mode augmentations do not stamp
  (variants are realized at training time, outside the pipeline).

  **Generation op contract extension.** The Generation op signature
  now requires an `op_name: str` kwarg so the op can key its stamp
  field on the recipe-defined identifier (in-tree plugins updated;
  any out-of-tree plugin needs the new kwarg).

  **Aggressive realizer extension.** `emit_variants(...)` accepts an
  optional `stamp_field` kwarg (default `None`, meaning don't stamp);
  `pipeline.stages.augmentations.realize_aggressive_split` always
  supplies `stamp_field=f"{AugmentationOp.name}_seed"`.

  **Pre-production cache invalidation.** Stamping changes the cached
  *record* bytes (JSONL contents) for any recipe with a stochastic
  op — not the canonical recipe bytes (which depend only on shape).
  Pre-prod rules apply; users re-materialize on upgrade. The pinned
  canonical-hash fixture is unaffected (canonical bytes unchanged).

  **Cross-repo coordination.** `docs/specs/modelfoundry/dependency-spec.md`
  updated with the per-record-seed field convention so downstream
  consumers can rely on the seed presence in cached JSONL.

- **Sinks — schema, validator, materialize-time `png_per_record` writer
  (Story I.d).** New top-level recipe section `Sinks` declares
  disk-output artifacts captured at materialize time. v1 ships one
  writer (`png_per_record`) targeting any pipeline stage's record
  output via a closed `stage` vocabulary
  (`post_InputContracts`...`post_Visualizations`). Sinks participate
  in canonical recipe bytes (cache identity) and the existing
  temp-then-promote atomic write (FR-5); pipeline failure leaves no
  partial sink output under the promoted instance path. Per-sink
  summaries land in a new `manifest.sinks[<name>]` map (`stage`,
  `format`, `files_written`, `bytes_total`,
  `path_template_resolved_root`). Closes the G18 surface symptom by
  making bit-identical export of pre-normalize stage outputs
  structural rather than reachable only via consumer-side
  re-derivation. See
  [`docs/specs/phase-i-intermediate-artifact-persistence-spec.md`](docs/specs/phase-i-intermediate-artifact-persistence-spec.md)
  for the full design.

  New validator check 24 (`sinks`): sink names unique within a recipe;
  path templates parse cleanly; templates do not escape the instance
  directory (`..` or absolute paths rejected); the referenced `field`
  appears in the recipe's known-field universe; each `splits` entry
  names a defined split. Total static checks: 23 → 24.

  **Pre-production cache invalidation.** Adding the new `Sinks: []`
  default to `Recipe` perturbs canonical recipe bytes for every
  recipe that omits the section. Per `project-essentials.md` §
  "Cache identity is the reproducibility contract" pre-prod rules,
  this is acceptable and noted here; users re-materialize on
  upgrade. The pinned canonical-hash fixture in
  `tests/unit/test_canonical_hash_pin.py` was bumped in the same
  commit as a deliberate sign-off.

  **Cross-repo coordination.** `docs/specs/modelfoundry/dependency-spec.md`
  updated with the `manifest.sinks` field shape so downstream tools
  (ModelFoundry today; other tools tomorrow) can read sink-output
  metadata without breakage. Additive section; no `schema_version`
  bump.

### Fixed

- **`click` declared as an explicit runtime dependency (regression
  from Story I.f).** [`cli/app.py`](src/datarefinery/cli/app.py)
  began importing `click` directly in I.f (alongside the existing
  `import typer`) so its exception-handling path could catch
  `click.exceptions.Exit` cleanly, but `click` was not added to
  `[project.dependencies]` at the same time. The package was still
  pulled in transitively via `typer`, so `pyve test` passed locally
  — but CI's `pip install -e ".[corruptions]"` path did not always
  resolve the transitive in time and collected `ModuleNotFoundError:
  No module named 'click'` on every CLI test. Pinning `click>=8` in
  `[project.dependencies]` makes the contract explicit and matches
  the `[[tool.mypy.overrides]]` entry that I.f had already added for
  click stubs. Caught at the I.g release ceremony.

### ⚠ Cache invalidation (pre-production)

Two effects combine on upgrade from 0.16.x. Pre-prod rules apply per
[`project-essentials.md` § "Cache identity is the reproducibility
contract"](docs/specs/project-essentials.md); users re-materialize
once. No `schema_version` bump — the changes are byte-level, not
recipe-shape-level.

- **Canonical recipe bytes shift (Story I.d).** Adding the
  `Sinks: []` default to `Recipe` perturbs canonical bytes for every
  recipe that omits the section, so every existing cache instance
  resolves to a new directory after upgrade. The pinned canonical-hash
  fixture in `tests/unit/test_canonical_hash_pin.py` was bumped in the
  I.d commit as a deliberate sign-off.
- **Cached JSONL record bytes shift (Story I.e).** Every record
  produced by a stochastic Generation / aggressive-mode Augmentation
  op now carries a `<op_name>_seed` field. Recipes without stochastic
  ops are unaffected at the record level (still affected by the
  canonical-bytes shift above).

## [0.16.2] - 2026-05-25

### Fixed

- **G4 — validator catches Featurization output_field colliding with a
  loader-stamped field (Story I.c).** Added validator check 23
  (`featurization_output_field_loader_collision`). Before this fix, a
  recipe declaring an `image_flat` + `label_from` Input plus a
  `label_from_path` Featurization writing `output_field: label` validated
  cleanly and then crashed at materialize time with the runtime collision
  detector at [`pipeline/stages/featurizations.py:110-115`](src/datarefinery/pipeline/stages/featurizations.py).
  Check 23 surfaces the failure at validate time, before any loading
  work runs. Covers all five loader-stamped fields for the
  `image_classification` plugin: `record_id`, `image`, `path` (always);
  `label` (when `Labels.source.kind == "direct"` and a label source
  exists); `partition` (when any `InputSource.partition` is declared).
  See [`docs/specs/dependency-gaps-v0.16.0.md` § G4](docs/specs/dependency-gaps-v0.16.0.md)
  for the full investigation record.

  Total static checks: 22 → 23. `validate` now reports `23/23 checks
  passed` on a clean recipe.

## [0.16.1] - 2026-05-25

### Fixed

- **G8 — contracts evaluator now accepts ndarray field values for `dtype`
  and `range` assertions (Story I.b).** Two unhandled-input bugs in
  `pipeline/contracts.py` are fixed:
  - `_eval_dtype` reported every record as the wrong type when the field
    value was a numpy ndarray (e.g., `dtype: uint8` on an `image` field).
    Root cause: `isinstance(v, accepted)` checked against Python scalar
    types only. Now: ndarray fields are checked via
    `v.dtype.name == expected`; scalar fields use the existing
    `isinstance` path.
  - `_eval_range` raised `ValueError: The truth value of an array with
    more than one element is ambiguous` when the field value was an
    ndarray. Root cause: `v < lo` on an ndarray returns an element-wise
    boolean array. Now: ndarray fields are reduced via `v.min()` /
    `v.max()` and compared as scalars; scalar fields use the existing
    direct-comparison path.

  No new assertion kinds are added; this fix relaxes existing evaluators
  to accept inputs the schema already permits. Bundled in this patch
  release; no schema bump. See
  [`docs/specs/dependency-gaps-v0.16.0.md` § G8](docs/specs/dependency-gaps-v0.16.0.md)
  for the full investigation record.

## [0.16.0] - 2026-05-23

### Added

- **FR-VIZ-1 `pixel_distribution` reporting visualization (Story H.t).**
  Per-channel R/G/B pixel-value histograms across a named split,
  rendered as a 1x3 matplotlib figure. Params:
  `bins: int = 64`, `splits: list[str]` (required, non-empty). Returns
  one PNG per requested split, persisted as
  `report/visualizations/<op.name>_<split>.png`. Introduces the
  `datarefinery.plugins.image_classification.visualizations/`
  submodule with shared matplotlib helpers in `_render.py`
  (pyplot-free, Agg-canvas, deterministic PNG metadata).
- **`VisualizationOpHandle` protocol extended to multi-PNG return
  (Story H.t).** A handle's `render(...)` may now return either
  `bytes` (single PNG, persisted as `<op.name>.png`) or
  `Mapping[str, bytes]` (one PNG per key, persisted as
  `<op.name>_<key>.png`). `RenderedVisualization` grows `extras` and
  `extra_paths` mappings so exploration-mode and `inspect` callers see
  the full multi-PNG output in memory. Existing single-PNG ops are
  unchanged.
- **FR-VIZ-2 `augmented_sample_grid` reporting visualization
  (Story H.u).** For each declared `AugmentationOp`, render an
  `n_base x n_variants` grid showing the policy applied to a
  deterministic train-split sample. Mode-aware: aggressive ops group
  the materialized train split by `source_record_id` +
  `variant_index`; lazy ops realize variants inline via the plugin's
  realizer registry. Params: `n_base: int` (>0, required),
  `n_variants: int` (>0, required), `seed: int | None = None`. One PNG
  per declared augmentation op, persisted as
  `<op.name>_<aug.name>.png`. Empty mapping (no PNGs written) when
  the recipe declares no augmentations.
- **`VisualizationOpHandle` protocol extended with optional `recipe`
  context (Story H.u).** `render(...)` accepts an optional
  `recipe: Recipe | None = None` kwarg threaded by the pipeline-stage
  runner, the exploration-mode renderer, the `report` CLI verb, and
  `inspect`. Policy-aware viz ops (e.g. `augmented_sample_grid`
  reading `recipe.Augmentations`; `corruption_severity_grid` and
  `severity_ladder` reading `_corruption_names.CORRUPTION_NAMES_ALL`)
  consume it; ops that don't need it ignore the argument.
- **FR-VIZ-3 `corruption_severity_grid` reporting visualization
  (Story H.v).** Single `K-corruption x L-severity` figure: each
  subplot tiles the same `n_images` train-split records side-by-side
  under that `(corruption_type, severity)` combination. Self-contained
  params (not derived from `recipe.Generation`). Params:
  `n_images: int` (>0, required), `corruption_types: list[str]`
  (non-empty, vocabulary-checked, no duplicates, required),
  `severities: list[int]` (non-empty, each in `1..5`, required).
  Single PNG persisted as `<op.name>.png`. Requires the
  `[corruptions]` extras at materialize time; the plugin remains
  importable without them (deferred-import guard inside `render(...)`
  surfaces a friendly `ImportError` with the install pointer when
  missing). Recipe-time vocabulary validation works without the
  extras via the in-tree `_corruption_names` module.
- **FR-VIZ-4 `severity_ladder` reporting visualization (Story H.w).**
  Single-corruption complement to `corruption_severity_grid`: renders
  `n_examples` train-split records across all five severities of one
  `corruption_type` as `n_examples x 5`. Params: `n_examples: int`
  (>0, required), `corruption_type: str` (non-empty,
  vocabulary-checked, required). Single PNG persisted as
  `<op.name>.png`. Same `[corruptions]`-extras-required and
  deferred-extras-guard model as `corruption_severity_grid`.
- **`matplotlib` added to base runtime dependencies (Story H.t).**
  All four FR-VIZ ops render via matplotlib; gating behind an extra
  would surprise users whose recipes declare a visualization
  (reporting-mode runs at materialize time, not as an opt-in tool).
  Pinned tested version: matplotlib 3.10+.

### ⚠ Cache invalidation (pre-production)

Declaring any of the four new visualization ops is **not**
cache-invalidating on its own — FR-13 visualizations are reporting-only
and never enter the cache identity. However, **users upgrading from
0.15.0 must run `pip install --upgrade ml-datarefinery` (or
`pip install ml-datarefinery==0.16.0`) to pick up the new `matplotlib`
runtime dependency** before any recipe that declares a visualization
op will materialize. Environments that don't declare a `Visualizations:`
section continue to materialize without matplotlib being exercised.
The canonical-hash pin in `tests/unit/test_canonical_hash_pin.py` is
unchanged — the pinned fixture has no `Visualizations` section.

## [0.15.0] - 2026-05-23

### Added

- **FR-11 augmentation framework — lazy + aggressive modes (Stories
  H.o–H.r.3).** `AugmentationOp` gains two new fields:
  `materialization: Literal["lazy", "aggressive"] = "lazy"` and
  `expansion: int = 1`. Lazy is the previous behavior (policy-only;
  ModelFoundry realizes on-the-fly at training time). Aggressive
  realizes `expansion` augmented variants per train record at
  materialize time; variants become peer records with persisted
  sidecar PNG image bytes. Both modes coexist in a single
  `Augmentations:` block.
- **Four concrete image-classification augmentation ops.**
  `random_crop` and `horizontal_flip` (Story H.q),
  `color_jitter` and `random_erasing` (Story H.r). Each has a
  pydantic param model (`RandomCropParams`, `HorizontalFlipParams`,
  `ColorJitterParams`, `RandomErasingParams`) and a deterministic
  aggressive-mode realizer. The four realizers are registered on
  `PLUGIN.augmentation_realizers` and dispatched by the augmentations
  stage.
- **Runner wiring for aggressive mode (Story H.r.1).**
  `pipeline.runner` invokes `realize_aggressive_split` for the train
  split when a recipe declares any aggressive op.
- **Image-bytes persistence for aggressive variants (Story H.r.2).**
  Each variant's image bytes are written to a sidecar PNG at
  `dataset/<split>/images/<record_id>.png` using Pillow's PNG encode
  (deterministic). The JSONL record carries `image_path: str`
  (relative to the dataset directory) instead of the dropped numpy
  `image` array. Materialized aggressive instances are self-contained:
  consumers read variant pixels from sidecars, not from the source
  filesystem.
- **`docs/specs/modelfoundry/dependency-spec.md`** — new authoritative
  cross-repo contract document. Enumerates the recipe-side
  augmentation surface, materialized dataset on-disk layout, manifest
  fields ModelFoundry binds against, report subsections, the
  cache-identity contract, schema-version coordination policy,
  forward-compatibility expectations, and failure modes downstream
  consumers should detect.
- **`docs/specs/project-essentials.md`** gains a new section: "Recipe
  / manifest / report shape changes need a cross-repo coordination
  check." Names the three external contract surfaces and points at
  `dependency-spec.md` as the authoritative reference.

### Fixed

- **CI mypy gap (Story H.r.3).** Widened
  `pipeline.stages.augmentations.realize_aggressive_split`'s `records`
  parameter from `list[Record]` to `Sequence[Record]` (covariant) so
  all test call sites passing `list[dict[str, Any]]` type-check
  cleanly. Removed 5 stale `# type: ignore[arg-type]` comments
  flagged as `[unused-ignore]`.

### ⚠ Cache invalidation (pre-production)

**Recipes that declare an `Augmentations:` section will re-materialize
on first run after upgrade.** Adding the `materialization` and
`expansion` defaults to `AugmentationOp` perturbs canonical recipe
bytes for any recipe that uses augmentations, which changes the cache
identity (instance directory path). Per
`docs/specs/project-essentials.md` § "Cache identity is the
reproducibility contract — invalidations are ceremonious," pre-prod
invalidation is acceptable; the next run after `pip install --upgrade
ml-datarefinery` will re-materialize affected recipes once. Recipes
without any augmentations are unaffected.

Post-production, this style of change will require a `schema_version`
bump + migration entry; pre-production it's a release-notes mention
only.

## [0.14.1] - 2026-05-22

### Fixed

- **Story H.n.4 — CI module-collection failure on missing `cv2`.** CI
  for the v0.14.0 release aborted at pytest *collection* time with
  `ModuleNotFoundError: No module named 'cv2'` because
  `tests/plugins/image_classification/test_corruptions_vendored.py`
  does a module-top-level `from datarefinery.plugins.image_classification
  import _corruptions`, which transitively does `import cv2` / `import
  skimage` at module load. CI's install step (`pip install -e .` +
  `pip install -r requirements-dev.txt`) never installed the
  `[corruptions]` extras, so collection failed and **no tests ran** —
  the run was a false negative on the entire suite, not just the
  corruptions tests. `test_generation_imagecorruptions.py` had the same
  defect one step deferred (the lazy `_corruptions` import inside
  `imagecorruptions_apply` would fire at test *execution* time) and
  would have failed identically had collection reached it.

  **Latent since Story H.m.1** (vendored `_corruptions` module);
  masked locally by an opportunistically-installed
  `opencv-python-headless` in the dev venv. The `[corruptions]` extras
  remain **optional for end users** per FR-GEN-1 — "only execution
  requires them" — but CI's job is to exercise every code path.

  Two-part fix (belt-and-suspenders):

  - **`.github/workflows/ci.yml`** — install step changed from
    `pip install -e .` to `pip install -e ".[corruptions]"` on both
    `ubuntu-latest` and `macos-latest` runners.
  - **`pytest.importorskip("cv2", reason=...)`** added at the top of
    both
    `tests/plugins/image_classification/test_corruptions_vendored.py`
    and
    `tests/plugins/image_classification/test_generation_imagecorruptions.py`.
    Dev environments without the extras now skip these test modules
    cleanly instead of failing. The CI install ensures the corruption
    codepaths are still actually exercised; the importorskip prevents
    this exact failure mode from recurring if CI infrastructure
    changes.

  `test_friendly_import_error_when_backend_missing` (which mocks the
  import failure to test the friendly-error path) still runs in CI
  where extras are installed; in dev environments without extras the
  whole file skips, which is acceptable since the failure-path test
  still has coverage in CI.

### Notes

- No code changes outside tests + CI workflow. No pydantic models or
  recipe semantics were touched. Canonical-hash pin holds unmodified.

## [0.14.0] - 2026-05-22

### Added

- **Story H.n — `stats_from_instance` on `normalize` + FR-ARCH-1
  loose-coupling decision (FR-TRANS-1).** New parameter on fit-on-train
  `Transformations` ops (v1: `normalize`; extensible to future
  fit-on-train ops) that imports fitted statistics from a sibling
  materialized DataRefinery instance instead of fitting locally — the
  train/inference parity contract made expressible at the recipe
  surface for distribution-shift, A/B, cross-team, and longitudinal
  evaluation workflows. Shape:

  ```yaml
  Transformations:
    - name: norm
      op: normalize
      params:
        stats_from_instance:
          recipe: ./train_recipe.yaml      # path to sibling recipe
          op_id: norm                       # op name inside the sibling
      splits: [eval]
  ```

  - **`StatsFromInstanceSpec` pydantic model** (`recipe: str`,
    `op_id: str`; frozen). Mutually exclusive with the op's
    `fit_source` field — exactly one must be set on a fit-on-train op,
    enforced by new validator check 22
    (`stats_from_instance_mutually_exclusive_with_fit_source`). Check 6
    short-circuits the "fit-on-train requires `fit_source: train`"
    requirement when `stats_from_instance` is set.
  - **`cache.sibling_stats.resolve_sibling_stats(...)`** (Story H.n.1):
    standalone resolver that loads the sibling recipe, computes its
    canonical hash, locates the most-recent matching promoted instance
    under `<cache_root>/instances/<recipe16>/`, and returns a
    read-only `FittedStatistics` handle pointing at its
    `fitted_statistics/`. Three explicit failure modes
    (`SiblingInstanceNotFoundError`, `SiblingOpNotFoundError`,
    `SiblingStatsIncompatibleError`) — each a `MaterializeError`
    subclass so callers can branch on the failure shape.
  - **Apply-path integration in the stage dispatcher** (Story H.n.2):
    `pipeline.stages.transformations.apply_transformations` gained a
    `cache_root` parameter and a `stats_from_instance`-branch that
    skips the local fit, resolves the sibling, materializes the
    sibling's `fitted_statistics/<op_id>/` as `FittedValues`, and feeds
    that into the op's `apply` phase. The op handle (`NormalizeOp`) is
    unchanged — any future fit-on-train op picks up sibling-import
    support by declaring `stats_from_instance` in its `OperationSpec`.
  - **Read-through, not copy.** Imported statistics are not duplicated
    into the consuming instance's own `fitted_statistics/`; the apply
    path reads through to the sibling's bytes. The consuming instance
    therefore has no `fitted_statistics/<op_id>/` for ops that import
    their stats — intentional, so the materialized output honestly
    reflects "stats are owned by the sibling."

### Loose-coupling semantics — read carefully

The v1 `stats_from_instance` design is **loose-coupled** per the
FR-ARCH-1 decision: the sibling recipe's `recipe_hash` does **NOT**
participate in the consuming recipe's cache identity. **Concretely:**

- Re-materializing an upstream (train) recipe does NOT auto-invalidate
  any downstream (eval) recipes that import its statistics.
- After re-materializing upstream, the user MUST manually re-materialize
  every downstream recipe that imports the sibling — DataRefinery will
  not detect the staleness for you.
- The resolver always picks the **most-recent** promoted instance of
  the sibling recipe (by `Manifest.created_at`), so re-materializing
  downstream after upstream changes naturally picks up the new stats —
  but the consumer's own cache identity hasn't changed, so a downstream
  re-`materialize` against an unchanged input + unchanged consumer
  recipe will hit the consumer cache and *not* re-run, even though the
  underlying stats moved. **`clean` the downstream entry first, or edit
  the downstream recipe semantically, to force a re-materialize.**
- This is justified for small-scale single-author workflows where the
  failure mode (stale downstream after upstream re-fit) is detectable
  by inspection. For multi-team, cross-org, or longitudinal workflows
  where the failure is harder to spot, tight coupling (sibling
  `recipe_hash` participates in cache identity) is the documented
  Future upgrade under FR-ARCH-1 — it will be a `schema_version` bump.

### Documentation

- **`features.md`** — added FR-2 check 22 (`stats_from_instance` /
  `fit_source` mutual exclusion); FR-4 Edge Cases bullet on the
  loose-coupling decision; FR-6 Behavior sub-points #5 (producer
  side: sibling-addressable fitted stats) and #6 (consumer side:
  read-through, not copied); FR-10 Behavior section on
  `stats_from_instance` with the four-scenario motivation
  (distribution-shift / A-B / cross-team / longitudinal) and the
  three failure-mode edge cases.
- **`tech-spec.md`** — new `cache.sibling_stats` § Key Component
  Design sub-heading with the resolver signature, lookup rules, three
  exception types, the dispatcher-vs-op-handle decision, and the
  read-through note; § Cross-Cutting Concerns > Caching paragraph on
  the loose-coupling cache-identity choice; § Data Models
  `TransformationOp` row extended with `StatsFromInstanceSpec` and the
  mutual-exclusion note; § Schema versioning sentence acknowledging
  tight coupling as a future `schema_version` bump; validator
  enumerated-count bumped 21 → 22.
- **`project-essentials.md`** — new `### Sibling-instance dependencies
  are loose-coupled in v1` reinforcement subsection (with the
  tempting-LLM-mistakes list: don't mix sibling `recipe_hash`, don't
  add stale-warning, don't copy sibling stats locally).

### Notes

- **Not cache-invalidating despite touching `recipe/`.** No pydantic
  field default changed; `stats_from_instance` lives inside the
  opaque `TransformationOp.params: dict[str, Any]`. Recipes that do
  not use the feature have identical canonical bytes pre- and
  post-upgrade. The canonical-hash pin (Story E.f gate at
  `tests/unit/test_canonical_hash_pin.py`) holds without modification.
  Despite the H.n umbrella story header preemptively labeling the
  release "cache-invalidating," the actual implementation chose an
  opaque-params shape rather than a new pydantic field, sidestepping
  invalidation entirely.

## [0.13.0] - 2026-05-22

### Added

- **Story H.m — `imagecorruptions_apply` Generation op + `[corruptions]`
  extras (FR-GEN-1).** New `Generation` operation in the
  `image_classification` plugin: applies Hendrycks-Dietterich (ICLR 2019,
  "Benchmarking Neural Network Robustness to Common Corruptions and
  Perturbations") image corruptions to each input record, emitting one
  output per `(corruption_type, severity)` pair with optional
  preserved-original copies. Per-record corruption seeds derived from
  the recipe master seed via `pipeline.workers.per_record_seed`, so
  output bytes are reproducible across runs and worker counts.

  - **`ImageCorruptionsApplyParams` pydantic model:** `corruption_types`
    (non-empty subset of the 19 canonical names), `severities` (each in
    `[1, 5]`, non-empty), `preserve_original: bool = False`, `tag_fields`
    (default `["corruption", "severity", "source_path"]`). Unknown
    names, duplicates, and out-of-range severities are rejected at
    `model_validate(...)` time.
  - **Vendored corruption module** at
    `src/datarefinery/plugins/image_classification/_corruptions.py`
    (Story H.m.1). Derived from upstream `imagecorruptions==1.1.2`
    (Apache-2.0, Claudio Michaelis; full attribution preserved in
    `_corruption_data/NOTICE.md`) and patched for current dependencies:
    `np.float_` → `np.float64` (NumPy 2.x); `multichannel=` →
    `channel_axis=` (scikit-image 0.21+); explicit `rng` threading for
    deterministic seeding under scikit-image's PCG64 default;
    `pkg_resources.resource_filename` → `importlib.resources` for the
    vendored frost JPEG textures (removes `setuptools<81` dependency);
    `scipy.ndimage.interpolation` → `scipy.ndimage` (deprecation). The
    upstream `imagecorruptions` package is **not** depended on; all 19
    corruptions execute on the project's existing NumPy 2.x /
    scikit-image 0.26 floor.
  - **`[corruptions]` extras group:** `scikit-image` +
    `opencv-python-headless`. Install with
    `pip install 'ml-datarefinery[corruptions]'`. The corruption
    *vocabulary* is in-tree (dependency-free `_corruption_names.py`) so
    recipe-time validation works without the extras; only execution
    requires them.

### Changed

- **`GenerationOp.params` field added.** Generation ops previously had
  no user-supplied params surface — only `seed` / `inputs` /
  `output_schema` / `applies_at`. Added `params: dict[str, Any] = {}`
  to `GenerationOp`; threaded through `pipeline/stages/generation.py`
  and the in-tree `duplicate_minority_class` op signature. Existing
  recipes that use Generation continue to validate (default-empty
  params); the canonical bytes of every such recipe now include an
  empty `"params": {}` entry. Per `project-essentials.md`'s "Cache
  identity is the reproducibility contract" pre-production rules,
  pre-prod invalidation is acceptable; the pinned canonical-hash
  fixture does not use Generation and is unchanged.
- **`duplicate_minority_class` OperationSpec parameters truthified.**
  The op never actually consumed `label_field` / `target_count` /
  `seed` as user-supplied params (those values come from `op.seed`,
  `Labels.field`, and a hard-coded majority count). OperationSpec now
  declares zero parameters across all three plugins (image_classification,
  tabular, text). Extends validator check 18 to cover Generation params,
  consistent with Filters / Transformations / Augmentations /
  Featurizations / Visualizations.

### Notes

- **Cache invalidation (pre-prod).** Introducing the new op kind and
  the `GenerationOp.params` field both perturb the canonical-form
  vocabulary. Pre-production invalidation is acceptable.

## [0.12.0] - 2026-05-22

### Added

- **Story H.l — `drop_by_label` filter op (FR-FILTER-3).** New `Filters`
  operation in the `image_classification` plugin: the destructive
  companion to FR-FILTER-1 / FR-FILTER-2 tagging. Reads
  `sample_per_class_tags` written by `sample_per_class` /
  `sample_per_class_fractional` and drops any record whose tag set
  intersects the `labels` parameter.

  - Parameter: `labels: list[str]` (non-empty, validated by frozen
    pydantic model `recipe.models.DropByLabelParams`).
  - Records without the tag field and records carrying only
    non-matching tags pass through unchanged. A `labels` entry that no
    record carries is a no-op rather than an error.
  - **Sibling-recipe split pattern.** Two recipes can replicate the
    same `sample_per_class` (or fractional) chain — same ops, same
    parameters, same seed — and then call `drop_by_label` with
    disjoint `labels` lists, peeling off byte-identical, non-
    overlapping sub-instances from a common labeled source.

### Notes

- **Cache invalidation (pre-prod).** Introducing the new op kind
  perturbs the canonical-form vocabulary the plugin advertises.
  Pre-production invalidation is acceptable per
  `project-essentials.md` § "Cache identity is the reproducibility
  contract" pre-production rules.

## [0.11.0] - 2026-05-22

### Added

- **Story H.k — `sample_per_class_fractional` filter op
  (FR-FILTER-2).** New `Filters` operation in the
  `image_classification` plugin: per-class subsampling at independent
  rates. Per-class surviving count = `floor(n_per_class_base *
  fractions.get(label, 1.0))`. Missing labels default to 1.0 (full base
  count); `fractions[label] = 0.0` drops that class entirely.

  - Parameters: `n_per_class_base: int > 0`, `fractions: dict[str,
    float]` (each in `[0.0, 1.0]`), `seed: int`, plus inherited `label`
    and `exclude_already_labeled` from FR-FILTER-1. New frozen pydantic
    model `recipe.models.SamplePerClassFractionalParams`.
  - Same disjoint-pool tagging mechanism as `sample_per_class`: a
    `sample_per_class_fractional` op can chain with a
    `sample_per_class` (or another fractional) via
    `exclude_already_labeled` to construct controlled-imbalance datasets
    disjoint from a balanced training pool.

### Changed

- **Shared stratified-sampling helper.** Extracted the per-record-seeded
  ranking + label-tagging logic from `sample_per_class` (H.j) into
  `plugins/image_classification/filters_stratified_sampling.py`
  (`stratified_seeded_sample`). Both H.j and H.k ops now call into the
  helper with their respective per-class target derivations. Behavior of
  `sample_per_class` is unchanged; the canonical-hash pin (the fixture
  recipe does not use either op) is unchanged.

### Notes

- **Cache invalidation (pre-prod).** Introducing the new op kind
  perturbs the canonical-form vocabulary the plugin advertises.
  Pre-production invalidation is acceptable per
  `project-essentials.md` § "Cache identity is the reproducibility
  contract" pre-production rules.

## [0.10.0] - 2026-05-21

### Added

- **Story H.j — `sample_per_class` filter op with disjoint-pool labeling
  (FR-FILTER-1).** New `Filters` operation in the `image_classification`
  plugin: stratified-by-label deterministic subsampling (`n_per_class`
  records per label, seeded via the existing per-record-seeding scheme
  in `pipeline.workers.per_record_seed`). The selection is invariant to
  input ordering and worker count.

  - **Two modes.** When `label` is omitted the op is destructive — only
    the chosen records pass through. When `label` is supplied the op is
    non-destructive marking: the full record set passes through and the
    chosen records are tagged in `sample_per_class_tags`. The
    destructive cut happens in a follow-up op (another
    `sample_per_class` with `exclude_already_labeled`, or `drop_by_label`
    in H.l).
  - **Disjoint-pool pattern.** Chaining two `sample_per_class` ops with
    the second referencing the first's `label` in
    `exclude_already_labeled` selects two non-overlapping balanced sets
    from one labeled source in a single recipe.
  - New pydantic model `recipe.models.SamplePerClassParams` (frozen):
    `n_per_class: int > 0`, `label: str | None`, `exclude_already_labeled:
    list[str] | None`. Validated inside the op via `model_validate`;
    recipe-level validation still routes through the plugin's
    `OperationSpec` (check 18).

### Changed

- **Cache invalidation (pre-prod).** Introducing a new op kind perturbs
  the canonical-form vocabulary the plugin advertises. Pre-production
  invalidation is acceptable per `project-essentials.md` § "Cache
  identity is the reproducibility contract" pre-production rules. The
  pinned canonical-hash fixture in
  `tests/unit/test_canonical_hash_pin.py` does not use the new op and is
  unchanged.

## [0.9.4] - 2026-05-12

### Documentation

- **Story H.h — README check-count fix + PyPI installability promoted
  to a requirement.** Doc-only cleanup; no code, tests, or workflows
  touched.

  - `README.md` CLI verbs table: `validate` now correctly says
    "Schema + 21 enumerated static logical checks" (was "18" —
    stale since H.a, H.b, and H.d added checks 19, 20, and 21).
  - `docs/specs/features.md` § Usability Requirements gains a new
    bullet, **Discoverable installation**, codifying that
    `pip install ml-datarefinery` from a clean Python 3.12 venv
    works with no extra configuration and explaining the
    distribution-name / import-name divergence.
  - `docs/specs/features.md` § Acceptance Criteria gains AC 12: the
    PyPI install succeeds in a clean venv and exposes
    `import datarefinery` plus the `datarefinery` console script.
    Verified manually on each release per the releasing guide.
  - `docs/specs/tech-spec.md` § Publishing: the "First publish" line
    is simplified from a v0.9.2/v0.9.3 conditional (written while
    H.f and H.g were both in flight) to the concrete
    "v0.9.3 (Story H.g). Pre-v0.9.3 tags exist but were never
    published to PyPI."

  No canonical-hash shift; no code surface affected.

## [0.9.3] - 2026-05-12

### Removed

- **Story H.g — Drop GitHub Releases workflow.** Removed
  `.github/workflows/release.yml`, which shipped in Story F.f and
  created a parallel GitHub Release object on every `v*` tag push.
  `publish.yml` is now the sole tag-triggered workflow; PyPI is the
  only distribution surface, and `CHANGELOG.md` is the canonical
  release log (visible directly in the repo and via the git tag's
  context on GitHub).

  No behavior change for end users — `pip install ml-datarefinery`
  still works identically. The "Releases" page on github.com no
  longer auto-populates on new tags; if a release object is wanted
  for a specific version after the fact, run `gh release create vX.Y.Z
  --notes-file <(awk ...)` manually.

  Setup simplification: `release.yml` did not have any preconditions
  (no environment / token / binding), so there is nothing to clean up
  on GitHub for this change.

  No code or tests touched; canonical-hash pin unchanged.

## [0.9.2] - 2026-05-12

### Fixed

- **Story H.f — Drop TestPyPI from publish workflow.** The
  `publish.yml` shipped in H.e (v0.9.1) included a `publish-testpypi`
  job that referenced a GitHub Actions environment named `testpypi`
  which did not exist in the repo. The v0.9.1 tag's publish run
  failed in CI at the TestPyPI step before reaching the production
  PyPI upload, so no successful PyPI publish ever happened for
  v0.9.1.

  This release removes the TestPyPI half entirely. The publish
  workflow is now a single `build → publish-pypi` flow; PyPI is the
  only upload target. The required-reviewer protection on the `pypi`
  GitHub environment continues to gate each production publish.

  Setup simplification: only one PyPI trusted-publisher binding
  (`ml-datarefinery` on https://pypi.org) and one GitHub Actions
  environment (`pypi`) need to exist before publishing. The
  TestPyPI/`testpypi` binding documented in v0.9.1's release notes is
  no longer required and can be deleted if it was created.

  No code or tests touched; canonical-hash pin unchanged. First
  *successful* PyPI publish is v0.9.2.

## [0.9.1] - 2026-05-12

### Changed

- **Story H.e — PyPI publish under `ml-datarefinery`.** Reverses the
  deferred-PyPI decision recorded for Phase G. The unprefixed
  `datarefinery` name on PyPI was taken before this project began, so
  the distribution now ships as **`ml-datarefinery`**. The Python
  import name and CLI script name are unchanged — users write
  `import datarefinery` and run `datarefinery --help` exactly as
  before; only the `pip install` command changes:

  ```bash
  pip install ml-datarefinery               # was: pip install datarefinery
  pip install 'ml-datarefinery[llm]'        # was: pip install 'datarefinery[llm]'
  ```

  Same shape as `scikit-learn` / `import sklearn`.

  - `pyproject.toml`: `[project].name` set to `ml-datarefinery`. The
    `packages`, `[project.scripts]`, and
    `[project.entry-points."datarefinery.plugins"]` entries are
    unchanged, so the wheel still installs the `datarefinery` package
    and console script.
  - New `.github/workflows/publish.yml`: on `v*` tag push, builds
    sdist + wheel and publishes to TestPyPI (env `testpypi`) and
    PyPI (env `pypi`, gated by required-reviewer protection) via
    PyPI Trusted Publishing (OIDC; no long-lived API tokens in the
    repo). Runs alongside the existing `release.yml`.
  - `.github/workflows/release.yml`: the "PyPI upload is deferred"
    comment is gone; the GitHub Release continues to be created from
    the same tag and CHANGELOG section.
  - `README.md`, `docs/guides/releasing.md`, `docs/specs/tech-spec.md`
    updated for the new install command and the one-time
    trusted-publisher setup (PyPI pending-publisher binding plus
    GitHub Actions environments `pypi` and `testpypi`).
  - No canonical-recipe-hash shift — the distribution name is not in
    `Recipe`; `test_canonical_hash_pin` continues to pass at
    `11a6ca0fd15e2995092fe6755ff188c05e9e814344209a9b6926a420fd487731`.

  Existing recipes do not need to be edited. Existing developer
  installs (`pyve run pip install -e .`) keep working — the editable
  install resolves the `ml-datarefinery` distribution but exposes the
  `datarefinery` import and script the same way it always did.

## [0.9.0] - 2026-05-12

### Added

- **Story H.d — Unlabeled partition support.** Adds first-class support
  for partitions that ship without labels — the Kaggle/inference-set
  shape where a heldout partition exists only for downstream prediction.
  A new `InputSource.unlabeled: bool` flag (default `False`) declares
  that a source's records arrive without labels; the loader honors the
  declaration and threads the records through label-independent stages
  (resize, normalize, augmentation) so they land in the materialized
  instance as a usable dataset for downstream inference. Label-dependent
  stages (`stratify_by`, `filter_by_label`, label-reading featurizations)
  are rejected at validate time via the new validator check 21
  (`unlabeled_consistency`).

  Recipe shape:

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
  Splits:
    ratios: { train: 0.85, val: 0.15 }
    applies_to: train                    # only sub-partition the labeled side
    stratify_by: label
  ```

  Pydantic-level validation: `unlabeled: true` requires the source to
  declare a `partition` and forbids `label_from`. Validator check 21
  adds the remaining cross-section rules:

  - `unlabeled: true` requires `type: image_flat` (v1 restriction;
    `image_folder` derives labels from class subdirectories, which
    contradicts the declaration). Users with an existing flat-directory
    `image_folder` layout rewrite it as `image_flat`.
  - `Splits.stratify_by` is rejected when `Splits.applies_to` names an
    unlabeled partition (no label field to stratify by).
  - `filter_by_label` filters and `label_from_path` featurizations
    targeting an unlabeled split are rejected.

  Reporting:

  - `drift.json` reports `class_distribution: null` for unlabeled splits
    with a `"skipped: unlabeled"` note (new `SplitDriftRecord.note`
    field).
  - `report.md` flags unlabeled splits with `*(unlabeled)*` in the
    Splits section.
  - `OutputExpectations` whose `field` equals `Labels.field` treat
    records lacking the field as "skipped" rather than failures when
    any source declares `unlabeled: true`. Records where the field is
    present but `None` still fail — `required_field: <label>` can now
    coexist with an unlabeled partition.

### Changed

- **Cache identity shift.** Adding `unlabeled: false` as a pydantic
  default on `InputSource` shifts the canonical recipe bytes for every
  existing recipe. The pinned canonical hash in
  `tests/unit/test_canonical_hash_pin.py` moves to
  `11a6ca0fd15e2995092fe6755ff188c05e9e814344209a9b6926a420fd487731`.
  Pre-production rules apply per `project-essentials.md` § "Cache
  identity": users re-materialize after upgrade; no migration ceremony
  required. Recipes do not need to be edited; the new field defaults to
  `false` and existing recipes continue to validate unchanged. Recompute
  cost: every materialized instance is invalidated and must be rebuilt
  on first access; the per-instance cost is one full pipeline run.

### Documentation

- `features.md` FR-2 enumerated checks: added 21 (`unlabeled_consistency`).
- `features.md` Inputs: fourth example added for the labeled-train +
  unlabeled-test shape.
- `features.md` FR-7 Splits: Behavior bullet 6 documents the unlabeled
  partition flow; FR-22 Labels: bullet 5 covers the
  `OutputExpectations` skip rule.
- `tech-spec.md`: validator section bumped to "21 enumerated checks";
  `InputSection` row in Data Models gains `unlabeled: bool = False` and
  model-level validation notes.
- `docs/guides/recipe-authoring.md`: new "Unlabeled partitions"
  subsection under § Input → Pre-partitioned sources.
- `README.md`: new "Unlabeled partitions (Kaggle-style test set with no
  labels)" subsection under Quickstart.

## [0.8.1] - 2026-05-12

### Changed

- **Story H.c — `features.md` + `tech-spec.md` alignment with H.a + H.b.**
  Documentation-only catch-up: the specs now reflect the structured
  `LabelFromSpec`, the `image_flat` source type, the
  `InputSource.partition` field, the `SplitsSection.applies_to` field,
  validator checks 19 and 20, and the new `pipeline/inputs.py` module
  that shipped in v0.7.0 and v0.8.0. No code changes; no behavior
  changes; no test changes.

  - `features.md` Inputs prose tightened ("multiple sources may be
    joined by a declared key" replaced with an accurate v1 description:
    sources are independent; the only v1 join is sidecar-manifest label
    joining within an `image_flat` source via `label_from`).
  - `features.md` Inputs: third example added for pre-partitioned
    Kaggle-style `train/` + `test/` sources.
  - `features.md` FR-2 enumerated checks: added 19 (`label_from_spec_resolves`)
    and 20 (`partitions_consistent`).
  - `features.md` FR-7 Splits: Behavior bullet 5 documents partition-honoring
    and sub-partition modes; Edge Cases note the partition-related failures
    caught by `validate` and the load-time defensive check.
  - `features.md` FR-22 Labels: Behavior bullet 4 connects the
    sidecar-manifest direct-label route (the `image_flat` + `label_from`
    shape from `Input`) back to `Labels.source.kind: direct`.
  - `tech-spec.md` Package Structure: added `pipeline/inputs.py`; bumped
    the `validator.py` comment from `checks 1–18` to `checks 1–20`.
  - `tech-spec.md` `recipe.validator` section heading prose: "18
    enumerated checks" → "20 enumerated checks".
  - `tech-spec.md` Data Models: `InputSection` row updated to include
    optional `label_from` and `partition`; new `LabelFromSpec` row with
    the headerless/headered semantics; `SplitsSection` row gained
    `applies_to`.
  - `tech-spec.md` `scaffolder.init`: noted that within
    `image_classification` the v1 scaffolder emits `image_folder`
    recipes only; `image_flat` + `label_from` users hand-author the
    recipe.

## [0.8.0] - 2026-05-12

### Added

- **Story H.b — InputSource partitions: honor pre-existing train/test
  directories.** Adds first-class support for datasets that ship
  pre-partitioned (Kaggle-style `train/` plus `test/`). Each
  `Input.sources[*]` may declare `partition: <name>`; the loader stamps
  the declared value onto every record from that source; the Splits
  stage honors the declared partitioning instead of pooling-then-
  shuffling. Two recipe shapes:

  - **Form A — pure honor.** Omit `Splits` (or write `Splits: {}`); the
    materialized instance carries one split per declared partition,
    record-for-record from the source directory.
  - **Form B — sub-partition.** Set `Splits.applies_to: <partition>`
    with `ratios: {...}` to carve sub-splits out of a single declared
    partition (typically `train` → `train`/`val`); sibling partitions
    (e.g. `test`) are preserved verbatim. `stratify_by` applies only
    within the named partition.

  ```yaml
  Input:
    sources:
      - name: train_data
        type: image_folder
        path: ./data/train
        partition: train                  # NEW
      - name: test_data
        type: image_folder
        path: ./data/test
        partition: test                   # NEW
  Splits:
    ratios: { train: 0.85, val: 0.15 }
    applies_to: train                     # NEW: sub-partition only this
    stratify_by: label
    seed: 7
  ```

  **`partition` is now a reserved record-field name**, analogous to
  `record_id`. The loader stamps it on every record when declared; the
  validator (new check 20) rejects recipes that also declare a
  `partition` field in `Output.record_schema`.

  **New validator check 20 — `partitions_consistent`.** Enforces:
  all-or-nothing partition declaration across sources; `partition` is
  not declared in `Output.record_schema`; `applies_to` references a
  declared partition; sub-partition names don't collide with sibling
  partition names; `ratios` is empty when `applies_to` is unset (no
  global re-shuffle of partitioned sources).

  **Backward-compat is clean.** Recipes that don't declare `partition`
  on any source keep working exactly as before — loader pools, Splits
  partitions the whole stream. The new fields default to `None`/`{}`
  and are additive.

  **Cache identity:** the new fields participate in canonical recipe
  bytes; the canonical-hash pin (`test_canonical_hash_pin`) shifted
  accordingly. Pre-production rules apply per
  `project-essentials.md` § "Cache identity": users re-materialize
  after upgrade, no migration ceremony required.

### Changed

- `Recipe` validator check count is now **20** (was 19). CLI output
  reports `20/20 checks passed` on clean recipes.
- Validator check 8 (`splits_partition_correctly`) is relaxed: it no
  longer rejects an empty `Splits` section when at least one
  `InputSource` declares `partition`. Source partitions are a valid
  partitioning surface; check 20 enforces consistency.
- `features.md` § Recipe ⇢ Splits and `docs/guides/recipe-authoring.md`
  § Input + § Splits gained "Pre-partitioned sources" and
  "Sub-partitioning via `applies_to`" subsections.
- `README.md` § Quickstart gained a "Pre-partitioned sources
  (Kaggle-style train/test)" subsection.

### Migration notes

- No action required for existing recipes; the `partition` and
  `applies_to` fields are optional. Recipes that previously used a
  Featurization to parse `record_id` and emit a per-record partition
  field as a workaround can now drop that Featurization and declare
  `InputSource.partition` directly.

## [0.7.0] - 2026-05-12

### Added

- **Story H.a — InputSource sidecar labels + flat-image layout for
  image_classification.** Adds two capabilities, scoped together because
  the real-world sidecar-CSV use case requires both:

  1. **`image_flat` source type.** A new `InputSource.type` value for
     flat directories of images (no class subdirectories required).
     Sits alongside the existing `image_folder` (ImageFolder layout)
     type; each type has exactly one labeling mechanism, no overlay/
     override semantics, no heuristic layout detection.
  2. **`label_from` wired up.** `InputSource.label_from` was declared
     in the Pydantic model since v0.0.1 but never consumed in `src/`.
     Promoted from `str | None` to a structured `LabelFromSpec` model
     with four fields: `path`, `join` (`by_id` or `by_row_order`),
     `header` (optional column-name list when the manifest is
     headerless), and `id_field` / `label_field`. The
     `image_classification` loader joins the manifest into each record
     at load time, so records arrive at the pipeline with labels
     already populated and `Labels.source.kind` can stay `"direct"`.

  Three manifest shapes are supported uniformly:
  - Headered CSV (most common third-party shape) — `header` omitted;
    loader reads column names from the file's header row.
  - Headerless CSV — recipe provides `header: [<names>]`; file is
    treated as headerless. Recipe-as-truth: if the file actually
    contains a header line, the loader reads it as a data row. No
    heuristic detection (aligns with the project-essentials "Recipe is
    authoritative for data-pipeline semantics" rule).
  - CIFAR-style row-order — `join: by_row_order` with a single-column
    `header`. Manifest row count must equal the source's enumerated
    image count.

  **Validator check 19 (`label_from_spec_resolves`)** enforces the
  invariants at validate time so authoring errors surface before
  materialize runs: manifest exists, column references resolve, no
  duplicate ids for `by_id`, row counts match for `by_row_order`, and
  type-vs-`label_from` consistency (`image_folder` + `label_from` →
  fail; `image_flat` without `label_from` → fail).

  **Cache identity:** for `image_flat` sources, the input hash now
  includes a digest of the manifest's bytes alongside the image-tree
  digest, so edits to `labels.csv` invalidate the cache without
  re-touching any image. Pre-production rules apply per
  `project-essentials.md`: re-materialize after upgrade, no migration
  ceremony required. The canonical-hash pin (`test_canonical_hash_pin`)
  was updated for the `LabelFromSpec` model change — the fixture recipe
  no longer carries the obsolete `label_from: parent_directory_name`
  string, which was a placeholder for the unused old field.

### Changed

- `Recipe` validator check count is now **19** (was 18). The new check
  is `label_from_spec_resolves`; CLI output reports `19/19 checks
  passed` on clean recipes.
- `features.md` § Raw data sources updated with both ImageFolder and
  flat+manifest example recipe shapes.
- `docs/guides/recipe-authoring.md` § Input and § Labels expanded to
  document the two source types, the three `label_from` modes, the
  recipe-as-truth header rule, and the join-mode semantics.
- `README.md` § Quickstart gained an "Alternative layout: flat
  directory + sidecar labels" subsection.

### Migration notes

- Existing recipes carrying `label_from: parent_directory_name` (or
  similar string values) no longer parse — that field is now a
  structured `LabelFromSpec` model. The pre-existing string values were
  never read by any production code; remove the line. `image_folder`
  sources do not need `label_from` (labels come from subdir names).

## [0.6.4] - 2026-05-12

### Added

- **Story G.c — Release Automation Polish.** Added
  `.github/workflows/release.yml` triggered on `v*` tag pushes. The
  workflow resolves the version from the tag, verifies
  `pyproject.toml` agrees, extracts the matching `## [X.Y.Z]`
  section from `CHANGELOG.md` (up to the next `## [` heading), and
  calls `gh release create` to publish a GitHub Release with that
  body. The workflow refuses to publish if the tag and
  `pyproject.toml` disagree or if `CHANGELOG.md` has no matching
  section — making tag-without-bump and bump-without-changelog
  failure modes loud rather than silent.

  Added `docs/guides/releasing.md` documenting the end-to-end
  procedure (bump → CHANGELOG → tag → workflow → verify),
  including the explicit note that PyPI publishing is deferred
  (the `datarefinery` name is taken on PyPI; the GitHub Release is
  the release artifact) and the recovery procedure for a mis-tagged
  push.

  Tag protection (`v*` restricted to maintainers) remains a
  developer-configured repo setting (GitHub UI → Settings → Tags),
  documented in the guide but not expressible in workflow YAML.

## [0.6.3] - 2026-05-12

### Added

- **Story G.b — Coverage Badge (Codecov).** Wired the existing
  `pytest --cov` run in CI to upload `coverage.xml` to Codecov via
  `codecov/codecov-action@v5`, one upload per matrix leg keyed by
  `flags: ${{ matrix.os }}`. Added `.codecov.yml` mirroring the
  `features.md` thresholds: project-wide gate at 85% marked
  `informational: true` for the pre-production window (flip at v1.0.0
  per Acceptance Criterion 10), plus a `core_invariants` component
  bundling the same eight modules listed in
  `[tool.coverage.datarefinery]` with a 95% project status — keeping
  Codecov's reporting view aligned with the per-module CI gate (which
  remains the enforcement point). Added Codecov + CI status badges to
  `README.md`.

  The Codecov uploader is tokenless on public repos; the workflow
  passes `token: ${{ secrets.CODECOV_TOKEN }}` so the same step keeps
  working if the repo is ever private or the org enables the
  upload-token requirement. `fail_ci_if_error: false` keeps a Codecov
  outage from masking real CI failures.

  Operational follow-ups for the developer (out of scope for the LLM):
  - On the first PR after merge, confirm the Codecov status check
    appears on the PR and the README badge resolves once `main` has
    been uploaded at least once.

## [0.6.2] - 2026-05-11

### Added

- **Story G.a — GitHub Actions: Lint + Type + Test.** Added
  `.github/workflows/ci.yml` running on every pull request and on
  pushes to `main`. Matrix runs Python 3.12 on `ubuntu-latest` and
  `macos-latest`, installs runtime + dev dependencies via plain `pip`
  (pyve's two-environment isolation is a local-dev convenience; CI
  uses a single throwaway env), and executes the same four gates the
  developer runs locally: `ruff check`, `ruff format --check`,
  `mypy --strict`, and `pytest --cov`. A final step reads the
  core-invariant module list and threshold from
  `[tool.coverage.datarefinery]` in `pyproject.toml` and enforces
  `coverage report --include=<module> --fail-under=95` per module —
  the gate stays single-sourced in `pyproject.toml` (per the comment
  block above the section), and the CI step picks it up at run time.
  All eight core-invariant modules currently sit at 96–100%.

  Operational follow-ups for the developer (out of scope for the LLM):
  - Configure branch protection on `main` to require both
    `ci (ubuntu-latest, 3.12)` and `ci (macos-latest, 3.12)` as
    status checks (GitHub UI → Settings → Branches; pickable after
    the workflow has run once).
  - Verify by introducing a deliberate lint violation in a feature
    branch + PR and confirming CI fails on both OS legs.

## [0.6.1] - 2026-05-11

**Test Release — Validation of feature fit.**

This is a test release, not a production release. Per `features.md` and
`project-essentials.md`, the bump to `v1.0.0` is intentionally postponed
until thorough downstream testing and confirmation of feature fit. Pre-
production cache-invalidation rules still apply (see
`project-essentials.md` § "Cache identity is the reproducibility
contract").

### Changed

- Pre-release lint/type cleanup so `features.md` Acceptance Criterion 10
  (*"`ruff` and `mypy --strict` pass clean"*) is demonstrably met:
  - **Story F.d — Fix ruff format drift.** Ran `ruff format` across
    `src/` and `tests/`; 86 files reformatted (45 `src/`, 41 `tests/`).
    Whitespace-only — no logic, identifier, or import changes
    (AST-equivalence spot-checked on representative files from `src/`,
    `tests/unit/`, and `tests/integration/`).
  - **Story F.e — Fix `mypy --strict` errors.** Drove `mypy --strict`
    from 104 errors → 0. Test-side type-annotation work only; `src/`
    was already clean and is untouched. Highlights: widened fixture
    builders (`_records`, `_splits`, `_record`, `_path_record`) from
    `dict[str, Any]`-flavored returns to `Mapping[...]`-flavored
    returns to satisfy `list[Mapping[...]]` invariance at stage-helper
    call sites; stripped 10 stale `# type: ignore[arg-type]` comments
    that mypy now flagged as unused; added focused
    `# type: ignore[attr-defined]` to two `monkeypatch.setattr` sites
    that reach into a module's imported submodule namespace; added
    `Operation` return annotation to the two test-fixture dummy
    plugins; annotated an empty-list dict literal in the drift tests.
    No `mypy --strict` configuration was weakened.

### Verified

- All 11 numbered items in `features.md` § "Acceptance Criteria" are
  demonstrably met by stories already `[Done]` (Phases A–E plus F.a–F.e).
- `pyve testenv run mypy src tests` → 0 errors across 130 source files.
- `pyve testenv run ruff check src tests` → all checks passed.
- `pyve testenv run ruff format --check src tests` → 130 files already
  formatted.
- `pyve test` → 639 passed.
- `python -m build` produces a clean wheel; `pip install` of that wheel
  in a fresh venv succeeds; `datarefinery check` reports environment
  soundness; the `init → validate → materialize` golden path passes on
  the installed wheel.

## [0.6.0] - 2026-05-11

### Added

- README expanded with quickstart (Story F.a) — opens Phase F:
  - Installation: PyPI install plus a from-source path that documents
    the pyve two-environment workflow (runtime venv + testenv).
  - Quickstart walking through `init → validate → materialize →
    status` against an image_classification folder layout, with the
    expected on-disk cache layout (`recipe.yaml`, `manifest.json`,
    `dataset/`, `fitted_statistics/`, `report/`).
  - Recipe anatomy: an end-to-end YAML example mirroring the
    scaffolder output, plus a section-by-section table covering
    Input, Output, Labels, SampleData, InputContracts, Filters,
    Generation, Splits, Transformations, Augmentations,
    Featurizations, OutputExpectations, Visualizations, and
    variants.
  - CLI verb summary table (`check`, `init`, `validate`,
    `materialize`, `status`, `report`, `inspect`, `clean`) with FR
    cross-references, plus the execution-context flag/env-var table.
  - Plugin model overview citing the v1 set
    (image_classification first-class; tabular and text as stubs)
    and pointing at `plugins/base.py` for the protocol.
  - Library API example covering both the one-shot `materialize`
    convenience and the lower-level `DataRefinery.from_recipe`
    surface; verified against the CIFAR-10-shaped fixture.
  - "v1 scope and non-goals" section sourced from `concept.md`.
  - Cross-links to `docs/specs/concept.md`,
    `docs/specs/features.md`, and `docs/specs/tech-spec.md`.
- Recipe Authoring Guide at `docs/guides/recipe-authoring.md` (Story
  F.b; doc-only, shares the F.a release):
  - Section-by-section walk-through of every recipe surface
    (`Input`, `Output`, `Labels`, `SampleData`, `InputContracts`,
    `Filters`, `Generation`, `Splits`, `Transformations`,
    `Augmentations`, `Featurizations`, `OutputExpectations`,
    `Visualizations`, `variants`).
  - Dedicated treatments of fit-on-train discipline (why
    `fit_source: train` is the only accepted value and where the
    statistics land on disk), variants (cache-identity implications,
    when to overlay vs. fork a recipe), `InputContracts` /
    `OutputExpectations` (assertion-kind table with required keys),
    and the Filters-vs-Splits decision for class imbalance.
  - A complete reference recipe that materializes against the
    CIFAR-10-shaped fixture; the default and `--variant no_augment`
    materializations were both verified end-to-end. Subsidiary
    snippets (Filters with `random_sample` and `filter_by_label`)
    were composed into materializable recipes and verified against
    the same fixture.
  - Cross-linked from `README.md` and `docs/specs/concept.md`.
- Plugin Authoring Guide at `docs/guides/plugin-authoring.md` (Story
  F.c; doc-only, shares the F.a release):
  - `Plugin` protocol reference: the six required attributes
    (`name`, `supported_sections`, `supported_operations`,
    `schema_version`, `operation_factory`, `is_stub`) with a table
    keyed to each, plus the canonical 13-section list asserted by
    the cross-plugin contract suite.
  - `OperationSpec` and `ParameterSpec` walk-through: `parameters`,
    `fit_on_train`, `applicable_splits`, `applicable_sections` — and
    how each interacts with validator checks 5, 6, and 18.
  - Operation-handle shape summary across stages (Filters callables;
    Transformations / Featurizations `fit` + `apply` objects with
    `FittedValues`; Visualizations `render`), each pointing at the
    canonical `pipeline/stages/` Protocol and the
    `image_classification` operation as the reference
    implementation.
  - Discovery and registration: the `datarefinery.plugins`
    entry-point group for installed packages, and `--plugin-path`
    for development; discovery rules (uniqueness, protocol
    attributes, `datarefinery check` listing).
  - Stub vs. real plugin semantics tied to the cross-plugin contract
    test assertions.
  - Hello-plugin walk-through: a minimal `hello` plugin declaring
    one Featurization `echo` op, plus a minimal recipe targeting it.
    Verified end-to-end via `datarefinery --plugin-path
    hello_plugin.py check` (plugin listed `active`) and
    `validate hello-recipe.yaml` (18/18 checks pass) against the
    CIFAR-10-shaped fixture.
  - References to `tabular` and `text` stubs as starting templates,
    plus a versioning/stability note tied to FR-16's
    pre-production-vs.-post-production rules.
  - Cross-linked from `README.md`, `docs/guides/recipe-authoring.md`,
    and `docs/specs/concept.md`.

## [0.5.7] - 2026-05-09

### Added

- Generic plugin contract harness (Story E.h) — closes Phase E:
  - `tests/plugin_contract/conftest.py` uses `pytest_generate_tests`
    to parametrize every test that consumes a `plugin` argument
    across all plugins discovered via the entry-point group, with
    plugin names as test ids. Adding a new plugin opts it into the
    harness automatically — no per-plugin file required.
  - `tests/plugin_contract/test_protocol.py` ships five
    cross-plugin assertions:
    1. `isinstance(plugin, Plugin)` — runtime-protocol satisfaction.
    2. Non-empty, stripped string name.
    3. `supported_sections` is a subset of the canonical 13 recipe
       section names; a plugin that lists a non-canonical section is
       wrong at the contract layer even before any recipe references
       it.
    4. Every `supported_operations` entry round-trips through
       `OperationSpec.model_validate`; each declares at least one
       `applicable_sections`, all of which must be canonical.
    5. `is_stub()` reflects reality — stubs must raise from
       `operation_factory` for at least one declared op; non-stubs
       must construct cleanly for at least one declared op. The
       asymmetry is intentional: a non-stub may ship some
       not-yet-implemented ops alongside real ones, but a plugin that
       claims to be a stub and yet successfully constructs operations
       breaks the materialize-time refusal contract.
  - Existing per-plugin contract files (`test_image_classification.py`,
    `test_tabular.py`, `test_text.py`) still cover plugin-specific
    schema assertions that go beyond the protocol.

### Tests

- 15 new parametrized tests (5 generic assertions × 3 discovered
  plugins).

## [0.5.6] - 2026-05-09

### Added

- Coverage configuration and per-module gates (Story E.g):
  - `[tool.coverage.run]` defaults `pyve test --cov` to the
    `src/datarefinery` package.
  - `[tool.coverage.report]` enables show-missing and excludes
    `pragma: no cover`, `raise NotImplementedError`, and
    `TYPE_CHECKING:` blocks.
  - `[tool.coverage.datarefinery]` (project-private TOML table)
    declares `core_invariant_modules` (the eight modules that gate the
    FR-4 reproducibility contract — `recipe.loader`,
    `recipe.canonical`, `cache.identity`, `cache.atomic`,
    `pipeline.stages.splits`, `pipeline.workers`, `plugins.base`,
    `plugins.discovery`) and `core_invariant_threshold = 95`. Phase G
    CI consumes this table via Python; `pytest-cov` doesn't natively
    support per-module `fail_under`.
  - The project-wide percentage gate is intentionally unset
    pre-production; an inline `# pre-prod: project-wide gate enabled
    at production release` comment marks the spot.

### Tests

- 3 new unit tests in `tests/unit/test_plugins_discovery.py`
  back-filling coverage of `plugins.discovery`:
  - Extra-path module without a top-level `PLUGIN` attr is ignored
    silently.
  - Extra-path module that fails to import surfaces as `PluginError`.
  - Top-level `PLUGIN` attr that doesn't satisfy the Plugin protocol
    raises with a class-named message.
  - These move the discovery module from 88% → 96% coverage. The two
    remaining uncovered lines are the entry-point class-instantiation
    branch and the `spec_from_file_location` defensive None-spec
    branch — both genuinely hard to exercise without full entry-point
    setup.

## [0.5.5] - 2026-05-09

### Added

- Cache-identity pinning gate (Story E.f, FR-4):
  - `tests/unit/test_canonical_hash_pin.py` is a single-test module
    pinning the canonical SHA-256 digest of a representative fixture
    recipe. A failed assertion walks the reviewer through the
    four-step ceremony from `project-essentials.md` "Cache identity
    is the reproducibility contract — invalidations are ceremonious":
    bump `SUPPORTED_SCHEMA_VERSIONS`, ship a migration, announce
    blast radius, update the pin in the same commit. Pre-production
    versus post-production rules are both spelled out so a future
    bump doesn't mis-apply the wrong ceremony level.
  - Module docstring includes a one-liner for legitimately
    regenerating the digest after a deliberate cache-invalidating
    change.

### Changed

- Removed the duplicate canonical-hash pin from
  `tests/unit/test_canonical.py` so the gate is single-source. The
  remaining tests in `test_canonical.py` cover cosmetic-edit
  invariance, value-edit sensitivity, and JSON wellformedness.

## [0.5.4] - 2026-05-08

### Added

- Per-stage failure-mode integration tests (Story E.e):
  - `tests/integration/test_failure_modes.py` parametrizes a forced
    failure across 10 stage labels (`InputContracts`,
    `Filters/pre_split`, `Splits`, `Filters/post_split`, `Generation`,
    `Transformations`, `Featurizations`, `Augmentations`,
    `OutputExpectations`, `Visualizations`). Plugin-op failures are
    injected via a `_FailingPlugin` wrapper around the
    `image_classification` plugin that raises from
    `operation_factory` whenever the named op is requested.
    Stage-driver failures use recipe shapes that trip the runner's
    own raise sites (record_count_min contract, key_assignment with
    unmapped records, non-train augmentation declaration).
  - Each case asserts the runner re-raises, the temp dir survives
    with a `FAILED` JSON marker naming the expected `current_stage`
    label, and the final cache path is never written to.
  - Tests bypass the FR-2 validator and instantiate
    `PipelineRunner` directly so failure recipes that intentionally
    violate FR-2 checks (e.g., the non-train augmentation case used
    to reach the augmentations-stage defensive guard) reach the
    runner unchanged.

## [0.5.3] - 2026-05-08

### Added

- End-to-end determinism integration test (Story E.d):
  - `tests/integration/test_determinism_workers.py` runs the same
    fixture pipeline three times at `--workers 1/2/4` (each into a
    fresh cache root so the second and third runs don't short-circuit
    on cache hit) and asserts the resulting instance directories are
    byte-identical. `manifest.json` is normalized by stripping
    `created_at` and `elapsed_seconds` (intrinsically run-specific),
    and `report.md` is normalized by stripping the two corresponding
    "Created at:" / "Elapsed:" lines that render those manifest
    fields. A second sanity-guard test confirms those two fields
    actually vary across independent runs — without it the
    determinism check could pass vacuously if the fields turned
    stable.
  - Both tests are marked `slow`; `pytest -m 'not slow'` skips them
    so CI can run them on demand.

### Changed

- `pyproject.toml` now declares the `slow` pytest marker so
  `--strict-markers` passes for the new tests and so `pytest -m
  'not slow'` is the documented opt-out.

## [0.5.2] - 2026-05-08

### Added

- Hypothesis property tests for split determinism (Story E.c, FR-7):
  - `tests/unit/test_splits_determinism.py` with two property tests:
    - **Repeat-run determinism** (200 examples). For varied record
      counts (8-120), label sets (2-4 distinct values), ratio shapes
      (two-way + three-way), seeds, and optional stratification, two
      independent `apply_splits(...)` calls produce byte-identical
      partitions.
    - **Cross-worker determinism** (10 examples). Records are
      pre-processed through `pipeline.workers.run_parallel(workers=W)`
      with an identity worker function at `W ∈ {1, 2, 4}`; the result
      is then split with the same seed. All three worker counts must
      produce byte-identical partitions, validating the
      `project-essentials.md` "Determinism contract in
      `pipeline.workers`" rule that worker count must not leak into
      downstream stage output. The example budget is small because
      every example spawns three `ProcessPoolExecutor`s.

## [0.5.1] - 2026-05-08

### Added

- Hypothesis property tests for cache identity (Story E.b, FR-4):
  - `tests/unit/test_cache_identity_properties.py` with two property
    tests, each running for 1000 examples per
    `@settings(max_examples=1000)`:
    - **Cosmetic invariance.** A composite strategy deep-copies the
      baseline recipe dict, recursively shuffles every nested
      mapping's key order via a Hypothesis-drawn seed, re-emits
      through `yaml.safe_dump` with varying `indent` and
      `default_flow_style`, and splices in random blank/comment
      lines. The recipe-portion of `compute_cache_key` must remain
      identical across every generated text variant.
    - **Semantic divergence.** Ten mutator strategies (combined with
      `st.one_of`) that change `recipe.seed`, `Splits.seed`, split
      ratios, `Labels.field`, input source path, or add a `Filters`,
      `InputContracts`, `Visualizations`, or `SampleData` entry, or
      toggle `label_from`. Each must produce a different cache key
      than the baseline; the rare strategy-regenerates-baseline case
      is detected via a canonical-hash equality check and skipped.
  - These complement the example-based fixtures in
    `tests/unit/test_canonical.py` and the canonical-hash pin —
    together they make every reproducibility guarantee in
    `project-essentials.md` "Cache identity is the reproducibility
    contract" a test that fails loudly when broken.

## [0.5.0] - 2026-05-08

### Added

- CIFAR-10-shaped test-fixture synthesizer (Story E.a) — opens Phase E:
  - `tests/fixtures/build_cifar10_shaped.py` exposes
    `build_cifar10_shaped(root, *, num_classes, per_class,
    image_size, seed)` plus default constants. The default config
    produces 10 class folders × 5 PNGs each = 50 8×8 RGB images via a
    seeded `numpy.random.default_rng`, byte-stable across runs.
  - `tests/conftest.py` provides a session-scoped
    `cifar10_shaped_dir` pytest fixture so the synthesis cost (<1s
    locally) is paid once per session instead of per test.
  - Module docstring documents the "do not check in real CIFAR-10
    here" rule with rationale (size, licensing, repo bloat) and
    points contributors at a one-shot local download for tests that
    genuinely need the real dataset.
- Migrated `tests/integration/test_golden_path.py` (Phase D's closing
  integration test) to consume the new session fixture, proving its
  reusability and keeping per-test isolation via `shutil.copytree`.

### Tests

- 6 new self-tests in `tests/unit/test_cifar10_shaped_fixture.py`
  cover the default 50-PNGs/10-class layout, 8×8 RGB image
  dimensions, same-seed byte-identical output, different-seed
  divergence, the <1s build-time budget called out in the story, and
  that the session fixture is consumable by name.

## [0.4.9] - 2026-05-08

### Added

- Phase D golden-path integration test (Story D.j) — closes Phase D:
  - `tests/integration/test_golden_path.py` exercises the documented
    user journey end-to-end through the typer CLI: synthesizes a
    CIFAR-10-shaped fixture (10 classes, 3 PNGs each, 8x8 RGB,
    seeded), runs `datarefinery init`, simulates the "review and
    uncomment the suggested Transformations" step by inserting a
    fit-on-train normalize op, then runs
    `datarefinery validate` → `datarefinery materialize` →
    `datarefinery status` and asserts all four exit 0.
  - Asserts every artifact called out in the story task is present in
    the final instance: `manifest.json`, `recipe.json`, per-split
    JSONL files, `fitted_statistics/norm/{mean,std}.parquet`,
    `report/report.md`, `report/drift.json`, and the two scaffolded
    reporting visualizations (`class_distribution.png`,
    `samples.png`). Final invocation reruns `materialize` and
    asserts `cache=hit` plus no new promotion.

## [0.4.8] - 2026-05-08

### Added

- `datarefinery clean` CLI verb (Story D.i, FR-21):
  - `src/datarefinery/cli/commands/clean_cmd.py` registered on the
    typer app via `app.command("clean", ...)`. Selectors:
    `--by-recipe HASH`, `--by-age DAYS`, `--orphans`, `--all`. The
    library `cache.cleaner.clean(...)` already supported all of these
    via `CleanSelector`; this verb is a thin typer wrapper plus the
    FR-21 confirmation guard.
  - `--all` requires either an interactive TTY confirmation (via
    `typer.confirm`) or `--yes` for non-TTY use (CI, piped
    invocations). Refusing without `--yes` in a non-TTY context
    raises `CacheError` with a documented message rather than
    blocking on a prompt that can never be answered.
  - Refuses with `CacheError` when no selector is given, matching the
    FR-21 "no silent broad delete" rule.
  - Renders a `rich` table summary (cache root, removed count,
    skipped count) plus per-path tables on success.

### Tests

- 7 new CLI smoke tests in `tests/cli/test_clean_cmd.py`: no-selector
  refusal, `--by-recipe` removes only the matching recipe shard,
  `--by-age` removes backdated instances, `--orphans` removes old
  temp dirs in `.tmp/`, `--all` without `--yes` in non-TTY refuses
  (cache untouched), `--all --yes` wipes the cache, and the summary
  table renders.

## [0.4.7] - 2026-05-08

### Added

- `datarefinery inspect` CLI verb (Story D.h, FR-20):
  - `src/datarefinery/core/inspect.py` with `InspectionView` (frozen
    dataclass: `instance_path`, `exploration_views`, optional
    `rendered`, `fitted_op_ids`, `record_counts`, `sample_records`),
    `RenderedView` (in-memory PNG bytes), and
    `build_inspection_view(instance, plugin, *, view,
    peek_per_split)`. The FR-20 partial-instance refusal lives here so
    library and CLI callers are guarded identically.
  - `DataRefinery.inspect(instance_path=None, view=None)` is now a
    real method (was a `NotImplementedError` stub): when called
    without `instance_path`, it resolves the bound recipe to its
    cached instance via `status()` and raises `MaterializeError` on
    cache miss.
  - `src/datarefinery/cli/commands/inspect_cmd.py` registered on the
    typer app via `app.command("inspect", ...)`. Accepts either a
    recipe YAML or an instance directory. `--view NAME` renders the
    named exploration visualization on demand; `--out PATH` writes
    the PNG bytes (and is rejected without `--view`). No-`--view`
    mode prints three `rich` tables: overview (instance,
    exploration views, fitted-stats op ids), records-per-split, and
    a sample-records peek (first three rows per split from the
    persisted JSONL).

### Tests

- 8 new CLI smoke tests in `tests/cli/test_inspect_cmd.py`: list+peek
  mode, `--view --out` PNG round-trip (with PNG signature check),
  `--view` without `--out`, unknown-view error, partial-instance
  refusal (manifest mutated to `is_partial=True` reaches the
  documented refusal path), recipe-path resolution to the cached
  instance, recipe-path cache miss errors, and `--out` without
  `--view` validation.

## [0.4.6] - 2026-05-08

### Added

- `datarefinery report` CLI verb (Story D.g, FR-15.4):
  - `src/datarefinery/cli/commands/report_cmd.py` registered on the
    typer app via `app.command("report", ...)`. Loads the materialized
    instance, discovers the plugin matching `instance.recipe.plugin`,
    and re-renders `report.md`, `drift.json`, and every reporting-mode
    visualization in place. Never reruns the pipeline. Prints the
    paths it touched.
  - `pipeline.inputs.reload_dataset(instance_dir, plugin)` reads the
    persisted per-split JSONL files and re-inflates plugin-specific
    record fields. For `image_classification`, the `image` array is
    reloaded via PIL from each record's `path` field. (Other plugins
    are stubs; reload is not implemented for them in v1.)
  - `reporting.report.re_render_report(instance_dir, recipe, *,
    plugin=None)` now also rewrites `drift.json` (via
    `compute_drift_placeholder` over the reloaded splits) and the
    reporting-mode visualizations (via
    `apply_reporting_visualizations`) when a `plugin` is supplied.
    Without a plugin the function still re-renders `report.md`-only,
    matching the previous behavior — useful for library callers who
    have already validated stat consistency.
  - `Instance.render_report(*, plugin=None)` and
    `DataRefinery.report(instance_path)` forward the plugin through;
    the latter passes its own bound plugin so library callers don't
    have to re-discover.
- The FR-15 "stale fitted-stats" hard error is reachable from two
  places: `Instance.load` already rejects instance dirs whose
  persisted `recipe.json` doesn't canonicalize to `manifest.recipe_hash`
  (Story D.a), and `re_render_report`'s own check guards the
  call when `Instance.load` is bypassed.

### Tests

- 4 new CLI smoke tests in `tests/cli/test_report_cmd.py`: round-trip
  re-render restores `report.md`, `drift.json`, and the
  visualization PNG byte-identically; the verb's announce output
  names every artifact; tampered persisted recipe → `MaterializeError`;
  missing instance dir is a usage error.

## [0.4.5] - 2026-05-08

### Added

- `datarefinery status` CLI verb (Story D.f, FR-19):
  - `src/datarefinery/core/status.py` with `StatusReport` (frozen
    dataclass: `cache_status` ∈ {hit, miss, corrupt}, `cache_key`,
    `instance_path`, optional `manifest`, optional `note`) and
    `resolve_status(cache_root, key)`.
  - `DataRefinery.status()` is now a real method (was a
    `NotImplementedError` stub): hashes the recipe's input sources via
    `pipeline.inputs.hash_inputs`, computes the cache key, and
    inspects `<cache_root>/instances/<key>/manifest.json`.
  - `src/datarefinery/cli/commands/status_cmd.py` registered on the
    typer app via `app.command("status", ...)`. Accepts either an
    instance directory (`Instance.load` path) or a recipe YAML file
    (recipe-path resolution). Hit renders a three-table `rich` summary
    (metadata, records-per-split, optional warnings); miss/corrupt
    render a single status table with the resolved hashes and
    expected instance path. `cache=miss` exits 0 (not an error);
    corrupt instances surface a `datarefinery clean` pointer per the
    FR-19 edge case.

### Tests

- 4 new CLI smoke tests in `tests/cli/test_status_cmd.py`: recipe-path
  hit on a freshly materialized instance, recipe-path miss on an
  unmaterialized recipe (exit 0), instance-path mode, and the FR-19
  corrupt-instance edge case (manifest.json removed → `cache=corrupt`
  + clean pointer).

## [0.4.4] - 2026-05-08

### Added

- `datarefinery materialize` CLI verb (Story D.e, FR-3) — closes the
  init → validate → materialize golden path:
  - `src/datarefinery/cli/commands/materialize_cmd.py` registered on
    the typer app via `app.command("materialize", ...)`. Renders a
    `rich` progress bar (driven by per-stage callbacks from the
    runner) and a three-table summary on completion: top-level
    metadata (cache hit/miss, instance path, hashes, seed, variant,
    elapsed), records-per-split counts, and optional warnings.
  - `--stage NAME` selects a partial run that stops after the named
    stage and leaves the result in the temp directory (no promote)
    with the manifest marked partial. Valid stage names are listed
    in the `--help` output.
- Disk-backed input loader (`src/datarefinery/pipeline/inputs.py`)
  deferred from Stories C.m and D.a:
  - `load_raw_records(recipe, plugin)` inflates `recipe.Input.sources`
    into records and a per-source SHA-256 content-hash dict for cache
    identity. The `image_classification` ImageFolder loader walks
    `<root>/<class>/<file>.{png,jpg,jpeg}` and only attaches a
    `label` field when `Labels.source.kind=="direct"` (so
    derived-label recipes leave the field for the featurization
    stage to populate).
  - `tabular` and `text` plugins refuse with `PluginError` until
    their full implementations land post-v1.
- `PipelineRunner` enhancements:
  - `progress_callback: Callable[[str], None] | None` parameter on
    `.run(...)`; invoked at the start of each stage.
  - `stop_after: str | None` parameter validated against the new
    public `STAGE_NAMES` tuple; partial runs write a manifest with
    the new `completed_through: str | None` field on
    `Manifest`, set `is_partial=True`, and skip atomic promote.
  - `RunnerResult` gained `is_partial: bool` so callers can
    distinguish a partial run from a completed one.
  - `PipelineRunner` accepts an optional `variant` keyword and
    records it in `manifest.variant` (was hard-coded to `None`).
- `DataRefinery.materialize()` upgrades:
  - Optional `raw_records` / `raw_input_hashes` (kept for library
    callers); when omitted the disk loader runs.
  - New `stop_after` and `progress_callback` keywords pass through
    to the runner.
  - New `last_run` property exposes the most recent `RunnerResult`
    (so the CLI can surface cache hit/miss).
- Top-level `materialize(recipe_path, *, config, variant, seed)` now
  performs disk-backed loading internally (was a
  `NotImplementedError` stub pointing at this story).

### Tests

- 5 new CLI smoke tests in `tests/cli/test_materialize_cmd.py`:
  cache-miss → instance produced (manifest, recipe.json, dataset
  jsonl per split, report.md, drift.json), rerun cache-hit on the
  second invocation, partial stage run with persisted partial
  manifest (`is_partial=True`, `completed_through="Splits"`),
  invalid stage name rejected, missing recipe is a usage error.

## [0.4.3] - 2026-05-08

### Added

- `datarefinery init` CLI verb (Story D.d, FR-17):
  - `src/datarefinery/cli/commands/init_cmd.py` registered on the
    typer app via `app.command("init", ...)`. Wraps
    `datarefinery.scaffolder.init.scaffold(...)`. Options: `--input`
    / `-i` (raw-inputs root, must exist as a directory), `--output`
    / `-o` (recipe YAML path; parent directories created on demand
    by the scaffolder), `--plugin` (defaults to
    `image_classification`; non-image categories raise the
    documented v1 refusal), `--enhance` (opt-in optional LLM
    enhancement; missing `[llm]` extra raises `PluginError` with the
    `pip install 'datarefinery[llm]'` install snippet, inherited
    from `scaffolder.llm.enhance`).
  - On success the verb prints a green confirmation plus a
    `datarefinery validate <output>` next-step pointer.

### Tests

- 6 new CLI smoke tests in `tests/cli/test_init_cmd.py` covering
  the basic write, the init→validate round-trip (scaffolded recipe
  passes every FR-2 check), parent-directory creation, the
  `--enhance` missing-extra error path (via propagated `PluginError`),
  the non-image plugin refusal, and the missing-input usage error.

## [0.4.2] - 2026-05-08

### Added

- `datarefinery validate` CLI verb (Story D.c, FR-2):
  - `src/datarefinery/cli/commands/validate_cmd.py` registered on the
    typer app via `app.command("validate", ...)`. Takes a recipe path
    argument, calls `DataRefinery.from_recipe(...).validate()`, and
    renders the 18-entry `ValidationReport` as a `rich` table (id,
    status, descriptor, location, message) with a summary line.
  - Status column is color-coded (green pass, yellow warn, red fail).
  - Honors the shared `--variant` option from the root callback — the
    overlay is applied to the recipe before validation runs.
  - Exits 0 on a clean recipe (warnings allowed); exits 1 on any check
    failure (per the documented user-error exit code).

### Tests

- 5 new CLI smoke tests in `tests/cli/test_validate_cmd.py` covering
  the clean-recipe exit-zero path, the multi-violation exit-one path
  (no short-circuit), full 18-row rendering, missing-file usage error,
  and `--variant` overlay flow-through.

## [0.4.1] - 2026-05-08

### Added

- `datarefinery check` CLI verb (Story D.b, FR-18):
  - `src/datarefinery/core/check.py` with `build_check_report()` and
    frozen `CheckReport`, `PluginInfo`, `DependencyStatus` dataclasses.
    Reports DataRefinery version, Python version, platform, plugin
    entry-point group, extra plugin discovery paths, every discovered
    plugin (name, schema version, stub-vs-active, source module),
    optional `[llm]` extra (`lmentry`), and optional accelerators
    (Metal/MPS, CUDA). Plugin-discovery errors are caught and recorded
    in `failures` so the report remains constructible.
  - `DataRefinery.check(config=None)` is now a static delegator
    returning the same `CheckReport`.
  - Accelerator probe is gated on `importlib.util.find_spec("torch")`
    and only imports torch if installed; otherwise both Metal and CUDA
    are reported missing with the documented "torch not installed"
    detail.
  - `src/datarefinery/cli/commands/__init__.py` (new package) and
    `src/datarefinery/cli/commands/check_cmd.py` render the report as a
    stack of `rich` tables on stdout. The verb is registered on the
    typer app via `app.command("check", ...)`. Exits 0 on a healthy
    environment (with warning rows for missing optional deps), exits 2
    on a soundness failure (e.g., plugin discovery raising
    `PluginError`).

### Tests

- 10 new unit tests in `tests/unit/test_check.py` covering the
  structured-report shape, plugin enumeration, optional-extra and
  accelerator probes (with the torch-not-installed branch documented),
  the `passed` property, frozen-dataclass invariants, plugin-discovery
  failure capture, and `RuntimeConfig.plugin_path` flow-through.
- 6 new CLI smoke tests in `tests/cli/test_check_cmd.py` covering
  exit-zero on a healthy environment, plugin and extras rendering, and
  the exit-2 path when discovery fails.

## [0.4.0] - 2026-05-08

### Added

- Public library entry point (Story D.a) — Phase D opens:
  - `src/datarefinery/core/datarefinery.py` with the `DataRefinery`
    class. Construction (`from_recipe`) loads the recipe, applies any
    requested variant overlay, discovers and binds the declared plugin,
    and runs the FR-2 validator exactly once; the report is memoized
    behind `validate()` so subsequent calls are zero-cost. The class
    exposes `recipe`, `plugin`, `seed`, `variant`, `config`, `validate`,
    `materialize`, `report`, `clean`, and a `cache_key(raw_input_hashes)`
    method. Verbs whose CLI counterparts ship in later stories
    (`status` → D.f, `inspect` → D.h, `check` → D.b) are present as
    `NotImplementedError` stubs so the public class shape is stable.
  - `src/datarefinery/core/instance.py` with `Instance` frozen
    dataclass (`path`, `manifest`, `recipe`, `fitted_statistics`,
    `report_path`, `is_partial`) and `Instance.load(path)`.
    `fitted_statistics` is exposed lazily — construction performs no
    fitted-statistics I/O. `Instance.render_report()` re-renders the
    instance's `report.md` from persisted state without rerunning the
    pipeline (FR-15.4).
  - Top-level `materialize(recipe_path, *, config, variant, seed)`
    convenience matching the tech-spec signature; raises
    `NotImplementedError` pointing at Story D.e (the CLI verb wires the
    disk-backed input loader). Library callers use
    `DataRefinery.from_recipe(...).materialize(raw_records=...,
    raw_input_hashes=...)` until D.e ships.
  - Public re-exports in `datarefinery/__init__.py`: `DataRefinery`,
    `Instance`, `materialize`, `__version__`.
- Per-instance recipe persistence:
  - `<instance>/recipe.json` is now written by `pipeline.runner` as the
    canonicalized recipe used for the run. `Instance.load()` reads it
    back, parses it through `Recipe.model_validate_json`, and verifies
    the canonical hash matches `manifest.recipe_hash` — a tampered or
    inconsistent instance directory raises `MaterializeError`.
  - `cache.layout.recipe_path(instance)` helper.
- `PipelineRunner` accepts an optional `variant` keyword and records it
  in `manifest.variant` so future tooling can attribute an instance to
  its source variant.

### Tests

- 15 new unit tests in `tests/unit/test_datarefinery.py` covering
  public re-exports, validation memoization (the FR-2 validator is
  invoked exactly once per `from_recipe`), seed override, unknown-plugin
  rejection, `cache_key` composition, the materialize → `Instance.load`
  round-trip, recipe-hash mismatch detection, lazy
  `fitted_statistics`, `clean` routing through the configured cache
  root, and `NotImplementedError` stubs for the deferred verbs.

## [0.3.13] - 2026-05-08

### Added

- Deterministic image-classification scaffolder (Story C.o, FR-17) -
  Phase C complete:
  - `src/datarefinery/scaffolder/__init__.py` (package),
    `src/datarefinery/scaffolder/init.py`
    (`scaffold_image_classification(input_path, output_path, *,
    enhance=False)` and the top-level `scaffold(...,
    plugin="image_classification", ...)` dispatcher), and
    `src/datarefinery/scaffolder/llm.py` (lazy `lmentry` import +
    offline detection). The deterministic path performs no network
    I/O and never imports `lmentry`; `enhance=True` is the only
    surface that touches the optional extra.
  - Recipe inspection: walks the ImageFolder layout
    (`<root>/<class>/<file>.{png,jpg,jpeg}`), inspects the first
    image for shape and dtype, sorts class names. Raises
    `RecipeError` for non-directory inputs, missing class
    subdirectories, or missing image files - each error message
    cites the expected layout.
  - Generated recipe: declares `Input` (image_folder source pointing
    at the scanned directory), `Output` (record schema with `image`
    and `label`, plus `path` for downstream traceability and so
    validator check 7 sees it in the field universe), `Labels` (kind
    "derived", derivation "parent_directory_name"), `Splits` (70/15/15
    stratified by `label`, seed 11), a `label_from_path`
    Featurization populating `label`, and reporting Visualizations
    (`class_distribution_histogram`, `sample_grid`). A commented-out
    block of suggested `Transformations` (resize, normalize) is
    appended below the recipe so the user can uncomment and tune.
  - LLM enhancement (`scaffolder.llm.enhance`): missing `lmentry` ->
    `PluginError` pointing at the `[llm]` extra; offline detection
    fails (UDP-level reachability probe via `_is_online`) -> the
    deterministic recipe is emitted with a "LLM enhancement
    skipped: offline" note in the YAML header. Online with `lmentry`
    installed -> v1 placeholder marker note "LLM enhancement
    applied" (full LLM-driven judgment lands post-v1).
  - Non-image refusals: `scaffold(..., plugin="tabular")` and
    `scaffold(..., plugin="text")` raise `PluginError` with the
    documented "init scaffolder not available for this category in
    v1" message per features.md FR-17 edge cases.
  - `tests/unit/test_scaffolder.py` covers: scaffold writes a recipe
    with the expected header + schema_version + plugin; loaded
    recipe validates clean (all 18 checks pass); image dimensions
    inferred from the first image; 70/15/15 stratified split; derived
    label via `label_from_path`; both reporting visualizations
    present; commented-out suggested Transformations in YAML;
    parent-dir creation for output path; tabular/text refusals;
    non-directory and empty-directory error paths; missing-images
    error; LLM-without-lmentry `PluginError`; offline note in YAML;
    online "applied" note; deterministic path doesn't import
    lmentry; end-to-end materialize round-trip via the runner
    (synthetic records matching the scaffolded on-disk layout
    produce a complete instance with both reporting PNGs and full
    record counts); module exposes `scaffold` and
    `scaffold_image_classification` (21 tests).

### Notes

- v1 deviation: the materialize round-trip test synthesizes records
  matching the scaffolded directory layout in-memory because
  disk-based input loading was deferred from C.m. The CLI
  `materialize` verb (Story D.e) will wire scaffolded recipes through
  end-to-end disk loading.

## [0.3.12] - 2026-05-08

### Added

- Reporting: report.md + drift.json (Story C.n, FR-15):
  - `src/datarefinery/reporting/drift.py` defines pydantic
    `DriftSchema` (frozen, `extra="forbid"`) plus `SplitDriftRecord`
    and `FeatureDriftRecord`. `DRIFT_SCHEMA_VERSION_PLACEHOLDER = 0`
    per features.md FR-15 #3 - the schema is unstable until
    production release (v1.0.0) at which point the version bumps to 1.
    `compute_drift_placeholder(splits, *, plugin_name, label_field)`
    builds the v1 placeholder: per-split record counts and (when a
    label field is provided) sorted class distributions. Feature-
    level summaries are intentionally empty in v1; the schema slot is
    reserved for DataMachine consumers. `write_drift`/`read_drift`
    canonical JSON round-trip with sorted keys.
  - `src/datarefinery/reporting/report.py` exposes
    `render_report_md(recipe, manifest, *, fitted_op_ids) -> str`
    producing a deterministic markdown summary: manifest header
    (recipe/input hashes, seed, variant, created_at, elapsed,
    partial-run marker), inputs, splits + total, operations applied
    per section (filters/generation/transformations/featurizations/
    augmentations/visualizations), fitted statistics op_ids, and any
    accumulated warnings. Same inputs -> byte-identical markdown.
  - `re_render_report(instance_dir, recipe)` regenerates `report.md`
    from a materialized instance without rerunning the pipeline
    (FR-15.4). Compares the manifest's `recipe_hash` against the
    canonical hash of the recipe handed in; mismatch raises
    `MaterializeError` per FR-15 edge case "re-rendering against a
    stale fitted-statistics block is rejected".
    `list_fitted_op_ids(fitted_root)` enumerates persisted op_ids
    for the report's fitted-statistics section.
  - `src/datarefinery/pipeline/runner.py` now also writes
    `<instance>/report/report.md` and `<instance>/report/drift.json`
    inside the temp directory before the atomic promote. Fitted
    op_ids accumulated across Transformations and Featurizations
    flow into the report.
  - `tests/unit/test_drift.py` covers placeholder version, frozen +
    extra-forbid model behavior, per-split counts, label-field-driven
    class distribution, missing-label-field skip, sorted split keys,
    unstable-notes, empty feature_summary, JSON round-trip, and
    canonical sort-keys output (13 tests).
  - `tests/unit/test_report.py` covers manifest summary inclusion,
    inputs/splits sections, per-section op listings, fitted op_ids
    listing, "(none)" placeholders, warning rendering, partial-run
    marker, byte-stability for identical inputs, the
    `list_fitted_op_ids` directory helper (missing dir + sorted
    subdirs), `re_render_report` happy path, recipe-hash-mismatch
    hard error, and overwrite-of-stale-content (13 tests).
  - `tests/integration/test_runner.py` adds an end-to-end check that
    the runner writes both `report.md` (with fitted op listed) and
    a parseable `drift.json` whose split records sum to the input
    record count.

### Notes

- The story checklist mentioned adding `reporting/__init__.py`; that
  package init was already created in Story C.k for the visualization
  library API. No change needed beyond noting the package now also
  hosts `report.py` and `drift.py`.

## [0.3.11] - 2026-05-08

### Added

- PipelineRunner conductor (Story C.m, FR-3) - Phase C orchestration:
  - `src/datarefinery/pipeline/manifest.py` defines pydantic
    `Manifest` (frozen, `extra="forbid"`) carrying full
    `recipe_hash`/`input_hash` (SHA-256 hex), `seed`, `variant`,
    `created_at`, `elapsed_seconds`, `is_partial`, `failed_stage`,
    `record_counts`, and `warnings`. `MANIFEST_SCHEMA_VERSION = 1` is
    a separate counter from the recipe schema version per tech-spec.
    `write_manifest`/`read_manifest` round-trip via JSON.
  - `src/datarefinery/pipeline/runner.py` exposes `PipelineRunner(
    recipe, plugin, config, seed)` with `run(temp_dir, *,
    raw_records, raw_input_hashes) -> RunnerResult`. Sequences:
    `InputContracts` -> pre-split `Filters` -> `Splits` -> post-split
    `Filters` -> `Generation` -> `Transformations` -> `Featurizations`
    -> `Augmentations` (policy capture) -> `OutputExpectations` ->
    reporting `Visualizations` -> dataset persistence -> manifest
    write -> `atomic_promote(temp_dir, final_dir)`.
  - Cache-hit short-circuit: if `<final_dir>/manifest.json` exists,
    return without touching the temp dir; the persisted manifest is
    re-read and returned alongside the path.
  - Failure path: any stage exception triggers
    `mark_failed(temp_dir, exc, current_stage)` and re-raises;
    `final_dir` is never touched and no partial manifest is promoted.
  - Warning aggregation: stage warnings (split unassigned, sparse
    classes, empty-class filters, generation non-train splits, etc.)
    are accumulated as `ManifestWarning(stage=..., message=...)` and
    persisted on the manifest.
  - v1 scope notes: raw input loading is the caller's responsibility
    (`run` accepts `raw_records` + per-source `raw_input_hashes`);
    the CLI `materialize` verb (Story D.e) wires disk-based loading.
    Dataset persistence is intentionally minimal - per-split
    JSON-lines under `<instance>/dataset/<split>.jsonl` with each
    record's serializable fields; numpy arrays, bytes, and other
    non-JSON-native values are dropped (image bytes are accessed via
    the source `path` field, not embedded in the materialized
    dataset).
  - `tests/integration/test_runner.py` covers end-to-end
    materialization (manifest + dataset/<split>.jsonl + report
    visualization PNGs), well-formed manifest fields and shape,
    `normalize` fitted-stats persistence (`mean.parquet` and
    `std.parquet`), temp-dir cleanup after promote, instance path
    matches `compute_cache_key` derivation, cache-hit short-circuit
    on second run (returns cached manifest, leaves temp untouched),
    different seed misses cache, visualization-failure injection
    leaves `FAILED` marker with `stage="Visualizations"` and never
    creates the final `manifest.json`, and dataset JSON-lines omits
    numpy `image` arrays while preserving `record_id` and `label`
    (11 tests).

## [0.3.10] - 2026-05-08

### Added

- Deterministic parallel worker pool (Story C.l):
  - `src/datarefinery/pipeline/workers.py` exposes
    `run_parallel(seed, fn, items, workers, *, record_id_field) ->
    Iterator[Record]` and the `per_record_seed(global_seed, record, *,
    record_id_field)` helper. Implements the determinism contract from
    `project-essentials.md`: per-record seed
    `sha256(global_seed.to_bytes(8, "big") + str(record_id).encode()).digest()[:8]`
    decoded as a 64-bit unsigned int, and reorder-by-`record_id`
    (stable across mixed-type ids via a `(type, str)` sort key)
    before yielding. Worker count and process scheduling are
    invisible to downstream stages.
  - Serial fast-path when `workers <= 1` bypasses
    `ProcessPoolExecutor` entirely (still per-record-seeded, still
    reorder-by-record-id). Worker exceptions surface to the caller
    via `Future.result()` in parallel mode and via direct call in
    serial mode. Records missing the `record_id` field raise
    `MaterializeError` rather than silently producing
    nondeterministic output.
  - `tests/unit/test_workers.py` covers the per-record seed formula
    pin (deliberate cache-relevant change marker), seed determinism,
    record/global-seed sensitivity, int/custom-field record ids,
    missing-id error, byte-identical workers=1/2/4 output (the
    headline determinism check, also parametrized), per-record-seed
    invariance across worker counts and matches against the formula,
    reorder-by-record-id in serial and parallel (with order-jumbling
    delays in parallel), mixed-type id handling, empty input,
    workers=0 serial fast-path, exception propagation in both modes,
    same-seed cross-run identity, different-seed produces different
    per-record seeds, and a serial-mode same-PID sanity check
    (23 tests).

## [0.3.9] - 2026-05-08

### Added

- Visualizations: reporting + exploration modes (Story C.k, FR-13):
  - `src/datarefinery/pipeline/stages/visualizations.py` exposes
    `apply_reporting_visualizations(splits, viz_ops, *, plugin,
    output_dir, label_field) -> VisualizationsResult`. The runner
    iterates `mode == "reporting"` ops, calls
    `plugin.operation_factory("Visualizations", op.op).render(...)`,
    and writes PNG bytes to `<output_dir>/<op.name>.png`.
    `exploration`-mode ops are skipped. Failures wrap as
    `MaterializeError` per FR-13 ("reporting visualization that fails
    -> hard error during materialization"); non-bytes returns also
    hard-error.
  - `src/datarefinery/reporting/__init__.py` and
    `src/datarefinery/reporting/visualizations.py` expose
    `render_visualization(splits, op, *, plugin, label_field) ->
    RenderedVisualization` for exploration-mode use (typically called
    by the `inspect` CLI verb in Story D.h). Returns the same handle
    output without persisting; failures propagate unwrapped per the
    "exploring, not materializing" semantics.
  - Visualization handle protocol is `(.render(splits, params, *,
    label_field) -> bytes)` returning PNG bytes.
    `RenderedVisualization` carries `name`, `op`, `png_bytes`, and
    `path` (`None` for exploration mode).
  - `src/datarefinery/plugins/image_classification/operations/visualizations.py`
    implements three viz handles with Pillow alone (no matplotlib in
    deps):
    - `ClassDistributionHistogramOp`: per-class bar chart on a
      400x300 canvas; class iteration is stably ordered for
      seed-deterministic PNG bytes.
    - `SampleGridOp`: tiles the first N records' images into a
      square-ish grid; with `per_class=True`, takes the first N from
      each class (validator check 18 enforces param shape; the op
      requires `Labels.field` only when `per_class=True`).
    - `MeanImagePerClassOp`: per-class mean image (resized to 32x32
      thumbnails) tiled in a row.
  - All three are deterministic by record order: no RNG, stable class
    sort by `(type, repr)`, and Pillow's PNG encoder is byte-stable
    for identical pixel inputs.
  - `image_classification.plugin.operation_factory` now dispatches
    Visualizations ops via `_VISUALIZATION_OPS`; the only remaining
    factory exemptions are `to_grayscale`, `cast_dtype`, and the
    three augmentation ops (which are policy-only in v1 per FR-11).
  - `tests/unit/test_visualizations_stage.py` covers writes-png-per-
    op, skips-exploration-in-reporting-mode, creates-output-directory,
    empty-op-list pass-through, byte determinism for all three ops,
    sensitivity to input changes, per-class sampling, no-records
    blank rendering, missing-`Labels.field` rejection, FR-13
    reporting-failure hard error, non-bytes return hard error,
    exploration-API no-persist + unwrapped error propagation +
    non-bytes TypeError, and pixel-level decoding-and-shape smoke
    checks (20 tests).
  - `tests/plugin_contract/test_image_classification.py` adds a
    Visualizations factory-callable assertion and asserts that
    augmentation ops still raise `NotImplementedError` (policy-only
    per FR-11).

## [0.3.8] - 2026-05-08

### Added

- Augmentations declaration stage (Story C.j, FR-11):
  - `src/datarefinery/pipeline/stages/augmentations.py` exposes
    `collect_augmentation_policies(augmentation_ops) ->
    AugmentationsResult` and the `manifest_block(result)` helper that
    renders the augmentation list as stable canonical JSON for the
    runner's manifest. Each declared `AugmentationOp` becomes a frozen
    `AugmentationPolicy` carrying `name`, `op`, `params`, `splits`,
    and `seed`.
  - v1 does NOT pre-materialize augmented examples (FR-11 #2, #3) -
    the recipe declares augmentation policies that ModelFoundry
    honors on-the-fly during training. This stage's only side effect
    is producing the manifest summary; no image bytes change.
  - Defensive train-only re-check: validator check 5 enforces
    `splits=["train"]` for augmentations; this stage raises
    `MaterializeError` if a non-train split somehow reached it.
  - Image plugin's three augmentation OperationSpecs (`random_crop`,
    `horizontal_flip`, `color_jitter`) declared in C.b remain
    policy-only; no factory wiring (the plugin's
    `operation_factory` still raises `NotImplementedError` for
    Augmentations).
  - `AugmentationPolicy.to_manifest_dict()` and
    `AugmentationsResult.to_manifest_list()` produce
    JSON-serializable dicts with sorted param keys for byte-stable
    manifest output.
  - `tests/unit/test_augmentations_stage.py` covers policy
    collection, params/splits/seed verbatim capture, empty-list
    pass-through, manifest dict shape, sorted param keys, stable JSON
    formatting, full round-trip preservation, `seed=None` round-trip,
    non-train and test-only defensive rejection, empty-splits
    permitted, and frozen-result guarantees (13 tests).
- Story title typo fix in `docs/specs/stories.md` for C.j: was
  `v0.3.28`, corrected to `v0.3.8` to match the bump-version task line.

## [0.3.7] - 2026-05-08

### Added

- Featurizations stage + derived-label machinery (Story C.i, FR-12,
  FR-22):
  - `src/datarefinery/pipeline/stages/featurizations.py` exposes
    `apply_featurizations(splits, ops, *, plugin, fitted_stats,
    label_field) -> FeaturizationsResult`. Operation handle protocol
    is `(.fit_on_train, .fit, .apply)` with kwargs `inputs`,
    `output_field`, `label_field`. The stage decides whether to fit
    via `OperationSpec.fit_on_train`; fitted values are persisted
    once via `FittedStatistics` and applied across every declared
    split (FR-12 #3 mirrors FR-10's discipline). Unknown ops, missing
    `fit_source`, or undeclared `splits`/`fit_source` references
    raise `MaterializeError`.
  - Field-collision hard error per FR-12 edge case: under the
    uniform-schema invariant, the stage checks the first record of
    each target split before applying; an existing key collision
    raises `MaterializeError` (no records mutated).
  - FR-22 derived-label wiring: when `Labels.source.kind == "derived"`,
    the recipe author writes a `FeaturizationOp` whose
    `output_field` matches `Labels.field`. The stage runs that
    featurization like any other; no special-casing needed - the
    same machinery produces derived labels.
  - `src/datarefinery/plugins/image_classification/operations/featurizations.py`
    implements two featurization handles:
    - `LabelFromPathOp` (no fit): derives a label from a record's
      path field. Default `source` is `parent_directory_name` (the
      ImageFolder convention - `cats/foo.jpg` -> `"cats"`); also
      supports `filename` and `stem`. Raises `PluginError` on missing
      input field, empty `inputs`, or unknown `source`.
    - `ImageSizeStatsOp` (no fit): writes the image's spatial
      shape (e.g., `[H, W, C]`) under `output_field`. Supports 2-D
      and 3-D arrays; raises `PluginError` on other ndim.
  - `image_classification.plugin.operation_factory` now dispatches
    `Featurizations` ops via `_FEATURIZATION_OPS`; `to_grayscale`,
    `cast_dtype`, all augmentation ops, and all visualization ops
    still raise `NotImplementedError` (lands in C.j-C.k).
  - `tests/unit/test_featurizations_stage.py` covers
    parent-directory derivation, alternate sources (`filename`),
    unknown source rejection, missing-input-field error, empty-inputs
    error, image-size-stats shape extraction (3-D and 2-D),
    invalid-ndim rejection, multi-record / multi-split determinism,
    field-collision hard error (FR-12 edge case), no-collision-on-
    empty-split, fit-on-train support via a fixture plugin
    (persistence + train-fitted apply across splits + missing-
    fit_source error), unknown-op error, undeclared-split error,
    empty-list pass-through, and input-list non-mutation
    (18 tests).
  - `tests/plugin_contract/test_image_classification.py` adds a
    `Featurizations` factory-callable assertion.

## [0.3.6] - 2026-05-07

### Added

- Transformations stage + FittedStatistics persistence (Story C.h,
  FR-10 / FR-6):
  - `src/datarefinery/pipeline/fitted_stats.py` exposes
    `FittedStatistics(root)` with `put_scalar`/`get_scalar` (storing
    `float`/`int`/`str`/`bool` values in `<root>/<op_id>/scalars.json`
    as a sorted JSON object) and `put_vector`/`get_vector` (storing
    `pyarrow.Table` instances as `<root>/<op_id>/<name>.parquet`).
    Multiple `put_scalar` calls for the same `op_id` accumulate into
    one JSON file; later writes overwrite by name. Reads raise
    `MaterializeError` for missing or malformed inputs (including
    non-object `scalars.json`, non-scalar JSON values, and
    non-`pyarrow.Table` vector inputs). Never opaque pickles
    (FR-6 #3).
  - `src/datarefinery/pipeline/stages/transformations.py` exposes
    `apply_transformations(splits, ops, *, plugin, fitted_stats,
    label_field) -> TransformationsResult`. The handle protocol for
    Transformations operations is `(.fit, .apply)`; the stage decides
    whether to fit using `OperationSpec.fit_on_train`. Fit phase runs
    against the declared `fit_source` split, persists results via the
    supplied `FittedStatistics`, and the same fitted values flow into
    the apply phase across every declared `splits` entry (FR-10 #2).
    `MaterializeError` covers unknown ops, fit-on-train without
    `fit_source`, and `fit_source`/`splits` referencing undeclared
    splits.
  - `FittedValues(scalars, vectors)` is the data carrier between fit
    and apply. Recipe-supplied `mean`/`std` for `normalize` short-
    circuit the per-split fit so authored values flow into the
    persisted output (useful for tabular pipelines; image recipes
    typically omit them).
  - `src/datarefinery/plugins/image_classification/operations/transformations.py`
    implements three transformation handles:
    - `ResizeOp` (no fit): resizes each record's NumPy `image` field
      via Pillow with the recipe-specified `size` and `method`
      (`nearest`/`bilinear`/`bicubic`/`lanczos`); raises `PluginError`
      on invalid params.
    - `NormalizeOp` (fit-on-train): per-channel mean/std fitted on
      the train split; apply does `(x - mean) / std` with a
      zero-variance guard. Honors recipe-pinned mean/std when both
      are supplied.
    - `MeanSubtractOp` (fit-on-train, mean only): per-channel mean
      fitted on train; apply does `x - mean`.
    The remaining declared ops (`to_grayscale`, `cast_dtype`) still
    raise `NotImplementedError` from the factory.
  - `image_classification.plugin.operation_factory` now dispatches
    `Transformations` ops via `_TRANSFORMATION_OPS`.
  - `tests/unit/test_fitted_stats.py` covers scalar/vector round-trip,
    multi-scalar same-file accumulation, sorted-key layout, value
    overwrite, missing-op/missing-name read errors, non-scalar reject,
    malformed/non-object JSON, vector type guard, per-`op_id`
    directory layout, and post-promote independent-instance read
    pattern (16 tests).
  - `tests/unit/test_transformations_stage.py` covers resize-no-fit,
    no-stats-persisted-for-resize, invalid resize params,
    normalize-fits-on-train-only-and-persists, apply-uses-train-stats
    (val/test do not refit), determinism, zero-variance guard,
    recipe-pinned mean/std, mean_subtract persists only mean and
    centers around zero, unknown-op error, fit-on-train-without-
    fit_source error, fit_source/splits-undeclared errors, empty-list
    pass-through, FittedValues default, input non-mutation, and
    pyarrow.Table persisted-stats invariant (19 tests).
  - `tests/plugin_contract/test_image_classification.py` updated to
    assert resize/normalize/mean_subtract handles are returned and
    `to_grayscale`/`cast_dtype` still raise `NotImplementedError`.

## [0.3.5] - 2026-05-07

### Added

- Generation stage + image plugin duplication op (Story C.g, FR-9):
  - `src/datarefinery/pipeline/stages/generation.py` exposes
    `apply_generation(splits, generation_ops, *, plugin,
    output_record_schema, label_field)` returning a frozen
    `GenerationResult` carrying the updated `splits` (fresh lists; the
    caller's inputs are not mutated), `counts_before`/`counts_after`
    per split (consumed by the runner for manifest pre/post counts),
    and any `warnings`. Generation dispatches via
    `plugin.operation_factory("Generation", op.name)` - the model has
    no separate `op` field, so `GenerationOp.name` doubles as the
    lookup key. The canonical Generation operation signature is
    `(records, *, seed, inputs, output_schema, label_field) ->
    list[Record]` returning *new* records to add; the stage
    concatenates onto the split's existing records.
  - Each generated record is validated against `Output.record_schema`;
    any record missing a required Output field raises
    `MaterializeError` with the op name, split, and missing fields
    listed.
  - `applies_at` is honored (default `["train"]` via the model);
    non-train splits emit a per-op warning per features.md FR-9 edge
    case ("atypical but legitimate, flagged in the report"). An
    `applies_at` referencing an undeclared split raises
    `MaterializeError` (validator check 15 normally enforces this;
    the stage fails loudly if invoked without that gate).
  - `src/datarefinery/plugins/image_classification/operations/generation.py`
    implements `duplicate_minority_class`: brings each non-majority
    class up to the majority count by sample-with-replacement using
    `numpy.random.default_rng(seed)`. Class iteration is stably
    ordered so output is seed-deterministic across hash-randomization
    variants. Requires `Labels.field`; raises `PluginError` otherwise.
    v1 simplification: target count is the majority class size (no
    user-tunable target).
  - `image_classification.plugin.operation_factory` now dispatches
    `Generation` ops via `_GENERATION_OPS`; remaining sections still
    raise `NotImplementedError` (lands in C.h-C.k).
  - `tests/unit/test_generation_stage.py` covers minority→majority
    rebalancing, pre/post counts, seed determinism, seed sensitivity,
    no-op when balanced, missing-`label_field` error, default
    train-only `applies_at`, non-train warning, undeclared-split hard
    error, output-schema mismatch hard error (via a fixture plugin
    that drops a field), empty-list pass-through, input-list non-
    mutation, and frozen-result guarantee (13 tests).
  - `tests/plugin_contract/test_image_classification.py` adds an
    assertion that `Generation` ops are callable through the factory.

## [0.3.4] - 2026-05-07

### Added

- Filters stage + first image plugin operations (Story C.f, FR-8):
  - `src/datarefinery/pipeline/stages/filters.py` exposes
    `apply_pre_split_filters(records, filter_ops, *, plugin, label_field)`
    and `apply_post_split_filters(splits, filter_ops, *, plugin,
    label_field)` returning frozen `FilterResult`s with `records`,
    `warnings`, and `removed` count. Filters dispatch through
    `plugin.operation_factory("Filters", op_name)`; the canonical filter
    operation signature is
    `(records, params, *, label_field) -> list[Record]`. Pre-split
    filters honor the default `stages=["pre_split"]`; post-split
    filters apply only to splits listed in `FilterOp.splits`.
  - Empty-class warnings: when a filter pass reduces a class's record
    count from positive to zero, a warning is emitted (FR-8 edge case).
    Per-split warnings include the split name; warnings are skipped
    when no `label_field` is supplied.
  - `src/datarefinery/plugins/image_classification/operations/filters.py`
    implements the image plugin's two filter operations:
    - `filter_by_label(records, params, *, label_field)`: include or
      exclude records by label-set membership; defaults `action` to
      `"include"`; raises `PluginError` if `label_field` is `None` or
      `action` is not `"include"`/`"exclude"`.
    - `random_sample(records, params, *, label_field)`: reproducible
      sampling via `numpy.random.default_rng(seed)`. Requires exactly
      one of `fraction` (in `[0, 1]`) or `n` (non-negative); requires
      integer `seed`. Output preserves original record order so
      downstream stages see a stable subsequence.
  - `image_classification.plugin.operation_factory` now dispatches
    `Filters` ops via `_FILTER_OPS`; remaining sections still raise
    `NotImplementedError` (lands in C.g-C.k).
  - `tests/unit/test_filters_stage.py` covers include/exclude, default
    action, unknown action, missing-`label_field` error, sampling
    reproducibility, seed sensitivity, order-preservation,
    `n > total`, fraction/`n` exclusivity, missing-seed and
    out-of-range fraction errors, pre/post stage dispatch, multi-stage
    runs, in-order multi-filter pipelines, empty-class warnings (with
    and without label field), per-split warning naming, missing-`op`
    predicate error, frozen-result, and empty-list pass-through
    (24 tests).
  - `tests/plugin_contract/test_image_classification.py` updated to
    assert filter ops now return callables while other sections still
    raise `NotImplementedError`.

## [0.3.3] - 2026-05-07

### Added

- Splits stage (Story C.e, FR-7):
  - `src/datarefinery/pipeline/stages/splits.py` exposes
    `apply_splits(records, section, *, seed) -> SplitResult` plus a
    `resolve_seed(section, fallback)` helper for callers to pick the
    section seed over the recipe-level fallback. `SplitResult` is a
    frozen dataclass listing `splits: Mapping[str, list[Record]]`,
    `unassigned: list[Record]`, the pass-through `class_balance` tag,
    and any sparse-class `warnings`.
  - Two splitting modes: ratio-based (cumulative-fraction
    partitioning; sub-1.0 ratio sums leave a recorded `unassigned`
    remainder per features.md FR-7 edge case) and key-based
    (`mapping[str(record[field])]` lookup; unmapped or missing-field
    records raise `MaterializeError` with sample indices).
  - Stratification (`stratify_by`) honored in ratio mode by
    partitioning each class's records by the same ratio shape.
    Sparse-class detection emits a per-class warning when any class
    has fewer records than the number of positive-ratio splits.
    Class iteration is stably ordered by `(type, repr)` so stratified
    output is seed-deterministic across hash-randomization variants.
  - `class_balance` is a tag passed through unchanged - resampling is
    ModelFoundry-side per features.md FR-7 #4; this stage does no
    resampling.
  - Determinism: shuffles use `numpy.random.default_rng(seed)`; same
    seed + same record order produces byte-identical partitions.
  - `tests/unit/test_splits_stage.py` covers ratio partitioning, seed
    determinism, sub-1.0 remainder, partition completeness with awkward
    counts, stratified class distribution, sparse-class warning, no-warn
    when classes are dense, stratified determinism, key-based
    partitioning, unmapped-record and missing-field hard errors,
    empty-target-split behavior, `class_balance` pass-through, no-
    resampling invariant, seed precedence helper, and empty-input
    edge case (18 tests).

## [0.3.2] - 2026-05-07

### Added

- Pipeline contracts: InputContracts and OutputExpectations evaluation
  (Story C.d, FR-23):
  - `src/datarefinery/pipeline/contracts.py` exposes
    `evaluate_input_contracts(records, contracts) -> ContractResult` and
    `evaluate_output_expectations(dataset, expectations) -> ContractResult`.
    Both materialize the iterable once internally so multiple assertions
    traverse the same records without callers re-buffering. The
    `ContractResult` aggregates one `AssertionResult` per declared
    contract and exposes `passed`, `failures`, `warnings`, plus a
    `raise_for_status()` method that raises `ContractError` only on
    error-severity failures (warnings are recorded but never raise).
  - Five assertion kinds: `record_count` (dataset-level `min`/`max`
    bounds), `required_field` (every record contains the field
    non-None), `dtype` (Python type tag with numpy aliases, rejecting
    `bool` for int-family tags), `range` (`min`/`max` per-field), and
    `distributional` (placeholder that always passes in v1; full
    machinery is post-v1 per features.md FR-23 edge cases).
  - The aggregator does not short-circuit; an unknown assertion `kind`
    or a missing required `field` is reported as a failure rather than
    raising.
  - `tests/unit/test_contracts.py` covers each assertion kind's pass
    and fail paths, severity handling (warning vs. error),
    `raise_for_status` behavior, the no-short-circuit aggregator,
    iterator consumption, and frozen-result guarantees (34 tests).

## [0.3.1] - 2026-05-07

### Added

- Tabular and text plugin stubs (Story C.c):
  - `src/datarefinery/plugins/tabular/` and
    `src/datarefinery/plugins/text/` packages, each declaring a section
    list and `OperationSpec` outlines so recipes targeting
    `plugin: tabular` or `plugin: text` validate clean against FR-2
    checks 1-18. Tabular outlines cover Filters
    (`filter_by_value`, `drop_nulls`, `random_sample`), Generation
    (`duplicate_minority_class`), Transformations
    (`standardize` [fit-on-train], `min_max_scale` [fit-on-train],
    `one_hot_encode` [fit-on-train], `cast_dtype`), Featurizations
    (`polynomial_features`), and Visualizations
    (`class_distribution_histogram`, `field_summary_table`). Text
    outlines cover Filters (`filter_by_label`, `filter_by_length`,
    `random_sample`), Generation (`duplicate_minority_class`),
    Transformations (`lowercase`, `strip_punctuation`, `tokenize`,
    `remove_stopwords`), Featurizations (`tfidf` [fit-on-train],
    `token_count`), and Visualizations
    (`class_distribution_histogram`, `token_length_histogram`).
  - Both plugins return `is_stub() -> True`; `operation_factory(...)`
    raises `PluginError("stub plugin; not implemented")` with plugin,
    section, and op name in the message. Full operation
    implementations are post-v1.
  - Registered under the `datarefinery.plugins` entry-point group in
    `pyproject.toml` so `discover_plugins()` returns both stubs.
  - `tests/plugin_contract/test_tabular.py` and
    `tests/plugin_contract/test_text.py` cover runtime-protocol
    satisfaction, metadata, declared section/op set, `OperationSpec`
    validity per operation, fit-on-train placement invariant, the
    `PluginError` factory contract, and entry-point discovery.
  - `tests/integration/test_tabular_stub_smoke.py` exercises a tabular
    recipe through `Recipe.model_validate` + `validator.validate`
    (all 18 checks pass) and confirms `operation_factory` raises
    `PluginError`.

## [0.3.0] - 2026-05-07

### Added

- Image classification plugin skeleton (Story C.b) - Phase C begins:
  - `src/datarefinery/plugins/image_classification/` package with
    `plugin.py` declaring full `OperationSpec` parameter schemas for
    16 operations across Filters (`filter_by_label`, `random_sample`),
    Generation (`duplicate_minority_class`), Transformations
    (`resize`, `normalize` [fit-on-train], `mean_subtract`
    [fit-on-train], `to_grayscale`, `cast_dtype`), Featurizations
    (`label_from_path`, `image_size_stats`), Augmentations
    (`random_crop`, `horizontal_flip`, `color_jitter` - all
    train-only), and Visualizations
    (`class_distribution_histogram`, `sample_grid`,
    `mean_image_per_class`).
  - `operation_factory` raises `NotImplementedError` for now (real
    implementations land in Stories C.f-C.k); `is_stub() -> False`
    because the schemas are real.
  - Registered under the `datarefinery.plugins` entry-point group in
    `pyproject.toml` so `discover_plugins()` returns it without
    requiring `--plugin-path`.
  - `tests/plugin_contract/test_image_classification.py` covers
    runtime-protocol satisfaction, metadata, declared section/op set,
    `OperationSpec` validity per operation, fit-on-train invariant
    (must be in Transformations), augmentation train-only invariant,
    `resize` parameter schema accepting fixture params, the
    `NotImplementedError` factory contract, and that
    `discover_plugins()` returns the plugin via entry points.

## [0.2.10] - 2026-05-07

### Added

- Cache cleaner library API (Story B.i, FR-21) - Phase B complete:
  - `src/datarefinery/cache/cleaner.py` exposes the frozen
    `CleanSelector` dataclass (`by_recipe_hash`, `by_input_hash`,
    `by_seed`, `by_age_days`, `orphans`, `orphan_age_days`, `all`) and
    `clean(cache_root, selector, *, force=False) -> CleanReport`. The
    `by_*` filters compose intersection-style; `orphans=True` adds
    temp dirs older than `orphan_age_days` to the target set;
    `all=True` requires `force=True` and clears every direct child of
    `<cache-root>/instances/`. Recipe and input hash matchers truncate
    callers' full hashes to 16 chars before comparison. Failed
    removals are captured in `CleanReport.skipped` rather than aborting
    the run. The CLI verb wrapping this lands in Phase D.
  - `tests/unit/test_cleaner.py` synthesizes a 4-instance + 2-orphan
    layout and covers each selector, intersection-style composition,
    the 16-char truncation invariant, the `all`-without-`force`
    refusal, the `orphan_age_days` threshold, missing-cache-root
    no-op, and `shutil.rmtree` failure capture in `skipped`.

## [0.2.9] - 2026-05-07

### Added

- Atomic temp-then-promote (Story B.h, FR-5):
  - `src/datarefinery/cache/atomic.py` exposes
    `atomic_promote(temp_dir, final_dir)` (cross-device guard via
    `os.stat(...).st_dev` comparison; `os.replace`-based rename; wraps
    `OSError` and missing-temp into `MaterializeError`) and
    `mark_failed(temp_dir, exc, stage)` (writes a `FAILED` JSON marker
    with stage, exception type/message/traceback, and ISO-8601 UTC
    timestamp; no-ops if `temp_dir` was already promoted/cleaned).
    Cross-device detection is wrapped in a `_device_id` helper so the
    guard is testable without a real multi-filesystem setup.
  - `tests/unit/test_atomic.py` covers success path (temp gone, final
    populated), missing-temp failure, cross-device refusal (with
    monkey-patched `_device_id`), `os.replace` `OSError` wrapping,
    `mark_failed` JSON shape and required fields, no-op on missing
    temp, and an end-to-end `atomic_promote` failure followed by
    `mark_failed` leaving temp + `FAILED` marker without ever touching
    the final cache path.

## [0.2.8] - 2026-05-07

### Added

- Cache layout helpers (Story B.g):
  - `src/datarefinery/cache/layout.py` exposes path helpers
    (`instances_root`, `instance_dir`, `tmp_dir`, `manifest_path`,
    `dataset_dir`, `fitted_stats_dir`, `report_dir`) producing the
    documented `<cache-root>/instances/<recipe16>/<input16>/<seed>/`
    shape (with in-flight runs under `<cache-root>/instances/.tmp/`).
    Final hashes truncate to 16 chars per `CacheKey`.
  - `make_run_id()` returns `<utc_iso_compact>-<8hex>` (e.g.
    `20260507T143022Z-deadbeef`); lex-sortable to the second with an
    8-hex random suffix for collision resistance under concurrent calls.
  - `tests/unit/test_cache_layout.py` covers each helper's path shape,
    `instance_dir` truncation invariant, `make_run_id` format, sortable-
    by-timestamp invariant, and uniqueness under both 2000-id sequential
    bursts and 8-thread concurrent generation.

## [0.2.7] - 2026-05-07

### Added

- Cache identity (Story B.f, FR-4):
  - `src/datarefinery/cache/__init__.py`,
    `src/datarefinery/cache/identity.py`. Frozen `CacheKey` dataclass
    (`recipe_hash`, `input_hash`, `seed`) with `.short` returning the
    first 16 hex characters of `recipe_hash` for cache-directory
    sharding. Full SHA-256 hashes are stored in `manifest.json`
    (per `project-essentials.md` "Cache identity is the
    reproducibility contract").
  - `compute_cache_key(recipe, raw_input_hashes, seed)` SHA-256s
    `to_canonical_bytes(recipe)` for `recipe_hash`, then SHA-256s the
    sorted-by-name concatenation of per-source content hashes
    (`name=<hex>;` pairs) for `input_hash`. Order-independent: dict
    insertion order does not affect `input_hash`.
  - `tests/unit/test_cache_identity.py` covers identity stability,
    sensitivity to recipe / input / seed changes, order-independence,
    name-vs-content-hash collision resistance, recipe-hash-matches-
    canonical-bytes-SHA-256 internal consistency, and hex-format
    invariants.

## [0.2.6] - 2026-05-07

### Added

- Recipe validator checks 14-18 (Story B.e.3, FR-2 part 3) - FR-2 complete:
  - `check_14_generation_output_schema_consistent` cross-checks each
    `GenerationOp.output_schema` against `Output.record_schema` for
    field name presence and dtype/shape match.
  - `check_15_split_references_defined` verifies every per-op
    `splits` and `Generation.applies_at` reference a name declared in
    `Splits.ratios` or `Splits.key_assignment.mapping` values.
  - `check_16_sample_data_strict_subset` enforces that
    `SampleData.selector` declares exactly one of `n` or `fraction`,
    `n >= 1`, and `0 < fraction < 1` (strict subset).
  - `check_17_contract_fields_exist_at_stage` requires `field`
    references in `InputContracts` and `OutputExpectations` to exist
    in the field universe (`Output.record_schema` ∪ `Labels.field`);
    dataset-level assertions with `field=None` pass through.
  - `check_18_plugin_operation_params_validate` looks up each
    Transformation/Augmentation/Featurization/Visualization's `op`
    against `plugin.supported_operations`; flags unknown operations,
    missing required parameters, and unexpected (extra) parameters.
    Type-checking parameter values is deferred to the runner.
  - `tests/unit/test_validator.py` adds 21 new tests including
    per-check failure fixtures, pass cases, and a multi-violation
    cross-check that simultaneously fires 17 distinct checks
    (everything except check 11, which the model already enforces
    at parse time).

## [0.2.5] - 2026-05-07

### Added

- Recipe validator checks 7-13 (Story B.e.2, FR-2 part 2):
  - `check_07_operations_reference_declared_fields` validates
    `FeaturizationOp.inputs` against the field universe
    (`Output.record_schema` keys ∪ `Labels.field` ∪ upstream
    Featurization `output_field`s). Field references inside opaque
    operation params (Filters/Transformations/Augmentations) are
    deferred to check 18.
  - `check_08_splits_partition_correctly` requires exactly one of
    `ratios` or `key_assignment`, non-negative ratios that sum to
    `<= 1.0` (sub-one is allowed; remainder is unsplit), and a
    non-empty `key_assignment.mapping`.
  - `check_09_stratification_keys_exist` checks
    `Splits.stratify_by` against the same field universe (including
    Featurization outputs).
  - `check_10_class_imbalance_strategy_in_one_place` (heuristic v1)
    flags simultaneous handling in `Splits.class_balance` and any
    `FilterOp.predicate` containing a `class_balance` key.
  - `check_11_visualization_mode_declared` is tautological for valid
    recipes (the model already constrains mode to
    `Literal["exploration", "reporting"]`); kept for FR-2
    completeness.
  - `check_12_variants_reference_declared_sections` rejects variant
    overlay keys that aren't valid Recipe section/scalar names.
  - `check_13_labels_resolvable` requires `Labels.field` to be in
    `Output.record_schema`.
  - `tests/unit/test_validator.py` adds 21 new tests covering
    per-check failure fixtures, pass cases, and a multi-violation
    cross-check spanning 6 simultaneous failures across checks 1-13.
  - Checks 14-18 land in B.e.3 (v0.2.6).

## [0.2.4] - 2026-05-07

### Added

- Recipe validator framework + checks 1-6 (Story B.e.1, FR-2 part 1):
  - `src/datarefinery/recipe/validator.py` exposes `CheckStatus`,
    `CheckResult` (frozen dataclass: `check_id`, `descriptor`, `status`,
    `location`, `message`), `ValidationReport` (with `passed`,
    `failures`, `warnings` properties), `validate(recipe, plugin)`
    aggregator that runs every registered check and never short-circuits
    (a check that raises is captured as a fail rather than aborting),
    and the first six checks: `check_01_schema_version_recognized`,
    `check_02_plugin_name_discoverable`,
    `check_03_section_names_valid_for_plugin`,
    `check_04_operations_declare_stages_and_splits`,
    `check_05_augmentations_train_only`,
    `check_06_fit_on_train_uses_train_split` (consults the plugin's
    `OperationSpec.fit_on_train`).
  - `tests/unit/test_validator.py` covers the valid-recipe-passes-all
    case, no-short-circuit aggregation, exception-as-failure capture,
    and per-check failure fixtures for each of checks 1-6 (with
    pre-split / post-split filter splits, train-only augmentations, and
    fit-on-train fit_source discipline edge cases).
  - Checks 7-13 land in B.e.2 (v0.2.5); checks 14-18 land in
    B.e.3 (v0.2.6).

## [0.2.3] - 2026-05-07

### Added

- Variant overlay (Story B.d, FR-14):
  - `src/datarefinery/recipe/variants.py` exposes
    `apply_variant(recipe, variant_name)` which replaces target sections
    wholesale (e.g., `Augmentations: []` clears, `seed: 99` replaces the
    scalar). The returned `Recipe` always has `variants={}` so cache
    identity reflects only the applied semantics — adding or editing
    unused variants does not invalidate cached instances of other
    variants.
  - Unknown variant name raises `RecipeError` listing the declared
    variants. An overlay that produces an invalid recipe surfaces the
    pydantic message wrapped in `RecipeError`.
  - `tests/unit/test_variants.py` covers `None` clears variants,
    section-clear via empty list, scalar replacement, unknown-variant
    failure, declared-variants listed in the message, distinct
    canonical bytes per variant, neutrality to unused variants,
    invalid-overlay handling, and input-recipe immutability.

## [0.2.2] - 2026-05-07

### Added

- Canonical bytes — recipe-side cache reproducibility contract (Story B.c, FR-4):
  - `src/datarefinery/recipe/canonical.py` exposes
    `to_canonical_bytes(recipe)` implementing
    `Recipe.model_dump(mode="json")` →
    `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` →
    UTF-8 encode.
  - `tests/unit/test_canonical.py` covers cosmetic-edit invariance
    (whitespace-only, comment-only, key-reordered YAML), value-edit
    sensitivity (changed scalar, added section), valid-UTF-8-JSON
    output with no whitespace separators, and byte stability across
    repeated calls.
  - **Canonical hash pin:** `_PINNED_DIGEST` records the SHA-256 of
    the baseline fixture's canonical bytes. Bumping this constant is
    a deliberate cache-invalidation event and must follow the
    ceremony in `project-essentials.md` "Cache identity is the
    reproducibility contract".

## [0.2.1] - 2026-05-07

### Added

- Recipe loader with FR-1 schema-version gate (Story B.b):
  - `src/datarefinery/recipe/loader.py` exposes
    `SUPPORTED_SCHEMA_VERSIONS = frozenset({1})`, an empty post-production
    `migrations: dict[(int, int), Callable]` registry, a
    `KNOWN_TOP_LEVEL_KEYS` constant, and `load(path) -> Recipe`. The gate
    runs before model validation; malformed YAML produces a `RecipeError`
    annotated with the offending line/column, and unknown top-level keys
    emit a forward-compatibility `UserWarning` before the inevitable
    `extra="forbid"` validation hard-error.
  - `tests/unit/test_recipe_loader.py` covers happy path, missing
    `schema_version`, unrecognized version (with supported-list +
    FR-1 pointer), non-integer and boolean schema versions, malformed
    YAML with line/column, non-mapping root, the unknown-top-level-key
    warning followed by hard error, and the constant/migrations stubs.

## [0.2.0] - 2026-05-07

### Added

- Recipe pydantic models (Story B.a) — Phase B begins:
  - `src/datarefinery/recipe/models.py` defines `Recipe` plus per-section
    models (`InputSection`, `InputSource`, `OutputSection`, `FieldSpec`,
    `LabelsSection`, `LabelSource`, `SampleDataSection`, `SampleSelector`,
    `Contract`, `Expectation`, `FilterOp`, `GenerationOp`,
    `SplitsSection`, `KeyAssignment`, `TransformationOp`,
    `AugmentationOp`, `FeaturizationOp`, `VisualizationOp`). All models
    inherit from a shared frozen base with `extra="forbid"`. Plugin-
    specific operation parameters are typed as opaque mappings here;
    cross-checking against `OperationSpec` lands in Story B.e.
  - `tests/unit/test_recipe_models.py` covers minimal-recipe validation,
    `model_dump` round-trip, unknown top-level keys, unknown per-section
    keys, missing required sections (`Input`/`Output`/`Labels`/`Splits`)
    and required top-level fields (`schema_version`/`plugin`),
    instance-frozen guarantee, the `mode` Literal on `VisualizationOp`,
    and `SplitsSection` with key-assignment only.

## [0.1.6] - 2026-05-07

### Added

- Plugin protocol and discovery (Story A.h):
  - `src/datarefinery/plugins/base.py` defines a runtime-checkable
    `Plugin` protocol (`name`, `supported_sections`,
    `supported_operations`, `schema_version`, `operation_factory`,
    `is_stub`) plus frozen pydantic `OperationSpec` (parameters,
    `fit_on_train`, `applicable_splits`, `applicable_sections`) and
    `ParameterSpec`. Both models reject extra fields.
  - `src/datarefinery/plugins/discovery.py` exposes
    `discover_plugins(extra_paths=None)` which walks the
    `datarefinery.plugins` entry-point group plus developer extra
    paths (directories or single `.py` files), looking for a
    top-level `PLUGIN` attribute. Duplicate names raise
    `PluginError`; missing paths and unloadable modules raise
    `PluginError` with the file path included.
  - `tests/fixtures/dummy_plugin.py` and `dummy_plugin_dup.py`
    provide a `_test_dummy` plugin and a duplicate-name partner for
    the discovery test suite.
  - `tests/unit/test_plugins_discovery.py` covers extra-paths file
    and directory discovery, duplicate-name failure, missing-path
    failure, `OperationSpec`/`ParameterSpec` extra-field rejection,
    defaults, frozenness, and round-trip parameters.

## [0.1.5] - 2026-05-07

### Added

- Runtime configuration and shared CLI options (Story A.g):
  - `src/datarefinery/core/config.py` defines a frozen pydantic
    `RuntimeConfig` with `cache_root`, `log_level`, `log_target`,
    `plugin_path`, `workers` and a `resolve()` classmethod implementing
    the documented CLI > env > default precedence (env mapping
    overridable for testing). `DATAREFINERY_PLUGIN_PATH` is split on
    `os.pathsep` (POSIX `:`).
  - `cli/app.py` adds shared options at the root callback:
    `--cache-root`, `--log-level`, `--log-target`,
    `--plugin-path` (repeatable), `--workers`, `--seed`, `--variant`,
    `--no-color`, `--quiet`, `--verbose`. The callback builds a
    `RuntimeConfig` and stashes it on the typer `Context` for downstream
    commands.
  - `tests/unit/test_config.py` covers env-only, CLI-only, both
    (CLI wins), partial overrides, empty-string env, PATH-style splitting,
    `frozen=True`, and `extra="forbid"`.

## [0.1.4] - 2026-05-07

### Added

- Error hierarchy and CLI exit-code mapping (Story A.f):
  - `src/datarefinery/core/errors.py` defines `DataRefineryError` plus
    `RecipeError`, `ValidationError`, `PluginError`, `ContractError`,
    `MaterializeError`, `CacheError`.
  - `src/datarefinery/cli/_exit_codes.py` exposes `EXIT_OK`, `EXIT_USER`,
    `EXIT_SYSTEM`, `EXIT_INTERRUPT` and `exit_code_for(exc)` mapping per
    tech-spec (user 1 / system 2 / SIGINT 130).
  - `cli/app.py` adds `main_entry()` that runs the typer app with
    `standalone_mode=False`, catches `DataRefineryError` and
    `KeyboardInterrupt`, renders a `rich` error panel on stderr, and exits
    with the mapped code; uncaught exceptions exit 2.
  - Console script (`pyproject.toml`) and `__main__.py` now route through
    `main_entry`.

### Tests

- `tests/unit/test_errors.py` — exhaustive subclass and exit-code mapping.
- `tests/cli/test_exit_codes.py` — subprocess tests asserting each error
  class produces the documented exit code through `main_entry`, plus
  `KeyboardInterrupt → 130`, uncaught `RuntimeError → 2`, and that
  `--help` / `--version` still exit 0.

## [0.1.3] - 2026-05-07

### Added

- Logging foundation (Story A.e):
  - `src/datarefinery/logging.py` exposes `JsonFormatter` (single-line JSON
    with `ts`, `level`, `logger`, `stage`, `op_id`, `message`, plus an
    `extras` bucket for non-reserved record attributes) and `get_logger`
    helper that idempotently attaches a `NullHandler` and a
    `JsonFormatter` `StreamHandler(stderr)` to the `datarefinery` package
    logger. Importing the module does not touch root logging.
  - CLI startup in `cli/app.py` now initializes the package logger via
    `get_logger("cli")`. `--log-target` is accepted as a reserved no-op
    stub; full routing lands in Story A.g.
  - `tests/unit/test_logging.py` covers single-line JSON shape, required
    fields, `extras` round-trip, and the no-root-handler invariant.

## [0.0.2] - 2026-05-06

### Added

- Hello-world Typer CLI (Story A.b):
  - `src/datarefinery/cli/app.py` exposes a `Typer` app with `--version` and `--help`; `--version` reads `datarefinery.__version__`.
  - `src/datarefinery/__main__.py` so `python -m datarefinery` invokes the CLI.
  - `tests/cli/test_smoke.py` smoke tests asserting `--version` and `--help` exit 0 and surface the package version.

## [0.0.1] - 2026-05-06

### Added

- Initial project scaffolding (Story A.a):
  - Apache-2.0 `LICENSE`.
  - `pyproject.toml` with hatchling backend, runtime dependencies, optional `[llm]` extra, console script, plugin entry-point group, and ruff / mypy / pytest configuration.
  - `requirements-dev.txt` listing the dev tool pinset for the pyve testenv.
  - `src/datarefinery/` package with `__version__` and PEP 561 `py.typed` marker.
  - `tests/` skeleton (`conftest.py` plus `unit/`, `integration/`, `cli/`, `plugin_contract/`, `fixtures/` subdirectories).
  - `README.md` with project tagline, install snippet, and one-line usage example.
  - `.gitignore` covering Python, pyve, build artifacts, and `data/`.
  - `environment.yml` for the pyve micromamba environment (Python 3.12.x).
