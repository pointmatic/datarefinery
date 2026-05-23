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
