Plan a **production-grade phase** for a project that has crossed (or is about to cross) the v1.0.0 threshold. Like `plan_phase`, this mode generates a combined concept/features/tech-spec document for a new phase and adds the phase plus its stories to `docs/specs/stories.md`. Unlike `plan_phase`, it adds production-readiness scrutiny: a hardening checklist walk, breaking-change negotiation, and an explicit version-bump target.

Use this mode when the package is at v1.0.0 or beyond. `plan_phase` is pre-1.0 only; once users depend on the package, every phase needs production-level review.

## Prerequisites

Before planning a production-grade phase, the following should exist or be true:
- `docs/specs/concept.md`, `docs/specs/features.md`, `docs/specs/tech-spec.md`, `docs/specs/stories.md` — same as `plan_phase`.
- The package version is at the verge of v1.0.0 (first invocation of this mode crosses the threshold) **or** already past it (subsequent invocations).
- CI is green on the main branch.
- The previous phase shipped to the registry (PyPI, npm, etc.) — i.e., this is not being invoked mid-phase.

If the package version is below v1.0.0 and this is **not** the first-time crossing, halt and recommend `plan_phase` instead.

## Steps

1. **Read the existing spec documents** to understand current project state. Same shape as `plan_phase` step 1 — `docs/specs/stories.md` may be **populated** or **empty (post-archive)**, and the next phase letter is determined by the existing letters in `stories.md` or in `docs/specs/.archive/stories-vX.Y.Z.md`. Phase letters continue across archive boundaries.

2. **Walk the Production-readiness checklist** with the developer **before gathering phase info**. This is the load-bearing difference from `plan_phase`. For each item below, ask "is this in place?" — if no, ask "what's blocking?". The mode does not proceed past unmet items without explicit developer override (e.g., "we're aware Dependabot isn't set up yet; we'll address it in this phase").

   **Production-readiness checklist:**
   - [ ] **Branch protection** on main (PRs required, status checks must pass before merge).
   - [ ] **Mandatory CI** — lint + tests run on every PR; merge blocked on red.
   - [ ] **`SECURITY.md`** — vulnerability reporting instructions.
   - [ ] **`CONTRIBUTING.md`** — development setup, code style, PR process, release process.
   - [ ] **`.github/dependabot.yml`** — automated dependency updates for pip / npm / github-actions / etc.
   - [ ] **Trusted publisher** configured for the package registry (PyPI / npm / crates.io / etc.) — no long-lived API tokens.
   - [ ] **PR-based workflow** — no direct commits to main since the v1.0.0 release (or, if this is the threshold crossing, this phase will switch to PR-based).
   - [ ] **Bundled-release cadence** understood — stories within a phase run unversioned; the phase ships as one tag at end-of-phase. Per the **Version Cadence** rule in `docs/specs/stories.md`.

   See [`developer/best-practices-guide.md`](../developer/best-practices-guide.md) — the **Velocity Mode vs. Production Mode** section is the rationale source for these items.

3. **Gather information from the developer about the new phase** — same as `plan_phase` step 2:
   - phase_name: A short name for the phase (e.g., "Sharding Support", "Audit Mode")
   - problem_gap: What capability is missing or what problem this phase solves
   - new_features: What the phase will add (functional requirements)
   - technical_approach: How it will be built (architecture changes, new modules, new dependencies)
   - constraints: Any limitations or compatibility requirements with existing code
   - scope: What this phase will and won't do

   **Plus, two production-specific prompts:**
   - **anticipated_breaking_changes:** Does this phase plan to introduce any *potentially* breaking changes? List each one (e.g., "deprecate the `--legacy-format` flag", "rename `BatchProcessor.run` to `BatchProcessor.execute`", "change default log format from text to JSON"). The breaking-change negotiation step (step 5 below) walks each item.
   - **production_concerns:** Are there security, performance, or reliability concerns that should drive the phase's design? (E.g., "this phase exposes a new HTTP endpoint — rate-limiting required"; "new background worker — graceful-shutdown handling required.")

4. **Generate a phase plan document** at `docs/specs/phase-<letter>-<name>-plan.md` that combines (parallel to `plan_phase` step 3):
   - **Gap analysis**: What exists vs. what's needed
   - **Feature requirements**: What the phase adds (mini features.md)
   - **Technical changes**: New/modified modules, dependencies, config changes (mini tech-spec.md)
   - **Production concerns**: Security, performance, reliability concerns identified in step 3
   - **Anticipated breaking changes**: Each item from `anticipated_breaking_changes`, with the negotiation result from step 5 below
   - **Anticipated version bump target**: `vX.Y.0` (minor) or `vX+1.0.0` (major), per the negotiation in step 5
   - **Out of scope**: What's deferred to future phases. **Walk through each Out-of-scope item with the developer** before committing — out-of-scope is a negotiation, not a unilateral declaration (same rule as `plan_phase`).

5. **Breaking-change negotiation.** For each item in `anticipated_breaking_changes`, walk the developer through the question:

   > "Does this change substantively break user expectations, or is it technically-but-trivially breaking?"

   Worked example to bake the discretion principle in: a **log-format change** is technically breaking (downstream log parsers may rely on the old format), but if the project's documented contract says "logs are operator-internal, not a core consumer capability", the developer may judge the change to be **non-breaking** for semver purposes (a minor or even patch bump suffices). The same is not true if the project ships a documented log schema as part of its public API.

   **The mode suggests** the version-bump target (minor vs. major) based on the negotiation result:
   - Any item judged substantively breaking → **major** bump (`vX+1.0.0`).
   - All items judged technically-but-trivially breaking, or no breaking changes → **minor** bump (`vX.Y+1.0`).
   - First-time invocation (crossing the v1.0.0 threshold) → **major** bump (`v1.0.0`), regardless.

   **The developer makes the final call.** Record the result in the phase plan's "Anticipated version bump target" line.

6. **Present the phase plan** to the developer for approval. Iterate if needed.

7. **After approval, add a new phase section and stories to `docs/specs/stories.md`** — same algorithm as `plan_phase` step 5 (next phase letter, base-26-no-zero successor scheme, insertion before `## Future`, story format). Stories within the phase run **unversioned** during work; the phase ships as one bundled release at the end (per the Version Cadence rule). Include a spike story if the phase introduces a new integration boundary.

8. **Present the updated stories** to the developer for approval.

9. **Append any new must-know facts to `project-essentials.md`** — same shape as `plan_phase` step 7. New architecture boundaries, workflow rules, hidden coupling, deferred-but-documented items. Skip if the phase introduces no new invariants.

10. **End-of-phase release** (after all phase stories are marked `[Done]` — typically a separate session, not part of this mode's run): the developer invokes `project-guide bump-version <X.Y.Z>` to bump the version and seed a `## [X.Y.Z] - <date>` CHANGELOG entry. The version is the target recorded in step 5; if implementation introduced unanticipated breaking changes, the developer revisits the target before bumping.

{% set next_mode = 'code_test_first' if test_first else 'code_direct' %}
{% include "modes/_header-sequence.md" %}

{% include "modes/_phase-letters.md" %}
