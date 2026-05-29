# Phase J planning context — ModelFoundry + NbFoundry integration

This document is a **context prompt**. Open a fresh conversation, switch to
`plan_phase` mode (`project-guide mode plan_phase`), and paste the
"Prompt" section below. It is a *phase-starter* for Phase J, not an
exhaustive backlog — Phase J is intended as a catch-all that accretes
integration stories as they surface while wiring DataRefinery to its
downstream consumers (ModelFoundry and NbFoundry).

Authored as Story I.z (documentation-only). It is a point-in-time
snapshot — the planning conversation should **verify current repo state**
(see the prompt) rather than trust the gap list verbatim.

---

## Prompt (paste this into a fresh `plan_phase` conversation)

You are starting **Phase J** of the DataRefinery project. Before drafting
anything, read `docs/project-guide/go.md` and follow its mode protocol.

**Theme.** Phase J covers **integration with downstream consumers** —
**ModelFoundry** (the training tool that consumes prepared instances) and
**NbFoundry** (notebook-side consumer). Treat Phase J as a *catch-all*:
seed it with the known gaps below, but expect most stories to emerge
reactively as real integration work exposes friction. Do **not** try to
anticipate and solve every problem up front. The phase-starter job is to
establish the theme, capture the known "not ready for consumption"
issues, and stand up the cross-repo contract discipline; concrete stories
land as integration proceeds.

**First, orient yourself (read in this order, then verify current state):**

1. `docs/project-guide/go.md` — workflow + the **scope-of-authority** rule (only `plan_phase` may create a `## Phase J:` heading).
2. `docs/specs/stories.md` — confirm Phase I is closed (its last story, I.y, ships **v0.19.0** and **schema_version 2**) and check which stories are actually `[Done]`. **Do not trust the snapshot below** — re-read the file. (At the time this prompt was authored, Phase I Bundle 3/4 stories I.s–I.y were still `[Planned]`.)
3. `docs/specs/project-essentials.md` — the cache-identity reproducibility contract, the loose-coupling decisions, and especially **"Recipe / manifest / report shape changes need a cross-repo coordination check."**
4. `docs/specs/modelfoundry/dependency-spec.md` — the **authoritative cross-repo contract** with ModelFoundry. This is the binding document; keep it current as the source of truth.
5. `docs/specs/features.md` and `docs/specs/tech-spec.md` — the what and the how.

**Known "not ready for consumption" gaps (seed material, priority order):**

1. **SampleData runtime gap (highest-priority seed).** The `SampleData`
   recipe section is *fully wired as a contract surface* (pydantic model,
   validator check 16, participates in canonical cache bytes) but is
   **never applied at materialize time** — declaring it shapes cache
   identity and validates, yet produces no subset. Story **I.r** landed
   the schema (`SampleSelector.kind` ∈ {uniform, per_class}, `splits`);
   the **runtime was deliberately carved out** to Phase J. The spike
   **Story I.r.0** (in `stories.md`) documents the open product decisions
   the runtime story must settle:
   - **Placement** — subset raw input pre-pipeline (matches FR-2 check
     #16 "subset of the declared input") vs. sample per-split
     post-pipeline (required to honor `kind: per_class` + `splits:`).
   - **Artifact semantics** — the sample *replaces* the materialized
     instance vs. a `sample/` *sidecar* emitted alongside the full
     dataset (recommended default: post-pipeline + sidecar).
   - **Manifest/report** implications of whichever choice.
   No functional requirement currently specifies SampleData runtime
   behavior — this needs a product decision before implementation.

2. **Only `image_classification` is a real plugin.** The `tabular` and
   `text` plugins are **stubs** (`is_stub()` → True; their input loaders
   raise `PluginError`). If ModelFoundry or NbFoundry need to consume
   tabular or text data, a real plugin is a prerequisite, not a given.

3. **`distributional` assertion kind is a placeholder** that always
   passes. Any consumer relying on distributional/drift assertions must
   implement its own checks until a real evaluator lands.

4. **`Splits.class_balance` is a training-time *hint*, not DR-side
   resampling.** DataRefinery emits the strategy verbatim through
   `SplitResult.class_balance` / `manifest.class_balance`; the consumer
   (ModelFoundry) must honor it at training time via framework
   primitives (`WeightedRandomSampler`, `class_weight=`, …). This is a
   binding expectation — confirm ModelFoundry implements it. (Schema
   landed as Story I.s / G10; contract in `dependency-spec.md`.)

5. **Report structure is a single `report.md` section.** Per-stage
   report subsections are deferred (`stories.md § Future`). Consumers
   that parse `report.md` / `drift.json` bind to the current structure —
   any restructure is a cross-repo contract change.

6. **schema_version 2 reshapes the recipe contract.** Phase I Bundle 4
   (Stories I.x.1–I.x.3) reshapes `FilterOp` (flat `op:`/`params:`),
   `GenerationOp` (top-level `op:`, `applies_at`→`splits`,
   `output_schema: matches_input`), and renames assertion kinds
   (`dtype`→`dtype_equals`, etc.). Consumers binding the recipe model
   must track v2. The v1→v2 migration is loader-side and
   cache-invalidating (pre-prod: re-materialize once).

7. **Internal specs still carry consumer-specific framing.** The Phase I
   gap doc and intermediate-artifact spec retain "Recipe A/B", "Module N",
   and consumer recipe filenames; a broad sanitizing rewrite is deferred
   (`stories.md § Future`, "Broad consumer-context rewrite"). Not
   consumer-blocking, but relevant if Phase J docs reference them.

**Cross-repo contract discipline (carry into every Phase J story):**

- Three surfaces leave DataRefinery and bind consumers: the **recipe
  model**, the **manifest schema**, and the **report subsections**
  (`report.md` + `drift.json`). Any change to these is a cross-repo
  contract change — read and update `dependency-spec.md` in the same
  change, and decide whether a `schema_version` bump is required (see
  `project-essentials.md`).
- `dependency-spec.md` is **ModelFoundry-specific**. **NbFoundry has no
  equivalent contract document yet** — an early Phase J task is likely to
  stand one up (or extend the existing doc to cover both consumers).

**Suggested first planning moves (the planner decides):**

- Pull the actual integration requirements from ModelFoundry and
  NbFoundry — let real needs drive the story list rather than this gap
  snapshot.
- Prioritize the **SampleData runtime** story and settle its placement /
  artifact-semantics product decision first (it blocks the documented
  consumer use case).
- Decide whether `tabular` / `text` plugins need real implementations for
  these consumers, or whether Phase J stays image-classification-scoped.
- Stand up an NbFoundry contract surface (or unify the consumer contract
  doc).
