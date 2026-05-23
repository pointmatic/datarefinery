# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-11 Augmentations stage: lazy policy capture + aggressive realization.

FR-11 originally framed augmentations as policy-only (lazy): the recipe
declares augmentation policies and ModelFoundry honors them on-the-fly
during training. Story H.p extends FR-11 with a second per-op
``materialization`` mode:

- ``materialization="lazy"`` (default): captured as a
  :class:`AugmentationPolicy` for the manifest; dataset bytes unchanged.
- ``materialization="aggressive"``: dispatched through
  :func:`plugins.image_classification.augmentations._realizer.emit_variants`
  to produce ``expansion`` augmented variant records per input record;
  variant records become peer records in the materialized dataset.

The two modes coexist within a single ``Augmentations`` block — the
runner walks each op and routes by its mode.

Train-only invariant: validator check 5 enforces that augmentation
operations declare ``splits=["train"]``. This stage re-checks
defensively for both modes — if a non-train split slipped past
validation, the stage raises ``MaterializeError`` rather than silently
writing a policy (lazy) or augmented records (aggressive) that
ModelFoundry might honor on val/test.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from datarefinery.core.errors import MaterializeError
from datarefinery.recipe.models import AugmentationOp

Record = Mapping[str, Any]
Realizer = Callable[[Record, int, int, Mapping[str, Any]], Record]
RealizerRegistry = Mapping[str, Realizer]
"""Map from ``AugmentationOp.op`` name to its single-variant realizer.

Populated by the plugin (H.q, H.r); the stage looks ops up by name and
raises :class:`MaterializeError` if an aggressive-mode op is missing
from the registry. The realizer is stateless w.r.t. ``params`` — the
stage passes each op's ``params`` mapping through on every call so one
registered callable handles every recipe instance of the same op name.
"""


@dataclass(frozen=True)
class AugmentationPolicy:
    """One augmentation operation captured as a runtime policy.

    The ``materialization`` and ``expansion`` fields default to the
    lazy-mode values (``"lazy"`` and ``1``) so older test fixtures that
    construct policies without them keep working unchanged; new H.p
    recipes set them explicitly via :func:`collect_augmentation_policies`.
    """

    name: str
    op: str
    params: Mapping[str, Any]
    splits: tuple[str, ...]
    seed: int | None
    materialization: str = "lazy"
    expansion: int = 1

    def to_manifest_dict(self) -> dict[str, Any]:
        """Render to a JSON-serializable manifest entry.

        ``params`` is rendered as a plain dict with sorted keys so two
        runs of the same recipe produce byte-identical manifest entries.
        """
        return {
            "name": self.name,
            "op": self.op,
            "params": dict(sorted(self.params.items())),
            "splits": list(self.splits),
            "seed": self.seed,
            "materialization": self.materialization,
            "expansion": self.expansion,
        }


@dataclass(frozen=True)
class AugmentationsResult:
    """Collected augmentation policies for one materialization."""

    policies: tuple[AugmentationPolicy, ...]

    def to_manifest_list(self) -> list[dict[str, Any]]:
        return [p.to_manifest_dict() for p in self.policies]


def collect_augmentation_policies(
    augmentation_ops: list[AugmentationOp],
) -> AugmentationsResult:
    """Capture every declared augmentation as a manifest-bound policy.

    Both lazy and aggressive ops are captured here — the manifest is the
    authoritative record of declared augmentation policy regardless of
    whether bytes were realized. The :attr:`AugmentationPolicy.materialization`
    field distinguishes the two at read time.

    Defensive train-only re-check; trust the validator for happy-path
    semantics.
    """
    policies: list[AugmentationPolicy] = []
    for op in augmentation_ops:
        non_train = [s for s in op.splits if s != "train"]
        if non_train:
            raise MaterializeError(
                f"Augmentations[{op.name!r}] declares non-train splits "
                f"{non_train!r}; validator check 5 should have caught this"
            )
        policies.append(
            AugmentationPolicy(
                name=op.name,
                op=op.op,
                params=dict(op.params),
                splits=tuple(op.splits),
                seed=op.seed,
                materialization=op.materialization,
                expansion=op.expansion,
            )
        )
    return AugmentationsResult(policies=tuple(policies))


def realize_aggressive_split(
    records: list[Record],
    augmentation_ops: list[AugmentationOp],
    *,
    global_seed: int,
    realizer_registry: RealizerRegistry,
    split: str = "train",
    workers: int = 1,
) -> list[dict[str, Any]]:
    """Apply every aggressive-mode op in sequence to a split's records.

    Lazy ops are skipped (they declare policy only). Aggressive ops are
    dispatched through their registered :data:`Realizer` via
    :func:`...augmentations._realizer.emit_variants`, producing
    ``expansion`` variants per input record. Each aggressive op operates
    on the output of the previous one — composition is sequential and
    explicit, matching the order the ops appear in the recipe.

    Returns a flat list of variant records sorted by ``record_id``,
    preserving the FR-3 determinism contract: identical input + global
    seed + op_id sequence → byte-identical output across worker counts
    (the per-variant seed depends only on
    ``(global_seed, op_id, record_id, variant_index)``).

    ``workers > 1`` runs the per-record :func:`emit_variants` calls
    through :class:`ProcessPoolExecutor`; realizers in
    ``realizer_registry`` must be picklable (module-level functions, not
    closures or lambdas) when ``workers > 1`` — the standard
    multiprocessing constraint, identical to the one
    :func:`run_parallel` imposes on its worker fns.

    ``split`` is currently advisory — the FR-2 check-5 invariant means
    only ``"train"`` reaches this function in normal recipes. A
    defensive non-train rejection still applies (mirroring
    :func:`collect_augmentation_policies`) so callers that wire this up
    to a non-train split discover the misuse loudly.
    """
    # Local import: keeps the heavyweight plugin import out of the
    # module-level dependency graph for callers that only need the
    # policy-capture path.
    from datarefinery.plugins.image_classification.augmentations._realizer import (
        emit_variants,
    )

    if split != "train":
        raise MaterializeError(
            f"realize_aggressive_split: split={split!r} is not train; "
            f"FR-11 aggressive augmentation only applies to the train split"
        )

    current: list[dict[str, Any]] = [dict(r) for r in records]
    for op in augmentation_ops:
        if op.materialization != "aggressive":
            continue
        non_train = [s for s in op.splits if s != "train"]
        if non_train:
            raise MaterializeError(
                f"Augmentations[{op.name!r}] declares non-train splits "
                f"{non_train!r}; validator check 5 should have caught this"
            )
        if op.op not in realizer_registry:
            raise MaterializeError(
                f"Augmentations[{op.name!r}]: no realizer registered for "
                f"op={op.op!r}; plugin must register a Realizer in "
                f"image_classification.augmentations for aggressive mode"
            )
        realize_fn = realizer_registry[op.op]
        op_id = op.op
        expansion = op.expansion
        params = dict(op.params)

        if workers <= 1:
            packs = [
                emit_variants(
                    record,
                    op_id=op_id,
                    global_seed=global_seed,
                    expansion=expansion,
                    realize_fn=realize_fn,
                    params=params,
                )
                for record in current
            ]
        else:
            from concurrent.futures import ProcessPoolExecutor

            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(
                        emit_variants,
                        record,
                        op_id=op_id,
                        global_seed=global_seed,
                        expansion=expansion,
                        realize_fn=realize_fn,
                        params=params,
                    )
                    for record in current
                ]
                packs = [f.result() for f in futures]

        next_records: list[dict[str, Any]] = []
        for pack in packs:
            next_records.extend(pack)
        # Sort by record_id — the zero-padded variant_index suffix in
        # `derive_variant_record_id` makes this equivalent to sorting
        # by ``(source_record_id, variant_index)`` while keeping the
        # sort key a single string. Worker count cannot perturb output
        # bytes downstream of this sort.
        next_records.sort(key=lambda r: str(r["record_id"]))
        current = next_records
    return current


def manifest_block(result: AugmentationsResult) -> str:
    """Render the augmentation block as a stable JSON string.

    The runner (Story C.m) embeds this in ``manifest.json``. Keys are
    sorted so the canonical output is reproducible across runs.
    """
    return json.dumps(result.to_manifest_list(), sort_keys=True, separators=(",", ":"))
