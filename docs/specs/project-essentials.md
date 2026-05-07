<!--
This file captures project-specific must-know facts that future LLMs need to
avoid blunders on the DataRefinery project. Anything covered by the bundled
pyve-essentials artifact (auto-rendered into every `go.md` under
`## Project Essentials > ### Pyve Essentials`) is intentionally NOT duplicated
here. General engineering hygiene (e.g. logging discipline) lives in the
tech-spec, not here. Only project-specific gotchas belong below.

Heading convention: NO top-level `#` heading (the rendered `go.md` wrapper
provides `## Project Essentials`); use `###` for sibling sections.
-->

### File header conventions

Every new source file must begin with a copyright notice and license
identifier. Use the comment syntax for the file type:

| File type | Comment syntax |
|-----------|---------------|
| Python, YAML, shell, Makefile | `#` |
| JavaScript, TypeScript, Go, Java, C/C++ | `//` or `/* */` |
| HTML, Svelte, XML | `<!-- -->` |
| CSS, SCSS | `/* */` |

**This project's header:**

- **Copyright**: `Copyright (c) 2026 Pointmatic`
- **SPDX identifier**: `SPDX-License-Identifier: Apache-2.0`

Python example:
```python
# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
```

YAML / shell example:
```yaml
# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
```

Markdown documents under `docs/` are not source files in this rule's sense
and do not carry copyright headers; the project `LICENSE` file at the repo
root is authoritative.

### Cache identity is the reproducibility contract — invalidations are ceremonious

DataRefinery's cache key is `SHA-256(canonical_recipe_bytes) ⊕ SHA-256(raw_input_bytes) ⊕ seed`. Cache directory paths use the **first 16 hex characters** of each hash; the **full hash** is recorded in `manifest.json`. Truncation is intentional — it keeps paths short and human-quotable while the full hash stays available for audit. Do not "fix" the truncation; doing so would change every cache path and orphan every existing instance on every developer's disk.

The canonical form is produced by `pydantic_model.model_dump(mode="json")` followed by `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. **This means every pydantic field default is part of the canonical bytes.** A field default change — even one that "looks like a no-op refactor" — silently shifts the canonical hash for every recipe that omits the field, invalidating every cached instance for every user.

**Pre-production rules** (current state per features.md): cache invalidation across DataRefinery versions is acceptable. Note the change in the release notes; users re-materialize.

**Post-production rules** (after the production-release event): any change that invalidates the cache is a **ceremonious event**, not a silent or subtle one. The blast radius is real — every existing user must re-run every recipe over every input, recomputing every materialized instance. That is potentially hours-to-days of compute per user, multiplied across every user. Therefore, every cache-invalidating change MUST:

1. **Bump `schema_version`** in `recipe/loader.py` (`SUPPORTED_SCHEMA_VERSIONS`).
2. **Ship a documented migration** in `recipe.loader.migrations` keyed by `(from_version, to_version)`, or — if no migration is possible — explicit refusal-with-pointer guidance in the loader.
3. **Announce the blast radius prominently** in release notes and in the upgrade-time CLI output: name the operation that changed, state that all existing instances are now stale, and document the recompute cost (rough order of magnitude).
4. **Be reviewed deliberately.** A unit test pins the canonical hash of a representative fixture recipe; bumping that pinned value requires a reviewer to consciously sign off on the invalidation.

This applies equally whether the trigger is a pydantic default change, a canonical-form algorithm change, an operation-implementation change that affects output bytes, or anything else that perturbs the cache identity or the bytes the cache stores. **No silent invalidations after production release.**

**How to apply:** before merging any change in `recipe/`, `cache/`, or `pipeline/` (post-prod), ask "could this affect the canonical bytes or the materialized output bytes?" If yes, run the canonical-hash pinning test and check whether it would need to change. If it would, the change is cache-invalidating and must follow the ceremony above.

### Recipe is authoritative for data-pipeline semantics

Configuration precedence in DataRefinery is **recipe → CLI flags → environment variables**, with a hard separation of concerns:

- **Recipe** is the single source of truth for *what the pipeline does* — sections, operations, parameters, splits, seeds, contracts.
- **CLI flags and env vars** control only *execution context* — `--cache-root`, `--log-level`, `--log-target`, `--plugin-path`, `--workers`. They never alter data-pipeline semantics.

**The only sanctioned CLI-overrides-recipe surface is `--seed`.** This is the documented ad-hoc-run case: a user wants to try the same pipeline with a different random seed without editing the recipe. The override changes the cache identity (so a different instance is produced), preserving the reproducibility contract.

**Why:** the recipe is the artifact users hand off, check into version control, and read six months later to understand what was done. If CLI flags could silently override pipeline semantics, the recipe would no longer be the source of truth — handoff would degrade back to "the recipe and the magic command-line incantation," which is the notebook-era problem DataRefinery exists to fix.

**How to apply:** when adding a new feature that has a "switch" or "toggle" character, route it through the recipe as a section field or a variant — not as a CLI flag or env var. Tempting LLM mistakes to refuse:

- "Let's add `--no-augment` so users can quickly disable augmentation." **No.** Augmentation policy lives in the recipe; the variant pattern (`Augmentations: []` under a named variant) covers this case explicitly. Users select the variant via `--variant no_augment`, which is execution-context selection, not recipe override.
- "Let's add `--cache-root-override` that supersedes a recipe-declared cache root." **N/A** — the recipe doesn't declare cache root; it's already execution-context.
- "Let's add `--operation-skip OP_NAME` for fast iteration." **No.** That's pipeline semantics. Use a variant or edit the recipe.

If a proposed CLI flag's effect would change the canonical bytes of the recipe, it is by definition a recipe-semantic flag and must be expressed in the recipe instead.

### Determinism contract in `pipeline.workers`

When `--workers > 1` (opt-in process pool), per-record operations are scheduled across workers via `concurrent.futures.ProcessPoolExecutor`. The determinism contract has two parts:

1. **Per-record seeding.** Each record's seed is derived as `sha256(global_seed.to_bytes(8, 'big') + record_id_bytes).digest()[:8]` decoded as a 64-bit int. Worker scheduling does not affect which seed each record receives, because the seed depends only on `(global_seed, record_id)` — not on which worker picks it up or in what order.
2. **Reorder by `record_id` before downstream stages.** `run_parallel(...)` collects worker outputs and sorts them by `record_id` before yielding. This ensures the iteration order presented to downstream stages is identical regardless of how many workers ran or how the OS scheduled them.

**Why:** the reproducibility guarantee in features.md is byte-identical re-runs. If worker output order leaked into downstream stages, two runs of the same recipe with the same seed and the same input could produce different materialized bytes whenever process scheduling differed — which is essentially every run on a different machine, or under different system load.

**How to apply:** any change to `pipeline/workers.py` or to call sites that iterate worker output must preserve both invariants. Tempting LLM mistakes to refuse:

- "Let's stream results as workers complete to reduce latency." **No** — that breaks the reorder-by-record-id invariant. If latency is a real concern, raise it with the developer; the fix is not to weaken the determinism contract.
- "Let's seed per-worker rather than per-record, since per-record seeding is wasteful." **No** — per-record seeding is what makes worker-count irrelevant to output. Per-worker seeding makes the output depend on the number of workers, which is exactly what we are guarding against.
- "Let's use the `as_completed` iteration pattern for `Future` objects." **Only if** the results are immediately reordered by `record_id` before crossing a stage boundary. The pattern is fine internally; the contract is at the boundary.

The integration test suite includes a determinism check that runs the same fixture pipeline with `workers=1`, `workers=2`, and `workers=4`, asserting all three produce byte-identical instances. Any change to `pipeline/workers.py` must keep that test green; if it cannot, the change is a determinism regression and must be reverted or escalated.
