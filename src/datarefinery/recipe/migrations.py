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


def generation_reshape_v1_to_v2(recipe_dict: dict[str, Any]) -> dict[str, Any]:
    """G12 / Story I.x.2: reshape each ``GenerationOp`` to v2 form.

    Three changes (none of which can collide with each other):

    1. **Lift ``op`` to top level.** v1 stored the op-name in
       ``GenerationOp.name`` (the runtime called
       ``plugin.operation_factory("Generation", op.name)``); the v2
       model has a separate ``op: str`` field, matching every other
       section. The migration sets ``op = name`` for the canonical v1
       shape, or lifts ``params["op"]`` if a recipe used the workaround
       pattern documented in the gap doc.
    2. **Rename ``applies_at`` -> ``splits``.** Same semantics, new
       name; every other section already says ``splits:``.
    3. **Lift ``output_schema_matches_input: true`` (workaround) ->
       ``output_schema: "matches_input"``.** Explicit dicts pass through
       unchanged — the migration cannot inflate to ``matches_input``
       without runtime context per the gap-doc fix-direction note.

    Idempotent on already-v2 input (entries with top-level ``op`` and
    ``splits`` pass through verbatim).
    """
    generation = recipe_dict.get("Generation")
    if not generation:
        return recipe_dict
    new_generation: list[dict[str, Any]] = []
    for entry in generation:
        new_entry = dict(entry)
        if "op" not in new_entry:
            # Lift from params (workaround pattern) if present, else
            # default to the canonical v1 convention of name == op-name.
            params = dict(new_entry.get("params") or {})
            if "op" in params and isinstance(params["op"], str):
                new_entry["op"] = params.pop("op")
                new_entry["params"] = params
            else:
                name = new_entry.get("name")
                if not isinstance(name, str):
                    raise RecipeError(
                        f"Generation[{name!r}]: cannot infer 'op' for v1->v2 "
                        "migration (entry has no top-level 'op', no string "
                        "'name', and no 'op' inside params)"
                    )
                new_entry["op"] = name
        if "applies_at" in new_entry:
            if "splits" in new_entry:
                raise RecipeError(
                    f"Generation[{new_entry.get('name')!r}]: cannot reshape — "
                    "entry has both 'applies_at' and 'splits'; resolve the "
                    "ambiguity by removing one"
                )
            new_entry["splits"] = new_entry.pop("applies_at")
        if new_entry.pop("output_schema_matches_input", False) is True:
            new_entry["output_schema"] = "matches_input"
        new_generation.append(new_entry)
    out = dict(recipe_dict)
    out["Generation"] = new_generation
    return out


# G16a (Story I.x.3) — naming pass for the v1 contracts-evaluator kinds.
# Two of the v1 names (`dtype`, `range`) clash with field-shape names
# elsewhere in the recipe (FieldSpec `dtype`, value `range`), so the v2
# names are predicate-sentence forms that read naturally in
# ``assertion: { kind: ... }``. The two v1 kinds that already read as
# sentences (`required_field`, `distributional`) are unchanged.
_ASSERTION_KIND_V1_TO_V2: dict[str, str] = {
    "dtype": "dtype_equals",
    "range": "value_range",
    "record_count": "record_count_in_range",
}


def assertion_naming_v1_to_v2(recipe_dict: dict[str, Any]) -> dict[str, Any]:
    """G16a / Story I.x.3: rename the v1 contracts-evaluator kinds to
    their v2 predicate-sentence form.

    Walks every ``InputContracts[i].assertion`` and
    ``OutputExpectations[i].assertion``, rewriting ``kind`` per
    :data:`_ASSERTION_KIND_V1_TO_V2`. The param shape inside each
    assertion is untouched (the rename only affects the dispatch key).

    Malformed entries (missing ``kind``, non-string ``kind``, unknown
    ``kind``) pass through unchanged — the model layer or runtime
    evaluator is responsible for surfacing those, and being lenient
    here keeps the migration robust under partial application.

    Idempotent on already-v2 input (v2 names are not present in the
    rename mapping's domain).
    """
    out = dict(recipe_dict)
    for section in ("InputContracts", "OutputExpectations"):
        entries = out.get(section)
        if not entries:
            continue
        new_entries: list[dict[str, Any]] = []
        for entry in entries:
            new_entry = dict(entry)
            assertion = new_entry.get("assertion")
            if isinstance(assertion, dict):
                kind = assertion.get("kind")
                if isinstance(kind, str) and kind in _ASSERTION_KIND_V1_TO_V2:
                    new_assertion = dict(assertion)
                    new_assertion["kind"] = _ASSERTION_KIND_V1_TO_V2[kind]
                    new_entry["assertion"] = new_assertion
            new_entries.append(new_entry)
        out[section] = new_entries
    return out


# Registry of (from_version, to_version) -> composed migration. Each
# Bundle 4 reshape story registers a step here; the loader composes
# them in declaration order.
_V1_TO_V2_FUNCS: list[Callable[[dict[str, Any]], dict[str, Any]]] = [
    filters_reshape_v1_to_v2,
    generation_reshape_v1_to_v2,
    assertion_naming_v1_to_v2,
]


def v1_to_v2(recipe_dict: dict[str, Any]) -> dict[str, Any]:
    """Composed v1 -> v2 migration. Bumps ``schema_version`` to 2 as
    its final step so a re-load reaches the v2 path directly."""
    out = compose(*_V1_TO_V2_FUNCS)(recipe_dict)
    out = dict(out)
    out["schema_version"] = 2
    return out


def v2_to_v3(recipe_dict: dict[str, Any]) -> dict[str, Any]:
    """Story J.n.3 flat→segmented bootstrap — the one-time pre-1.0
    cache-invalidation event (design Q4).

    v3 is the *segmented-canonical era*: recipe identity switched from the
    flat ``model_dump`` sha256 to the per-segment ``join_stable`` combiner
    (:func:`datarefinery.recipe.segments.recipe_identity_hash`). That is a
    canonical-form algorithm change, which ``project-essentials.md`` requires
    to ride a ``schema_version`` bump.

    Under the confirmed Option-1 design the recipe stays *flat* on disk —
    segmentation is an internal partition, not an author-facing reshape — so
    this whole-recipe migration performs **no field redistribution**. (Default
    injection for the no-implicit-defaults rollout is Q7 / Story J.n.4, not
    here.) The only on-disk change is the version stamp; the identity shift is
    carried entirely by the new combiner. Idempotent on already-v3 input.
    """
    out = dict(recipe_dict)
    out["schema_version"] = 3
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
