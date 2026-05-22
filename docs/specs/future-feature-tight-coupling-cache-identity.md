# DataRefinery Feature Spec — Tight-Coupling Cache Identity for Cross-Recipe Dependencies

**Status:** Future-queue recommendation. Successor to FR-ARCH-1 (loose coupling),
which ships in the Phase H sub-bundle as the initial implementation. This spec
covers the follow-up upgrade to tight coupling.

**Proposed ID:** FR-ARCH-2 (rename at filing time if the FR-ARCH-1 designation
has been retired or re-used).

---

## Context

DataRefinery's cache identity today is the XOR of three hashes: the canonical
recipe bytes, the raw input bytes, and the seed. The Phase H sub-bundle adds
`stats_from_instance` (FR-TRANS-1), which lets a recipe import fitted
statistics from a sibling materialized instance — fitted normalization
parameters, and in the future any analogous learned state (vocabularies,
embeddings, indices, calibration tables).

The Phase H bundle ships this with **loose coupling**: the downstream recipe
declares the sibling by reference but cache identity does not track the
sibling's hash. Re-materializing the upstream recipe does not invalidate
downstream cached instances. The downstream operator is responsible for
deleting or invalidating the downstream cache when upstream changes.

Loose coupling is sufficient for single-author, single-pass workflows where
the operator knows the dependency exists and remembers to invalidate. It
becomes a correctness hole in any workflow where that knowledge or memory
can't be guaranteed.

---

## What

When a recipe declares `stats_from_instance` (or any future analogous
cross-recipe dependency), the referenced sibling instance's cache identity
becomes a term in the current recipe's cache identity. Cache key composition
becomes:

```
H(current) = H(canonical_recipe_bytes)
           ⊕ H(raw_input_bytes)
           ⊕ H(seed)
           ⊕ H(sibling.cache_identity)    // new term
```

If a sibling's cache identity changes (because its bytes, inputs, or seed
changed), the current recipe's cache key changes, and any prior cached
instance of the current recipe is no longer addressable by the new key —
re-materialization happens automatically on next use.

Sibling resolution happens at recipe-validation time. A reference to a
sibling that has never been materialized is a fail-fast validation error,
not a runtime surprise.

---

## Why

The use cases where loose coupling's failure mode (silent staleness of
downstream caches) becomes a real correctness concern:

- **Multi-team workflows.** Team A maintains the upstream recipe; Team B
  maintains the downstream recipe and consumes Team A's fitted state. Team
  A re-materializes upstream for an unrelated reason (input refresh,
  parameter retune); Team B's cached downstream instance is now using stale
  state that no longer corresponds to any actual upstream instance. Team B
  has no signal that this happened.

- **Longitudinal evaluation.** The same downstream recipe (e.g., a periodic
  robustness evaluation set, an ongoing fairness audit, a quarterly model-
  drift check) is materialized repeatedly over time against an upstream
  that occasionally changes. Loose coupling leaves the operator with no
  systematic way to know whether a given downstream materialization
  reflects current upstream state or stale state from a prior version.

- **CI / automated pipelines.** A pipeline materializes downstream recipes
  on a schedule or in response to triggers, without a human in the loop to
  remember which upstream caches need invalidating. Tight coupling makes
  correctness automatic; loose coupling requires the pipeline operator to
  encode invalidation logic by hand and keep it in sync with the recipe
  dependency graph.

- **Reproducibility audits.** A downstream cached instance is presented as
  the artifact of record for some evaluation. The auditor wants to confirm
  it was materialized against the upstream state declared in its
  provenance. Loose coupling makes this confirmation a manual cross-check;
  tight coupling makes it a property of the cache identity itself.

In all four cases, loose coupling silently produces a class of bug that's
hard to detect after the fact — the cached instance is well-formed and
loads correctly; nothing surfaces the staleness. Tight coupling closes
the hole at the system level.

---

## Design Decisions to Resolve

Three decisions need to be made and documented before implementation. Each
has multiple defensible answers; the choice between them affects spec
semantics and downstream behavior.

### Decision 1: Recursive vs. flat dependency tracking

When recipe C depends on recipe B which depends on recipe A, does C's
cache identity fold in B's identity directly, or fold in the transitive
closure (B's identity, which itself already folds in A's)?

- **Recursive (transitive).** Each recipe's cache identity incorporates
  the full upstream chain. A change anywhere in the chain invalidates
  every downstream. Cleanest correctness story; requires cycle detection.
- **Flat (direct only).** Each recipe only tracks its direct dependencies.
  Changes propagate one hop at a time as each affected downstream is
  re-materialized. Simpler implementation; risk of partial-update
  inconsistencies during in-flight propagation.

Recursive is the architecturally correct answer if dependency chains are
expected to be more than one hop deep. Flat is acceptable if dependencies
are nearly always single-hop in practice.

### Decision 2: Sibling addressing scheme

Today recipes are addressed by canonical-bytes hash; this is fine for cache
keys but not for one recipe to reference another by name in declarative
YAML. Three options:

- **By path.** "The recipe at `recipes/base.yaml`." Simple to implement,
  matches how operators already think about recipes on disk. Brittle:
  renaming or moving a recipe breaks all downstream references even when
  content is unchanged.
- **By declared name.** Each recipe declares a `name` field; downstream
  references resolve by name. Stable across path changes. Requires a
  recipe namespace and a name-uniqueness invariant — and a resolution
  policy when names collide (cache hit nearest match? fail?).
- **By upstream content hash.** Downstream declares the literal hash of
  the upstream recipe. Maximally precise. Authoring friction: the
  downstream recipe's bytes change every time upstream changes, which
  defeats the upstream-change-shouldn't-touch-downstream-bytes property
  that path-based and name-based addressing preserve.

By-name is the most operator-friendly and the most likely to be the right
long-term answer. By-path is the lowest-implementation-cost interim choice
if a recipe namespace isn't yet warranted.

### Decision 3: Invalidation semantics under partial materialization

When an upstream recipe is re-materialized and its cache identity changes,
what happens to existing downstream cached instances?

- **Lazy invalidation.** Existing downstream caches stay on disk. Next
  time a downstream is requested, the cache loader recomputes its key
  (which now includes the new upstream identity), sees no match, treats
  as uncached, re-materializes. Simple. Stale instances accumulate on
  disk until garbage-collected.
- **Eager invalidation.** Re-materializing upstream actively walks the
  dependency graph and invalidates downstream caches. Requires
  DataRefinery to maintain a cross-recipe dependency graph at the cache
  layer.
- **Proactive validation on read.** Every cache read recomputes the
  upstream chain and confirms freshness before returning the cached
  instance. Correct, but adds filesystem walks to every cache hit.

Lazy invalidation is the obviously-correct first implementation:
correctness without complexity, at the cost of disk-space hygiene that's
easily addressed by an existing or future garbage-collection mechanism.
Eager and proactive are optimizations that can be added if disk pressure
or read-latency profiles demand them.

---

## Dependencies and Ordering

- **Depends on:** FR-TRANS-1 (`stats_from_instance` parameter, shipping in
  Phase H sub-bundle as v0.13.0) — without it there's no cross-recipe
  dependency to track.
- **Successor to:** FR-ARCH-1 loose coupling (Phase H sub-bundle).
- **Backward compatibility:** all loose-coupling recipes continue to work
  unchanged. Tight coupling activates only when the cache-identity logic
  is enabled (could be a config flag during rollout, or a one-way upgrade).
- **Cache-identity impact:** activating tight coupling invalidates every
  cached instance that uses cross-recipe dependencies. This is acceptable
  per the pre-prod cache-identity rules at the time the feature ships; if
  it ships post-1.0, the rollout needs an explicit migration story.

Suggested ordering for the implementation work:

1. Resolve Decisions 1-3 (design phase, documented outcome).
2. Implement lazy invalidation with by-name (or by-path) addressing and
   recursive (or flat) dependency tracking, per the decisions in step 1.
3. Tests covering: upstream re-materialization invalidates downstream
   cache; sibling not yet materialized produces validation error;
   transitive dependency tracking works correctly (if recursive); cycle
   detection works (if recursive).
4. Documentation update: cross-recipe dependencies, addressing scheme,
   invalidation semantics, garbage-collection guidance.

Implementation budget estimate (excluding the design-decision phase): two
to three days of work plus testing.

---

## Out of Scope

- **Cross-recipe dependencies beyond `stats_from_instance`.** This spec
  covers the mechanism. Future operations that import sibling state
  (vocabularies, embeddings, indices, calibration tables) inherit the
  tight-coupling behavior automatically once the mechanism is in place,
  but each new operation is its own feature.
- **Cache garbage collection.** Lazy invalidation leaves stale instances
  on disk. A separate mechanism to identify and remove them is desirable
  but independent of this feature.
- **Multi-instance materialization orchestration.** The question of how to
  efficiently re-materialize a dependency chain in the right order is a
  pipeline-runner concern, not a cache-identity concern.
- **Distributed cache scenarios.** This spec assumes a single
  filesystem-backed cache. Distributed or remote-shared caches add
  resolution and consistency questions outside this scope.
