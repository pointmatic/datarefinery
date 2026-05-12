# Releasing DataRefinery

This guide documents the end-to-end release procedure: prepare the
version bump, push a tag, and let the release workflow publish a
GitHub Release sourced from `CHANGELOG.md`.

> **PyPI publishing is intentionally deferred.** The `datarefinery`
> name is taken on PyPI. The release artifact is the **GitHub
> Release** (and the git tag it points to) until that situation is
> resolved. The PyPI half of `features.md` Acceptance Criterion 4
> ("`pip install datarefinery` from a clean venv works") is satisfied
> locally against the built wheel, not against a public index.

## Prerequisites

- You are the developer driving the release (not the LLM — the LLM
  presents the story, the developer commits and tags).
- You are on `main` with a clean working tree and the story whose
  title pins the new version is `[Done]`.
- The repo has tag-protection rules in place restricting `v*` pushes
  to maintainers (see [Tag protection](#tag-protection) below).

## Procedure

1. **Confirm the version bump is in place.** The owning story's
   tasks should already have updated:

   - `pyproject.toml` `[project].version`
   - `src/datarefinery/__init__.py` `__version__`
   - `CHANGELOG.md` with a section heading of the exact form
     `## [X.Y.Z] - YYYY-MM-DD`

   The release workflow uses these as the source of truth and
   refuses to publish if the tag does not match `pyproject.toml` or
   if no matching `CHANGELOG.md` section is found.

2. **Commit any pending release prep.** The story's normal
   `code_direct` cycle should have produced one or more commits
   already; if anything is uncommitted, commit it now.

3. **Wait for CI green on `main`.** Both
   `ci (ubuntu-latest, 3.12)` and `ci (macos-latest, 3.12)` must
   pass — and Codecov should have reported in. Tagging before CI is
   green risks shipping a release that does not match the gates.

4. **Tag the release.** Use an annotated tag named exactly `vX.Y.Z`:

   ```bash
   git tag -a v0.6.4 -m "v0.6.4"
   git push origin v0.6.4
   ```

   The leading `v` is required — the workflow trigger is `v*` and
   the workflow strips the prefix when comparing against
   `pyproject.toml`.

5. **Watch the Release workflow.** On tag push, `.github/workflows/
   release.yml` runs and:

   1. Resolves the version from the tag.
   2. Verifies `pyproject.toml`'s version matches.
   3. Extracts the `## [X.Y.Z]` section from `CHANGELOG.md` (up to
      the next `## [` heading).
   4. Calls `gh release create` to publish a GitHub Release named
      after the tag with the extracted section as the body.

6. **Verify the Release.** Browse to the repo's Releases page and
   confirm:

   - The new release exists with the tag as the title.
   - The body contains the CHANGELOG section verbatim.
   - The "Source code" archives (`zip`, `tar.gz`) are attached
     (GitHub generates these automatically).

## Tag protection

Tag protection is a repo-level setting and is **not** expressible in
workflow YAML. Configure it once via the GitHub UI:

1. Repo → Settings → Tags → "New rule".
2. Pattern: `v*`.
3. Restrict to maintainers (or whichever team owns releases).

Until that rule is in place, anyone with write access can push a
`v*` tag and trigger a release.

## When the workflow refuses

The workflow fails with a clear `::error::` message in these cases:

- **`Tag <vX.Y.Z> does not match pyproject.toml version <Y>`** — the
  tag was pushed before the version bump landed, or the wrong tag
  name was used. Delete the tag, fix the version bump in a follow-up
  commit, and re-tag.
- **`No CHANGELOG.md section found for [X.Y.Z]`** — the
  `CHANGELOG.md` entry is missing or its heading is not in the
  expected `## [X.Y.Z] - YYYY-MM-DD` form. Fix the changelog, then
  re-tag.

To "re-tag," delete the bad tag locally and on the remote, then
push the corrected tag:

```bash
git tag -d v0.6.4
git push origin :refs/tags/v0.6.4
# fix the underlying issue, commit, then:
git tag -a v0.6.4 -m "v0.6.4"
git push origin v0.6.4
```

Force-deleting a tag from the remote is a destructive operation;
only do it if the GitHub Release has not yet been published, or
manually delete the published Release first.

## What this workflow does *not* do

- **Build wheels / sdists.** The release artifact is the source-tagged
  GitHub Release. Run `python -m build` locally to produce wheels for
  side-channel distribution.
- **Upload to PyPI.** Deferred (see top of this document).
- **Mutate `CHANGELOG.md`.** The workflow is read-only against the
  repo state at the tag.
