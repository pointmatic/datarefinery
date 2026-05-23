# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-VIZ-2 ``augmented_sample_grid`` tests (Story H.u).

Renders an ``n_base x n_variants`` grid per declared ``Augmentations`` op:

* Aggressive-mode ops: the variants are already in the materialized
  train split (carrying ``source_record_id`` + ``variant_index``); the
  viz groups records, picks the first ``n_base`` groups in
  ``source_record_id`` order, and takes the first ``n_variants`` per
  group.
* Lazy-mode ops: the train split is unaugmented. The viz picks the
  first ``n_base`` records and realizes ``n_variants`` variants inline
  via the plugin's realizer registry, seeded by
  ``per_record_variant_seed`` against the recipe seed XOR-mixed with
  any explicit ``viz.seed`` param.

One PNG per declared augmentation op, persisted as
``<viz_op.name>_<aug_op.name>.png`` via the H.t multi-PNG protocol.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from datarefinery.pipeline.stages.visualizations import (
    apply_reporting_visualizations,
)
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.image_classification.visualizations.augmented_sample_grid import (
    AugmentedSampleGridOp,
    AugmentedSampleGridParams,
    build_augmented_sample_grid_figure,
    realize_lazy_grid,
    select_aggressive_grid,
)
from datarefinery.recipe.models import (
    AugmentationOp,
    FieldSpec,
    InputSection,
    InputSource,
    LabelSource,
    LabelsSection,
    OutputSection,
    Recipe,
    SplitsSection,
    VisualizationOp,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _img(value: int = 0) -> np.ndarray:
    return np.full((8, 8, 3), value, dtype=np.uint8)


def _aggressive_record(source_rid: str, vi: int, value: int) -> dict[str, Any]:
    return {
        "record_id": f"{source_rid}__v{vi:03d}",
        "source_record_id": source_rid,
        "variant_index": vi,
        "image": _img(value),
        "label": "cat",
    }


def _base_record(rid: str, value: int) -> dict[str, Any]:
    return {"record_id": rid, "image": _img(value), "label": "cat"}


def _recipe(*, augmentations: list[AugmentationOp], seed: int = 7) -> Recipe:
    """Build a minimal Recipe carrying the Augmentations under test."""
    return Recipe(
        schema_version=1,
        plugin="image_classification",
        seed=seed,
        Input=InputSection(sources=[InputSource(name="src", type="image_folder", path=Path("."))]),
        Output=OutputSection(record_schema={"image": FieldSpec(dtype="uint8")}),
        Labels=LabelsSection(field="label", source=LabelSource()),
        Splits=SplitsSection(),
        Augmentations=augmentations,
    )


def _viz(name: str, **params: Any) -> VisualizationOp:
    return VisualizationOp(
        name=name,
        op="augmented_sample_grid",
        params=params,
        stage="post_pipeline",
        mode="reporting",
    )


def _is_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


# ---------------------------------------------------------------------------
# AugmentedSampleGridParams
# ---------------------------------------------------------------------------


def test_params_requires_positive_n_base() -> None:
    with pytest.raises(ValidationError):
        AugmentedSampleGridParams(n_base=0, n_variants=2)
    with pytest.raises(ValidationError):
        AugmentedSampleGridParams(n_base=-1, n_variants=2)


def test_params_requires_positive_n_variants() -> None:
    with pytest.raises(ValidationError):
        AugmentedSampleGridParams(n_base=2, n_variants=0)


def test_params_defaults_seed_to_none() -> None:
    p = AugmentedSampleGridParams(n_base=3, n_variants=2)
    assert p.seed is None


def test_params_accepts_seed_int() -> None:
    p = AugmentedSampleGridParams(n_base=3, n_variants=2, seed=123)
    assert p.seed == 123


# ---------------------------------------------------------------------------
# select_aggressive_grid: groups + truncates by source_record_id / variant_index
# ---------------------------------------------------------------------------


def test_select_aggressive_picks_first_n_base_groups_in_id_order() -> None:
    records = [
        _aggressive_record("c", 0, 30),
        _aggressive_record("a", 0, 10),
        _aggressive_record("b", 1, 21),
        _aggressive_record("a", 1, 11),
        _aggressive_record("b", 0, 20),
        _aggressive_record("c", 1, 31),
    ]
    grid = select_aggressive_grid(records, n_base=2, n_variants=2)
    assert [row[0]["source_record_id"] for row in grid] == ["a", "b"]
    for row in grid:
        assert [r["variant_index"] for r in row] == [0, 1]


def test_select_aggressive_truncates_n_variants() -> None:
    records = [_aggressive_record("a", vi, 10 + vi) for vi in range(4)] + [
        _aggressive_record("b", vi, 20 + vi) for vi in range(4)
    ]
    grid = select_aggressive_grid(records, n_base=2, n_variants=2)
    for row in grid:
        assert [r["variant_index"] for r in row] == [0, 1]


def test_select_aggressive_raises_when_group_has_fewer_variants() -> None:
    records = [
        _aggressive_record("a", 0, 10),
        _aggressive_record("a", 1, 11),
        _aggressive_record("b", 0, 20),  # only 1 variant for b
    ]
    with pytest.raises(ValueError, match="fewer than n_variants=2"):
        select_aggressive_grid(records, n_base=2, n_variants=2)


def test_select_aggressive_raises_when_too_few_base_groups() -> None:
    records = [_aggressive_record("a", 0, 10), _aggressive_record("a", 1, 11)]
    with pytest.raises(ValueError, match="fewer than n_base=2"):
        select_aggressive_grid(records, n_base=2, n_variants=2)


# ---------------------------------------------------------------------------
# realize_lazy_grid: calls realizer n_base x n_variants times, deterministic
# ---------------------------------------------------------------------------


def test_realize_lazy_grid_produces_n_base_rows_of_n_variants() -> None:
    records = [_base_record(f"r{i}", 10 + i) for i in range(5)]
    aug = AugmentationOp(
        name="flip",
        op="horizontal_flip",
        params={"p": 1.0},  # always flip — output is deterministic
        splits=["train"],
        seed=None,
    )
    grid = realize_lazy_grid(
        records,
        aug=aug,
        realizer=IMAGE_PLUGIN.augmentation_realizers["horizontal_flip"],
        n_base=3,
        n_variants=2,
        global_seed=42,
    )
    assert len(grid) == 3
    for row in grid:
        assert len(row) == 2


def test_realize_lazy_grid_is_deterministic_for_same_seed() -> None:
    records = [_base_record(f"r{i}", 10 + i) for i in range(3)]
    aug = AugmentationOp(
        name="flip",
        op="horizontal_flip",
        params={"p": 0.5},
        splits=["train"],
        seed=None,
    )
    realizer = IMAGE_PLUGIN.augmentation_realizers["horizontal_flip"]
    a = realize_lazy_grid(
        records, aug=aug, realizer=realizer, n_base=2, n_variants=2, global_seed=42
    )
    b = realize_lazy_grid(
        records, aug=aug, realizer=realizer, n_base=2, n_variants=2, global_seed=42
    )
    for row_a, row_b in zip(a, b, strict=True):
        for ra, rb in zip(row_a, row_b, strict=True):
            assert np.array_equal(np.asarray(ra["image"]), np.asarray(rb["image"]))


def test_realize_lazy_grid_raises_when_too_few_base_records() -> None:
    records = [_base_record("r0", 10)]
    aug = AugmentationOp(name="flip", op="horizontal_flip", params={}, splits=["train"], seed=None)
    realizer = IMAGE_PLUGIN.augmentation_realizers["horizontal_flip"]
    with pytest.raises(ValueError, match="fewer than n_base=2"):
        realize_lazy_grid(
            records, aug=aug, realizer=realizer, n_base=2, n_variants=2, global_seed=42
        )


# ---------------------------------------------------------------------------
# build_augmented_sample_grid_figure: n_base x n_variants subplots
# ---------------------------------------------------------------------------


def test_figure_subplot_count_matches_grid_shape() -> None:
    grid = [
        [_base_record("a", 10), _base_record("a_v1", 11)],
        [_base_record("b", 20), _base_record("b_v1", 21)],
        [_base_record("c", 30), _base_record("c_v1", 31)],
    ]
    fig = build_augmented_sample_grid_figure(grid, title="flip")
    assert len(fig.axes) == 3 * 2


# ---------------------------------------------------------------------------
# AugmentedSampleGridOp.render: integration via the handle
# ---------------------------------------------------------------------------


def test_render_emits_one_png_per_aug_op() -> None:
    aggressive_records: list[Mapping[str, Any]] = [
        _aggressive_record(src, vi, 10 * i + vi)
        for i, src in enumerate(["a", "b", "c"], start=1)
        for vi in range(2)
    ]
    recipe = _recipe(
        augmentations=[
            AugmentationOp(
                name="flip",
                op="horizontal_flip",
                params={"p": 0.5},
                splits=["train"],
                materialization="aggressive",
                expansion=2,
            ),
        ],
    )
    handle = AugmentedSampleGridOp()
    out = handle.render(
        {"train": aggressive_records},
        {"n_base": 2, "n_variants": 2},
        label_field="label",
        recipe=recipe,
    )
    assert isinstance(out, Mapping)
    assert set(out.keys()) == {"flip"}
    assert _is_png(out["flip"])


def test_render_returns_empty_mapping_when_no_augmentations() -> None:
    recipe = _recipe(augmentations=[])
    handle = AugmentedSampleGridOp()
    train: list[Mapping[str, Any]] = [_base_record("a", 10), _base_record("b", 20)]
    out = handle.render(
        {"train": train},
        {"n_base": 2, "n_variants": 2},
        label_field="label",
        recipe=recipe,
    )
    assert out == {}


def test_render_raises_when_recipe_is_none() -> None:
    handle = AugmentedSampleGridOp()
    train: list[Mapping[str, Any]] = [_base_record("a", 10)]
    with pytest.raises(ValueError, match="recipe context"):
        handle.render(
            {"train": train},
            {"n_base": 1, "n_variants": 1},
            label_field="label",
            recipe=None,
        )


def test_render_handles_lazy_and_aggressive_in_same_recipe() -> None:
    aggressive_records: list[Mapping[str, Any]] = [
        _aggressive_record(src, vi, 1) for src in ["x", "y"] for vi in range(2)
    ]
    recipe = _recipe(
        augmentations=[
            AugmentationOp(
                name="aggr_flip",
                op="horizontal_flip",
                params={"p": 0.5},
                splits=["train"],
                materialization="aggressive",
                expansion=2,
            ),
            AugmentationOp(
                name="lazy_flip",
                op="horizontal_flip",
                params={"p": 0.5},
                splits=["train"],
            ),
        ],
    )
    # NOTE: in a real pipeline the aggressive op would have already
    # populated the train split with variants; for this test the records
    # we pass mimic post-aggressive output. Lazy ops realize inline from
    # the *same* records — which is fine because lazy realization treats
    # each record as a base record.
    handle = IMAGE_PLUGIN.operation_factory("Visualizations", "augmented_sample_grid")
    out = handle.render(
        {"train": aggressive_records},
        {"n_base": 2, "n_variants": 2},
        label_field="label",
        recipe=recipe,
    )
    assert set(out.keys()) == {"aggr_flip", "lazy_flip"}
    assert _is_png(out["aggr_flip"]) and _is_png(out["lazy_flip"])


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def test_plugin_registers_augmented_sample_grid_spec() -> None:
    spec = IMAGE_PLUGIN.supported_operations["augmented_sample_grid"]
    assert "Visualizations" in spec.applicable_sections
    assert spec.parameters["n_base"].required is True
    assert spec.parameters["n_variants"].required is True
    assert spec.parameters["seed"].required is False


def test_plugin_factory_returns_augmented_sample_grid_handle() -> None:
    handle = IMAGE_PLUGIN.operation_factory("Visualizations", "augmented_sample_grid")
    assert isinstance(handle, AugmentedSampleGridOp)


# ---------------------------------------------------------------------------
# Pipeline stage: <viz.name>_<aug.name>.png written per aug op
# ---------------------------------------------------------------------------


def test_stage_writes_one_png_per_aug_op(tmp_path: Path) -> None:
    aggressive_records: list[Mapping[str, Any]] = [
        _aggressive_record(src, vi, 1) for src in ["a", "b"] for vi in range(2)
    ]
    recipe = _recipe(
        augmentations=[
            AugmentationOp(
                name="flip",
                op="horizontal_flip",
                params={"p": 0.5},
                splits=["train"],
                materialization="aggressive",
                expansion=2,
            ),
        ],
    )
    op = _viz("aug_grid", n_base=2, n_variants=2)
    result = apply_reporting_visualizations(
        {"train": aggressive_records},
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path,
        label_field="label",
        recipe=recipe,
    )
    written = {p.name for p in result.written_paths}
    assert written == {"aug_grid_flip.png"}
    for path in result.written_paths:
        assert _is_png(path.read_bytes())


def test_stage_render_is_deterministic(tmp_path: Path) -> None:
    records: list[Mapping[str, Any]] = [_base_record(f"r{i}", 10 + i) for i in range(3)]
    recipe = _recipe(
        augmentations=[
            AugmentationOp(
                name="flip",
                op="horizontal_flip",
                params={"p": 0.5},
                splits=["train"],
            ),
        ],
    )
    op = _viz("aug_grid", n_base=2, n_variants=2)
    a = apply_reporting_visualizations(
        {"train": records},
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path / "a",
        label_field="label",
        recipe=recipe,
    )
    b = apply_reporting_visualizations(
        {"train": records},
        [op],
        plugin=IMAGE_PLUGIN,
        output_dir=tmp_path / "b",
        label_field="label",
        recipe=recipe,
    )
    assert a.rendered[0].png_bytes == b.rendered[0].png_bytes
