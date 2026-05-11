# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-11 Augmentations stage: policy-only declarations.

v1 does NOT pre-materialize augmented examples (FR-11 #2, #3): the
recipe declares augmentation policies that ModelFoundry honors on-the-
fly during training. This stage's job is to convert each declared
``AugmentationOp`` into a manifest-serializable :class:`AugmentationPolicy`
record. No image bytes change here.

Train-only invariant: validator check 5 enforces that augmentation
operations declare ``splits=["train"]``. This stage re-checks
defensively - if a non-train split slipped past validation, the stage
raises ``MaterializeError`` rather than silently writing a policy that
ModelFoundry might honor on val/test.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from datarefinery.core.errors import MaterializeError
from datarefinery.recipe.models import AugmentationOp


@dataclass(frozen=True)
class AugmentationPolicy:
    """One augmentation operation captured as a runtime policy."""

    name: str
    op: str
    params: Mapping[str, Any]
    splits: tuple[str, ...]
    seed: int | None

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
    """Capture declared augmentations as manifest-bound policies.

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
            )
        )
    return AugmentationsResult(policies=tuple(policies))


def manifest_block(result: AugmentationsResult) -> str:
    """Render the augmentation block as a stable JSON string.

    The runner (Story C.m) embeds this in ``manifest.json``. Keys are
    sorted so the canonical output is reproducible across runs.
    """
    return json.dumps(result.to_manifest_list(), sort_keys=True, separators=(",", ":"))
