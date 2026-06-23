# Phase J · Subphase J-1 — audio acceptance-gate friction list (Story J.v)

**Status:** closed for the J-1 bundle. The J.v end-to-end acceptance gate
(`tests/integration/test_audio_classification.py`, AC1-AC9) was authored against
a synthetic 9-clip fixture (3 classes, varied durations, mixed source sample
rates, one unlabeled heldout partition) + the committed recipe
`tests/fixtures/recipes/audio_classification_v1.yaml`. Its dry run surfaced
**exactly two** latent gaps — both on the **unlabeled-partition path**, both
cross-cutting (image + audio), both latent because no prior recipe windowed /
featurized a heldout unlabeled partition. Per the developer's decision at the
J.v gate (2026-06-22), each was fixed in its own prerequisite story before the
gate landed.

The audio R1-R7 *happy path* (all-labeled, no unlabeled partition) materialized
end-to-end with **no** gaps — windowing (R3), log-mel (R4), fit-on-train
per-mel-bin normalization (R5), clip-level stratified splits (R6), and the
`source_record_id` grouping key (R7) all worked on first try. The friction was
confined to the unlabeled-partition interaction.

---

## F1 (fixed, Story J.v.1) — validator check 15 rejected source-partition-derived splits

**Expected.** A recipe with a pre-partitioned heldout `test` partition
(`Input.sources[*].partition: test`, Form B: `Splits.ratios {train, val}` +
`applies_to: train`) and ops declaring `splits: [train, val, test]` validates.

**Happened.** Check 15 (`split_references_defined`) flagged `test` as an
undefined split. `recipe.validator._defined_split_names` derived the defined-set
from `Splits.ratios` / `key_assignment` only, omitting source-partition names.

**Fix.** `_defined_split_names` now unions the non-None
`Input.sources[*].partition` names into the defined splits (benefiting checks 10
/ 25 too). Latent because `test_partitioned_inputs.py` splits records but runs no
op targeting the heldout partition.

---

## F2 (fixed, Story J.v.2) — Generation output-schema check required `label` on unlabeled records

**Expected.** Running a record-emitting Generation op (audio `window`) on an
unlabeled heldout partition materializes; those records carry no `label` (FR-22).

**Happened.** `pipeline.stages.generation._validate_against_output_schema`
required every `Output.record_schema` field on every record, so the unlabeled
`test` split failed with `missing required Output field(s) ['label']`.

**Fix.** `apply_generation` now takes the `unlabeled_splits` set (threaded from
the runner's `unlabeled_split_names(recipe)`) and exempts the recipe's
`Labels.field` from the requirement on unlabeled splits only; every other field
stays required, and labeled splits are unchanged.

---

## Authoring notes (not bugs)

- **`init` is image-only (documented v1 non-goal).** Audio recipes are
  hand-authored; the scaffolder refuses non-image plugins with an actionable
  `PluginError`. AC1 therefore exercises `validate → materialize → status`
  (the journey minus `init`) and separately asserts `init` declines audio.
- **In-pipeline array fields are declared in `Output.record_schema`.** The
  audio loader stamps `sample_array`; `log_mel_spectrogram` writes `mel`;
  `audio_normalize` writes `feature`. Per the image convention (`image` is
  declared even though pixel bytes resolve via `path`), the recipe declares
  `sample_array` in `record_schema` so ops referencing it pass check 7. `mel`
  and `feature` are upstream-featurization outputs (auto-recognized) and need no
  declaration. None of these arrays are serialized into the dataset JSONL.
- **"Broken decode params" → FAILED temp dir (AC9).** Decode failures surface
  *pre-temp-dir* at load (before the runner creates the atomic temp directory),
  so AC9 exercises the temp-then-promote FAILED path with a mid-pipeline failure
  instead (a window longer than every clip with `remainder: drop` → empty splits
  → `audio_normalize` fit-on-train sees an empty train split and raises). The
  run leaves a `FAILED`-marked temp directory and promotes no instance.

No open follow-ups for the J-1 bundle.
