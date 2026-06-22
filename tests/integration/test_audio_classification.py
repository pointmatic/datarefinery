# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.v — audio-classification end-to-end acceptance gate (AC1-AC9).

Exercises the full R1-R7 audio path against a synthetic 9-clip fixture (3
classes, varied durations, mixed source sample rates, one unlabeled heldout
partition) and the committed recipe
`tests/fixtures/recipes/audio_classification_v1.yaml`. This is the integration
gate that catches inter-story gaps before the Subphase J-1 phase-bundle release;
its dry run surfaced (and J.v.1 + J.v.2 fixed) two latent unlabeled-partition
validator/runtime gaps — see `docs/specs/phase-j-subphase-1-audio-friction.md`.

Requires the `[audio]` extra (librosa); skips without it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

pytest.importorskip("librosa")
pytest.importorskip("soundfile")

from tests.fixtures.build_audio_fixture import build_audio_fixture, fixture_summary
from typer.testing import CliRunner

from datarefinery import DataRefinery
from datarefinery.cache.atomic import FAILED_MARKER
from datarefinery.cache.layout import (
    TMP_DIR_NAME,
    dataset_dir,
    fitted_stats_dir,
    instances_root,
)
from datarefinery.cli.app import app
from datarefinery.core.config import RuntimeConfig
from datarefinery.core.errors import MaterializeError, PluginError
from datarefinery.plugins.discovery import discover_plugins
from datarefinery.recipe.loader import load as load_recipe
from datarefinery.recipe.overlays import apply_overlays
from datarefinery.recipe.segments import recipe_identity_hash
from datarefinery.scaffolder.init import scaffold

cli = CliRunner()

_RECIPE_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "recipes" / "audio_classification_v1.yaml"
)


def _concrete_recipe(tmp_path: Path) -> tuple[Path, Path]:
    """Build the audio fixture and write a recipe with its paths injected.

    Returns ``(recipe_path, fixture_root)``. Path injection is test-harness
    wiring (the fixture lives in a temp dir), not a pipeline workaround — the
    committed recipe shape is used verbatim apart from the two source paths.
    """
    root = build_audio_fixture(tmp_path / "audio")
    raw = yaml.safe_load(_RECIPE_FIXTURE.read_text(encoding="utf-8"))
    raw["Input"]["sources"][0]["path"] = str(root / "train")
    raw["Input"]["sources"][1]["path"] = str(root / "test")
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return recipe_path, root


def _materialize(recipe_path: Path, cache: Path, *, workers: int = 1) -> Any:
    dr = DataRefinery.from_recipe(
        recipe_path, config=RuntimeConfig(cache_root=cache, workers=workers)
    )
    instance = dr.materialize()
    return dr, instance


def _split_clip_ids(instance_dir: Path, split: str) -> set[str]:
    path = dataset_dir(instance_dir) / f"{split}.jsonl"
    if not path.exists():
        return set()
    return {
        json.loads(line)["source_record_id"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    }


def _promoted_instances(cache: Path) -> list[Path]:
    iroot = instances_root(cache)
    if not iroot.is_dir():
        return []
    return [
        seed_dir
        for shard in iroot.iterdir()
        if shard.is_dir() and shard.name != TMP_DIR_NAME and not shard.name.startswith(".")
        for input_shard in shard.iterdir()
        if input_shard.is_dir()
        for seed_dir in input_shard.iterdir()
        if seed_dir.is_dir()
    ]


# --------------------------------------------------------------------------- #
# AC1 — documented journey (validate → materialize → status) + init non-goal
# --------------------------------------------------------------------------- #


def test_ac1_validate_materialize_status_no_workarounds(tmp_path: Path) -> None:
    recipe_path, _ = _concrete_recipe(tmp_path)
    cache = tmp_path / "cache"

    validate = cli.invoke(app, ["validate", str(recipe_path)])
    assert validate.exit_code == 0, validate.stdout
    assert "passed" in validate.stdout

    materialize = cli.invoke(app, ["--cache-root", str(cache), "materialize", str(recipe_path)])
    assert materialize.exit_code == 0, materialize.stdout
    assert "miss" in materialize.stdout

    assert len(_promoted_instances(cache)) == 1

    status = cli.invoke(app, ["--cache-root", str(cache), "status", str(recipe_path)])
    assert status.exit_code == 0, status.stdout
    assert "hit" in status.stdout
    assert "audio_classification" in status.stdout


def test_ac1_init_declines_audio_category(tmp_path: Path) -> None:
    # `init` is image-only in v1 (documented non-goal); audio recipes are
    # hand-authored. The scaffolder refuses non-image plugins cleanly.
    with pytest.raises(PluginError, match="not available for this category"):
        scaffold(tmp_path, tmp_path / "out.yaml", plugin="audio_classification")


# --------------------------------------------------------------------------- #
# AC2 — byte-identical re-run (excluding created_at / elapsed_seconds)
# --------------------------------------------------------------------------- #


def test_ac2_byte_identical_across_independent_runs(tmp_path: Path) -> None:
    recipe_path, _ = _concrete_recipe(tmp_path)
    _, inst_a = _materialize(recipe_path, tmp_path / "cache_a")
    _, inst_b = _materialize(recipe_path, tmp_path / "cache_b")
    a, b = inst_a.path, inst_b.path

    # recipe.json + every dataset jsonl + fitted parquet are byte-identical;
    # manifest.json is excluded (carries created_at / elapsed_seconds).
    for rel in ["recipe.json"]:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel
    for split in ("train", "val", "test"):
        name = f"{split}.jsonl"
        assert (dataset_dir(a) / name).read_bytes() == (dataset_dir(b) / name).read_bytes(), name
    for stat in ("mean.parquet", "std.parquet"):
        pa = fitted_stats_dir(a) / "norm" / stat
        pb = fitted_stats_dir(b) / "norm" / stat
        assert pa.read_bytes() == pb.read_bytes(), stat


# --------------------------------------------------------------------------- #
# AC3 — cosmetic edit → cache hit; semantic edit → cache miss
# --------------------------------------------------------------------------- #


def test_ac3_cosmetic_hit_semantic_miss(tmp_path: Path) -> None:
    recipe_path, _ = _concrete_recipe(tmp_path)
    base_hash = recipe_identity_hash(apply_overlays(load_recipe(recipe_path), None))

    # Cosmetic edit: append a comment + blank lines (whitespace/comments are not
    # canonical bytes) → identical hash.
    cosmetic = tmp_path / "cosmetic.yaml"
    cosmetic.write_text(
        recipe_path.read_text(encoding="utf-8") + "\n# a trailing comment\n\n", encoding="utf-8"
    )
    assert recipe_identity_hash(apply_overlays(load_recipe(cosmetic), None)) == base_hash

    # Semantic edit: change the window length → different hash (cache miss).
    raw = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    raw["Generation"][0]["params"]["window_length_samples"] = 800
    semantic = tmp_path / "semantic.yaml"
    semantic.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    assert recipe_identity_hash(apply_overlays(load_recipe(semantic), None)) != base_hash

    # And the hit/miss shows through the runtime cache-hit signal.
    cache = tmp_path / "cache"
    dr1, _ = _materialize(recipe_path, cache)
    assert dr1.last_run is not None and dr1.last_run.cache_hit is False
    dr2 = DataRefinery.from_recipe(cosmetic, config=RuntimeConfig(cache_root=cache))
    dr2.materialize()
    # cosmetic edit resolves to the same instance
    assert dr2.last_run is not None and dr2.last_run.cache_hit is True


# --------------------------------------------------------------------------- #
# AC4 — window determinism across worker counts
# --------------------------------------------------------------------------- #


def test_ac4_byte_identical_across_worker_counts(tmp_path: Path) -> None:
    recipe_path, _ = _concrete_recipe(tmp_path)
    _, inst1 = _materialize(recipe_path, tmp_path / "w1", workers=1)
    _, inst2 = _materialize(recipe_path, tmp_path / "w2", workers=2)
    for split in ("train", "val", "test"):
        name = f"{split}.jsonl"
        assert (dataset_dir(inst1.path) / name).read_bytes() == (
            dataset_dir(inst2.path) / name
        ).read_bytes(), name


# --------------------------------------------------------------------------- #
# AC5 — featurization is one-output-per-input (no record-count change)
# --------------------------------------------------------------------------- #


def test_ac5_featurization_preserves_record_count(tmp_path: Path) -> None:
    recipe_path, _ = _concrete_recipe(tmp_path)
    dr = DataRefinery.from_recipe(recipe_path, config=RuntimeConfig(cache_root=tmp_path / "c"))
    # Stop just after Generation (windowing) — count windows before featurization.
    post_gen = dr.materialize(stop_after="Generation")
    gen_total = sum(post_gen.manifest.record_counts.values())
    # Full run: featurization (log_mel + audio_normalize) must not change the count.
    _, full = _materialize(recipe_path, tmp_path / "c2")
    assert sum(full.manifest.record_counts.values()) == gen_total
    assert gen_total > 0


# --------------------------------------------------------------------------- #
# AC6 — stats_from_instance round-trip with a sibling eval recipe
# --------------------------------------------------------------------------- #


def test_ac6_stats_from_instance_sibling_round_trip(tmp_path: Path) -> None:
    recipe_path, _ = _concrete_recipe(tmp_path)
    cache = tmp_path / "cache"
    _materialize(recipe_path, cache)  # the "train" instance carrying norm stats

    # Sibling eval recipe: import the train instance's audio_normalize stats
    # instead of re-fitting (fit_source dropped; stats_from_instance set).
    raw = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    norm = next(f for f in raw["Featurizations"] if f["op"] == "audio_normalize")
    norm.pop("fit_source", None)
    norm["params"] = {"stats_from_instance": {"recipe": str(recipe_path), "op_id": "norm"}}
    eval_path = tmp_path / "eval.yaml"
    eval_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    _, eval_inst = _materialize(eval_path, cache)
    # Read-through: the consumer instance did not persist its own norm stats
    # (it read them from the sibling).
    assert not (fitted_stats_dir(eval_inst.path) / "norm").exists()


# --------------------------------------------------------------------------- #
# AC7 — stratified splits keep every clip's windows in exactly one split
# --------------------------------------------------------------------------- #


def test_ac7_clip_windows_stay_in_one_split(tmp_path: Path) -> None:
    recipe_path, _ = _concrete_recipe(tmp_path)
    _, inst = _materialize(recipe_path, tmp_path / "cache")
    splits = {sp: _split_clip_ids(inst.path, sp) for sp in ("train", "val", "test")}
    names = [s for s in splits.values() if s]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            assert names[i].isdisjoint(names[j]), f"clip in two splits: {names[i] & names[j]}"
    # Labeled clips fully covered across train+val; test is the heldout partition.
    summary = fixture_summary()
    assert len(splits["train"] | splits["val"]) == summary["n_labeled_clips"]
    assert len(splits["test"]) == summary["n_unlabeled_clips"]


# --------------------------------------------------------------------------- #
# AC8 — plugin-contract sanity (discovery + op set)
# --------------------------------------------------------------------------- #


def test_ac8_plugin_contract(tmp_path: Path) -> None:
    plugins = discover_plugins()
    assert "audio_classification" in plugins
    plugin = plugins["audio_classification"]
    assert plugin.is_stub() is False
    assert {"window", "log_mel_spectrogram", "audio_normalize"}.issubset(
        set(plugin.supported_operations)
    )


# --------------------------------------------------------------------------- #
# AC9 — failure path leaves a FAILED temp dir and no partial cached instance
# --------------------------------------------------------------------------- #


def test_ac9_failure_leaves_failed_temp_and_no_instance(tmp_path: Path) -> None:
    recipe_path, _ = _concrete_recipe(tmp_path)
    # Break the run mid-pipeline: a window longer than every clip with
    # remainder=drop yields zero windows on every split → audio_normalize's
    # fit-on-train sees an empty train split and raises. (Decode failures
    # surface pre-temp-dir at load; this exercises the temp-then-promote
    # FAILED path inside the runner.)
    raw = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    raw["Generation"][0]["params"]["window_length_samples"] = 10_000_000
    broken = tmp_path / "broken.yaml"
    broken.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    cache = tmp_path / "cache"
    with pytest.raises(MaterializeError):
        _materialize(broken, cache)

    # No instance was promoted, and a FAILED-marked temp dir remains for diagnosis.
    assert _promoted_instances(cache) == []
    tmp_root = instances_root(cache) / TMP_DIR_NAME
    failed_markers = list(tmp_root.glob(f"*/{FAILED_MARKER}")) if tmp_root.is_dir() else []
    assert failed_markers, "expected a FAILED marker in the temp directory"


# --------------------------------------------------------------------------- #
# Fixture sanity
# --------------------------------------------------------------------------- #


def test_fixture_has_nine_clips(tmp_path: Path) -> None:
    _, root = _concrete_recipe(tmp_path)
    wavs = list(root.rglob("*.wav"))
    assert len(wavs) == 9
    labeled = list((root / "train").rglob("*.wav"))
    unlabeled = list((root / "test").glob("*.wav"))
    assert len(labeled) == 6
    assert len(unlabeled) == 3
