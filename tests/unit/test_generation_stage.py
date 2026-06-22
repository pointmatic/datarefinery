# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-9 Generation stage tests (Story C.g).

Covers stage dispatch, output-schema validation, applies_at honoring,
counts tracking, and the image plugin's `duplicate_minority_class` op
end-to-end through `plugin.operation_factory("Generation", op_name)`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from datarefinery.core.errors import MaterializeError, PluginError
from datarefinery.pipeline.stages.generation import (
    GenerationResult,
    apply_generation,
)
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.recipe.models import FieldSpec, GenerationOp


def _output_schema() -> dict[str, FieldSpec]:
    return {
        "image": FieldSpec(dtype="uint8", shape=[32, 32, 3]),
        "label": FieldSpec(dtype="int32"),
    }


def _record(label: Any, image: Any = 0) -> Mapping[str, Any]:
    return {"image": image, "label": label}


def _imbalanced_train_split() -> list[Mapping[str, Any]]:
    # 6 of class 0, 2 of class 1
    return [_record(0, image=i) for i in range(6)] + [_record(1, image=10 + i) for i in range(2)]


# ---------------------------------------------------------------------------
# duplicate_minority_class via the stage
# ---------------------------------------------------------------------------


def test_generation_brings_minority_class_up_to_majority() -> None:
    op = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=7,
        splits=["train"],
    )
    splits = {"train": _imbalanced_train_split(), "val": [_record(0)]}
    result = apply_generation(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    assert isinstance(result, GenerationResult)
    train = result.splits["train"]
    counts: dict[Any, int] = {}
    for r in train:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    assert counts == {0: 6, 1: 6}  # both classes at majority count


def test_generation_records_pre_and_post_counts() -> None:
    op = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=7,
    )
    splits = {"train": _imbalanced_train_split(), "val": [_record(0)]}
    result = apply_generation(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    assert result.counts_before == {"train": 8, "val": 1}
    assert result.counts_after == {"train": 12, "val": 1}


def test_generation_is_deterministic_for_fixed_seed() -> None:
    op = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=99,
    )
    splits = {"train": _imbalanced_train_split()}
    a = apply_generation(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    b = apply_generation(
        {"train": _imbalanced_train_split()},
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    assert [r["image"] for r in a.splits["train"]] == [r["image"] for r in b.splits["train"]]


def test_generation_different_seeds_produce_different_clones() -> None:
    op_a = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=1,
    )
    op_b = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=2,
    )
    a = apply_generation(
        {"train": _imbalanced_train_split()},
        [op_a],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    b = apply_generation(
        {"train": _imbalanced_train_split()},
        [op_b],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    # Tail (the appended duplicates) should differ across seeds.
    assert [r["image"] for r in a.splits["train"][8:]] != [
        r["image"] for r in b.splits["train"][8:]
    ]


def test_generation_no_op_when_already_balanced() -> None:
    op = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=0,
    )
    balanced = [_record(0, image=i) for i in range(3)] + [
        _record(1, image=i + 10) for i in range(3)
    ]
    result = apply_generation(
        {"train": balanced},
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    assert result.counts_before == {"train": 6}
    assert result.counts_after == {"train": 6}


def test_generation_requires_label_field() -> None:
    op = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image"],
        output_schema=_output_schema(),
        seed=0,
    )
    with pytest.raises(PluginError, match=r"Labels\.field"):
        apply_generation(
            {"train": _imbalanced_train_split()},
            [op],
            plugin=IMAGE_PLUGIN,
            output_record_schema=_output_schema(),
        )


# ---------------------------------------------------------------------------
# splits handling (v1's ``applies_at`` was renamed to ``splits``; G12 / Story I.x.2)
# ---------------------------------------------------------------------------


def test_default_splits_is_train_only() -> None:
    op = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=0,
    )
    splits = {
        "train": _imbalanced_train_split(),
        "val": _imbalanced_train_split(),
        "test": _imbalanced_train_split(),
    }
    result = apply_generation(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    assert result.counts_after["train"] > result.counts_before["train"]
    assert result.counts_after["val"] == result.counts_before["val"]
    assert result.counts_after["test"] == result.counts_before["test"]


def test_splits_non_train_emits_warning() -> None:
    op = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=0,
        splits=["val"],
    )
    result = apply_generation(
        {"val": _imbalanced_train_split(), "train": []},
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    assert any("non-train" in w and "'val'" in w for w in result.warnings)


def test_splits_undeclared_split_raises_materialize_error() -> None:
    op = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=0,
        splits=["train", "no_such_split"],
    )
    with pytest.raises(MaterializeError, match="undeclared split"):
        apply_generation(
            {"train": _imbalanced_train_split()},
            [op],
            plugin=IMAGE_PLUGIN,
            output_record_schema=_output_schema(),
            label_field="label",
        )


# ---------------------------------------------------------------------------
# Output-schema validation
# ---------------------------------------------------------------------------


class _DropFieldPlugin:
    """Test plugin whose generation op produces records missing a field."""

    name = "drop_field"
    schema_version = 1
    supported_sections = frozenset({"Generation"})

    def __init__(self) -> None:
        self.supported_operations: dict[str, Any] = {}

    def recommended_params(self, section: str, op_name: str) -> dict[str, object]:
        del section, op_name
        return {}

    def operation_factory(self, section: str, op_name: str) -> Any:
        del section, op_name

        def op(
            records: list[Mapping[str, Any]],
            *,
            seed: int,
            inputs: list[str],
            output_schema: Mapping[str, Any],
            params: Mapping[str, Any],
            label_field: str | None,
            op_name: str,
        ) -> list[Mapping[str, Any]]:
            del records, seed, inputs, output_schema, params, label_field, op_name
            return [{"image": 0}]  # missing 'label'

        return op

    def is_stub(self) -> bool:
        return False

    def extension_keys(self) -> dict[str, set[str]]:
        return {}


def test_generation_record_missing_output_field_raises_materialize_error() -> None:
    plugin = _DropFieldPlugin()
    op = GenerationOp(
        name="bad_gen",
        op="bad_gen",
        inputs=["image"],
        output_schema={"image": FieldSpec(dtype="uint8", shape=[1])},
        seed=0,
    )
    with pytest.raises(MaterializeError, match="missing required Output field"):
        apply_generation(
            {"train": [_record(0)]},
            [op],
            plugin=plugin,
            output_record_schema=_output_schema(),
            label_field="label",
        )


# ---------------------------------------------------------------------------
# replace_input_records (Story I.q / G18)
# ---------------------------------------------------------------------------


class _ReplacingPlugin:
    """Test plugin whose generation op emits two new records per input record."""

    name = "replacing"
    schema_version = 1
    supported_sections = frozenset({"Generation"})

    def __init__(self) -> None:
        self.supported_operations: dict[str, Any] = {}

    def recommended_params(self, section: str, op_name: str) -> dict[str, object]:
        del section, op_name
        return {}

    def operation_factory(self, section: str, op_name: str) -> Any:
        del section, op_name

        def op(
            records: list[Mapping[str, Any]],
            *,
            seed: int,
            inputs: list[str],
            output_schema: Mapping[str, Any],
            params: Mapping[str, Any],
            label_field: str | None,
            op_name: str,
        ) -> list[Mapping[str, Any]]:
            del seed, inputs, output_schema, params, label_field, op_name
            new: list[Mapping[str, Any]] = []
            for r in records:
                new.append({"image": r["image"], "label": r["label"], "variant": "a"})
                new.append({"image": r["image"], "label": r["label"], "variant": "b"})
            return new

        return op

    def is_stub(self) -> bool:
        return False

    def extension_keys(self) -> dict[str, set[str]]:
        return {}


def test_replace_input_records_replaces_split_with_generated_records() -> None:
    plugin = _ReplacingPlugin()
    op = GenerationOp(
        name="gen2",
        op="gen2",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=0,
        replace_input_records=True,
    )
    splits = {"train": [_record(0, image=1), _record(1, image=2)]}
    result = apply_generation(
        splits,
        [op],
        plugin=plugin,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    train = result.splits["train"]
    # 2 inputs * 2 emitted per input = 4; originals replaced (none lack 'variant').
    assert len(train) == 4
    assert all("variant" in r for r in train)
    assert result.counts_before == {"train": 2}
    assert result.counts_after == {"train": 4}


def test_replace_input_records_defaults_false_and_appends() -> None:
    plugin = _ReplacingPlugin()
    op = GenerationOp(
        name="gen2",
        op="gen2",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=0,
    )
    assert op.replace_input_records is False
    splits = {"train": [_record(0, image=1), _record(1, image=2)]}
    result = apply_generation(
        splits,
        [op],
        plugin=plugin,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    train = result.splits["train"]
    # 2 originals + 4 generated = 6; originals (no 'variant') retained.
    assert len(train) == 6
    assert sum(1 for r in train if "variant" not in r) == 2
    assert result.counts_after == {"train": 6}


# ---------------------------------------------------------------------------
# Misc / pass-through
# ---------------------------------------------------------------------------


def test_empty_generation_list_is_passthrough() -> None:
    splits = {"train": _imbalanced_train_split()}
    result = apply_generation(
        splits,
        [],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    assert result.counts_before == result.counts_after
    assert result.warnings == ()


def test_returned_splits_are_fresh_lists() -> None:
    """The stage must not mutate the caller's input split lists."""
    original_train = _imbalanced_train_split()
    splits = {"train": original_train}
    op = GenerationOp(
        name="duplicate_minority_class",
        op="duplicate_minority_class",
        inputs=["image", "label"],
        output_schema=_output_schema(),
        seed=0,
    )
    apply_generation(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
        label_field="label",
    )
    assert len(original_train) == 8  # unchanged


def test_generation_result_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    gr = GenerationResult(splits={}, counts_before={}, counts_after={}, warnings=())
    with pytest.raises(FrozenInstanceError):
        gr.warnings = ("x",)  # type: ignore[misc]
