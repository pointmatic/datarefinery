<!--
Copyright (c) 2026 Pointmatic
SPDX-License-Identifier: Apache-2.0
-->

# Story K.f — [Spike] Path-template grammar + shared cross-plugin resolver boundary

**Flavor:** architectural spike. **Deliverable:** a documented design decision (the
`layout` grammar, the `path_tree` resolver boundary, the `{split}`/`partition`
reconciliation, the field-rename refutation, the input-hash coupling). **No production
code.** De-risks FR-K-1 (Story K.h) and is the coupling point with FR-K-2 (Story K.g).

Grounded against current `main`: the image loader (`pipeline/inputs.py`
`_load_one_image_folder` / `_enumerate_flat_images` / `_hash_image_folder` /
`_iter_files`) and the audio loader (`plugins/audio_classification/inputs.py`, which
reimplements the identical one-level contract and carries the **same** symlink-blind
`rglob("*")` at lines 258 + 281 — the K.g housekeeping target).

---

## 1. The `layout` template grammar

A `*_tree` source declares a `layout` string that describes the directory structure from
the source `path` root down to each file. Roles + wildcards express arbitrary nesting, so
all of today's enumerated flavors (and the reported-but-unsupported ones) collapse to one
parametric form.

```yaml
Input:
  sources:
    - name: logos
      type: image_tree            # audio_tree for the audio plugin
      path: datasets/logos
      layout: "{split}/*/{label}/{file}"
```

**Decision — `layout` is a path-segment *matcher*, not a field *substituter*.** This is
the load-bearing distinction from the sink `path_template` grammar
([`pipeline/sinks/template.py`](../../src/datarefinery/pipeline/sinks/template.py)): the
sink grammar *substitutes record field values into an output path*; `layout`
*parses an existing directory tree to extract roles*. They share **surface syntax**
(`{name}` placeholders, recipe-author familiarity) but are **semantically inverse**. We
deliberately reuse the brace surface for author consistency and keep the implementations
separate (a new `recipe/layout.py` parser, not a reuse of `sinks/template.py`).

### Components (each binds exactly one path segment, except the wildcards)

| Token | Meaning | Cardinality |
|---|---|---|
| `{label}` | the segment whose name is the record's label (subsumes `Labels.source.derivation: parent_directory_name`) | **0 or 1** — exactly 1 for a path-labeled source; 0 when labels come from `label_from` or the source is `unlabeled` |
| `{split}` | the segment whose name is the split assignment (folds partitioning into the tree) | **0 or 1**; mutually exclusive with per-source `partition` (§ 4) |
| `{file}` | the terminal file component; matched against the plugin's file-extension set | **exactly 1, must be last** |
| `*` | exactly one path level, ignored ("category" level we do not bind) | any number |
| `**` | any depth (zero or more levels), ignored | **0 or 1**, and not adjacent to another `**` |

### Flavor crosswalk (all collapse to templates)

| Layout | Captures | Backward-compat note |
|---|---|---|
| `{label}/{file}` | today's strict `image_folder` / `audio_folder` (one class level) | **bare `image_folder` / `audio_folder` stay as sugar for exactly this** |
| `{file}` | flat directory (labels from `label_from` sidecar or `unlabeled`) | models today's `image_flat` / `audio_flat` |
| `**/{label}/{file}` | "label is the leaf dir at any depth" (covers `class/file` **and** `category/class/file`) | the reported Gap-1 taxonomy case |
| `{split}/*/{label}/{file}` | `split/category/class/file` in a single source | new — the second-form dataset |

**Decision — `record_id` derivation stays `f"{source_name}/{rel_posix}"`** where
`rel_posix = path.relative_to(root).as_posix()`. For the `{label}/{file}` sugar this is
**byte-identical** to today's `f"{source_name}/{cls}/{path.name}"` (the file sits directly
in the class dir, so `rel_posix == "{cls}/{file}"`), so **the bare-folder sugar produces
unchanged `record_id`s** — no shape-binding churn for existing recipes. Ignored `*` / `**`
levels remain part of `rel_posix` (and thus `record_id`), keeping ids unique and stable.

---

## 2. Static validation rules (FR-K-5, Story K.i)

These are *static* (no filesystem access) — they parse the `layout` string and the
source's label configuration. The filesystem-satisfiability check (a `{label}` level that
resolves to only further subdirectories) is the deferred-to-materialize gap FR-K-5 closes
*statically* where it can:

1. **Exactly one `{file}`, and it is the terminal component.** A layout without `{file}`,
   or with `{file}` not last, is rejected.
2. **At most one `{label}`.** Labeled-by-path sources need exactly one; sources using
   `label_from` or `unlabeled: true` must have **zero** `{label}` (a `{label}` + `label_from`
   combination is contradictory — two label sources — and is rejected, mirroring today's
   `image_folder` + `label_from` refusal).
3. **At most one `{split}`**, and `{split}` xor per-source `partition` (§ 4).
4. **At most one `**`**, not adjacent to another `**` (`**/**` is meaningless).
5. **Unknown tokens rejected.** Only `{label}` / `{split}` / `{file}` / `*` / `**` and
   literal segments are valid; `{foo}` is an error (closed vocabulary).
6. **Depth-satisfiability (best-effort static):** a layout whose fixed (non-`**`) depth
   cannot be satisfied by a well-formed tree is flagged with a message naming the nesting —
   the cheap static gate FR-K-5 adds, instead of deferring to `materialize`.

The existing `image_folder` + `label_from` / `image_flat`-without-`label_from` refusals
(current check 19) carry forward, re-expressed against `{label}` presence/absence.

---

## 3. The shared `path_tree` resolver boundary

```python
# pipeline/inputs.py (new shared helper)
def path_tree(
    root: Path,
    layout: str,
    *,
    extensions: frozenset[str],      # the plugin's file-extension set
    source_name: str,
) -> list[ResolvedFile]: ...

@dataclass(frozen=True)
class ResolvedFile:
    path: Path            # the matched file
    record_id: str        # f"{source_name}/{rel_posix}"
    label: str | None     # the {label} segment's name, or None
    split: str | None     # the {split} segment's name, or None
```

**Decision — the resolver is payload-agnostic; it returns `[(path, record_id, label?,
split?)]` and does NOT decode.** This refines the K.f plan checklist, which listed a
"plugin decode hook" as a resolver *input*: the spike moves decode **out** of the resolver.
The resolver deals only in `path` + `record_id` + roles; the **loader** maps over the
resolved files and applies the plugin's decode (`PIL.Image.open` → `image`;
`librosa.load` → `sample_array`) and payload-field naming *after* resolution. Rationale:
this is exactly what makes the field-rename refutation (§ 5) hold — the shared resolver
never touches the decoded payload field, so it stays modality-independent with no
`image`/`sample_array` knowledge. The plugin contributes only its **extension set** to the
resolver; the decode hook stays plugin-owned in the loader.

**How the loaders call it.** `_load_one_image_folder` / the audio folder loader become thin
adapters: `path_tree(root, layout, extensions=PLUGIN_EXTS, source_name=src.name)` → for
each `ResolvedFile`, decode `path` → build the record `{record_id, <payload>, path[,
label]}`, stamp `partition` if declared. Modality-prefixed type names (`image_tree` /
`audio_tree`) stay at the recipe surface for clarity; the resolver is shared underneath
(clarity on top, DRY beneath). Bare `image_folder` / `audio_folder` resolve to
`layout="{label}/{file}"` internally.

**Determinism.** `path_tree` returns results sorted by `rel_posix` (POSIX-form path
relative to `root`), so filesystem-walk order never leaks into record order or `record_id`
assignment — preserving the `by_row_order` join guarantee and byte-identical re-runs.

---

## 4. `{split}` vs per-source `InputSource.partition` precedence

**Decision — mutual exclusion; the template wins when present.**

- A source may declare **either** a `{split}` token in its `layout` **or** a
  `partition: <name>` field — **never both** (validator-rejected, FR-K-5 rule 3).
- `{split}` folds the split assignment *into the tree* (one source root spanning multiple
  splits, each in its own subtree). It is a strict superset of `partition` for the
  "splits live in subdirectories" case.
- `partition` is **retained** for the still-valid "separate roots per split" case (one
  source per split, each with its own `path` + `partition`), which `{split}` cannot express
  (different roots, not one tree).
- When `{split}` is present, the resolver returns each file's `split`, and `Splits`
  consumes it exactly as it consumes a per-source `partition` today (clip-level discipline,
  stratification, etc. are unchanged — `{split}` only changes *where the split label comes
  from*, not what `Splits` does with it).

---

## 5. Field-rename refutation (closed decision)

**Decision — `image` / `sample_array` (and `mel` / `feature`) stay plugin-owned; NO
`observation` / `sample` generalization. Closed, not deferred.**

The directory resolver touches only `path` + `record_id` + roles — never the decoded
payload field (§ 3) — so generalizing the field name buys the resolver *nothing*. The
per-record payload field name is a **shape-binding cross-repo surface** (the JSONL field
set binds ModelFoundry/NbFoundry; see `project-essentials.md` § "Recipe / manifest / report
shape changes"); renaming it would cost the full ceremony (schema bump + migration +
`vendor-dependency-spec.md` + deprecation horizon) for negative value — it *removes*
modality information and overloads a term (`sample` is already a PCM sample in audio and the
whole dataset in statistics). If ever revisited, prefer `observation` over `sample`. This
matches the phase plan § "Out of scope" (REFUTED) — the spike records *why*; it does not
reopen it.

---

## 6. Input-hash coupling (the K.g ↔ K.h seam)

**Decision — one shared enumeration helper; the input hash digests the *resolved* file
set, following symlinks, deterministically sorted.**

The root cause of Gap 2 is that the **loader and the hasher walk different file sets**
(`project-essentials.md` § "The loader and the input hasher must walk the *same* file
set"). The durable fix is structural, not a local patch:

- **One enumeration helper** underlies both the loader (`path_tree`) and the input hasher.
  After K.h, the hasher digests **exactly the files `path_tree` resolves** (layout-matched,
  extension-filtered, symlink-followed) — not a parallel `rglob` walk.
- **Symlink-following with cycle protection (K.g, lands first).** Because
  `recurse_symlinks=True` is unavailable on Python 3.12, the helper does an explicit walk
  (e.g. `os.walk(..., followlinks=True)` over the resolved root, or a manual stack that
  `resolve()`s each dir and dedupes on real-paths) so a symlinked-dir tree is no longer
  hashed as an empty set. Cycle protection dedupes on resolved real-paths.
- **Deterministic sort** by `rel_posix` (same key the resolver uses), so the digest is
  invariant to filesystem-walk order across machines/Python versions.
- **`label_from` manifests stay hashed separately** (as `_hash_image_flat` does today) —
  the resolved file set is the *data* files; the sidecar manifest is mixed in alongside.

**Cache-identity consequence (flag for K.g / K.h CHANGELOG).** Two changes perturb existing
input hashes — both **pre-prod-acceptable invalidations** (note in release notes, users
re-materialize):

1. **Symlink-following (K.g):** a symlinked-dir source that previously hashed to an
   (effectively empty) set now hashes its real content. This is the *correctness fix* — the
   old digest was wrong.
2. **Extension-filtering unification (K.h):** the hasher currently digests *all* regular
   files under root (`_iter_files`), while the loader reads only extension-matched files.
   Unifying on the resolved set means a stray non-data file (a `README`, a `.DS_Store`) no
   longer perturbs the hash. This tightens the fingerprint to *exactly the bytes consumed* —
   the intended contract — and changes the digest for any source that had such files.

New `layout` text adds to canonical recipe bytes (a `core`/`plugin`-segment surface) — also
pre-prod-acceptable.

---

## Sequencing note (carried to K.g / K.h)

K.g (FR-K-2, symlink fix) and K.h (FR-K-1, resolver + `*_tree` + `layout`) **land together
on the shared enumeration helper** — K.g introduces the helper with the symlink-following
walk + the failing-reproduction test; K.h builds `path_tree` on top of it and migrates both
plugins' loaders. Both ride the bundled `v0.25.0` (K.i owns the bump). This co-landing is
why the spike settles the resolver boundary *and* the hash coupling in one memo: they are
one design, split across two stories only for reviewable commit size.

---

## Deliverable summary

- `layout` grammar decided: `{label}` / `{split}` / `{file}` + `*` / `**`, a path-segment
  *matcher* (semantically inverse to the sink substituter), with the flavor crosswalk and
  the backward-compatible `record_id` rule (§ 1).
- Static validation rules specified for FR-K-5 (§ 2).
- `path_tree` resolver boundary decided — **payload-agnostic**, returns
  `[(path, record_id, label?, split?)]`, decode stays in the loader (§ 3, refines the plan).
- `{split}` xor `partition` precedence settled (§ 4).
- Field rename refuted as a closed decision (§ 5).
- Input-hash coupling settled: one shared enumeration, resolved-set hashing, symlink-follow,
  with the cache-invalidation flags for K.g/K.h (§ 6).

No production code. Next: **Story K.g** — the symlink-hash bugfix + the shared enumeration
helper (test-first), which K.h's resolver then builds on.
