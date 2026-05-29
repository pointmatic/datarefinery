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

## Phase I: Recipe-focused Bug Fixes and Feature Gaps in v0.16.0

Phase I collects investigation and fix work surfaced by the consumer's cross-check against DataRefinery v0.16.0 (see [`docs/specs/dependency-gaps-v0.16.0.md`](dependency-gaps-v0.16.0.md), entries G1–G19 + DOC; G18 and G19 were captured after the initial gap doc was written) together with the intermediate-artifact persistence feature ("Sinks") scoped in [`docs/specs/phase-i-intermediate-artifact-persistence-spec.md`](phase-i-intermediate-artifact-persistence-spec.md) (closes the G18 surface symptom by making bit-identical stage-snapshot export structural). Each gap entered Phase I as a candidate bug; debug-mode investigation determines whether each is a defect (closes here with a code fix) or a feature/architectural gap (a `[Planned]` story is captured here and handed off to `plan_phase` when the developer scopes the work).

Stories I.a–I.c (`[Done]`) closed three gaps in v0.16.0–v0.16.2. The remaining open items land as stories I.d–I.y across four release bundles. The Sinks bundle is highest priority and ships first:

- **Bundle 1 (v0.17.0 minor, Sinks):** I.d, I.e, I.f, release I.g. Scoped in [`phase-i-intermediate-artifact-persistence-spec.md`](phase-i-intermediate-artifact-persistence-spec.md).
- **Bundle 2 (v0.17.1 patch):** I.h, I.i, release I.j. Scoped in [`phase-i-recipe-focused-bug-fixes-plan.md`](phase-i-recipe-focused-bug-fixes-plan.md).
- **Bundle 3 (v0.18.0 minor):** I.k–I.v, release I.w. Scoped in [`phase-i-recipe-focused-bug-fixes-plan.md`](phase-i-recipe-focused-bug-fixes-plan.md).
- **Bundle 4 (v0.19.0 minor, schema_version 1→2):** I.x.1–I.x.3, release I.y. Scoped in [`phase-i-recipe-focused-bug-fixes-plan.md`](phase-i-recipe-focused-bug-fixes-plan.md).

Story ID position in this file follows historical order of authoring (I.d–I.g appear after I.y even though they ship first). Release order is governed by the bundle list above, not by ID position.

Within a bundle, work stories carry no version in their title; a dedicated release-ceremony story owns the version bump and the CHANGELOG entry.

**Phase I story conventions.** Every Phase I story includes, in addition to its core code change: (a) `recipe-authoring.md` update per the DOC rule in [`dependency-gaps-v0.16.0.md` § DOC](dependency-gaps-v0.16.0.md); (b) gap-doc update (status block, priority summary, workarounds table); (c) cross-repo coordination check against [`docs/specs/modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md) per [`project-essentials.md` § "Recipe / manifest / report shape changes need a cross-repo coordination check"](project-essentials.md); (d) CI parity verification (`pyve test`, `pyve testenv run mypy src tests`, `pyve testenv run ruff check src/ tests/`, `pyve testenv run ruff format --check src/ tests/`). These are not re-enumerated in every story's task list below.

### Story I.a: G5 investigation — reclassify as G7 (no code fix) [Done]

**Disposition: documentation-only.** No version bump (no code change).

Debug-mode investigation of [`dependency-gaps-v0.16.0.md` § G5](dependency-gaps-v0.16.0.md) (`augmented_sample_grid` raises `TypeError` on post-normalize float images) determined that G5 is **not a defect**. It is the surface symptom of G7 (visualization stage dispatch — all reporting visualizations run at `post_pipeline` only). The architectural fact is that `augmented_sample_grid` is semantically defined on pixel arrays; z-score values aren't pixels; the viz crashes because it has no way to observe the pre-normalize representation. That capability is G7.

Three candidate code fixes were considered and rejected:

1. **Convert `TypeError` → actionable `RecipeError` at the viz layer.** Error-message quality only; the recipe still cannot use the viz post-normalize. Pure polish.
2. **Make realizers float-tolerant.** Suppresses the crash, but the viz's `_tile` clip-casts z-score values ~[-2, 2] to uint8 [0, 255], producing mostly-black tiles. Silently wrong is worse than crashing.
3. **Stage-aware viz dispatch (= G7).** The honest fix; out of scope for a debug cycle, captured as Story I.h below.

This story produces no code change. Its deliverable is the reclassification in the gap doc and the planned-story handoff to G7.

**Tasks:**

- [x] Reproduce the bug with a failing test (`tests/plugins/image_classification/test_visualizations_augmented_sample_grid.py`); confirmed the documented `TypeError: Cannot handle this data type: (1, 1, 3), <f8` symptom from PIL.Image.fromarray. Test reverted — would pin the wrong contract going forward.
- [x] Audit the four lazy-mode augmentation realizers for float-input behavior: `horizontal_flip` and `color_jitter` crash on float arrays (PIL-backed); `random_crop` and `random_erasing` are pure-numpy and don't crash but the downstream `_tile` would clip-cast z-score values to a meaningless tile.
- [x] Document the investigation outcome in [`docs/specs/dependency-gaps-v0.16.0.md` § G5](dependency-gaps-v0.16.0.md): status block, severity reclassified to "Subsumed by G7," fix path "implement G7."
- [x] Update the dependency-gaps priority summary table: G5 row severity → "Subsumed by G7."
- [x] Update the dependency-gaps recipe-side workarounds table: G5 row → "(No G5-only recipe edit; when G7 lands, restore the viz with `stage: pre_transformations`)."
- [x] Capture Story I.h in this file for G7 — the genuine fix path.

**Prevention scan (no code changes needed for I.a, but captured for the G7 implementer):**

- The lazy-mode augmentation realizer dtype-handling matrix (above) is the audit surface G7's implementer should inspect first. Two realizers crash on floats; two are silent-but-wrong. Either way, stage-aware dispatch is the right fix; per-realizer dtype-coercion is the wrong fix.
- The viz `_tile` clip-cast at [`augmented_sample_grid.py:144-145`](../../src/datarefinery/plugins/image_classification/visualizations/augmented_sample_grid.py#L144-L145) is dead code once G7 lands and viz operates on uint8 inputs. Remove it as part of G7 unless a defensible cross-stage compatibility argument surfaces.

**Out of Scope**

- Implementing G7 itself. That's Story I.h.
- Implementing options 1 or 2 above as a polish-only intermediate fix. Both were rejected during investigation; shipping polish doesn't move the consumer closer to the working viz they want.
- Reclassifying other G entries (G6, G8, etc.) in the same pass. Each gets its own debug cycle.

### Story I.b: v0.16.1 G8 — contracts evaluator handles ndarray fields [Done]

**Disposition: bug fix.** Patch bump (`v0.16.0 → v0.16.1`).

Debug-mode investigation of [`dependency-gaps-v0.16.0.md` § G8](dependency-gaps-v0.16.0.md) confirmed two unhandled-input bugs in [`pipeline/contracts.py`](../../src/datarefinery/pipeline/contracts.py):

1. **`_eval_dtype` on a tensor field** (e.g., `dtype: uint8` on an `image` ndarray) reported every record as the wrong type. Root cause: `isinstance(v, accepted)` where `accepted` is `(int,)` or `(float, int)` — Python scalar types. `np.ndarray` is not an `int` regardless of its element dtype.
2. **`_eval_range` on a tensor field** (e.g., `value_range: [-3, 3]` on an `image` ndarray) raised `ValueError: The truth value of an array with more than one element is ambiguous`. Root cause: `v < lo` on an ndarray returns an element-wise boolean array; the `if` branch chokes.

Both evaluators now accept ndarrays in the obvious way: `_eval_dtype` compares `v.dtype.name` against the expected tag; `_eval_range` reduces via `v.min()`/`v.max()` and compares scalars. Scalar-field semantics are unchanged. **No new assertion kinds are added** — the broader G16 work (`tensor_range`, `tensor_shape`, `value_in_set`, etc.) remains plan_phase scope.

**Tasks:**

- [x] Reproduce both failure modes with 5 unit tests in [`tests/unit/test_contracts.py`](../../tests/unit/test_contracts.py): dtype-on-uint8-ndarray passes; dtype-on-float32-ndarray passes; dtype-on-wrong-dtype-ndarray fails with a message that cites the actual dtype name; range-on-tensor-passes; range-on-tensor-out-of-bounds fails with a message that cites the bad value.
- [x] Confirmed all 5 fail today (TypeError / "expected dtype X; got ndarray" / `ValueError: truth value ambiguous`).
- [x] Add `import numpy as np` at module level in [`pipeline/contracts.py`](../../src/datarefinery/pipeline/contracts.py). (numpy is already a hard dep through the image_classification plugin; no new dependency.)
- [x] Add an ndarray branch to `_eval_dtype` at [`contracts.py:182`](../../src/datarefinery/pipeline/contracts.py#L182): when `v` is an ndarray, compare `v.dtype.name` against `expected` and report the actual dtype name on failure. The scalar fall-through path is unchanged.
- [x] Widen `bad: list[tuple[int, type]]` to `bad: list[tuple[int, str]]` and store `type(v).__name__` instead of `type(v)` in the scalar branch, so the error-message format string takes a single uniform `str` regardless of which branch produced the failure. Pure refactor — no behavior change to the scalar path.
- [x] Add an ndarray branch to `_eval_range` at [`contracts.py:216`](../../src/datarefinery/pipeline/contracts.py#L216): when `v` is an ndarray, reduce via `float(v.min())` and `float(v.max())` and compare scalars. Bad-value reporting uses the out-of-range extremum.
- [x] Prevention scan: search the pipeline package for similar `<`/`>` or `isinstance` comparisons on field values that could exhibit the same ndarray bug. Result: contracts evaluator was the only site.
- [x] Verify CI parity locally: `pyve test` (1032 passed; +5 from this story), `pyve testenv run mypy src tests` (clean, 175 source files), `pyve testenv run ruff check src/ tests/` (clean), `pyve testenv run ruff format --check src/ tests/` (clean).
- [x] Per the [`dependency-gaps-v0.16.0.md` DOC rule](dependency-gaps-v0.16.0.md): update [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) § InputContracts assertion-kinds table — clarify that `dtype` and `range` accept ndarray fields with the documented semantics.
- [x] Update [`dependency-gaps-v0.16.0.md` § G8](dependency-gaps-v0.16.0.md): status block at top documenting Story I.b outcome; severity in priority summary table updated to "Closed in v0.16.1"; entry in workarounds table updated to "(restored — `dtype` and `range` now work on tensor fields)."
- [x] Update [`CHANGELOG.md`](../../CHANGELOG.md) with `## [0.16.1]` entry: "Fixed: G8 — contracts evaluator now accepts ndarray field values for `dtype` and `range` assertions."
- [x] Bump `pyproject.toml` and `src/datarefinery/__init__.py` to `0.16.1`.
- [x] Cross-repo coordination check ([`docs/specs/modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md)): no change. The fix relaxes evaluator behavior to accept inputs the schema already permits; no field is renamed, no new kind is added, no manifest shape changes. ModelFoundry consumers see strictly more recipes validate successfully.

**Prevention notes:**

- The existing scalar tests (`test_dtype_match_passes`, `test_range_within_bounds_passes`, etc.) all pass unchanged — the scalar path was structurally untouched.
- The ndarray test fixtures use plain `np.zeros((4, 4, 3), dtype=...)` and `np.full(...)`. Tensor-shape testing per se (`shape_equals`) is not added here — that's G15 / G16 territory.
- The widening of `bad` from `tuple[int, type]` to `tuple[int, str]` is a pure refactor: callers downstream consume the second element only in the failure message format string, which now reads `{t}` instead of `{t.__name__}`. mypy validates the change.

**Out of Scope**

- Adding new assertion kinds (`tensor_range`, `tensor_shape`, `value_in_set`, `*_equals` renames). All G15/G16 plan_phase work.
- Per-split assertion machinery (`split_record_counts`, `per_class_count_per_split`). G6 plan_phase work.
- Numpy scalar handling (`np.int64(3)`, `np.float32(1.5)` as scalar field values, not ndarrays). The current `_PY_DTYPE_TAGS` aliases tolerate Python scalars; numpy 0-D scalars would need a separate audit and aren't surfaced by any consumer recipe today.
- Empty-ndarray edge case (`arr.min()` raises on a 0-element array). Not surfaced by any consumer recipe; can be addressed when a real case appears.

### Story I.c: v0.16.2 G4 — validator catches Featurization output_field colliding with loader-stamped field [Done]

**Disposition: bug fix.** Patch bump (`v0.16.1 → v0.16.2`).

Debug-mode investigation of [`dependency-gaps-v0.16.0.md` § G4](dependency-gaps-v0.16.0.md) confirmed the gap: the runtime collision detector at [`pipeline/stages/featurizations.py:110-115`](../../src/datarefinery/pipeline/stages/featurizations.py#L110-L115) correctly rejects a Featurization whose `output_field` collides with a field the input loader stamps on every record — but it does so at materialize time, after loading work has already run. The validator was missing the symmetric pre-flight check. This is a classic shift-left: the contract violation is identical; the failure timing moves from materialize to validate.

The new check (number 23 of the FR-2 set) computes the loader-stamped field set from the recipe's `Input` / `Labels` configuration and flags any Featurization writing to one of those fields. For the `image_classification` plugin the set is:

- `record_id`, `image`, `path` — always.
- `label` — when `Labels.source.kind == "direct"` and a label source is available (`image_folder` parent directory, or `image_flat` + `label_from` sidecar manifest).
- `partition` — when any `InputSource.partition` is declared.

**Tasks:**

- [x] Confirm the runtime collision check exists and works: read [`pipeline/stages/featurizations.py:110-115`](../../src/datarefinery/pipeline/stages/featurizations.py#L110-L115) and validate that it raises `MaterializeError` with a "collides with an existing field" message when a Featurization writes to a loader-stamped field.
- [x] Locate the loader to enumerate stamped fields: [`pipeline/inputs.py`](../../src/datarefinery/pipeline/inputs.py) stamps `record_id`, `image`, `path` always; `label` when a label source exists; `partition` when an InputSource declares one. Document the enumeration in `check_23`'s docstring as the in-tree authoritative source.
- [x] Add `check_23_featurization_output_field_loader_collision` to [`src/datarefinery/recipe/validator.py`](../../src/datarefinery/recipe/validator.py). Compute the reserved set from the recipe, walk `recipe.Featurizations`, report any collision with a clear message that names the reserved set and suggests how to resolve (rename `output_field` or remove the loader-side source).
- [x] Register the new check in the `_CHECKS` tuple at the bottom of [`validator.py`](../../src/datarefinery/recipe/validator.py).
- [x] Write 10 unit tests in [`tests/unit/test_validator.py`](../../tests/unit/test_validator.py) covering: passing case with no Featurizations; passing case with a novel `output_field`; failure on each of the five reserved fields (`record_id`, `image`, `path`, `label`, `partition`); the canonical G4 case (`image_flat` + `label_from` + `Labels.direct` + `output_field: label`); the symmetric `image_folder` case; the `Labels.kind: derived` case where the loader does NOT stamp `label` and the Featurization writing `label` is valid; the `partition` case only fires when an InputSource declares one. All 10 fail today, all 10 pass after the check is added.
- [x] Update [`tests/unit/test_validator.py`](../../tests/unit/test_validator.py) `test_valid_recipe_passes_all_twenty_two_checks` → `_twenty_three_checks` (literal count + `range(1, 24)`).
- [x] Update [`tests/integration/test_image_flat_label_from.py`](../../tests/integration/test_image_flat_label_from.py), [`tests/integration/test_partitioned_inputs.py`](../../tests/integration/test_partitioned_inputs.py), [`tests/integration/test_unlabeled_partition.py`](../../tests/integration/test_unlabeled_partition.py): change CLI-output literal `"22/22 checks passed"` to `"23/23 checks passed"`. (4 call sites total across the three files.)
- [x] Update [`tests/integration/test_tabular_stub_smoke.py`](../../tests/integration/test_tabular_stub_smoke.py): `assert len(report.results) == 22` → `== 23`.
- [x] Update [`docs/specs/features.md` § FR-2](../specs/features.md) enumeration: append item 23 describing `featurization_output_field_loader_collision`.
- [x] Update [`docs/specs/tech-spec.md`](../specs/tech-spec.md): `# FR-2 enumerated checks 1–22` → `1–23` in the package-structure tree comment.
- [x] Update [`README.md`](../../README.md) § CLI verbs table: validate row count `22` → `23`.
- [x] Per the [`dependency-gaps-v0.16.0.md` DOC rule](dependency-gaps-v0.16.0.md): update [`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md) § Featurizations — add a "Reserved `output_field` names" subsection enumerating the loader-stamped set per Input/Labels configuration, plus a "loader-stamped label vs. derived label" guidance block explaining the two mutually-exclusive patterns.
- [x] Update [`dependency-gaps-v0.16.0.md` § G4](dependency-gaps-v0.16.0.md): status block at top documenting Story I.c outcome; severity in priority summary table updated to "Closed in v0.16.2"; entry in workarounds table updated.
- [x] Update [`CHANGELOG.md`](../../CHANGELOG.md) with `## [0.16.2]` entry under `### Fixed`, citing the check name, the runtime-vs-validator timing shift, and the new 23/23 total.
- [x] Bump `pyproject.toml` and `src/datarefinery/__init__.py` to `0.16.2`.
- [x] Verify CI parity locally: `pyve test` (1042 passed; +10 from this story), `pyve testenv run mypy src tests` (clean, 175 source files), `pyve testenv run ruff check src/ tests/` (clean), `pyve testenv run ruff format --check src/ tests/` (clean).
- [x] Cross-repo coordination check ([`docs/specs/modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md)): no change. The new check tightens validation for a contract that already existed at the runtime layer; no recipe-model, manifest, or report shape changes. ModelFoundry consumers see strictly fewer recipes silently pass validate (which is the intended behavior).

**Prevention notes:**

- The runtime collision check at [`pipeline/stages/featurizations.py:110-115`](../../src/datarefinery/pipeline/stages/featurizations.py#L110-L115) remains in place as second-line defense. Validator check 23 is shift-left for the recipe author's diagnosability; the runtime check protects against future loader-stamp changes that the validator's enumeration doesn't yet know about.
- The reserved-field enumeration in `check_23` is duplicated knowledge with [`pipeline/inputs.py`](../../src/datarefinery/pipeline/inputs.py). If the loader changes which fields it stamps (e.g., adds a `source_name` field, or stops stamping `partition` for a corner case), `check_23`'s set must be updated in lockstep. The runtime check is the authoritative source — when there's a divergence, the runtime wins and the validator's enumeration is the bug.
- Plugin scope: the reserved-field set today is hardcoded for the `image_classification` plugin. The `tabular` and `text` stub plugins don't declare a loader with these stamps. When a non-stub plugin lands for those modalities, `check_23` will need a plugin-pluggable reserved-set hook (similar to how `OperationSpec.parameters` flows from the plugin).

**Out of Scope**

- Plugin-pluggable reserved-set hook (`Plugin.loader_stamped_fields(recipe) -> set[str]`). Not needed in v1 since only `image_classification` has a real loader; defer until `tabular` or `text` get their own loaders.
- Backporting the same shift-left pattern for the Augmentation-output / Transformation-output collision cases. The Augmentation contract is "in-place rewrite of `image`" (no new fields), and Transformations have a similar in-place semantic, so there's no symmetric collision class to shift left. Leave them as they are.
- Renaming any of the loader-stamped fields. Out of scope and would be a breaking change requiring a `schema_version` bump.

---

### Story I.d: Sinks — schema, validator, materialize-time `png_per_record` writer [Done]

**Disposition: feature addition.** Part of Bundle 1 (v0.17.0 release, Sinks — highest priority).

Per [`phase-i-intermediate-artifact-persistence-spec.md` §§ 3–4](phase-i-intermediate-artifact-persistence-spec.md): introduce a new top-level `Sinks` recipe section that captures stage-snapshot artifacts to disk at materialize time. v1 ships one writer (`png_per_record`) targeting any pipeline stage's record output via a closed `stage` vocabulary. Sinks participate in canonical recipe bytes (cache identity per spec § 4.1) and integrate with the temp-then-promote atomic write contract (FR-5 / spec § 4.2). Closes the G18 surface symptom — bit-identical export of pre-normalize stage outputs becomes structural rather than reachable only via consumer-side re-derivation.

**Tasks:**

- [x] Add `SinkOp` pydantic model to [`recipe/models.py`](../../src/datarefinery/recipe/models.py) with fields per spec § 3.2: `name: str`, `stage: Literal[...]`, `splits: list[str] | None = None`, `field: str`, `format: Literal["png_per_record"]`, `path_template: str`.
- [x] Add `Sinks: list[SinkOp] = []` to the `Recipe` model. Added to canonical bytes via the existing `to_canonical_bytes(recipe)` algorithm (default `[]` is part of `model_dump(mode="json")`) — pre-prod cache invalidation event; pinned canonical-hash fixture bumped in same change.
- [x] Add the closed stage-name Literal enum per spec § 3.3 (`SinkStage` in `recipe/models.py`). Public-exported for future G7 (Story I.v) reuse on visualization-stage dispatch.
- [x] Add validator check 24 (`sinks`) in [`recipe/validator.py`](../../src/datarefinery/recipe/validator.py): name uniqueness; template parseability; path-escape rejection (`..` or absolute); referenced `field` in the recipe's known-field universe (loader-stamped + `Output.record_schema` + Generation outputs + Featurization output fields); `splits` entries match defined splits. Stage / format are constrained by the pydantic `Literal[...]` so the validator delegates those.
- [x] Implement the path-template grammar in [`pipeline/sinks/template.py`](../../src/datarefinery/pipeline/sinks/template.py): `{field}` / `{field|stem|lower|upper|str}` / `{split}`; `parse_template` for validate-time checks; `render_template` raises `MaterializeError` on missing fields at runtime; `template_escapes_root` for the validator's path-escape check.
- [x] Implement the `png_per_record` writer in [`pipeline/sinks/writers.py`](../../src/datarefinery/pipeline/sinks/writers.py) using `PIL.Image.fromarray`. Required field shape: uint8 H×W×C (or H×W for grayscale). Non-uint8 / wrong ndim / missing field / non-ndarray each raise `MaterializeError` with an actionable message.
- [x] Add the sink-execution hook in [`pipeline/sinks/runner.py`](../../src/datarefinery/pipeline/sinks/runner.py) (`execute_sinks(...)`) and wire it into [`pipeline/runner.py`](../../src/datarefinery/pipeline/runner.py) after each named stage. Output writes under the existing temp dir; atomic temp-then-promote (FR-5) covers sink output for free, satisfying spec § 4.2.
- [x] Manifest emission per spec § 4.3: new `Manifest.sinks: dict[str, SinkManifestEntry]` field carrying `stage`, `format`, `files_written`, `bytes_total`, `path_template_resolved_root`. Added `SinkCardinalityError` for expected-vs-actual file-count assertion (also covers per-record path collisions).
- [x] Atomic write integration: sink output participates in the existing temp-then-promote rename. Failure path is exercised in `tests/integration/test_sinks.py::test_atomic_failure_leaves_no_sink_output_under_promoted_path` — pipeline fails, temp dir is flagged FAILED with sink output present, final promoted path never exists.
- [x] Added `recipe-authoring.md § Sinks` initial subsection ([`docs/guides/recipe-authoring.md`](../guides/recipe-authoring.md)): fields, stage vocabulary, path template grammar, the `png_per_record` format, cache-identity / atomicity / manifest notes, and a where-to-place-the-sink tip.
- [x] **Cross-repo coordination.** Updated [`dependency-spec.md`](modelfoundry/dependency-spec.md) with the `manifest.sinks` field shape (additive; no `schema_version` bump per spec § 7).
- [x] Updated [`tech-spec.md`](tech-spec.md): added `Sinks: list[SinkOp]` to the `Recipe` model table, the `SinkOp` row in per-section models, the `Manifest.sinks` field, the sink-execution stage hook description, and the recipe sections recap.
- [x] Unit tests: pydantic model validation (`tests/unit/test_sinks_model.py`); validator checks (`tests/unit/test_sinks_validator.py`); template grammar (`tests/unit/test_sinks_template.py`); writer round-trip vs. `Image.fromarray` baseline (`tests/unit/test_sinks_writers.py`); cache-identity participation (canonical-bytes shift for added sink and `path_template`-only change); sink-runner unit harness with collision / stage-mismatch / split-filter cases (`tests/unit/test_sinks_runner.py`).
- [x] Integration test mirroring spec § 6: `tests/integration/test_sinks.py` materializes a recipe with `post_Filters` and `post_Generation` `png_per_record` sinks, asserts both file trees + both `manifest.sinks` entries; second test asserts atomicity on injected mid-pipeline failure.

**Out of Scope:**

- The `datarefinery export` verb and per-record-seed persistence — Stories I.e and I.f.
- Additional formats (`npy_per_record`, `parquet`, `tar`) — deferred to `stories.md § Future` per spec § 8.
- Cross-record sink formats (e.g., one tar per split) — Future per spec § 8.
- Conditional sinks (capture-if-predicate) — Future per spec § 8.
- Sink output validation beyond the cardinality check — Future per spec § 8.

---

### Story I.e: Per-record-seed persistence (prerequisite for `datarefinery export`) [Done]

**Disposition: feature addition.** Part of Bundle 1 (v0.17.0 release, Sinks).

Per [`phase-i-intermediate-artifact-persistence-spec.md` § 5](phase-i-intermediate-artifact-persistence-spec.md): the `datarefinery export` verb (Story I.f) re-executes stage-internal logic against a cached instance to produce sink output post-hoc. That requires per-record stochastic seeds to be persistable so the export verb can reconstruct stage outputs without re-deriving from the master seed alone. This story stamps `<op_name>_seed` onto every record produced by a stochastic op in Generation and aggressive-mode Augmentations. Transformations and Filters are deterministic given `record_id` and need no seed sidecar.

**Tasks:**

- [x] Identified the stochastic-op surface. **Generation:** `imagecorruptions_apply` ([`generation_imagecorruptions.py`](../../src/datarefinery/plugins/image_classification/generation_imagecorruptions.py)) computes `prs = per_record_seed(op.seed, record)` from [`pipeline/workers.py`](../../src/datarefinery/pipeline/workers.py) once per input record and consumes that RNG across every (corruption, severity) combination. **Augmentations (aggressive):** `emit_variants` in [`augmentations/_realizer.py`](../../src/datarefinery/plugins/image_classification/augmentations/_realizer.py) calls `per_record_variant_seed(global_seed, record, vi, op_id=op.op)` once per variant. `duplicate_minority_class` is op-level stochastic (not per-record), so it does not need a stamp — the op-level seed already lives in `recipe.json` and duplicated records share their source `record_id`. Lazy Augmentations / Transformations / Filters confirmed deterministic given `record_id`.
- [x] Persistence schema: `<GenerationOp.name>_seed: int` / `<AugmentationOp.name>_seed: int` (8-byte unsigned). Keyed on the recipe-defined op name (`op.name` / `AugmentationOp.name`) — not the op kind — so two ops of the same kind in one recipe never collide. The field rides through to cached JSONL (the existing runner serializer accepts ints) and is captured by any Sink targeting `post_<stochastic_stage>`.
- [x] Updated [`generation_imagecorruptions.py`](../../src/datarefinery/plugins/image_classification/generation_imagecorruptions.py) to accept a new required `op_name: str` kwarg and stamp `<op_name>_seed = prs` on every output record (corrupted and preserved-original). The Generation contract documented in [`pipeline/stages/generation.py`](../../src/datarefinery/pipeline/stages/generation.py) is extended with `op_name`; the stage's `_invoke_one` always passes `op_name=op.name`. `duplicate_minority_class` accepts and ignores `op_name` for contract uniformity.
- [x] Updated [`pipeline/stages/augmentations.py`](../../src/datarefinery/pipeline/stages/augmentations.py): aggressive dispatch now passes `stamp_field=f"{op.name}_seed"` to `emit_variants`. `emit_variants` gained an optional `stamp_field` parameter (defaults to `None` for ad-hoc / test callers); when supplied each variant carries `merged[stamp_field] = seed`. Per-variant seed derivation (`op_id=op.op`) is unchanged — the FR-3 determinism contract is preserved.
- [x] Confirmed cached JSONL persistence: the runner's `_serializable` / `_coerce` accept Python ints verbatim, so `<op_name>_seed` appears in `dataset/<split>.jsonl` without further plumbing. `Output.record_schema` validates "every declared field present"; extras like the seed stamp pass through.
- [x] Cache-identity note recorded: stamping does NOT perturb canonical recipe bytes (no shape change; the pinned hash from Story I.d is unaffected). It DOES change cached record bytes for any recipe with a stochastic op. Pre-prod invalidation per `project-essentials.md § "Cache identity is the reproducibility contract"`. Documented in CHANGELOG `[Unreleased]`; Story I.g release notes will fold this into the v0.17.0 announcement.
- [x] Updated [`tech-spec.md`](tech-spec.md): new "Per-record-seed persistence (Story I.e)" subsection in `pipeline.runner` describing the Generation op contract extension, the aggressive `stamp_field` plumbing, and the cache-bytes-only invalidation property.
- [x] Updated [`recipe-authoring.md § Generation`](../guides/recipe-authoring.md) and § Augmentations with author-facing callouts on the `<op_name>_seed` field and its role for the future `datarefinery export` verb.
- [x] **Cross-repo coordination.** [`dependency-spec.md`](modelfoundry/dependency-spec.md) JSONL-record section now documents the per-record-seed stamp fields (Generation + aggressive Augmentation), including the exact derivation formulas so consumer tools can compute the expected stamp from the recipe + input record.
- [x] Unit tests in [`tests/plugins/image_classification/test_per_record_seed_persistence.py`](../../tests/plugins/image_classification/test_per_record_seed_persistence.py): stamp matches `per_record_seed(op.seed, input)` per output; deterministic across runs; required `op_name` kwarg; aggressive `emit_variants` stamps `<stamp_field>` matching `per_record_variant_seed`; no leakage when `stamp_field` is omitted.
- [x] Integration test [`tests/integration/test_per_record_seed_persistence.py`](../../tests/integration/test_per_record_seed_persistence.py): a Generation-only recipe materializes; cached JSONL records each carry `imagecorruptions_apply_seed`; replaying `corrupt(...)` with the recorded seed reproduces the post-Generation sink PNG bytes bit-identically.

**Out of Scope:**

- The `datarefinery export` verb itself — Story I.f.
- Per-record seeds for non-stochastic ops (Transformations, Filters) — those are deterministic given `record_id`.
- Lazy-mode Augmentation seed stamping — lazy realization happens at consume time outside the pipeline; not a sink-target stage.

---

### Story I.f: `datarefinery export` verb + `recipe-authoring.md § Sinks` consolidation [Done]

**Disposition: feature addition.** Part of Bundle 1 (v0.17.0 release, Sinks).

Per [`phase-i-intermediate-artifact-persistence-spec.md` § 5](phase-i-intermediate-artifact-persistence-spec.md): a new `datarefinery export` CLI verb (and library method) re-runs sinks against an already-materialized instance. Unblocks the workflow where a recipe author adds a sink to a recipe with a live cache and wants the sink output without invalidating the cache. v1 restriction: only sinks whose stage output is reconstructable from cached state + fitted statistics + per-record seeds (Story I.e's prerequisite); non-reconstructable stages refuse cleanly with a pointer to re-materialize.

**Tasks:**

- [x] Added `datarefinery export <recipe> [--sink <name> ...]` CLI verb in [`cli/commands/export_cmd.py`](../../src/datarefinery/cli/commands/export_cmd.py) wired into [`cli/app.py`](../../src/datarefinery/cli/app.py). Default: re-run all sinks declared on the recipe. `--sink <name>` (repeatable): filter to the named sinks. Unknown `--sink` name → `MaterializeError` listing the declared names.
- [x] Added `DataRefinery.export(sink_names=..., raw_input_hashes=..., raw_records=...)` in [`core/datarefinery.py`](../../src/datarefinery/core/datarefinery.py). The optional `raw_records` / `raw_input_hashes` kwargs mirror the materialize library API so library callers using synthetic records (not the disk loader) can still resolve the bound instance.
- [x] Resolved the bound instance via a sinks-stripped cache-key lookup — adding a sink to a recipe perturbs canonical bytes but the previously-materialized instance is the relevant one to read from. Refuses cleanly with a pointer to `datarefinery materialize` when no matching instance exists.
- [x] Implemented re-execution dispatch in [`pipeline/sinks/export.py`](../../src/datarefinery/pipeline/sinks/export.py). `post_OutputExpectations` / `post_Visualizations` read cached JSONL directly. `post_Generation` reconstructs by re-loading the input subset, re-running the recipe's `Generation` ops over it, and matching outputs to cached records by `record_id` (byte-identical because Story I.e's per-record seeds pin the stochastic outputs). All other stages refuse with a pointer to re-materialize.
- [x] Per-file atomic writes: each sink stages output under `.export_tmp_<uuid>/` and `os.replace`s onto the final layout. An interrupted export never leaves a half-written file under the promoted path.
- [x] v1 reconstructability table lives in `pipeline/sinks/export.py` (`_TRIVIAL_STAGES` / `_GENERATION_STAGE` / `_RECONSTRUCTABLE_STAGES`); both validate-time and runtime checks consult the same constants.
- [x] Consolidated [`recipe-authoring.md § Sinks`](../guides/recipe-authoring.md): added the `datarefinery export` usage block, the full v1 reconstructability table, a "when to prefer materialize over export" callout, and the per-record-seed dependency from Story I.e.
- [x] Updated [`tech-spec.md`](tech-spec.md): added the export-verb dispatch table to the `pipeline.runner` section and a row in the CLI Subcommands table.
- [x] Unit + CLI tests: `tests/integration/test_export_verb.py` covers parity vs. re-materialize (byte-identical sink output), `--sink` selection, unknown-sink refusal, no-bound-instance refusal, and non-reconstructable-stage refusal. `tests/cli/test_export_cmd.py` exercises the Typer surface end-to-end through `CliRunner`.
- [x] Integration parity test: materialize the recipe without sinks → run `datarefinery export` with a sink-added recipe → confirm the export output is byte-identical to a fresh materialize-with-the-sink. The recipe-hash mismatch is the expected state; export bypasses the materialize gate via the sinks-stripped cache-key lookup.
- [x] **Latent issues closed alongside.** Added `"Sinks"` to `recipe.loader.KNOWN_TOP_LEVEL_KEYS` (Story I.d shipped the model + validator but missed the loader's forward-compat key set). Added a `[[tool.mypy.overrides]]` entry suppressing the `click` missing-stub error so CI mypy passes against environments without `types-click` (click v8+ ships its own typing; the override is a no-op locally and silences CI on older clients).

**Out of Scope:**

- Sink output behavior under partial / `stop_after` materialize runs — open question per spec § 10 #3; deferred to Story I.f.1.
- Conditional sinks — Future per spec § 8.
- Cross-record sink formats — Future per spec § 8.

---

### Story I.f.1: Announced-skip for partial-run sinks [Done]

**Disposition: feature follow-on.** Part of Bundle 1 (v0.17.0 release, Sinks). Closes spec open question § 10 #3 ([`phase-i-intermediate-artifact-persistence-spec.md`](phase-i-intermediate-artifact-persistence-spec.md)).

When `materialize --stage <stop>` runs partially, sinks targeting stages later than `<stop>` never fire. Today the partial manifest doesn't mention them at all (silent skip). This story changes that to **announced skip**: the partial manifest records skipped sinks under a new `manifest.sinks_skipped: dict[str, str]` field (sink name → declared stage), and also threads the in-progress `sink_results` into `_partial_finish` so sinks that DID fire appear in `manifest.sinks` (today's `_partial_finish` ignored them — a small inconsistency with `is_partial=True` semantics where the manifest is supposed to reflect what completed).

**Tasks:**

- [x] Added `Manifest.sinks_skipped: dict[str, str]` in [`pipeline/manifest.py`](../../src/datarefinery/pipeline/manifest.py). Default empty dict; structured map kept separate from `Manifest.sinks` so fired-vs-skipped is unambiguous for downstream consumers.
- [x] Track reached sink stages in [`pipeline/runner.py`](../../src/datarefinery/pipeline/runner.py): `_run_sinks(stage, ...)` adds the stage to a `reached_sink_stages: set[str]` on every invocation (including when the recipe declares no sinks at that stage). `_partial_finish` computes `sinks_skipped = {s.name: s.stage for s in recipe.Sinks if s.stage not in reached_sink_stages}`.
- [x] Threaded `sink_results` into `_partial_finish` as a keyword-only arg so the partial manifest's `sinks` map reflects every sink that fired before the stop point. Closes the latent gap noted during the open-question discussion.
- [x] CLI: extended [`cli/commands/status_cmd.py`](../../src/datarefinery/cli/commands/status_cmd.py) with `_sinks_skipped_table`; renders only when `manifest.sinks_skipped` is non-empty, neutral cyan border (informational, not warning-styled).
- [x] **Cross-repo coordination.** Added the `sinks_skipped` row to the manifest-fields table in [`dependency-spec.md`](modelfoundry/dependency-spec.md). Additive; no `schema_version` bump.
- [x] Unit test [`tests/integration/test_sinks_partial_run.py`](../../tests/integration/test_sinks_partial_run.py): runner pass with `stop_after="Filters/post_split"` and sinks declared at `post_Filters`, `post_Generation`, `post_Visualizations` produces a partial manifest with the post_Filters sink in `sinks` and the other two in `sinks_skipped`. Companion tests pin the full-run case (`sinks_skipped == {}`) and the no-sinks case.
- [x] CLI test in [`tests/cli/test_status_cmd.py`](../../tests/cli/test_status_cmd.py): `datarefinery status` against the partial instance shows the "Sinks skipped" table with the declared stage names.
- [x] CHANGELOG entry under `[Unreleased]`.

**Out of Scope:**

- Changing `--stage` to fail when sinks are declared at later stages — confirmed declined per the spec resolution.
- Surfacing the skip list in the `materialize` CLI summary output — `status` is the canonical inspection surface for partial instances; adding a second site would risk drift.

---

### Story I.g: Release v0.17.0 (Phase I bundle 1, Sinks) [Done]

**Disposition: release ceremony.** Minor bump (`v0.16.2 → v0.17.0`). Closes Bundle 1.

Bundle 1 contents: I.d (sinks schema + materialize-time writer), I.e (per-record-seed persistence), I.f (`datarefinery export` verb + author guide). Additive — no `schema_version` bump. The cross-repo contract bound during this bundle is `manifest.sinks` + the per-record-seed field convention (both documented in `modelfoundry/dependency-spec.md` by Stories I.d and I.e).

One cached-bytes change: Story I.e stamps `<op_name>_seed` onto cached records for any recipe with a stochastic op, changing JSONL contents. Pre-production rules apply per [`project-essentials.md` § "Cache identity is the reproducibility contract"](project-essentials.md): users re-materialize once at upgrade; documented in the release notes below.

**Tasks:**

- [x] Bump `pyproject.toml` `version = "0.16.2"` → `"0.17.0"`.
- [x] Bump `src/datarefinery/__init__.py` `__version__` accordingly.
- [x] [`CHANGELOG.md`](../../CHANGELOG.md) `## [0.17.0]`:
   - **Added:** "Sinks — new top-level recipe section that captures stage-snapshot artifacts to disk at materialize time. v1 ships the `png_per_record` writer; full author guide in `recipe-authoring.md § Sinks` (Story I.d)."
   - **Added:** "Per-record `<op_name>_seed` persistence on every record produced by a stochastic Generation or aggressive-mode Augmentation op (Story I.e)."
   - **Added:** "`datarefinery export <recipe> [--sink <name> …]` CLI verb (and `DataRefinery.export()` library method) — re-runs sinks against an already-materialized instance without invalidating the cache (Story I.f)."
   - **Notes:** "Cached JSONL records now include `<op_name>_seed` fields for stochastic ops. One-time pre-production cache invalidation event; re-materialize existing recipes once at upgrade. No `schema_version` bump (the change is record-byte-level, not recipe-shape-level)."
- [x] Cross-repo coordination: confirm `dependency-spec.md` was updated by I.d (`manifest.sinks` shape) and I.e (per-record-seed field convention).
- [x] Ensure the canonical-hash pinning test for representative recipes either (a) is unaffected (recipes without sinks AND without stochastic ops produce byte-identical canonical bytes) or (b) is updated alongside this bump with reviewer sign-off per `project-essentials.md`.
- [x] **Release-time fix — regression from Story I.f.** I.f added a direct `import click` to [`cli/app.py`](../../src/datarefinery/cli/app.py) without declaring `click` in `[project.dependencies]`; it was pulled in transitively via `typer`, so `pyve test` passed locally but CI's `pip install -e ".[corruptions]"` path collected `ModuleNotFoundError: No module named 'click'` on every CLI test at the I.g release ceremony. Added `click>=8` to `[project.dependencies]` and recorded the fix in the v0.17.0 CHANGELOG `Fixed` subsection.

---

### Story I.h: Sanitize consumer-context leakage + renumber G7 placeholder [Done]

**Disposition: documentation-only.** Part of Bundle 2; no version bump (no code change).

The gap doc, the existing Story I.h body (G7 placeholder), and the intermediate-artifact persistence spec may carry residual references to the downstream consumer's project context. Phase I's expansion stories cite the gap doc by section; sanitizing first prevents that leakage from propagating into the new story bodies. This story also renumbers the existing I.h (G7) to its new slot at Story I.v per the Phase I plan and adds deferred items to `stories.md § Future`.

**Scope decision.** During execution the consumer-context surface in [`phase-i-dependency-gaps-v0.16.0.md`](phase-i-dependency-gaps-v0.16.0.md) was deeper than a vocabulary sweep — the gap doc is structurally a consumer-perspective document (title, framing, specific consumer recipe filenames, consumer story IDs, consumer-specific numbers). Sanitizing it to fully generic framing would substantially rewrite nearly every section. The developer scoped this story to a **narrow sweep** — scrubbing only the hard-blacklisted course identifiers (the consumer-side course number, institution acronym, and full institution name; full list lives in the developer's auto-memory under "Anonymize consumer-spec context") that would directly tie the repo to the downstream course — and deferred the broader rewrite to a post-course Future story (see § Future "Broad consumer-context rewrite of internal specs"). Lower-impact surface (Recipe A/B framing, Module N references, specific consumer numbers, links to consumer-side docs) remains in place; git history will continue to carry that surface regardless of the post-course scrub. Story body uses oblique terms ("course identifier", "institution acronym") rather than the literal strings so the scrubbed terms don't reappear in the working tree.

**Tasks:**

- [x] Search [`phase-i-dependency-gaps-v0.16.0.md`](phase-i-dependency-gaps-v0.16.0.md) for hard-blacklisted course identifiers. **Result:** zero hits — gap doc was clean for the narrow scope. Broader consumer-context framing (Recipe A/B, Module N, consumer phase plan, consumer recipe filenames) deferred to the post-course Future story.
- [x] Search [`stories.md`](stories.md) Story I.h body for the same blacklist. **Result:** zero hits — story bodies were clean for the narrow scope.
- [x] Renumber the existing Story I.h (G7 stage-aware visualization dispatch) to Story I.v within Bundle 2. Per the [renumber pre-condition](../project-guide/go.md#inserting-a-new-story): verified I.h was `[Planned]` and no references had accreted.
- [x] Verify no residual blacklist leakage anywhere in `docs/`, `src/`, `recipes/`, `tests/`. Ran the auto-memory blacklist grep. **Result:** 6 hits in [`phase-i-intermediate-artifact-persistence-spec.md`](phase-i-intermediate-artifact-persistence-spec.md) (lines 4, 42, 344, 347, 394, 435); each rephrased to a generic equivalent (`consumer-side`, `downstream submission deliverable`, etc.). Post-sweep grep returns empty.
- [x] Append the new Phase I stories I.i through I.y under the existing Phase I heading; insert before `## Future`.
- [x] Append the following deferred items to `stories.md § Future` (per the Phase I plan's "Future-section addition" subsection): `stats_from_instance.variant: <name>` selector; `to_grayscale` Transformation op; plugin-pluggable validator-check reserved-set hook; per-stage report subsections; scaffolder v2 grand sweep; real `distributional` assertion kind; DR-side `class_balance` resampling.
- [x] Append a new `stories.md § Future` entry capturing the deferred broad consumer-context rewrite (post-course execution).
- [x] No code change, no test change. No version bump; bundled at I.j.

**Out of Scope:**

- Edits to "deep-learning curriculum" / "students and instructors" mentions in `concept.md`, `features.md`, `idea.md`, `idea-supplement.md`. Those describe the product's target-user type generically and are not consumer-specific.
- Broad consumer-context rewrite of `phase-i-dependency-gaps-v0.16.0.md` and `phase-i-intermediate-artifact-persistence-spec.md` (Recipe A/B framing, Module N references, consumer recipe filenames, consumer phase-plan links, consumer-specific record counts). Deferred to a post-course Future story to lower blast radius without forcing a structural rewrite of working consumer-perspective documents mid-course.

---

### Story I.i: G19 — sibling-stats resolver strips variants [Done]

**Disposition: bug fix.** Part of Bundle 2 (v0.17.1 release).

Per [`dependency-gaps-v0.16.0.md` § G19](phase-i-dependency-gaps-v0.16.0.md): `resolve_sibling_stats` ([`cache/sibling_stats.py:88`](../../src/datarefinery/cache/sibling_stats.py)) loads the sibling recipe and hashes it without stripping the variants block first. The materialize path always strips variants via `apply_variant(recipe, None)` before computing the cache key; the resolver diverges, producing a hash mismatch any time the sibling declares variants. The fix is a one-line addition mirroring the materialize path.

**Tasks:**

- [x] Reproduce with a failing test in `tests/unit/test_sibling_stats.py`: a sibling recipe declaring `variants`, materialized once via a materialize-path-mirroring helper, then `resolve_sibling_stats` called with the sibling path. Pre-fix: raises `SiblingInstanceNotFoundError`. Post-fix: returns the FittedStatistics handle.
- [x] Apply the one-line fix in [`cache/sibling_stats.py`](../../src/datarefinery/cache/sibling_stats.py): wrap `load_recipe(recipe_path)` with `apply_variant(..., None)` before `to_canonical_bytes`. Import path mirrors `core/datarefinery.py:92`.
- [x] Add a regression test for the no-variant case: `apply_variant(recipe, None)` preserves canonical bytes when no variants are declared, so the fix does not invalidate sibling lookups for existing recipes.
- [x] DOC: added "FR-TRANS-1 across variants" subsection to [`recipe-authoring.md` § Transformations](../guides/recipe-authoring.md) documenting that `stats_from_instance` resolves the sibling's no-variant canonical instance, with the future variant-selector form referenced from `stories.md § Future`.
- [x] Updated [`phase-i-dependency-gaps-v0.16.0.md` § G19](phase-i-dependency-gaps-v0.16.0.md): status block; priority summary row → "Closed in v0.17.1 (Story I.i)"; workarounds row prefixed "Closed in v0.17.1 (Story I.i)".
- [x] Cross-repo coordination check ([`modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md)): no contract surface change — `stats_from_instance` resolution semantics aren't named in the spec; the fix is purely an internal resolver bug fix.
- [x] CI parity: `pyve test` 1106 passed; `pyve testenv run mypy src tests` clean; `pyve testenv run ruff check src/ tests/` clean; `pyve testenv run ruff format --check src/ tests/` clean.

**Out of Scope:**

- `stats_from_instance.variant: <name>` selector — deferred to `stories.md § Future`.

---

### Story I.j: Release v0.17.1 (Phase I bundle 2) [Done]

**Disposition: release ceremony.** Patch bump (`v0.17.0 → v0.17.1`). Closes Bundle 2.

Dedicated commit for the version bump so the release is identifiable in commit history rather than buried in the bug-fix commit. Bundle 2 contents: I.h (doc sanitize, no code) + I.i (G19 resolver fix). Ships after the Sinks bundle (v0.17.0).

**Tasks:**

- [x] Bumped `pyproject.toml` `version = "0.17.0"` → `"0.17.1"`.
- [x] Bumped `src/datarefinery/__init__.py` `__version__` to `"0.17.1"`.
- [x] [`CHANGELOG.md`](../../CHANGELOG.md) `## [0.17.1] - 2026-05-27` added with Fixed entry for G19 (Story I.i) and Documentation entry for the narrow-scope sanitize and Phase I Future-section additions (Story I.h). Per the I.h scope-decision note, the Documentation bullet reflects what was actually scrubbed (`phase-i-intermediate-artifact-persistence-spec.md`) rather than the pre-execution placeholder wording in this task list, and uses the existing `### Documentation` section heading already established in the CHANGELOG (e.g., v0.13.0, v0.12.0).
- [x] Cross-repo coordination: no change ([`modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md) untouched; neither I.h nor I.i altered a contract surface).
- [x] CI parity: `pyve test` 1106 passed; `pyve testenv run mypy src tests` clean; `pyve testenv run ruff check src/ tests/` clean; `pyve testenv run ruff format --check src/ tests/` clean.

---

### Story I.k: G2 — `cast` Transformation [Done]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`phase-i-dependency-gaps-v0.16.0.md` § G2](phase-i-dependency-gaps-v0.16.0.md): `cast_dtype` was declared in `_supported_operations()` but missing from `_TRANSFORMATION_OPS` (`NotImplementedError` at materialize). This story registers the runtime factory under the canonical name `cast`, adds a `scale` parameter (for the common uint8 → float32-scaled-by-1/255 pattern), and removes the unimplemented `cast_dtype` and `to_grayscale` OperationSpec entries.

**Tasks:**

- [x] Added `CastOp` to [`plugins/image_classification/operations/transformations.py`](../../src/datarefinery/plugins/image_classification/operations/transformations.py): `np.dtype(params["dtype"])` + `params.get("scale", 1.0)`, deterministic per-record apply, no fit phase.
- [x] OperationSpec in [`plugin.py`](../../src/datarefinery/plugins/image_classification/plugin.py): added `"cast"` with `dtype: str` (required) + `scale: float, default=1.0`. Removed the `"cast_dtype"` and `"to_grayscale"` entries.
- [x] Registered `"cast": CastOp()` in `_TRANSFORMATION_OPS`.
- [x] Updated [`tests/plugin_contract/test_image_classification.py`](../../tests/plugin_contract/test_image_classification.py): swapped `EXPECTED_OPERATIONS` (`cast_dtype` + `to_grayscale` → `cast`); dropped the `NotImplementedError`-pinning assertions for both; extended the C.h-wired-op test to cover `cast`.
- [x] Unit tests in [`test_transformations_stage.py`](../../tests/unit/test_transformations_stage.py): cast uint8→float32 scale=1/255 → values in [0,1]; cast with no `scale` is dtype change only (values unchanged); cast on already-float32 input is a dtype no-op; cast persists no fitted stats. Plus two recipe-level rejection tests: old name `cast_dtype` and removed `to_grayscale` each fail validator check 18 with "not declared by plugin".
- [x] DOC: added worked YAML examples for `op: cast` (with `dtype` and `scale`), backfilled `resize`, `mean_subtract`, and `normalize` summary blocks under [`recipe-authoring.md` § Transformations](../guides/recipe-authoring.md), closing the DOC-drift gap for the Transformations section.
- [x] Updated [`phase-i-dependency-gaps-v0.16.0.md` § G2](phase-i-dependency-gaps-v0.16.0.md): status block; priority-summary row → "Closed in v0.18.0 (Story I.k)"; workarounds row prefixed "Closed in v0.18.0 (Story I.k)".
- [x] Cross-repo coordination check ([`modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md)): no mention of `cast` / `cast_dtype` / `to_grayscale` — no contract surface change.
- [x] CI parity: `pyve test` 1111 passed; `pyve testenv run mypy src tests` clean; `pyve testenv run ruff check src/ tests/` clean; `pyve testenv run ruff format --check src/ tests/` clean.

**Out of Scope:**

- Real `to_grayscale` op implementation. Removed from OperationSpec; deferred to `stories.md § Future`.
- Aliasing `cast_dtype` to `cast`. Old name removed (not aliased) to keep the surface single-named.

---

### Story I.l: G3 — `categorical_encode` Featurization [Done]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`phase-i-dependency-gaps-v0.16.0.md` § G3](phase-i-dependency-gaps-v0.16.0.md): a new Featurization op that derives an integer-encoded field from a categorical source. Two modes: recipe-declared `vocabulary` (deterministic, persisted-but-verbatim) and fit-on-train (vocabulary derived from train split, persisted to `fitted_statistics/<op_name>/vocabulary.parquet`, replayed identically on val/test). The fit-on-train mode is FR-TRANS-1 transplanted to Featurizations.

**Tasks:**

- [x] Added `CategoricalEncodeOp` class to [`plugins/image_classification/operations/featurizations.py`](../../src/datarefinery/plugins/image_classification/operations/featurizations.py). Fit phase: returns the recipe-supplied vocabulary verbatim when present, else derives the vocabulary from train labels per `ordering` (`alphabetical` default, `first_seen` alternative). Apply: builds the string→int index from `params.vocabulary`, `fitted.vectors["vocabulary"]`, or a sibling-stats import; encodes each record's input label to the declared `output_dtype` (default `int32`); raises a `PluginError` naming the missing label when a record's value is outside the vocabulary.
- [x] OperationSpec in [`plugin.py`](../../src/datarefinery/plugins/image_classification/plugin.py): `vocabulary: list[str], required=False`; `ordering: str, required=False, default="alphabetical"`; `output_dtype: str, required=False, default="int32"`; `stats_from_instance: StatsFromInstanceSpec, required=False`. `fit_on_train=True`. The spec follows the NormalizeOp pattern (recipe-supplied data still goes through fit so it lands in the audit trail).
- [x] Registered `"categorical_encode": CategoricalEncodeOp()` in `_FEATURIZATION_OPS`.
- [x] **Stage-runner extension.** Added a `cache_root: Path | None` parameter and a `stats_from_instance` branch to [`pipeline/stages/featurizations.py`](../../src/datarefinery/pipeline/stages/featurizations.py) mirroring the Transformations-stage behavior; `_load_sibling_fitted` is shared with the Transformations stage. Pipeline runner ([`pipeline/runner.py`](../../src/datarefinery/pipeline/runner.py)) now passes `cache_root=self.config.cache_root` to `apply_featurizations` so FR-TRANS-1 imports work for any fit-on-train Featurization, not just `categorical_encode`. This was not in the original task list — the story's FR-TRANS-1 unit-test prescription assumes the path works, so the runner extension is the natural follow-on rather than a scope expansion.
- [x] Plugin contract test: added `categorical_encode` to `EXPECTED_OPERATIONS`; extended the C.i wired-op test; renamed `test_fit_on_train_ops_are_in_transformations` → `test_fit_on_train_ops_are_in_fit_capable_sections` since fit-on-train Featurizations are now valid (the prior test enforced "Transformations only", which was an implicit Story-C.h-era invariant).
- [x] Unit tests in [`test_featurizations_stage.py`](../../tests/unit/test_featurizations_stage.py): recipe-declared vocabulary path (mode 1, persisted verbatim); fit-on-train path (mode 2) with `alphabetical` and `first_seen` orderings; `output_dtype: int64` honored; unknown-label rejection naming the missing label; unknown-`ordering` rejection. Integration test for FR-TRANS-1 sibling-stats import in [`tests/plugins/image_classification/test_categorical_encode_stats_from_instance.py`](../../tests/plugins/image_classification/test_categorical_encode_stats_from_instance.py).
- [x] DOC: added worked YAML examples for both modes under [`recipe-authoring.md` § Featurizations](../guides/recipe-authoring.md), plus backfilled `image_size_stats` (closes DOC drift) and short summaries for `label_from_path`'s alternative `source` values.
- [x] Updated [`phase-i-dependency-gaps-v0.16.0.md` § G3](phase-i-dependency-gaps-v0.16.0.md): status block; priority-summary row → "Closed in v0.18.0 (Story I.l)"; workarounds row prefixed "Closed in v0.18.0 (Story I.l)".
- [x] Cross-repo coordination check ([`modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md)): no mention of `categorical_encode` or fit-on-train Featurizations — no contract surface change.
- [x] CI parity: `pyve test` 1119 passed; `pyve testenv run mypy src tests` clean; `pyve testenv run ruff check src/ tests/` clean; `pyve testenv run ruff format --check src/ tests/` clean.

---

### Story I.m: G9 — `flatten` Featurization [Done]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`phase-i-dependency-gaps-v0.16.0.md` § G9](phase-i-dependency-gaps-v0.16.0.md): a new Featurization op that reshapes a multi-dimensional field to a 1-D vector. Unblocks variants that want both the original tensor and a flattened view (e.g., MLP-shaped vs. CNN-shaped consumption from one recipe).

**Tasks:**

- [x] Added `FlattenOp` class to [`plugins/image_classification/operations/featurizations.py`](../../src/datarefinery/plugins/image_classification/operations/featurizations.py). Deterministic, no fit phase: `np.asarray(r[src]).reshape(-1)` per record, with the source field preserved alongside the new `output_field`.
- [x] OperationSpec in [`plugin.py`](../../src/datarefinery/plugins/image_classification/plugin.py): no params; `applicable_sections=frozenset({"Featurizations"})`. The "exactly one input" rule is enforced op-side at apply time (`PluginError`); no validator-check change needed.
- [x] Registered `"flatten": FlattenOp()` in `_FEATURIZATION_OPS`.
- [x] Unit tests in [`test_featurizations_stage.py`](../../tests/unit/test_featurizations_stage.py): 3-D image → 1-D vector with correct shape and values; dtype preserved; source field not dropped; multi-input rejected with `PluginError`; zero-input rejected; variant overlay (`variants.mlp_flat.Featurizations: [flatten op]`) round-trips through `apply_variant(recipe, "mlp_flat")` and `apply_variant(recipe, None)` cleanly.
- [x] Plugin contract test: added `flatten` to `EXPECTED_OPERATIONS`; extended the C.i wired-op test.
- [x] DOC: added worked YAML example under [`recipe-authoring.md` § Featurizations](../guides/recipe-authoring.md) (Image-classification Featurizations subsection).
- [x] Updated [`phase-i-dependency-gaps-v0.16.0.md` § G9](phase-i-dependency-gaps-v0.16.0.md): status block; priority-summary row → "Closed in v0.18.0 (Story I.m)"; workarounds row prefixed "Closed in v0.18.0 (Story I.m)".
- [x] Cross-repo coordination check ([`modelfoundry/dependency-spec.md`](modelfoundry/dependency-spec.md)): no mention of `flatten` — no contract surface change.
- [x] CI parity: `pyve test` 1126 passed; `pyve testenv run mypy src tests` clean; `pyve testenv run ruff check src/ tests/` clean; `pyve testenv run ruff format --check src/ tests/` clean.

---

### Story I.n: G11 — `seed_derive_from: master` on Filters and Generation [Planned]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`dependency-gaps-v0.16.0.md` § G11](dependency-gaps-v0.16.0.md): a new `SeedDerivationSpec` schema accepts the literal `"master"` as an alternative to a fixed integer at every seeded-op site. Resolution at materialize time computes `derived_seed = sha256(recipe.seed.to_bytes(8, "big") + op_name_bytes).digest()[:8]`. The derivation participates in cache identity (via the master seed already being in canonical bytes) and is pinned by test.

**Tasks:**

- [ ] Add `SeedDerivationSpec` to [`recipe/models.py`](../../src/datarefinery/recipe/models.py) — pydantic model accepting `from: Literal["master"]`.
- [ ] Widen the seed-accepting sites to `int | SeedDerivationSpec`: `FilterOp.predicate.seed` (via plugin OperationSpec); `GenerationOp.seed` (model field); `SplitsSection.seed` (model field); `AugmentationOp.seed` (already optional, add accepting form).
- [ ] Implement derivation in a shared helper (e.g., `recipe/seeds.py`): `derive_seed(master_seed: int, op_name: str) -> int`. Pinned by canonical-derivation test.
- [ ] Update each seed-consuming op site to resolve `SeedDerivationSpec` → concrete int via the helper before use.
- [ ] Unit tests: same master seed + different op name → different derived seeds (no collision); changing master seed → all derived seeds change; same op name + same master → same derived seed; explicit int still works (regression).
- [ ] DOC: new "Seeds and determinism" subsection in [`recipe-authoring.md`](../guides/recipe-authoring.md) covering the master-seed derivation policy, cache-identity implications, and the per-op-seed escape hatch.
- [ ] Update [`tech-spec.md`](tech-spec.md) with the pinned derivation function (participates in cache identity).
- [ ] Update [`dependency-gaps-v0.16.0.md` § G11](dependency-gaps-v0.16.0.md): status block; priority summary → "Closed in v0.18.0"; workarounds row.

---

### Story I.o: G6 + G16b — per-split / per-class / structural assertion kinds [Planned]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`dependency-gaps-v0.16.0.md` § G6](dependency-gaps-v0.16.0.md) and [§ G16b](dependency-gaps-v0.16.0.md): seven new assertion kinds land together (they share evaluator plumbing). The `evaluate_output_expectations` signature widens from `Iterable[Record]` to `Mapping[str, list[Record]]` keyed by split. `evaluate_input_contracts` keeps its flat form (contracts run pre-splits). The naming-rename pass for existing kinds (G16a) is separate; ships in Bundle 4.

**New kinds:**

- `split_record_counts` — `{counts: {<split>: <int>, …}}`
- `per_class_count_per_split` — `{field: <label_field>, per_class: <int>}` (warning-severity tolerant of stratification rounding)
- `count_by_field` — `{field: <name>, value_per_key: <int>}`
- `count_by_fields` — `{fields: [<name1>, <name2>], value_per_combination: <int>}`
- `shape_equals` — `{field: <name>, value: [<dim>, …]}` (asserts ndarray shape)
- `value_in_set` — `{field: <name>, value: [<v>, <v>, …]}`
- `per_class_count_equals` — `{field: <label_field>, value: <int>}` (single-split form)

**Tasks:**

- [ ] Widen `evaluate_output_expectations` signature to `Mapping[str, list[Record]]`; route single-split callers as a one-key mapping for backward compatibility.
- [ ] Implement each new kind in [`pipeline/contracts.py`](../../src/datarefinery/pipeline/contracts.py); register in the dispatch table.
- [ ] Unit tests per kind: positive case + at least one negative case with precise diff message ("split 'val' expected 300, got 350", etc.).
- [ ] Integration test: a recipe declaring all seven kinds materializes; expectations pass on canonical fixture; mutating ratios / shapes / class counts produces precise failure messages.
- [ ] DOC: extend the assertion-kinds table in [`recipe-authoring.md` § InputContracts](../guides/recipe-authoring.md) and § OutputExpectations with a row per new kind. Add a "Cross-split assertions" subsection explaining per-split semantics.
- [ ] Update [`tech-spec.md`](tech-spec.md) assertion-kinds enumeration.
- [ ] Update [`dependency-gaps-v0.16.0.md` § G6 + § G16b](dependency-gaps-v0.16.0.md): status blocks; priority summary → "Closed in v0.18.0"; workarounds rows.

---

### Story I.p: G17 — `class_distribution_histogram` accepts `group_by` [Planned]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`dependency-gaps-v0.16.0.md` § G17](dependency-gaps-v0.16.0.md): a `group_by: str` optional param on the `class_distribution_histogram` viz selects the field to bucket on; default is `Labels.field` (current behavior). A validator check ensures `group_by` names a known field per `Output.record_schema` or a Generation-introduced tag field.

**Tasks:**

- [ ] OperationSpec update in [`plugin.py`](../../src/datarefinery/plugins/image_classification/plugin.py): add `group_by: str, required=False`.
- [ ] Runtime: histogram on the named field when present; fall back to `Labels.field` when absent.
- [ ] New validator check: `group_by` value resolves to a known field. Reject unknown-field references at validate time.
- [ ] Unit tests: no-param case bucketed by Labels.field (current behavior, regression); `group_by: <new_field>` bucketed correctly; `group_by: nonexistent_field` rejected at validate time.
- [ ] DOC: update [`recipe-authoring.md` § Visualizations](../guides/recipe-authoring.md) with the new param; backfill FR-VIZ-1..4 (DOC drift — `mean_image_per_class`, `pixel_distribution`, `augmented_sample_grid`, `corruption_severity_grid`, `severity_ladder`, all currently undocumented).
- [ ] Update [`dependency-gaps-v0.16.0.md` § G17](dependency-gaps-v0.16.0.md): status block; priority summary → "Closed in v0.18.0"; workarounds row.

---

### Story I.q: G18 — Generation `replace_input_records` [Planned]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`dependency-gaps-v0.16.0.md` § G18](dependency-gaps-v0.16.0.md): a new `GenerationOp.replace_input_records: bool = False` field declares whether the op's output augments (current behavior, default) or replaces the input records. Default preserves backward compatibility; opt-in covers transformation-style Generation (e.g., on-the-fly corruption application) that produces N output records per input and doesn't want the originals tagged along.

**Tasks:**

- [ ] Add `replace_input_records: bool = False` to `GenerationOp` in [`recipe/models.py`](../../src/datarefinery/recipe/models.py).
- [ ] Update [`pipeline/stages/generation.py`](../../src/datarefinery/pipeline/stages/generation.py): branch on `op.replace_input_records` — `True` assigns `out[split_name] = list(new_records)`, `False` keeps current `.extend(...)`.
- [ ] Unit tests: with `imagecorruptions_apply` op and `replace_input_records: true`, output count is `(n_corruptions × n_severities × n_base_records)`; with the field omitted (default `False`), output reproduces current 0.16.x behavior byte-identically (regression pin).
- [ ] DOC: add "When to use `replace_input_records`" subsection to [`recipe-authoring.md` § Generation](../guides/recipe-authoring.md) with the corruption-apply use case.
- [ ] Update [`dependency-gaps-v0.16.0.md` § G18](dependency-gaps-v0.16.0.md): status block; priority summary → "Closed in v0.18.0"; workarounds row.

**Out of Scope:**

- Generation schema reshape (top-level `op:`, `splits:` rename, `output_schema: matches_input` shorthand). That's G12, Story I.x.2 (Bundle 4).

---

### Story I.r: G14 — SampleData `kind` + `splits` [Planned]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`dependency-gaps-v0.16.0.md` § G14](dependency-gaps-v0.16.0.md): `SampleSelector` gains `kind: Literal["uniform", "per_class"] = "uniform"` and `splits: list[str] | None = None`. `kind: per_class` requires `Labels.field` populated (validator check); selects `n` records per class from the declared splits. `kind: uniform` (default) preserves current behavior.

**Tasks:**

- [ ] Widen `SampleSelector` in [`recipe/models.py`](../../src/datarefinery/recipe/models.py).
- [ ] Runtime: per-class branch in the sample-data selector.
- [ ] New validator check: `kind: per_class` requires `Labels.field` and an available label source.
- [ ] Unit tests: `kind: per_class, n: 1, splits: [train]` on a labeled fixture yields exactly N records, one per class, all from train; `kind: uniform` (default) regression; per_class on unlabeled source rejected at validate time.
- [ ] DOC: rewrite [`recipe-authoring.md` § SampleData](../guides/recipe-authoring.md) with both kinds + the splits-selector example.
- [ ] Update [`dependency-gaps-v0.16.0.md` § G14](dependency-gaps-v0.16.0.md): status block; priority summary → "Closed in v0.18.0"; workarounds row.

---

### Story I.s: G10 — `Splits.class_balance` dict shape (MF-binding hint) [Planned]

**Disposition: feature addition + cross-repo contract.** Part of Bundle 3 (v0.18.0 release).

Per [`dependency-gaps-v0.16.0.md` § G10](dependency-gaps-v0.16.0.md) and the plan_phase decision recorded in [`phase-i-recipe-focused-bug-fixes-plan.md`](phase-i-recipe-focused-bug-fixes-plan.md) (MF-side resampling): widen `SplitsSection.class_balance: str | None` to `str | dict[str, Any] | None`. The dict shape is `{strategy: <str>, applies_to: [<split>, …]}`. DataRefinery's runtime treats the field as a forward-declared training-time hint — **no resampling, no weight emission at the DR layer**. The strategy passes through verbatim to `SplitResult.class_balance` and `manifest.class_balance`; consumer tools (ModelFoundry) bind against the dict shape via `dependency-spec.md`.

**Tasks:**

- [ ] Widen `SplitsSection.class_balance` in [`recipe/models.py`](../../src/datarefinery/recipe/models.py); add validator check that dict shape has required `strategy` + `applies_to` keys.
- [ ] No runtime change in [`pipeline/stages/splits.py`](../../src/datarefinery/pipeline/stages/splits.py) — the field rides through `SplitResult.class_balance` as today.
- [ ] Update `manifest.class_balance` emission to serialize the dict shape.
- [ ] Unit tests: dict-shape validates with valid strategy names; bare-string shape still works (regression); manifest round-trips the dict shape.
- [ ] DOC: rewrite [`recipe-authoring.md` § Filters vs Splits for class imbalance](../guides/recipe-authoring.md) to spell out the runtime-vs-training-time separation explicitly: DR does not resample; the strategy is a hint for the training tool. Reference dependency-spec.md as the binding contract.
- [ ] **Cross-repo coordination required.** Update [`dependency-spec.md`](modelfoundry/dependency-spec.md) with the dict-shape contract: keys, allowed strategy values, applies_to semantics, MF's responsibility to honor the hint at training time. Document the strategy vocabulary v1 supports (e.g., `oversample_minority_to_majority`, `emit_inverse_frequency_weights`).
- [ ] Update [`dependency-gaps-v0.16.0.md` § G10](dependency-gaps-v0.16.0.md): status block recording the MF-side decision; priority summary → "Closed in v0.18.0"; workarounds row.

**Out of Scope:**

- DR-side resampling (Option 1 from the gap doc). Deferred to `stories.md § Future`.

---

### Story I.t: G1 — tag-driven `Splits.applies_to` [Planned]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`dependency-gaps-v0.16.0.md` § G1](dependency-gaps-v0.16.0.md): validator check 20 (`partitions_consistent`) broadens to accept `applies_to` values that match a filter-emitted tag (the `label` parameter on `sample_per_class` / `sample_per_class_fractional`). The pipeline runner learns to partition only tagged records and pass through other-tagged records verbatim under their existing tag-driven partitions.

**Tasks:**

- [ ] Broaden check 20 in [`recipe/validator.py`](../../src/datarefinery/recipe/validator.py) to also accept `applies_to` matching `FilterOp.predicate.params.label` (where predicate op is in `{sample_per_class, sample_per_class_fractional}`).
- [ ] Update [`pipeline/stages/splits.py`](../../src/datarefinery/pipeline/stages/splits.py) to learn the tag → partition pass-through: when `applies_to` names a tag, produce sub-splits per `ratios` for tagged records; emit untagged-or-other-tagged records as `<other_tag>` splits verbatim.
- [ ] Unit + integration tests: two `sample_per_class` filters tagging `train_pool` and `test_pool` + `Splits.applies_to: train_pool` validates and materializes; counts match tag populations within stratification rounding; swapping filter order produces the same test-split membership (proving tag-driven determinism).
- [ ] DOC: new "Sub-partitioning via tag" subsection in [`recipe-authoring.md` § Splits](../guides/recipe-authoring.md) paralleling the existing `InputSource.partition` subsection.
- [ ] Update [`dependency-gaps-v0.16.0.md` § G1](dependency-gaps-v0.16.0.md): status block; priority summary → "Closed in v0.18.0"; workarounds row.

---

### Story I.u: G13 — `tag_fields` dict-rename form [Planned]

**Disposition: feature addition.** Part of Bundle 3 (v0.18.0 release).

Per [`dependency-gaps-v0.16.0.md` § G13](dependency-gaps-v0.16.0.md): `ImageCorruptionsApplyParams.tag_fields: list[str] | dict[str, str]`. The list form (canonical names, current behavior) remains valid. The dict form maps the authored output field name → the canonical tag name the runtime understands (`corruption`, `severity`, `source_path`). Runtime asserts each dict value is in the canonical set at validate time.

**Tasks:**

- [ ] Widen `ImageCorruptionsApplyParams.tag_fields` in [`recipe/models.py`](../../src/datarefinery/recipe/models.py) to `list[str] | dict[str, str]`.
- [ ] Update [`generation_imagecorruptions.py`](../../src/datarefinery/plugins/image_classification/operations/generation_imagecorruptions.py) to walk the dict form: each value must be in `{corruption, severity, source_path}`; write each tag under the authored key.
- [ ] Validator check: dict values are in the canonical set; reject unknown values with a clear message.
- [ ] Unit tests: list form (subset selection, current behavior); dict form (output-field rename); dict form with unknown canonical tag rejected.
- [ ] DOC: document both shapes in [`recipe-authoring.md` § Generation](../guides/recipe-authoring.md).
- [ ] Update [`dependency-gaps-v0.16.0.md` § G13](dependency-gaps-v0.16.0.md): status block; priority summary → "Closed in v0.18.0"; workarounds row.

---

### Story I.v: G7 — Stage-aware visualization dispatch (closes G5) [Planned]

**Disposition: feature addition (architectural).** Part of Bundle 3 (v0.18.0 release). Renumbered from the original Story I.h (G7 placeholder) per the I.h sanitize step. Closes G5 as a side effect.

Per [`dependency-gaps-v0.16.0.md` § G7](dependency-gaps-v0.16.0.md): all reporting-mode visualizations today run at `post_pipeline` only. `VisualizationOp.stage` is read by the model but not honored by the runtime. This story implements stage-aware dispatch via stage snapshots: each pipeline stage that materially changes records snapshots a reference to its outputs; `apply_reporting_visualizations` receives a `Mapping[str, Mapping[str, list[Record]]]` keyed by stage then split; each `VisualizationOp.stage` selects which snapshot it renders against. `STAGE_NAMES` in [`pipeline/runner.py:96`](../../src/datarefinery/pipeline/runner.py) already enumerates valid stages.

Closing G5: `augmented_sample_grid` runs at `stage: pre_transformations` and reads uint8 records by construction.

**Tasks:**

- [ ] Constrain `VisualizationOp.stage` from `str` to `Literal[<STAGE_NAMES>]`. Unknown-stage typos fail at validate time.
- [ ] Add a validator check that the named stage produced output records (i.e., not bypassed by an empty pipeline branch).
- [ ] Extend [`pipeline/runner.py`](../../src/datarefinery/pipeline/runner.py) to snapshot per-stage split outputs (references, not copies). Snapshot points: post-Input, post-Filters/pre_split, post-Splits, post-Filters/post_split, post-Transformations, post-Augmentations, post-Featurizations, post-pipeline.
- [ ] Change `apply_reporting_visualizations` in [`pipeline/stages/visualizations.py`](../../src/datarefinery/pipeline/stages/visualizations.py) to accept the snapshot mapping; dispatch each `VisualizationOp` against its declared stage's snapshot.
- [ ] Update [`scaffolder/init.py`](../../src/datarefinery/scaffolder/init.py) to write `stage: post_pipeline` as the default when no stage is declared (preserves current behavior for unmigrated recipes).
- [ ] Integration test: a recipe with two `sample_grid` ops at `stage: post_filter` and `stage: post_transformations` materializes; both PNGs land in `report/visualizations/`; pre-transformations PNG is uint8 / recognizable, post-transformations PNG shows the normalized representation.
- [ ] G5 close-out test: a recipe with `normalize` Transformation + `augmented_sample_grid` at `stage: pre_transformations` materializes successfully and produces a visually sensible PNG.
- [ ] Remove the dead `_tile` clip-cast at [`augmented_sample_grid.py:144-145`](../../src/datarefinery/plugins/image_classification/visualizations/augmented_sample_grid.py) (the viz now reads uint8 by construction), or document why it remains as defense-in-depth.
- [ ] DOC: update [`recipe-authoring.md` § Visualizations](../guides/recipe-authoring.md) with the `stage:` vocabulary, the stage-to-records mapping, and worked examples.
- [ ] Update [`dependency-gaps-v0.16.0.md` § G5 + § G7](dependency-gaps-v0.16.0.md): status blocks; priority summary → "Closed in v0.18.0"; workarounds rows.
- [ ] Cross-repo coordination: minor — note in `dependency-spec.md` that per-stage report subsections remain a single section in v1; the snapshot indirection is internal.

**Out of Scope:**

- Per-stage report subsections (one `report.md` heading per snapshotted stage). Deferred to `stories.md § Future`.
- Backfilling FR-VIZ-1..4 visualizations to declare richer stages (each already runs at `post_pipeline`; updating is a follow-up).
- Resume-from-stage during materialization. Snapshots are in-memory references for viz dispatch only.

---

### Story I.w: Release v0.18.0 (Phase I bundle 3) [Planned]

**Disposition: release ceremony.** Minor bump (`v0.17.1 → v0.18.0`). Closes Bundle 3.

Twelve additive feature stories (I.k–I.v) ship as one minor bump because each is opt-in or backward-compatible (no canonical-bytes perturbation for existing recipes) and the capabilities are interrelated. Dedicated commit for the version bump.

**Tasks:**

- [ ] Bump `pyproject.toml` `version = "0.17.1"` → `"0.18.0"`.
- [ ] Bump `src/datarefinery/__init__.py` `__version__` accordingly.
- [ ] [`CHANGELOG.md`](../../CHANGELOG.md) `## [0.18.0]` with subsections for each closed G:
   - **Added:** G2 (`cast` Transformation), G3 (`categorical_encode`), G9 (`flatten`), G11 (`seed_derive_from: master`), G6+G16b (seven new assertion kinds), G17 (`group_by` histogram), G18 (`replace_input_records`), G14 (SampleData `kind`/`splits`), G10 (class_balance dict hint), G1 (tag-driven applies_to), G13 (tag_fields dict-rename), G7 (stage-aware viz, closes G5).
   - **Removed:** `cast_dtype` and `to_grayscale` OperationSpec entries (formerly declared-but-unimplemented).
   - **Docs:** DOC-rule backfill across Transformations, Featurizations, Filters, Generation, Visualizations, InputContracts, OutputExpectations, Splits, SampleData sections of `recipe-authoring.md`.
- [ ] Cross-repo coordination: confirm `dependency-spec.md` was updated by I.s (class_balance dict contract) and I.v (per-stage subsections clarification).
- [ ] No schema bump — all changes are additive / opt-in.

---

### Story I.x.1: G15 — Filters reshape + loader migration framework [Planned]

**Disposition: schema reshape (canonical-bytes-perturbing).** Part of Bundle 4 (v0.19.0 release, schema_version 1 → 2). Sub-numbered story 1 of 3 in the schema-v2 cluster.

Per [`dependency-gaps-v0.16.0.md` § G15](dependency-gaps-v0.16.0.md): `FilterOp` reshapes from `{name, predicate: {op, …rest}, stages, splits, seed}` to `{name, op, params, stages, splits, seed}` — matching every other section's top-level `op:` + `params:` shape. This story also stands up the v1→v2 migration framework in [`recipe/loader.py`](../../src/datarefinery/recipe/loader.py) that I.x.2 and I.x.3 will extend.

**Tasks:**

- [ ] Reshape `FilterOp` in [`recipe/models.py`](../../src/datarefinery/recipe/models.py): replace `predicate: dict[str, Any]` with `op: str` + `params: dict[str, Any] = {}`.
- [ ] Update `SUPPORTED_SCHEMA_VERSIONS` in [`recipe/loader.py`](../../src/datarefinery/recipe/loader.py): `{1}` → `{1, 2}`. Set default emit version to 2 for new authoring.
- [ ] Add the v1→v2 migration registry: `migrations[(1, 2)] = compose(filters_reshape_v1_to_v2, …)`. I.x.2 and I.x.3 register more entries against `(1, 2)` later.
- [ ] Implement `filters_reshape_v1_to_v2(recipe_dict) -> recipe_dict`: walks every `Filters[i].predicate`, lifts `op` to top level and renames the rest of the dict to `params`.
- [ ] Update validator checks 21 and the predicate-shape inspections at [validator.py:928](../../src/datarefinery/recipe/validator.py) and similar sites: port `predicate.get("op") == "filter_by_label"` → `op == "filter_by_label"`.
- [ ] DOC: rewrite [`recipe-authoring.md` § Filters](../guides/recipe-authoring.md) with the new flat shape. Backfill `sample_per_class`, `sample_per_class_fractional`, `drop_by_label` (DOC drift — shipped in v0.10.0–v0.12.0, currently undocumented).
- [ ] Update [`tech-spec.md`](tech-spec.md) schema-version section to enumerate `{1, 2}` and the migration.
- [ ] **Cross-repo coordination required.** Update [`dependency-spec.md`](modelfoundry/dependency-spec.md) with the recipe-model v2 reshape: name both old and new field names; deprecation horizon for v1 callers.
- [ ] Migration round-trip test: a v1-shape Filters block migrates to v2 and produces canonical bytes byte-identical to a directly-authored v2 recipe.
- [ ] Update [`dependency-gaps-v0.16.0.md` § G15](dependency-gaps-v0.16.0.md): status block; priority summary → "Closed in v0.19.0"; workarounds row.

---

### Story I.x.2: G12 — Generation schema reshape [Planned]

**Disposition: schema reshape (canonical-bytes-perturbing).** Part of Bundle 4 (v0.19.0 release). Sub-numbered story 2 of 3.

Per [`dependency-gaps-v0.16.0.md` § G12](dependency-gaps-v0.16.0.md): `GenerationOp` reshapes — `op:` lifts to top level, `applies_at: list[str]` renames to `splits: list[str]`, `output_schema` accepts `dict[str, FieldSpec] | Literal["matches_input"]` (shorthand expands to input record schema + declared tag fields), `seed` accepts `int | SeedDerivationSpec` (from FR-I-5, Story I.n).

**Tasks:**

- [ ] Reshape `GenerationOp` in [`recipe/models.py`](../../src/datarefinery/recipe/models.py).
- [ ] Implement `generation_reshape_v1_to_v2` migration: `params.op` → top-level `op:`; `applies_at` → `splits`; preserve other fields; emit a default `output_schema` carryover (cannot inflate to `"matches_input"` without runtime context — leave concrete dicts as-is).
- [ ] Register the migration in `migrations[(1, 2)]` alongside Filters reshape from I.x.1.
- [ ] Implement runtime expansion of `output_schema: "matches_input"` in [`pipeline/stages/generation.py`](../../src/datarefinery/pipeline/stages/generation.py): copy input record shape + add declared `tag_fields` from the op's params.
- [ ] Unit tests: v1-shape Generation block migrates to v2 cleanly; `output_schema: matches_input` expands to the correct dict at materialize time; explicit `output_schema: {…}` still works.
- [ ] Migration round-trip test extends the v1→v2 fixture from I.x.1 to include Generation blocks.
- [ ] DOC: rewrite [`recipe-authoring.md` § Generation](../guides/recipe-authoring.md) with the new shape; worked `imagecorruptions_apply` example with `output_schema: matches_input`.
- [ ] Cross-repo coordination: update `dependency-spec.md` Generation section for the v2 shape.
- [ ] Update [`dependency-gaps-v0.16.0.md` § G12](dependency-gaps-v0.16.0.md): status block; priority summary → "Closed in v0.19.0"; workarounds row.

---

### Story I.x.3: G16a — assertion `kind` naming pass [Planned]

**Disposition: schema reshape (canonical-bytes-perturbing).** Part of Bundle 4 (v0.19.0 release). Sub-numbered story 3 of 3.

Per [`dependency-gaps-v0.16.0.md` § G16a](dependency-gaps-v0.16.0.md): the contracts-evaluator naming convention shifts from bare verbs + struct-shape (`dtype: {expected: X}`, `range: {min, max}`) to predicate-sentence form (`dtype_equals: {value: X}`, `value_range: {min, max}`, `value_in_set: {value: […]}`, etc.). The five existing v1 kinds (`dtype`, `range`, `record_count`, `required_field`, `distributional`) each get a v2 canonical name; v1 names are removed (not aliased) and the migration entry rewrites them.

**Mapping (v1 → v2):**

- `dtype` → `dtype_equals`
- `range` → `value_range`
- `record_count` → `record_count_in_range`
- `required_field` → unchanged (the verb form already reads as a sentence)
- `distributional` → unchanged (placeholder; will gain real form post-Phase-I)

**Tasks:**

- [ ] Rename each evaluator in [`pipeline/contracts.py`](../../src/datarefinery/pipeline/contracts.py); update the dispatch table to the v2 names.
- [ ] Implement `assertion_naming_v1_to_v2` migration: walks every `InputContracts[i].assertion` and `OutputExpectations[i].assertion`, rewrites `kind` per the mapping.
- [ ] Register the migration in `migrations[(1, 2)]` alongside the prior two reshapes.
- [ ] Migration round-trip test extends the v1→v2 fixture to include assertions.
- [ ] Update the existing five-kind tests for the new names (matches v2 schema).
- [ ] DOC: update the assertion-kinds tables in [`recipe-authoring.md` § InputContracts and § OutputExpectations](../guides/recipe-authoring.md) with v2 names; remove v1 names.
- [ ] Update [`tech-spec.md`](tech-spec.md) assertion-kind enumeration.
- [ ] Cross-repo coordination: update `dependency-spec.md` with v2 assertion-kind names.
- [ ] Update [`dependency-gaps-v0.16.0.md` § G16a](dependency-gaps-v0.16.0.md): status block; priority summary → "Closed in v0.19.0"; workarounds row.

---

### Story I.y: Release v0.19.0 (Phase I bundle 4, schema_version 1→2) [Planned]

**Disposition: release ceremony + schema-bump ceremony.** Minor bump (`v0.18.0 → v0.19.0`). Closes Bundle 4 and Phase I.

The schema-v2 migration is cache-invalidating per [`project-essentials.md` § "Cache identity is the reproducibility contract"](project-essentials.md). Pre-production rules apply: documented in release notes, announced as a one-time re-materialization cost, no post-production ceremony required (no `schema_version` re-pinning beyond the v1→v2 bump itself). This story performs the bump and the announcement.

**Tasks:**

- [ ] Bump `pyproject.toml` `version = "0.18.0"` → `"0.19.0"`.
- [ ] Bump `src/datarefinery/__init__.py` `__version__` accordingly.
- [ ] Update the canonical-hash pinning test fixtures: confirm v2-shape canonical bytes for representative recipes; record the new pinned hashes. A reviewer must consciously sign off on the pinned hash change.
- [ ] [`CHANGELOG.md`](../../CHANGELOG.md) `## [0.19.0]`:
   - **Schema:** "Recipe `schema_version` bumped from 1 to 2. The v1→v2 migration is automatic via the recipe loader; recipes do not need manual rewriting. **Cache invalidation:** all existing materialized instances become stale and must be re-materialized. This is a one-time event per installation."
   - **Changed:** G15 (Filters flat shape), G12 (Generation reshape), G16a (assertion naming pass).
   - **Notes:** "Pre-production cache invalidation per `project-essentials.md`. See migration entries in `recipe.loader.migrations` for the precise reshape rules."
- [ ] Ensure the v1→v2 migration is exercised by an integration test that loads a representative v1 recipe, applies the migration, and produces a canonical instance.
- [ ] Cross-repo coordination: confirm `dependency-spec.md` is consistent across all three v2 reshapes (Filters, Generation, assertions).
- [ ] Update `recipe-authoring.md`'s overall introduction (or the schema-version subsection) to enumerate `schema_version: 2` as the canonical recipe version.

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
  - FR-ARCH-1 tight coupling — sibling `recipe_hash` participating in the current recipe's cache identity, so re-materializing upstream auto-invalidates downstream. The Phase H sub-bundle shipped FR-TRANS-1 with loose coupling; tight coupling is the follow-up needed for multi-team or longitudinal workflows.
  - Generic record-tagging primitive — factor FR-FILTER-1's bespoke `label` / `exclude_already_labeled` params into a shared mechanism multiple filter ops can use.
- **Default-change discipline tooling for cache-identity stability** — expand the canonical-hash pinning test suite to cover multiple fixture recipes with different default-coverage profiles, so any change to a pydantic field default (anywhere in the recipe model graph) trips at least one pin and forces the developer to either revert or bump `schema_version`. Add an optional pre-commit / CI hook that diffs pydantic field defaults against `main` and requires a `schema_version` bump or an explicit "non-semantic default change" acknowledgement in the commit message. End-state invariant: cache invalidations are always deliberate (acknowledged at change time, announced in release notes); never silent. Plan as production-readiness work.
- **`stats_from_instance.variant: <name>` selector** — let a consumer recipe pin a specific sibling-variant's fitted statistics (e.g., normalize stats fit under a specific experimental overlay). The Phase I G19 fix closes the no-variant case; the variant-selector form is a follow-up. Added during Phase I planning (Story I.h).
- **Real `to_grayscale` Transformation op** — Phase I removed the declared-but-unimplemented `to_grayscale` OperationSpec entry to keep the surface honest. A real implementation with a `method: average | luminance | …` parameter set is deferred until a recipe surfaces a concrete need. Added during Phase I planning (Story I.h).
- **Plugin-pluggable validator-check reserved-set hook** — let plugins declare `Plugin.loader_stamped_fields(recipe) -> set[str]` so validator check 23 (Featurization `output_field` collision) can be applied to non-stub plugins when their loaders ship. Today the reserved-set is hardcoded for `image_classification`; tabular and text stubs don't stamp fields and don't need the hook yet. Originally noted in Story I.c's prevention notes; added during Phase I planning (Story I.h).
- **Per-stage report subsections** — extend the snapshot-based stage-aware viz dispatch (Story I.v / G7) so the rendered `report.md` carries one heading per snapshotted stage. The v1 deliverable is one report section with per-viz `stage:` annotations; richer structure is a UX polish follow-up. Added during Phase I planning (Story I.h).
- **Scaffolder v2 grand sweep** — refresh the bundled `init` scaffolder ([`scaffolder/init.py`](../../src/datarefinery/scaffolder/init.py)) to actively showcase v2 affordances in the scaffolded recipe (`seed_derive_from: master` on every seeded op, tag-driven `applies_to` example, `replace_input_records: true` demo, `value_in_set` instead of bare enum lists, etc.). Phase I's Bundle 4 ships the *minimal* scaffolder update (emit valid v2-shape recipes); the grand-sweep redesign of the scaffolded recipe as a teaching artifact is a follow-up. Added during Phase I planning (Story I.h).
- **Real `distributional` assertion kind** — replace the v1 placeholder with a real evaluator (KS test, JS divergence, or similar). The current placeholder always passes; downstream drift tools (DataMachine) implement their own checks. Added during Phase I planning (Story I.h).
- **DR-side `class_balance` resampling** — physically resample (oversample minority records into the cached train split, or emit per-record `class_weight`) at the Splits stage rather than passing the strategy through as an MF-binding hint. Phase I chose MF-side resampling (Story I.s / G10); revisit if downstream evidence accumulates that the materialized instance needs to be framework-agnostic and self-contained. Added during Phase I planning (Story I.h).
- **Broad consumer-context rewrite of internal specs** — sanitize the deeper consumer-perspective surface in [`phase-i-dependency-gaps-v0.16.0.md`](phase-i-dependency-gaps-v0.16.0.md) and [`phase-i-intermediate-artifact-persistence-spec.md`](phase-i-intermediate-artifact-persistence-spec.md): replace "Recipe A" / "Recipe B" with generic role names, drop or rephrase Module N / Phase B / Phase D / Task 2 references, replace consumer recipe filenames (`cifar10-base.yaml`, `cifar10c-eval.yaml`) and consumer-side phase-plan links with generic placeholders, generalize consumer-specific record counts and tag names. Story I.h scrubbed only the hard-blacklisted course identifiers (see developer auto-memory) for in-course blast-radius reduction; this Future story is the deliberate rewrite once the course is complete. Git history will continue to carry the original consumer surface regardless. Added during Story I.h execution.
