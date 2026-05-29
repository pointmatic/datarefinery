# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Master-seed derivation for the `seed_derive_from: master` recipe form (G11).

A seeded recipe op may declare its seed as a literal integer or, when
the recipe author wants per-op seeds tied to a single master seed, as
the `SeedDerivationSpec` form:

    seed:
      from: master

At materialize time the spec is resolved to a deterministic integer
via :func:`derive_seed`:

    derived = sha256(master_seed.to_bytes(8, "big") + op_name.encode("utf-8")).digest()[:8]

The derivation participates in cache identity through the master seed —
``Recipe.seed`` is part of the canonical bytes, so changing the master
seed propagates to every derived seed. The `SeedDerivationSpec` itself
is also preserved in canonical bytes, so the YAML intent (rather than
its resolved integer) is what the cached `recipe.json` records.

The exact derivation function is a contract surface: changing it would
invalidate every cached instance for every recipe that uses the
derivation form. Pinned by a unit test on a fixed (master, op_name)
pair.
"""

from __future__ import annotations

import hashlib

from datarefinery.recipe.models import SeedDerivationSpec

_U64_MASK = (1 << 64) - 1


def derive_seed(master_seed: int, op_name: str) -> int:
    """Derive a 64-bit per-op seed from a master seed and an op name.

    Negative master seeds are wrapped into the 64-bit unsigned range
    before hashing so the byte representation is well-defined.
    """
    master_u64 = master_seed & _U64_MASK
    digest = hashlib.sha256(master_u64.to_bytes(8, "big") + op_name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def resolve_seed(
    value: int | SeedDerivationSpec | None,
    *,
    master_seed: int,
    op_name: str,
) -> int | None:
    """Resolve a recipe-declared seed value to a concrete integer.

    ``None`` is returned unchanged; the caller decides any fallback.
    A literal ``int`` is returned as-is. A ``SeedDerivationSpec`` is
    resolved via :func:`derive_seed`.
    """
    if value is None:
        return None
    if isinstance(value, SeedDerivationSpec):
        return derive_seed(master_seed, op_name)
    return int(value)
