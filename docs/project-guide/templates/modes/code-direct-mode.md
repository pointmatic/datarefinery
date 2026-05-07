Implement stories rapidly with direct commits to main. Focus on feature completion and iteration speed over process overhead.

{% include "modes/_header-cycle.md" %}

## Cycle Steps

For each story:

1. **Read** the story's checklist from `docs/specs/stories.md` — always re-fetch from disk with the `Read` tool at the start of each cycle. The developer may have edited the file since you last viewed it (added tasks, reworded scope, marked items done), so do not rely on prior conversation context for its contents.
2. **Identify and announce** the intended next story to the developer **before implementing anything**. State the **story ID** (e.g., `Story B.c`), **title**, and a **one-line scope summary** of what implementing it covers. Then wait for the developer to say "go" (a precise confirmation of *this specific story*) — or to redirect you to a different story. Do not start implementation work on the strength of your own pick; the announce-and-wait beat exists so the developer can redirect cheaply before any code is written.
3. **Implement** all tasks in the checklist
4. **Add copyright/license headers** to every new source file
5. **Run tests** -- `{{ test_invocation }}` (fix failures before continuing)
6. **Run linting** -- fix any issues immediately
7. **Mark tasks** as `[x]` in `stories.md` and change story suffix to `[Done]`
8. **Bump version** in package manifest and source — only if the story has a version assigned. **Determine the bump magnitude per the Version Cadence rule** (see `docs/specs/stories.md`'s Version Cadence section, summarized in this mode's header above): patch for bugfix, minor for feature, major for breaking (post-1.0 only via `plan_production_phase`). **Do not extrapolate from `pyproject.toml`'s current version** — re-read the cadence rule if unsure.
9. **Update CHANGELOG.md** with the version entry
10. **Present** the completed story concisely: what changed (files + line refs), verification results (test counts, lint status), and the suggested next story. Do not propose commits, pushes, or bundling options. Do not offer "want me to also…?" follow-ups.
11. **Wait** for the developer to say "go" before starting the next cycle. "Go" re-enters the cycle at **Step 1** — a fresh `stories.md` read and a new announce in Step 2 — never silent implementation of whatever you assumed was next.

## Velocity Practices

**LLM's role in each cycle:**

- **Version bump per story** — magnitude per the Version Cadence rule (bugfix=patch, feature=minor, breaking=major-post-1.0-only); bump in package manifest and source
- **Minimal process overhead** -- focus on making it work, not making it perfect
- **Tests run after every story** -- not after every file, but before presenting to developer
- **Fix linting immediately** -- small incremental fixes, not batch cleanup
- **Update CHANGELOG.md** with the version entry before presenting

**Developer's role (do NOT prompt for, offer, or initiate):**

- **Direct commits to main** -- no branches, no PRs, no code review (velocity convention)
- **Commit messages** reference story IDs: `"Story A.a: v0.1.0 Hello World"`
- **Decides when to commit** -- the LLM presents, the developer commits. Multiple stories may be bundled into one commit at the developer's discretion — that is not the LLM's call to make or suggest.

## Story Ordering

- Start with Story A.a (Hello World) if not yet implemented
- The Step 2 announce-and-wait gate is where the developer confirms (or redirects). If you are unsure which story is next, that is the moment to surface the ambiguity in the announce — e.g., "I see two candidates: Story B.c and Story B.d. Which should I work on?" — not a moment to silently pick one.
- Never skip ahead -- complete stories in order within each phase

## File Header Reminder

Every new source file must include the copyright and license header as the very first content (before code, docstrings, or imports).

## When to Switch Modes

Switch to **code_test_first** when:
- Working on a story with complex logic that benefits from TDD
- The developer requests test-first approach

Switch to **debug** when:
- A bug is discovered during implementation
- Tests are failing unexpectedly

Switch to **production mode** when:
- CI/CD phase is complete and branch protection is enabled
- The project is ready for public users
