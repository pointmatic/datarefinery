# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Recipe schema migrations (v1 -> v2 first wave, Phase I bundle 4).

Each migration is a pure ``dict -> dict`` function executed before
pydantic validation in :func:`datarefinery.recipe.loader.load`. The
loader composes the registered migrations for a ``(from, to)`` pair
into one chain — additional reshape stories register more callables
against the same key (Story I.x.2 for Generation, Story I.x.3 for
assertion naming).

Migrations are *idempotent on already-v2 input* by convention, so the
chain stays robust if a downstream tool partially migrates a recipe
dict before handing it to the loader.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from datarefinery.core.errors import RecipeError


def compose(
    *funcs: Callable[[dict[str, Any]], dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Compose dict-rewriting migrations left-to-right."""

    def _composed(data: dict[str, Any]) -> dict[str, Any]:
        for fn in funcs:
            data = fn(data)
        return data

    return _composed


def filters_reshape_v1_to_v2(recipe_dict: dict[str, Any]) -> dict[str, Any]:
    """G15 / Story I.x.1: lift ``predicate.op`` and ``predicate.seed`` out
    of every ``FilterOp``; rename remaining predicate keys to ``params``.

    v1 shape::

        {name, predicate: {op, ...rest, seed?}, stages?, splits?, seed?}

    v2 shape::

        {name, op, params: {...rest}, stages?, splits?, seed?}

    The migration is *strict* about malformed v1 input: a predicate
    without an ``op`` key is rejected (the v1 runtime already failed at
    materialize on this shape, so no real recipe relied on it). A filter
    carrying both an ``op`` top-level field and a ``predicate`` key is
    also rejected — that combination is ambiguous and almost certainly
    indicates a partial hand-edit.
    """
    filters = recipe_dict.get("Filters")
    if not filters:
        return recipe_dict
    new_filters: list[dict[str, Any]] = []
    for entry in filters:
        if "predicate" not in entry:
            # Already v2 or no work to do; pass through verbatim.
            new_filters.append(entry)
            continue
        if "op" in entry:
            raise RecipeError(
                f"Filters[{entry.get('name')!r}]: cannot reshape — entry has both "
                "'op' and 'predicate'; resolve the ambiguity by removing one"
            )
        predicate = dict(entry["predicate"])
        op_name = predicate.pop("op", None)
        if not isinstance(op_name, str):
            raise RecipeError(
                f"Filters[{entry.get('name')!r}]: predicate missing 'op' string "
                "(v1->v2 migration cannot infer an operation name)"
            )
        seed = predicate.pop("seed", None)
        new_entry = {k: v for k, v in entry.items() if k != "predicate"}
        new_entry["op"] = op_name
        new_entry["params"] = predicate
        if seed is not None and "seed" not in new_entry:
            new_entry["seed"] = seed
        new_filters.append(new_entry)
    out = dict(recipe_dict)
    out["Filters"] = new_filters
    return out


# Registry of (from_version, to_version) -> composed migration. Other
# Bundle 4 stories (I.x.2, I.x.3) extend this by re-composing more
# callables into the (1, 2) entry.
_V1_TO_V2_FUNCS: list[Callable[[dict[str, Any]], dict[str, Any]]] = [
    filters_reshape_v1_to_v2,
]


def v1_to_v2(recipe_dict: dict[str, Any]) -> dict[str, Any]:
    """Composed v1 -> v2 migration. Bumps ``schema_version`` to 2 as
    its final step so a re-load reaches the v2 path directly."""
    out = compose(*_V1_TO_V2_FUNCS)(recipe_dict)
    out = dict(out)
    out["schema_version"] = 2
    return out


def register_v1_to_v2(*funcs: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    """Append additional v1->v2 reshape callables. Used by I.x.2 and
    I.x.3 to extend the chain without re-importing private state."""
    _V1_TO_V2_FUNCS.extend(funcs)


def _funcs_for(
    from_version: int, to_version: int
) -> Iterable[Callable[[dict[str, Any]], dict[str, Any]]]:
    if (from_version, to_version) == (1, 2):
        return list(_V1_TO_V2_FUNCS)
    return ()
