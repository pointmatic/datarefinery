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

## Phase F: Documentation & Release

Pre-production v1 polish. README expanded with quickstart and recipe authoring; recipe + plugin authoring guides; final `v1.0.0` cut as the production-release marker (which flips post-production rules per `features.md`).

### Story F.a: v0.6.0 README Expanded with Quickstart [Done]

Promote the package to a non-trivial first-impression README. Minor bump reflects the leap from "scaffolding present" to "documented usable tool."

- [x] Expand `README.md` with: install (PyPI + dev paths), quickstart (`init` → `validate` → `materialize` on CIFAR-shaped data), recipe-anatomy section, CLI verb summary table, plugin model overview, link to features.md/tech-spec.md.
- [x] Add a recipe example for `image_classification` end-to-end.
- [x] Add a "v1 scope and non-goals" section sourced from concept.md.
- [x] Update CHANGELOG.md
- [x] Verify: README renders cleanly on GitHub; quickstart commands succeed against the fixture.

### Story F.b: Recipe Authoring Guide [Done]

Doc-only; shares F.a's release.

- [x] Add `docs/guides/recipe-authoring.md`: section-by-section walk-through, fit-on-train discipline, variants, contracts/expectations, when to use Filters vs Splits for class imbalance.
- [x] Cross-link from README and concept.md.
- [x] Verify: every code snippet in the guide is materializable against the fixture.

### Story F.c: Plugin Authoring Guide [Done]

Doc-only; shares F.a's release.

- [x] Add `docs/guides/plugin-authoring.md`: how to declare a plugin, `OperationSpec` schema, fit-on-train flag, applicable splits, registration via entry-point group.
- [x] Reference the tabular/text stubs as starting templates.
- [x] Verify: a hand-written hello-plugin following the guide is discovered and validates a minimal recipe.

### Story F.d: Fix ruff format drift [Done]

Pre-test-release cleanup so the `ruff` half of `features.md` Acceptance Criterion 10 (*"`ruff` and `mypy --strict` pass clean"*) passes for F.f. Style only — no behavioral changes. Shares F.f's `v0.6.1` release (no separate version bump).

State at story start (audited 2026-05-11):
- `pyve testenv run ruff check src tests` → all checks passed (lint is already clean).
- `pyve testenv run ruff format --check src tests` → 86 files would reformat (45 `src/`, 41 `tests/`).

- [x] Run `pyve testenv run ruff format src tests` and stage the resulting edits.
- [x] Spot-check at least three reformatted files (one under `src/`, one under `tests/unit/`, one under `tests/integration/`) to confirm the diffs are whitespace-only — no logic, identifier, or import changes.
- [x] Run the full check suite and confirm:
  - `pyve testenv run ruff check src tests` → all checks passed.
  - `pyve testenv run ruff format --check src tests` → 0 files would reformat.
  - `pyve test` → all tests still pass (no regression from the reformat).
- [x] Verify: the `ruff` half of F.f Acceptance Criterion 10 is now demonstrably met.

### Story F.e: Fix `mypy --strict` errors [Done]

Pre-test-release cleanup so the `mypy --strict` half of `features.md` Acceptance Criterion 10 (*"`ruff` and `mypy --strict` pass clean"*) passes for F.f. Test-side type-annotation work only — no behavioral changes. Shares F.f's `v0.6.1` release (no separate version bump).

State at story start (audited 2026-05-11):
- `pyve testenv run mypy src tests` → 104 errors in 16 files, all under `tests/` — `src/` is clean.

- [x] Fix the dominant mypy cluster (≈90 errors): the `dict[str, list[dict[str, Any]]]` vs `Mapping[str, list[Mapping[str, Any]]]` invariance at stage-helper call sites in `test_visualizations_stage.py`, `test_transformations_stage.py`, `test_runner.py`, `test_generation_stage.py`, `test_featurizations_stage.py`, `test_drift.py`, `test_filters_stage.py`, `test_splits_determinism.py`, `test_workers.py`, `test_scaffolder.py`, `test_failure_modes.py`. Prefer annotating the local fixture variables as `Mapping[...]` (or `dict[str, list[Mapping[str, Any]]]` where mutation is needed) over casting at every call site.
- [x] Fix the residual mypy errors:
  - Remove the 9 `[unused-ignore]` `# type: ignore` comments that mypy now flags as stale (concentrated in `test_visualizations_stage.py` and `test_fitted_stats.py`).
  - Add return annotations to `tests/fixtures/dummy_plugin.py:24` and `tests/fixtures/dummy_plugin_dup.py:20` (`[no-untyped-def]`).
  - Resolve the 2 `[attr-defined]` errors in `test_atomic.py` and `test_cleaner.py` where tests reach into the module's `shutil`/`os` import namespace via `monkeypatch.setattr` — either patch the underlying module path or add a focused `# type: ignore[attr-defined]` per call.
  - Resolve the remaining 1× `[var-annotated]`, 1× `[str]`, 1× `[object]`, and any `[dict-item]` strays not closed by the previous task.
- [x] Do **not** weaken `mypy --strict` configuration to mask errors. If a `# type: ignore[...]` is genuinely warranted (e.g. a test deliberately constructs a malformed value to exercise a guard), narrow the ignore to the specific code and add a one-line comment explaining why.
- [x] Run the full check suite and confirm:
  - `pyve testenv run mypy src tests` → 0 errors (the full test surface plus `src/`).
  - `pyve testenv run ruff check src tests` → all checks passed.
  - `pyve testenv run ruff format --check src tests` → 0 files would reformat (F.d's gain is not regressed).
  - `pyve test` → all tests still pass (no behavioral regressions from the type-annotation work).
- [x] Verify: the `mypy --strict` half of F.f Acceptance Criterion 10 is now demonstrably met.

### Story F.f: v0.6.1 Test Release [Done]

This is a test release event. Per `features.md` and `project-essentials.md`, and we will postpone production release until thorough testing and we have confirmation of feature fit. 

- [x] Final pass on `features.md` "Acceptance Criteria" — every numbered item demonstrably met.
- [x] Add release notes section in `CHANGELOG.md` titled "**Test Release — Validation of feature fit.**"
- [x] Bump version to v0.6.1
- [x] Update CHANGELOG.md
- [x] Verify: `python -m build` produces a clean wheel; `pip install ./dist/datarefinery-0.6.1-*.whl` in a fresh venv succeeds; `datarefinery check` reports environment soundness; `init → validate → materialize` golden path passes on the installed wheel.

**Out of Scope**
- Add `recipe.loader.migrations` registry header documentation: "post-production: every cache-invalidating change requires a migration entry here."
- Bump to `v1.0.0` and declare production release
- Publish workflow uploads to PyPI. (NOTE: PyPI publication is deferred)
- Verify: tagged release lands on PyPI; `pip install datarefinery==1.0.0` from a clean venv 

---

## Phase G: CI/CD & Automation

Continuous-integration workflow (lint + type + test on every PR), coverage badge, and post-production release-automation polish. The publish workflow already shipped in A.d so the PyPI name was reserved early; Phase G adds the rest.

### Story G.a: v1.0.1 GitHub Actions: Lint + Type + Test [Planned]

CI runs `ruff`, `mypy --strict`, and `pytest` on every PR and on `main`.

- [ ] Add `.github/workflows/ci.yml` running on pull_request and push to `main`.
- [ ] Matrix: Python 3.12 on ubuntu-latest and macos-latest.
- [ ] Steps: checkout, setup-python, install dev requirements, `pyve testenv run ruff check src tests`, `pyve testenv run ruff format --check src tests`, `pyve testenv run mypy src tests`, `pyve test --cov --cov-fail-under` (core-invariant gates from E.g).
- [ ] Required-status-check on `main` for all matrix legs.
- [ ] Bump version to v1.1.0
- [ ] Update CHANGELOG.md
- [ ] Verify: a deliberate lint violation in a PR fails CI on both OS legs.

### Story G.b: v1.0.2 Coverage Badge (Codecov) [Planned]

- [ ] Add Codecov upload step to `ci.yml` using `codecov/codecov-action`.
- [ ] Configure `.codecov.yml` with target ≥85% post-production (per features.md) and per-module ≥95% on core invariants.
- [ ] Add Codecov badge to `README.md`.
- [ ] Bump version to v1.1.1
- [ ] Update CHANGELOG.md
- [ ] Verify: a PR shows a Codecov status check and the README badge updates after merge to `main`.

### Story G.c: v1.0.3 Release Automation Polish [Planned]

- [ ] Add a GitHub Action that on tag push extracts the corresponding `CHANGELOG.md` section and creates a GitHub Release with that body.
- [ ] Add tag protection rule: only maintainers can push `v*` tags.
- [ ] Document the release procedure in `docs/guides/releasing.md` (bump → CHANGELOG → tag → workflow → verify).
- [ ] Bump version to v1.1.2
- [ ] Update CHANGELOG.md
- [ ] Verify: a new tag push produces a GitHub Release with the changelog body and a successful PyPI upload.

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
