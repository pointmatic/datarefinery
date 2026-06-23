# Design spec — Segmented recipe identity (Q1–Q8 resolved)

**Status:** frozen design (Story J.n.1) — **pending developer confirmation at the J.n.1 approval gate.** Once confirmed, Stories **J.n.2–J.n.8 execute against this doc without re-debating.**
**Builds on:** the [spike memo](phase-j-recipe-architecture-spike.md). Its § 3 "resolved stance" (no-implicit-defaults, required-vs-optional = bump-vs-free, pre-1.0 zero support window) is **settled input**, not re-litigated here. This doc resolves the eight open dimensions Q1–Q8.
**Method:** every decision is grounded in verified current-source citations (gathered for this story); each names its downstream story owner.

---

## 0. Verified current state (the ground truth these decisions stand on)

- **`Recipe` is a flat frozen model**, `extra="forbid"`, `frozen=True` (`_Frozen` base, [models.py:21-24](../../src/datarefinery/recipe/models.py#L21-L24)); fields at [models.py:455-473](../../src/datarefinery/recipe/models.py#L455-L473), including `variants: dict[str, dict[str, Any]] = Field(default_factory=dict)` ([models.py:473](../../src/datarefinery/recipe/models.py#L473)).
- **`InputSource.type` is a free `str`, not a `Literal`** ([models.py:88](../../src/datarefinery/recipe/models.py#L88)) — audio source *type names* need no model change; only the audio-specific *fields* (e.g. `target_sample_rate`) are new.
- **Canonical bytes = `recipe.model_dump(mode="json")` → sorted compact `json.dumps`** ([canonical.py:20-37](../../src/datarefinery/recipe/canonical.py#L20-L37)). `model_dump` is total (every field, every default).
- **`apply_variant` already clears `variants={}` and overlays before hashing** ([variants.py:41-44](../../src/datarefinery/recipe/variants.py#L41-L44)): "editing or adding an unused variant does not invalidate cached instances of other variants." So **overlay isolation already holds**; selecting A vs B changes the hash, defining an unused variant does not. Applied pre-validation/pre-hash in `from_recipe` ([datarefinery.py:93](../../src/datarefinery/core/datarefinery.py#L93)).
- **Migration registry:** `dict[tuple[int,int], Callable[[dict],dict]]` ([migrations.py:36-38](../../src/datarefinery/recipe/migrations.py#L36-L38)); loader walks `current→current+1` in `_migrate_to_latest` ([loader.py:118-135](../../src/datarefinery/recipe/loader.py#L118-L135)); `SUPPORTED_SCHEMA_VERSIONS={1,2}`, `LATEST=2` ([loader.py:29-30](../../src/datarefinery/recipe/loader.py#L29-L30)).
- **Defaults blast radius:** ~28 `ParameterSpec(..., default=...)` across plugins (21–23 in image_classification, 3 text, 2 tabular); the only no-default mode-selecting optionals are `normalize.mean`/`normalize.std` ([plugin.py:214-215](../../src/datarefinery/plugins/image_classification/plugin.py#L214-L215)). `ParameterSpec` = `{type, required=True, default=None, description}` ([base.py:22-30](../../src/datarefinery/plugins/base.py#L22-L30)).
- **Scaffolder already emits explicit values** into the YAML (`_build_recipe` returns a fully-populated dict, `yaml.safe_dump`'d — [init.py:134-204](../../src/datarefinery/scaffolder/init.py#L134-L204), [init.py:228-239](../../src/datarefinery/scaffolder/init.py#L228-L239)); it does not rely on pydantic defaults for what it writes.
- **Validator plugin-coupling:** checks 19/20/21 gate on `image_classification`/`_PARTITION_PLUGINS` ([validator.py:763,929,1037](../../src/datarefinery/recipe/validator.py#L763)); check_23 builds the reserved set dynamically from recipe config ([validator.py:1167-1180](../../src/datarefinery/recipe/validator.py#L1167-L1180)).

### Pivotal interaction (shapes Q1 + Q7 + Finding A)

**With no-implicit-defaults (Q7) + sparse hashing, Finding A is resolved by serialization, not by physical field relocation.** Once absent fields never serialize, `target_sample_rate` appears only in recipes that set it (audio) — it can never enter an image recipe's canonical bytes regardless of where it lives on the model. **Therefore plugin *segmentation*'s job is NOT byte-isolation** (Q7 gives that) **— it is per-plugin *versioning*, *validation dispatch*, and *pin-test boundaries*.** This narrows Q1 substantially.

---

## Q1 — Plugin-surface representation → **section-granular segments + narrow discriminated unions; sparse hashing (not relocation) carries byte-isolation**

**Decision.**
1. **Segment boundaries are section-granular**, expressed as segment-typed sub-models on `Recipe` (per J.n.3 "split Recipe into segment-typed sub-models"):
   - **`core`** — `schema`/versions, `plugin`, `seed`, `Input` (structure), `Output`, `Labels`, `Splits`, `SampleData`, `InputContracts`, `OutputExpectations`.
   - **`plugin`** — the op-list sections whose op vocabulary is plugin-defined: `Filters`, `Generation`, `Transformations`, `Augmentations`, `Featurizations`, `Visualizations`, `Sinks` (each op's `params` bag is already plugin-interpreted and self-isolating).
   - **`overlays`** — `variants` reborn (Q2).
   - **`extensions`** — the new namespace (Q5).
2. **Plugin-specific *fields on shared structural models* are typed via a narrow discriminated union** on `InputSource.type` (`ImageSource | AudioSource`, discriminator `type`). The union exists for **type-safety/validation**, not byte-isolation. **Rule for the straddle:** base `InputSource` fields (`name`/`type`/`path`/`label_from`/`partition`/`unlabeled`) are version-governed by `core`; a discriminated subclass's *extra* fields (e.g. `AudioSource.target_sample_rate`) are version-governed by that field's **`plugin:<name>` segment**. So an audio-source-field change bumps `plugin:audio`, never `core`.
3. **Reject the disruptive pure-nested-`plugin:` sub-doc** that would relocate op `params` under a top-level `plugin:` key — unnecessary (op params are already isolated bags; sparse hashing handles fields) and a needless author-facing reshape.

**Rationale.** Byte-isolation comes free from Q7 (sparse). What the bundle's machinery (J.n.2 per-segment version constants, J.n.7 per-segment pin tests) actually needs is *clean, coarse segment boundaries* — section-granular gives that with the least author disruption. Discriminated unions are used only where a shared structural model genuinely grows per-plugin fields (today: just `InputSource`), keeping those fields **typed and validated** rather than dumped in an opaque bag.

**Downstream:** J.n.2 (per-segment version constants over these four segments), J.n.3 (the model refactor + `AudioSource` union; this is the one-time invalidation), J.n.7 (per-segment pin tests including the Finding-A image/audio isolation pair).

**⚠ Highest-stakes decision — flag for explicit developer scrutiny at the gate.** The section→segment assignment and the "subclass-extras → plugin segment" straddle rule are the load-bearing choices.

---

## Q2 — Overlays → **generalize today's variant mechanism to an ordered multi-overlay list; hash the resolved recipe; keep override (last-writer-wins) semantics**

**Decision.**
- Definitions live in the recipe's `overlays` segment (today's `variants` dict, renamed). A run selects an **ordered list** of overlays (execution-context, generalizing `--variant` → `--overlay a --overlay b`).
- **Composition: applied in selection order, last-writer-wins per key** (the current single-variant override semantics, generalized). Not free-form deep-merge — predictable and matches today.
- **Identity: hash the *resolved* recipe** (base + applied overlays), with overlay *definitions* stripped before hashing — exactly today's mechanism ([variants.py:44](../../src/datarefinery/recipe/variants.py#L44)), extended to the list. Selected overlay names recorded in the manifest (generalize `manifest.variant` → `manifest.overlays: list[str]`).
- **Overlays are open override-bags** (like today's `dict[str, dict]`), validated *post-merge* against the typed sections. Empty selection → empty `overlays` segment → fixed-nothing contribution (additivity pin test, J.n.7).

**Rationale.** The verification shows DR's key isolation property (unused overlays don't perturb the hash) **already exists**. The genuine gap is only *composability* (single-select → ordered-multi) and *naming the segment*. Resist over-building "independent per-overlay sub-hashes": hashing the resolved recipe already gives correct identity (same resolved bytes ⇒ same instance) and isolation already holds via stripping. Order-stability falls out of "applied in selection order."

**Downstream:** J.n.5 (overlays mechanism), J.n.8 (`manifest.variant`→`overlays` cross-repo rename).

---

## Q3 — `join_stable` shape → **ordered concatenation of per-segment SHA-256 digests; fixed empty-segment marker; prefix-capable by construction**

**Decision.**
```
seg_digest(s)   = SHA-256(canonical_subbytes(s))           # canonical_subbytes = sorted-compact json of the segment, sparse
seg_digest(∅)   = EMPTY_MARKER                             # one fixed 32-byte constant for an empty/absent segment
canonical_join  = b"\x1f".join([ seg_digest(core), seg_digest(plugin), seg_digest(overlays), seg_digest(extensions) ])  # fixed order
recipe_hash     = SHA-256(canonical_join)
```
- **Concatenated digests, not a Merkle tree** — only 4 (later ~9) segments; Merkle buys nothing here and adds complexity.
- **Prefix support (for the deferred vertical axis, Q8) is intrinsic:** a stage prefix hash is just `SHA-256(b"\x1f".join(seg_digests[:k]))`. No redesign needed to adopt vertical later.

**Rationale.** Simplest form that (a) makes per-segment isolation literal (a segment's digest is independent of others'), (b) makes empty-segment additivity a one-constant rule, (c) already expresses cumulative prefixes. Keeps J.n.2 trivial to implement and pin-test.

**Downstream:** J.n.2 (`join_stable` + empty marker), J.n.7 (empty-segment + isolation pin tests).

---

## Q4 — Versioning → **per-segment versions, no global umbrella; structural era-detection; migration keyed `(segment, from, to)`**

**Decision.**
- **Per-segment version map** (`core`, `plugin:<name>`, `overlays`, `extensions`); **no global umbrella counter** (a global counter would re-couple every segment's changes). A segment bump invalidates only that segment's scope.
- **Era detection is structural, not a counter:** the loader detects legacy flat recipes (top-level flat `schema_version: 1|2`, no segment-version block) vs. segmented recipes (segment-version block present) and routes accordingly.
- **Migration registry keyed `(segment, from, to) → fn`**, `fn: dict→dict` on that segment's sub-dict (generalizes today's `(int,int)` keying, [migrations.py:36-38](../../src/datarefinery/recipe/migrations.py#L36-L38)). The **flat→segmented bootstrap** is one special whole-recipe migration that distributes fields into segments **and injects the previously-implicit defaults explicitly** (see Q7) — this is the J.n.3 one-time event. After it, all migrations are per-segment.

**Rationale.** Per-segment versioning is the entire point of scoped invalidation; a global umbrella defeats it. Structural era-detection avoids minting a meta-counter. The bootstrap migration is where the one-time cost is paid, deliberately, pre-1.0.

**Downstream:** J.n.2 (version constants + registry skeleton), J.n.3 (bootstrap migration), J.n.7 (registry population).

---

## Q5 — Extensions namespace → **a single top-level `extensions:` block, namespaced by owner; plugins declare consumed keys; `extra="forbid"` relaxes only inside**

**Decision.**
- **One `extensions:` block**, shape `extensions: { <namespace>: { <key>: <value> } }` (namespace = the consuming plugin/owner). Chosen over scattered `x-*` keys: one place to find all experimental config, one subtree to hash, one clean validator surface.
- **`extra="forbid"` relaxes only inside `extensions.<namespace>`**; everywhere else stays strict.
- **Plugin extension-key declaration:** a plugin exposes `extension_keys() -> set[str]` (or `{namespace: set[str]}`). The validator refuses any `extensions` key not declared by an installed plugin, naming the unknown key.
- **Identity:** empty `extensions` → empty-segment marker (Q3) → contributes nothing, so the mechanism lands additively (breaks no existing cache).
- **Trust boundary (spike memo § 6, unchanged):** extensions carry **declarative parameters** read by installed code. Recipe-activated arbitrary code is OUT.

**Rationale.** Namespacing prevents cross-plugin key collisions and makes the consume-check precise. A single block keeps the segment boundary and validator surface clean.

**Downstream:** J.n.6 (extensions namespace + declaration), J.n.7 (empty-extensions isolation pin test).

---

## Q6 — Validator adaptation → **plugin-owned segment validation + formalize the `loader_stamped_fields` hook; collapse the Future reserved-set entry into the bundle**

**Decision.**
- **check_23's reserved set becomes the plugin-provided `loader_stamped_fields(recipe) -> set[str]` hook** (already forward-declared; scaffolded as a stub in J.o). check_23 calls `plugin.loader_stamped_fields(recipe)` instead of the hardcoded image set ([validator.py:1167-1180](../../src/datarefinery/recipe/validator.py#L1167-L1180)).
- **Plugin-name-gated checks (19/20/21) become plugin-segment-dispatched:** the plugin validates its own `plugin` segment via a `validate_plugin_segment(recipe) -> list[CheckResult]` hook; core checks stay in the shared validator. (Incremental: keep the name-gates working until each plugin grows its hook.)
- **YES, collapse the Future "plugin-pluggable validator reserved-set hook" entry into the bundle** (tracked under J.n.7's Future-entry-removal task) — the segmented model + plugin-owned validation subsumes it.

**Rationale.** The plugin already owns its op vocabulary; it should own its segment's validation and its loader-stamped-field set. This removes the hardcoded `image_classification` coupling that audio would otherwise have to special-case again.

**Downstream:** J.n.3/J.n.6 (validator made segment-aware + `loader_stamped_fields` formalized), J.n.7 (remove the Future entry).

---

## Q7 — No-implicit-defaults rollout → **drop `ParameterSpec.default`; plugin *recommends*, scaffolder *emits*, code *never substitutes*; bootstrap migration injects old defaults explicitly**

**Decision.**
- **Remove `default=` from `ParameterSpec`** ([base.py:22-30](../../src/datarefinery/plugins/base.py#L22-L30)); a param is either `required=True` or **mode-selecting optional** (`required=False`, absence is documented behavior, **no value substitution**). Classify the ~28 current defaults:
  - **default-value** (resize.method, color_jitter.\*, random_crop.padding/padding_mode, cast.scale, sample_grid.\*, pixel_distribution.bins, text/tabular ops, …) → become **required**; the scaffolder emits the recommended value.
  - **mode-selecting** (`normalize.mean`/`std` — absent ⇒ fit-from-train) → **keep** as no-value optionals; document the "absent ⇒ behavior" mapping in the plugin-segment contract.
- **Recommended values live in a plugin-provided `recommended_params(section, op) -> dict`**, read by the scaffolder. The plugin (domain owner) recommends; the scaffolder bakes the values into recipe text; the interpreting code supplies nothing. The scaffolder already emits explicit values ([init.py:134-204](../../src/datarefinery/scaffolder/init.py#L134-L204)), so this extends an existing pattern.
- **The flat→segmented bootstrap migration (Q4) injects each previously-defaulted param's old default value explicitly** into existing recipes, so they stay valid (no newly-"required" param goes missing) and their post-migration behavior is unchanged.
- **Regression guard:** a pin test fails CI if any `ParameterSpec` reintroduces a `default=` (J.n.4/J.n.7). **Collapse the Future "default-change discipline tooling" entry** into J.n.4 + J.n.7 (already planned).

**Rationale.** This is what makes canonical bytes equal "exactly what the author wrote," dissolves the project-essentials silent-default-shift nightmare, and (with sparse hashing) resolves Finding A. The verified ~28-default count + already-explicit scaffolder make the rollout bounded.

**Downstream:** J.n.4 (the rollout), J.n.3 (bootstrap injection), J.n.7 (regression pin test + Future-entry removal).

---

## Q8 — Vertical stage-reuse → **decline for this bundle; rely on existing `export`/`report`/partial-run primitives; keep `join_stable` prefix-capable (Q3) so it stays adoptable later**

**Decision.** **No** prefix-keyed stage caching in this bundle. DR's compute gradient is flat (spike memo § 4 "honest asymmetry") — the stage-artifact-store + materialization-control-flow overhaul is disproportionate. Existing `export` (re-run sinks), `report()` (re-render), and `stop_after`/partial runs already cover the practical downstream-iteration cases. **Q3's `join_stable` is prefix-capable by construction**, so a minimal cut (aggressive-aug realization / audio decode+window+featurize / normalize fit) can be added post-bundle *without* re-architecting if a concrete expensive workload demands it.

**Rationale.** Keeps the bundle focused on the horizontal axis (the actual Finding-A driver) and avoids permanent machinery DR's cost profile doesn't justify. The vertical axis stays ModelFoundry's (its 1,000-GPU-hour gradient earns it).

**Downstream:** J.n.7 stage-boundary pin tests are **skipped** (their "if Q8 adopted" guard is not met).

---

## Cross-tool family coordination (spike memo § 10; J.n.1 final task)

The **horizontal mechanism + no-implicit-defaults are the cross-tool-family standard**; ModelFoundry adopts them wholesale ([MF reciprocal spike](modelfoundry/phase-i-recipe-architecture-spike.md)). Decisions here that MF must mirror or knowingly diverge from before locking:
- **Q3 `join_stable` form** (concatenated digests, fixed empty marker, prefix-capable) — MF's vertical axis depends on the prefix capability; this form supplies it.
- **Q4 per-segment versioning + `(segment, from, to)` keying** — MF's per-segment + per-stage versioning extends this.
- **Q5 `extensions:` block shape + plugin-key declaration** — shared so a recipe author sees the same extension grammar across tools.
- **Q7 no-implicit-defaults + `recommended_params`/scaffolder-emits** — family policy.
- **Q1 segment set** — MF adds vertical *stage* segments atop the same horizontal four; confirm the horizontal four match.

**Action (developer / cross-repo, not executable from here):** pass this doc to the ModelFoundry repo for its `plan_phase`; reconcile any divergence on the five points above before either side locks. J.n.8 carries the DR-side doc sweep.

---

## What is settled vs. still-flexible

- **Settled by this doc** (J.n.2–J.n.8 build on it): the four-segment set + section-granular boundaries (Q1); overlays = ordered-multi override, resolved-hash (Q2); concatenated-digest `join_stable` (Q3); per-segment versioning, no umbrella (Q4); single namespaced `extensions:` block (Q5); plugin-owned validation + `loader_stamped_fields` (Q6); drop `ParameterSpec.default`, plugin-recommends/scaffolder-emits (Q7); vertical declined-but-not-precluded (Q8).
- **Deliberately left to implementation** (named in the owning stories, not forced here): exact `recommended_params` API surface; exact `validate_plugin_segment` signature; the precise YAML shape of the segment-version block; whether `overlays` selection is CLI-only or also recipe-pinned. These are mechanics, not architecture.

---

## Recommendation

Confirm Q1–Q8 as above (Q1 and Q7 are the load-bearing ones worth the closest read). On confirmation, this doc freezes and **J.n.2** (segment-aware hasher + shadow mode) begins. Cross-tool reconciliation on the five coordination points should happen before J.n.3's one-time invalidation lands.
