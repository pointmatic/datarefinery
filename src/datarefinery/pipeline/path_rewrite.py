# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Lazy-mode ``path`` rewrite for pixel-altering Transformations (Story J.g).

Background. For non-aggressive ("lazy") records, the dataset writer drops
the in-memory numpy ``image`` field at JSONL serialization and leaves
``path`` pointing at the *source* file. When a recipe declares a
pixel-altering Transformation (e.g. ``resize``), the source pixels no
longer match the prepared dataset — a consumer reading ``path`` silently
gets pre-transform geometry.

Fix. DataRefinery requires a ``Sinks`` block that writes the transformed
``image`` per record (a ``png_per_record`` sink observing a post-transform
stage) and rewrites each lazy record's ``path`` to point at that sink's
per-record output, under the instance directory. Validator check 26
refuses the combination *pixel-altering Transformation + no qualifying
sink* so the silent-divergence recipe cannot be authored in the first
place.

This module holds the shared classification + sink-matching logic so the
validator and the runner agree on exactly one definition. Story J.i
reuses the same ``pixel_altering`` flag to refuse the
dtype-altering-transform + aggressive-augmentation crash combination.
"""

from __future__ import annotations

from datarefinery.plugins.base import Plugin
from datarefinery.recipe.models import Recipe, SinkOp, TransformationOp

#: Sink stages whose record snapshot observes the ``image`` field *after*
#: the Transformations stage has run. A qualifying image-writing sink must
#: target one of these so the bytes it persists are the transformed bytes.
POST_TRANSFORM_SINK_STAGES: frozenset[str] = frozenset(
    {
        "post_Transformations",
        "post_Featurizations",
        "post_Augmentations",
        "post_OutputExpectations",
        "post_Visualizations",
    }
)


def pixel_altering_transformations(recipe: Recipe, plugin: Plugin) -> list[TransformationOp]:
    """Recipe Transformations whose op the plugin flags ``pixel_altering``.

    The classification lives on the plugin's ``OperationSpec`` (Story J.g)
    so it stays a plugin concern rather than a hardcoded recipe-layer set.
    Ops the plugin does not declare are treated as non-pixel-altering
    (check 18 surfaces the unknown-op error separately).
    """
    ops: list[TransformationOp] = []
    for op in recipe.Transformations:
        spec = plugin.supported_operations.get(op.op)
        if spec is not None and spec.pixel_altering:
            ops.append(op)
    return ops


def _aggressively_realized_splits(recipe: Recipe) -> set[str]:
    """Splits whose records materialize as aggressive variants.

    Aggressive augmentation realizes the variant image bytes onto disk as
    sidecar PNGs (``image_path``), so those records carry the transformed
    pixels honestly and have no lazy ``path`` divergence — they are
    excluded from the rewrite's required coverage (Out of scope:
    aggressive-mode behavior is already correct).
    """
    splits: set[str] = set()
    for op in recipe.Augmentations:
        if op.materialization == "aggressive":
            splits.update(op.splits)
    return splits


def _lazy_pixel_altering_splits(recipe: Recipe, plugin: Plugin) -> set[str]:
    """Splits that need a ``path`` rewrite: a pixel-altering Transformation
    applies to them AND their records serialize lazily (not as aggressive
    variants)."""
    aggressive = _aggressively_realized_splits(recipe)
    splits: set[str] = set()
    for op in pixel_altering_transformations(recipe, plugin):
        splits.update(s for s in op.splits if s not in aggressive)
    return splits


def _sink_covers_split(sink: SinkOp, split: str) -> bool:
    return sink.splits is None or split in sink.splits


def qualifying_image_sinks(recipe: Recipe) -> list[SinkOp]:
    """Sinks that persist the transformed ``image`` per record.

    A qualifying sink writes the ``image`` field as ``png_per_record`` at a
    post-transform stage, so its per-record output is the transformed
    bytes a rewritten ``path`` can point at.
    """
    return [
        sink
        for sink in recipe.Sinks
        if sink.format == "png_per_record"
        and sink.field == "image"
        and sink.stage in POST_TRANSFORM_SINK_STAGES
    ]


def path_rewrite_plan(recipe: Recipe, plugin: Plugin) -> dict[str, SinkOp]:
    """Map each split needing a rewrite to the sink that provides it.

    For each lazy pixel-altering split, the first qualifying sink (in
    recipe declaration order) that covers the split wins. Splits with no
    covering sink are omitted — that case is refused at validate time by
    check 26, so a well-formed recipe yields a plan covering every needed
    split.
    """
    sinks = qualifying_image_sinks(recipe)
    plan: dict[str, SinkOp] = {}
    for split in _lazy_pixel_altering_splits(recipe, plugin):
        for sink in sinks:
            if _sink_covers_split(sink, split):
                plan[split] = sink
                break
    return plan


def uncovered_pixel_altering_splits(recipe: Recipe, plugin: Plugin) -> set[str]:
    """Lazy pixel-altering splits with no qualifying sink (validator gap)."""
    needed = _lazy_pixel_altering_splits(recipe, plugin)
    covered = set(path_rewrite_plan(recipe, plugin).keys())
    return needed - covered
