Break the project into an ordered sequence of small, independently completable stories grouped into phases. Each story has a checklist of concrete tasks. Stories reference modules defined in `tech-spec.md`.

The high-level concept (why) should be captured in `concept.md`. The requirements and behavior (what) should be captured in `features.md`. The implementation details (how) should be written in `tech-spec.md`.

## Prerequisites — inputs the LLM reads in Step 2

`plan_stories` reads (it does **not** interrogate the developer to confirm these exist or are "approved" — the developer's choice to invoke this mode and the presence of the files imply approval; the natural pause-on-summary at Step 4 is the rejection path):

- `docs/specs/concept.md` — why
- `docs/specs/features.md` — what
- `docs/specs/tech-spec.md` — how, **including CI/CD scope** under its `## CI/CD Automation` section (or equivalent CI/automation language under packaging/distribution)

**CI/CD scope is read from `tech-spec.md`, not asked of the developer.** Derive whether to include a CI/CD phase from the spec; ask the developer only if the spec is silent or genuinely ambiguous on the point. Do **not** present a standalone CI/CD-automation prompt to the developer when the spec already covers it.

## Steps

1. **Verify this is the right mode.** `plan_stories` is for *initial* story planning of a project that does not yet have a story plan. Before reading specs, run three deterministic checks:

   - Does `docs/specs/stories.md` already contain `### Story` headings (i.e., story content beyond the rendered template scaffold)?
   - Does the working tree contain substantive source beyond Phase A scaffolding (heuristic: more than a handful of files in the package directory, or a populated `tests/` directory)?
   - Is `git log --oneline | wc -l` deeper than ~10 commits?

   If any check trips, **halt** and present the developer with a one-paragraph diagnosis: this project already has prior planning or implementation work, so `plan_stories` is likely the wrong mode. Suggest `plan_phase` (to add a new phase to an existing project), optionally preceded by `refactor_plan` if `features.md` / `tech-spec.md` need to change first. Do not proceed without explicit developer override.

2. Read `docs/specs/concept.md`, `docs/specs/features.md`, and `docs/specs/tech-spec.md`. Extract CI/CD scope from `tech-spec.md`'s CI/CD section so it informs the Phase G decision below — do not re-ask the developer when the spec answers the question.

3. Generate `docs/specs/stories.md` using the artifact template at `docs/project-guide/templates/artifacts/stories.md` (installed by `project-guide init`; refreshed by `project-guide update`). Include a CI/CD phase (Phase G) if and only if `tech-spec.md` indicates the project needs CI/CD automation.

   **Version assignment** — the artifact template's **Version Cadence** section (rendered into the generated `stories.md`) is the authoritative rule for every story's version. Most stories in initial planning are features → **minor** bumps. Bug-fix stories are **patch**. Major bumps are forward-deferred to `plan_production_phase` (post-1.0 only). Story A.a starts at **v0.1.0**. Do not extrapolate from prior projects' version schemes.

4. Present the complete document to the developer for approval. Iterate as needed.

{% include "modes/_phase-letters.md" %}

## Story Writing Rules

- **Story ID**: see the Phase and Story ID Scheme above.
- **Version**: per the **Version Cadence** section in the generated `stories.md` — bugfix=patch, feature=minor, breaking=major (post-1.0 only, via `plan_production_phase`). Stories with no code changes (doc-only / polish) omit the version. Phase-bundled releases also omit per-story versions; the bundle ships with one tag at end-of-phase.
- **Status suffix**: `[Planned]` initially, changed to `[Done]` when completed.
- **Checklist**: use `- [ ]` for planned tasks, `- [x]` for completed tasks. Subtasks indented with two spaces.
- **First story (A.a)**: Always Project Scaffolding — LICENSE, copyright header, package manifest, README, CHANGELOG, .gitignore. This story is executed in `scaffold_project` mode, not `{% if test_first %}code_test_first{% else %}code_direct{% endif %}`. It is marked `[Done]` by `scaffold_project` mode upon completion.
- **Second story (A.b)**: Always a minimal "Hello World" -- the smallest runnable artifact proving the environment is wired up.
- **Third story (A.c)**: An end-to-end stack spike -- a throwaway script (in `scripts/`, not the package) that wires the full critical path together before production modules.
- **Additional spikes**: Add as the first story of any phase introducing a major new integration boundary.
- **Each story**: Completable in a single session and independently verifiable.
- **Verification tasks**: Include where appropriate (e.g., "Verify: command prints version").
- **Version bump and changelog tasks**: Every versioned story must include these two tasks as the last items before any Verify tasks: `- [ ] Bump version to vX.Y.Z` (substituting the actual version) and `- [ ] Update CHANGELOG.md`.

## Recommended Phase Progression

| Phase | Name | Purpose |
|-------|------|---------|
| A | Foundation | Scaffolding (A.a), hello world (A.b), spike (A.c), core models, config, logging |
| B | Core Services | The main functional modules (one story per service) |
| C | Pipeline & Orchestration | Wiring services together, caching, concurrency, error handling |
| D | CLI & Library API | User-facing interfaces |
| E | Testing & Quality | Test suites, coverage, edge case tests |
| F | Documentation & Release | README, changelog, final testing, polish |
| G | CI/CD & Automation | GitHub Actions, coverage badges, release automation (if requested) |

Phases may be added, removed, or renamed to fit the project.

## Story Format

```markdown
### Story <Phase>.<letter>: v<version> <Title> [Planned]

<Optional one-line description.>

- [ ] Task 1
  - [ ] Subtask 1a
  - [ ] Subtask 1b
- [ ] Task 2
- [ ] Task 3
- [ ] Bump version to vX.Y.Z
- [ ] Update CHANGELOG.md
- [ ] Verify: <how to confirm the story is complete>
```

{% include "modes/_header-sequence.md" %}
