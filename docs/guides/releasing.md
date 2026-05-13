# Releasing DataRefinery

This guide documents the end-to-end release procedure: prepare the
version bump, push a tag, and let the publish workflow upload an
`ml-datarefinery` distribution to PyPI. `CHANGELOG.md` is the
canonical release log; there is no separate GitHub-Release object
created on tag push (see Story H.g).

> **PyPI distribution name is `ml-datarefinery`.** The bare
> `datarefinery` name on PyPI was taken before this project began, so
> the distribution ships as `ml-datarefinery`; the Python import name
> and console script remain `datarefinery`. End users install with
> `pip install ml-datarefinery` and write `import datarefinery`. Same
> shape as `scikit-learn` / `import sklearn`.

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

   The publish workflow uses `pyproject.toml`'s version as the source
   of truth and refuses to publish if the tag does not match.

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

5. **Watch the Publish workflow.** On tag push, `.github/workflows/
   publish.yml` runs and:

   1. Verifies `pyproject.toml`'s version matches the tag.
   2. Builds `sdist` + `wheel` via `python -m build`.
   3. Uploads to **PyPI** under the `pypi` GitHub environment
      (required-reviewer protection — a maintainer must approve the
      deploy in the GitHub UI before the upload runs) via PyPI
      Trusted Publishing (OIDC; no API token in the repo).

   The distribution uploaded is `ml-datarefinery`; once approved,
   `pip install ml-datarefinery==X.Y.Z` works from any clean venv.

6. **Verify the PyPI distribution.** In a fresh venv:

   ```bash
   python -m venv /tmp/dr-verify && source /tmp/dr-verify/bin/activate
   pip install ml-datarefinery==X.Y.Z
   datarefinery --version
   python -c "import datarefinery; print(datarefinery.__version__)"
   ```

   The console script name and import name are both `datarefinery`;
   only the distribution name is `ml-datarefinery`.

## Tag protection

Tag protection is a repo-level setting and is **not** expressible in
workflow YAML. Configure it once via the GitHub UI:

1. Repo → Settings → Tags → "New rule".
2. Pattern: `v*`.
3. Restrict to maintainers (or whichever team owns releases).

Until that rule is in place, anyone with write access can push a
`v*` tag and trigger a release.

## When the workflow refuses

The publish workflow fails with a clear `::error::` message in this
case:

- **`Tag <vX.Y.Z> does not match pyproject.toml version <Y>`** — the
  tag was pushed before the version bump landed, or the wrong tag
  name was used. Delete the tag, fix the version bump in a follow-up
  commit, and re-tag.

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
only do it if the PyPI upload has not yet been published (i.e., the
`pypi` environment deploy is still "Waiting for review" or the
workflow failed before the upload step). Once the wheel is on PyPI,
that version is permanent — you cannot re-upload the same version,
only yank it and ship `X.Y.Z+1`.

## One-time PyPI Trusted Publisher setup

Before the first publish (and again for any new project name), the
trusted-publisher binding must be registered on PyPI **and** the
matching GitHub Actions environment must exist. This is a manual,
one-time step; the workflow cannot bootstrap itself.

1. **PyPI — pending publisher.** Log in to https://pypi.org → Account
   Settings → Publishing → "Add a new pending publisher". Fill in:

   - **PyPI Project Name:** `ml-datarefinery`
   - **Owner:** `pointmatic` (the GitHub org or user that owns the
     repo)
   - **Repository name:** `datarefinery`
   - **Workflow filename:** `publish.yml`
   - **Environment name:** `pypi`

2. **GitHub — `pypi` Actions environment.** Repo → Settings →
   Environments → "New environment" → name `pypi`. Under "Deployment
   protection rules", add "Required reviewers" and select the
   maintainer team. This is the human gate that blocks the
   production-PyPI upload until someone clicks "Approve and deploy"
   on each release.

After the first successful PyPI upload, the "pending publisher" on
PyPI becomes a regular trusted publisher and stops appearing in the
pending list.

## What this workflow does *not* do

- **Create a GitHub Release object.** `CHANGELOG.md` is the canonical
  release log; the git tag itself is visible on GitHub without a
  parallel Release entry. (See Story H.g for the rationale.)
- **Mutate `CHANGELOG.md`.** The workflow is read-only against the
  repo state at the tag.
- **Build wheels / sdists for non-release commits.** Side-channel
  builds are still done locally with `python -m build`; the publish
  workflow only runs on `v*` tag pushes.
- **Reserve the `datarefinery` name on PyPI.** That name is taken by
  another project; this repo publishes as `ml-datarefinery` and is
  not in a position to claim the unprefixed name.
