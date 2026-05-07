Implement stories using test-driven development (TDD). Write a failing test before writing any implementation code.

{% include "modes/_header-cycle.md" %}

## Cycle Steps

For each story:

1. **Read** the story's checklist from `docs/specs/stories.md` — always re-fetch from disk with the `Read` tool at the start of each cycle. The developer may have edited the file since you last viewed it (added tasks, reworded scope, marked items done), so do not rely on prior conversation context for its contents.
2. **Identify and announce** the intended next story to the developer **before writing any tests or implementation**. State the **story ID** (e.g., `Story B.c`), **title**, and a **one-line scope summary** of what implementing it covers. Then wait for the developer to say "go" (a precise confirmation of *this specific story*) — or to redirect you to a different story. Do not start the red-green-refactor loop on the strength of your own pick; the announce-and-wait beat exists so the developer can redirect cheaply before any code is written.
3. For each task in the checklist:
   a. **Write a failing test** that describes the expected behavior
   b. **Run the test** -- confirm it fails (red)
   c. **Write the minimal implementation** to make the test pass
   d. **Run the test** -- confirm it passes (green)
   e. **Refactor** if needed -- clean up while tests still pass
   f. **Run full test suite** -- `{{ test_invocation }}` -- no regressions
4. **Add copyright/license headers** to every new source file
5. **Run linting** -- fix any issues immediately
6. **Mark tasks** as `[x]` in `stories.md` and change story suffix to `[Done]`
7. **Bump version** in package manifest and source — only if the story has a version assigned. **Determine the bump magnitude per the Version Cadence rule** (see `docs/specs/stories.md`'s Version Cadence section, summarized in this mode's header above): patch for bugfix, minor for feature, major for breaking (post-1.0 only via `plan_production_phase`). **Do not extrapolate from `pyproject.toml`'s current version** — re-read the cadence rule if unsure.
8. **Update CHANGELOG.md** with the version entry
9. **Present** the completed story concisely: what changed (files + line refs), verification results (test counts, lint status, red-green-refactor summary), and the suggested next story. Do not propose commits, pushes, or bundling options. Do not offer "want me to also…?" follow-ups.
10. **Wait** for the developer to say "go" before starting the next cycle. "Go" re-enters the cycle at **Step 1** — a fresh `stories.md` read and a new announce in Step 2 — never silent implementation of whatever you assumed was next.

## Red-Green-Refactor

The TDD cycle:

1. **Red** -- Write a test that fails. The test defines the desired behavior.
2. **Green** -- Write the simplest code that makes the test pass. No more.
3. **Refactor** -- Clean up the code while keeping tests green. Remove duplication, improve naming, simplify logic.

## Test Writing Guidelines

- **Test behavior, not implementation** -- assert on outputs and side effects, not internal state
- **One assertion per concept** -- each test should verify one thing
- **Use descriptive names** -- `test_override_with_nonexistent_guide_errors` not `test_override_3`
- **Prefer unit tests** -- test individual functions in isolation
- **Use integration tests sparingly** -- for verifying component interactions
- **Test edge cases** -- empty inputs, boundary values, error conditions

## Test Hierarchy

| Level | Speed | Scope | Use for |
|-------|-------|-------|---------|
| Unit | Fast | Single function | Core logic, edge cases, error paths |
| Integration | Medium | Multiple components | Verifying wiring, config loading |
| End-to-end | Slow | Full system | Final validation, smoke tests |

## When to Switch Modes

Switch to **code_direct** when:
- The story is straightforward and TDD overhead isn't justified
- The developer requests faster iteration

Switch to **debug** when:
- A bug is discovered during implementation
- Tests are failing unexpectedly and need root cause analysis
