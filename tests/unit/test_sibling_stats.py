# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story H.n.1 unit tests for the sibling-instance fitted-stats resolver.

Builds a synthetic cache directory tree under ``tmp_path`` with a real
sibling recipe YAML and a real ``fitted_statistics/<op_id>/`` directory
written via ``FittedStatistics``. Exercises the happy path plus the
three explicit failure modes (sibling-instance-not-found,
sibling-op-not-found, statistics-incompatible).
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pytest

from datarefinery.cache.identity import CacheKey
from datarefinery.cache.layout import (
    fitted_stats_dir,
    instance_dir,
    instances_root,
    manifest_path,
)
from datarefinery.cache.sibling_stats import (
    SiblingInstanceNotFoundError,
    SiblingOpNotFoundError,
    SiblingStatsIncompatibleError,
    resolve_sibling_stats,
)
from datarefinery.pipeline.fitted_stats import FittedStatistics
from datarefinery.pipeline.manifest import Manifest, write_manifest
from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.loader import load as load_recipe
from datarefinery.recipe.overlays import apply_overlays
from datarefinery.recipe.segments import recipe_identity_hash

_RECIPE_YAML = textwrap.dedent(
    """\
    schema_version: 1
    plugin: image_classification
    seed: 0
    Input:
      sources:
        - name: train
          type: image_folder
          path: /data/train
    Output:
      record_schema:
        image: {dtype: uint8, shape: [4, 4, 3]}
        label: {dtype: str}
    Labels:
      field: label
      source: {kind: direct}
    Splits:
      ratios: {train: 0.6, val: 0.2, test: 0.2}
      seed: 11
    Transformations:
      - name: norm
        op: normalize
        params: {}
        fit_source: train
        splits: [train, val, test]
    """
)


def _write_recipe(path: Path) -> Path:
    path.write_text(_RECIPE_YAML, encoding="utf-8")
    return path


def _recipe_hash(recipe_path: Path) -> str:
    recipe = load_recipe(recipe_path)
    return recipe_identity_hash(recipe)


def _build_promoted_instance(
    cache_root: Path,
    recipe_path: Path,
    *,
    op_id: str = "norm",
    vectors: dict[str, pa.Table] | None = None,
    created_at: datetime | None = None,
    input_hash: str = "a" * 64,
    seed: int = 7,
) -> Path:
    """Materialize a fake promoted instance under cache_root.

    Writes a manifest with the right recipe_hash (so the resolver finds
    it) and the requested fitted-statistics vectors under
    ``fitted_statistics/<op_id>/``.
    """
    recipe_hash = _recipe_hash(recipe_path)
    key = CacheKey(recipe_hash=recipe_hash, input_hash=input_hash, seed=seed)
    inst = instance_dir(cache_root, key)
    inst.mkdir(parents=True, exist_ok=True)

    write_manifest(
        manifest_path(inst),
        Manifest(
            datarefinery_version="0.0.0-test",
            plugin="image_classification",
            plugin_version="1",
            recipe_hash=recipe_hash,
            input_hash=input_hash,
            seed=seed,
            created_at=created_at or datetime(2026, 5, 22, tzinfo=UTC),
            elapsed_seconds=0.0,
            record_counts={"train": 1},
        ),
    )

    fs = FittedStatistics(fitted_stats_dir(inst))
    for name, table in (vectors or {}).items():
        fs.put_vector(op_id, name, table)

    return inst


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_resolver_returns_handle_for_matching_sibling(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    _build_promoted_instance(
        cache_root,
        recipe_path,
        vectors={
            "mean": pa.table({"value": [1.0, 2.0, 3.0]}),
            "std": pa.table({"value": [0.5, 0.6, 0.7]}),
        },
    )

    stats = resolve_sibling_stats(
        cache_root,
        recipe_path,
        "norm",
        required_vectors=("mean", "std"),
    )
    assert isinstance(stats, FittedStatistics)
    mean = stats.get_vector("norm", "mean")
    assert mean.to_pydict() == {"value": [1.0, 2.0, 3.0]}
    std = stats.get_vector("norm", "std")
    assert std.to_pydict() == {"value": [0.5, 0.6, 0.7]}


def test_resolver_picks_most_recent_when_multiple_instances_share_recipe(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    older = _build_promoted_instance(
        cache_root,
        recipe_path,
        vectors={"mean": pa.table({"value": [10.0]})},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        input_hash="a" * 64,
        seed=1,
    )
    newer = _build_promoted_instance(
        cache_root,
        recipe_path,
        vectors={"mean": pa.table({"value": [99.0]})},
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=30),
        input_hash="b" * 64,
        seed=2,
    )
    del older  # the resolver should pick `newer`

    stats = resolve_sibling_stats(cache_root, recipe_path, "norm", required_vectors=("mean",))
    assert stats.get_vector("norm", "mean").to_pydict() == {"value": [99.0]}
    # FittedStatistics points at the newer instance's fitted_statistics dir.
    assert str(stats.root).startswith(str(newer))


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_raises_sibling_instance_not_found_when_shard_missing(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    # No instance built — shard directory does not exist.
    with pytest.raises(SiblingInstanceNotFoundError, match="no promoted instance"):
        resolve_sibling_stats(cache_root, recipe_path, "norm")


def test_raises_sibling_instance_not_found_when_shard_empty(tmp_path: Path) -> None:
    """The shard directory exists but contains no valid instance manifest."""
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    shard = instances_root(cache_root) / _recipe_hash(recipe_path)[:16]
    shard.mkdir(parents=True)
    # A subdir without a manifest.json should be ignored.
    (shard / "deadbeefdeadbeef" / "7").mkdir(parents=True)
    with pytest.raises(SiblingInstanceNotFoundError, match="no promoted instance"):
        resolve_sibling_stats(cache_root, recipe_path, "norm")


def test_raises_sibling_op_not_found_when_op_id_missing(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    # Build an instance but DON'T write the "norm" op directory.
    _build_promoted_instance(cache_root, recipe_path, vectors={})
    with pytest.raises(SiblingOpNotFoundError, match="fitted_statistics/norm/"):
        resolve_sibling_stats(cache_root, recipe_path, "norm")


def test_raises_sibling_op_not_found_when_other_op_id_present(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    _build_promoted_instance(
        cache_root,
        recipe_path,
        op_id="other_op",
        vectors={"mean": pa.table({"value": [1.0]})},
    )
    with pytest.raises(SiblingOpNotFoundError):
        resolve_sibling_stats(cache_root, recipe_path, "norm")


def test_raises_stats_incompatible_when_required_vector_missing(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    # Op dir exists with only "mean"; we ask for "mean" + "std".
    _build_promoted_instance(cache_root, recipe_path, vectors={"mean": pa.table({"value": [1.0]})})
    with pytest.raises(SiblingStatsIncompatibleError, match="required vector 'std'"):
        resolve_sibling_stats(cache_root, recipe_path, "norm", required_vectors=("mean", "std"))


def test_raises_stats_incompatible_when_required_scalar_missing(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    _build_promoted_instance(cache_root, recipe_path, vectors={"mean": pa.table({"value": [1.0]})})
    with pytest.raises(SiblingStatsIncompatibleError, match="required scalar 'count'"):
        resolve_sibling_stats(cache_root, recipe_path, "norm", required_scalars=("count",))


def test_raises_stats_incompatible_when_parquet_unreadable(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    inst = _build_promoted_instance(
        cache_root, recipe_path, vectors={"mean": pa.table({"value": [1.0]})}
    )
    # Corrupt the mean.parquet so pyarrow's read fails.
    bad = fitted_stats_dir(inst) / "norm" / "mean.parquet"
    bad.write_bytes(b"not a parquet file")
    with pytest.raises(SiblingStatsIncompatibleError):
        resolve_sibling_stats(cache_root, recipe_path, "norm", required_vectors=("mean",))


# ---------------------------------------------------------------------------
# Loose-coupling invariant
# ---------------------------------------------------------------------------


def test_recipe_hash_lookup_is_independent_of_input_hash(tmp_path: Path) -> None:
    """The resolver locates instances by recipe_hash only; input_hash
    and seed vary across calls (matching the FR-ARCH-1 loose-coupling
    contract — the sibling's input identity does NOT enter into the
    consumer's lookup).
    """
    cache_root = tmp_path / "cache"
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    _build_promoted_instance(
        cache_root,
        recipe_path,
        vectors={"mean": pa.table({"value": [42.0]})},
        input_hash="c" * 64,
        seed=999,
    )
    stats = resolve_sibling_stats(cache_root, recipe_path, "norm", required_vectors=("mean",))
    assert stats.get_vector("norm", "mean").to_pydict() == {"value": [42.0]}


# ---------------------------------------------------------------------------
# G19: resolver must strip variants before hashing the sibling recipe
# ---------------------------------------------------------------------------


_RECIPE_YAML_WITH_VARIANTS = textwrap.dedent(
    """\
    schema_version: 1
    plugin: image_classification
    seed: 0
    Input:
      sources:
        - name: train
          type: image_folder
          path: /data/train
    Output:
      record_schema:
        image: {dtype: uint8, shape: [4, 4, 3]}
        label: {dtype: str}
    Labels:
      field: label
      source: {kind: direct}
    Splits:
      ratios: {train: 0.6, val: 0.2, test: 0.2}
      seed: 11
    Transformations:
      - name: norm
        op: normalize
        params: {}
        fit_source: train
        splits: [train, val, test]
    overlays:
      no_norm:
        Transformations: []
    """
)


def _recipe_hash_stripped(recipe_path: Path) -> str:
    """Canonical recipe hash with variants stripped, mirroring the
    materialize path at ``core/datarefinery.py:92-93``.
    """
    recipe = apply_overlays(load_recipe(recipe_path), None)
    return recipe_identity_hash(recipe)


def _build_promoted_instance_materialize_path(
    cache_root: Path,
    recipe_path: Path,
    *,
    op_id: str = "norm",
    vectors: dict[str, pa.Table] | None = None,
    input_hash: str = "a" * 64,
    seed: int = 7,
) -> Path:
    """Materialize a fake promoted instance under the materialize-time
    (variants-stripped) recipe hash, mirroring what the real materialize
    path produces. Used to reproduce G19.
    """
    recipe_hash = _recipe_hash_stripped(recipe_path)
    key = CacheKey(recipe_hash=recipe_hash, input_hash=input_hash, seed=seed)
    inst = instance_dir(cache_root, key)
    inst.mkdir(parents=True, exist_ok=True)

    write_manifest(
        manifest_path(inst),
        Manifest(
            datarefinery_version="0.0.0-test",
            plugin="image_classification",
            plugin_version="1",
            recipe_hash=recipe_hash,
            input_hash=input_hash,
            seed=seed,
            created_at=datetime(2026, 5, 22, tzinfo=UTC),
            elapsed_seconds=0.0,
            record_counts={"train": 1},
        ),
    )

    fs = FittedStatistics(fitted_stats_dir(inst))
    for name, table in (vectors or {}).items():
        fs.put_vector(op_id, name, table)

    return inst


def test_resolver_finds_instance_when_sibling_declares_variants(tmp_path: Path) -> None:
    """G19 reproduction: a sibling recipe declaring ``overlays:`` and a
    promoted instance written under the materialize-path (stripped)
    hash. The resolver must strip variants before hashing the sibling,
    matching the materialize path, or the shard lookup fails.
    """
    cache_root = tmp_path / "cache"
    recipe_path = tmp_path / "train_recipe_with_variants.yaml"
    recipe_path.write_text(_RECIPE_YAML_WITH_VARIANTS, encoding="utf-8")
    _build_promoted_instance_materialize_path(
        cache_root,
        recipe_path,
        vectors={"mean": pa.table({"value": [7.0, 8.0, 9.0]})},
    )

    stats = resolve_sibling_stats(
        cache_root,
        recipe_path,
        "norm",
        required_vectors=("mean",),
    )
    assert stats.get_vector("norm", "mean").to_pydict() == {"value": [7.0, 8.0, 9.0]}


def test_apply_overlays_none_preserves_canonical_hash_when_no_overlays_declared(
    tmp_path: Path,
) -> None:
    """No-variant regression for the G19 fix: a recipe with no declared
    variants must hash identically with or without the
    ``apply_overlays(..., None)`` strip. Guards against the fix silently
    invalidating sibling-stats lookups for existing recipes.
    """
    recipe_path = _write_recipe(tmp_path / "train_recipe.yaml")
    raw = load_recipe(recipe_path)
    stripped = apply_overlays(raw, None)
    assert to_canonical_bytes(raw) == to_canonical_bytes(stripped)
