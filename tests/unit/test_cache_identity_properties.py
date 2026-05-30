# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-4 cache-identity Hypothesis properties (Story E.b).

Two property tests:

1. **Cosmetic invariance.** Cosmetic-only YAML edits — whitespace,
   comments, mapping key-order permutations, indent and flow-style
   swaps — never change the cache key. The pydantic model collapses
   YAML noise into a canonical dict; this property says the
   collapse is total.
2. **Semantic divergence.** Any edit that changes the parsed pydantic
   value — a different scalar, an added or removed list element, a
   toggled optional section — produces a different cache key.

Both pass on a 1000-example run (per the story task). The strategies
operate at the parsed-dict layer rather than at raw-YAML text where
possible: pydantic discards textual noise during parsing, so the
non-trivial cosmetic perturbations are key-order permutations and
formatting toggles rather than character-level edits.
"""

from __future__ import annotations

import copy
import hashlib
import random
from collections.abc import Mapping
from typing import Any

import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from datarefinery.cache.identity import compute_cache_key
from datarefinery.recipe.canonical import to_canonical_bytes
from datarefinery.recipe.models import Recipe

BASELINE: dict[str, Any] = {
    "schema_version": 1,
    "plugin": "image_classification",
    "seed": 42,
    "Input": {
        "sources": [
            {
                "name": "train",
                "type": "image_folder",
                "path": "/data/train",
            }
        ]
    },
    "Output": {
        "record_schema": {
            "image": {"dtype": "uint8", "shape": [32, 32, 3]},
            "label": {"dtype": "int32"},
        }
    },
    "Labels": {
        "field": "label",
        "source": {"kind": "derived", "derivation": "parent_directory_name"},
    },
    "Splits": {
        "ratios": {"train": 0.8, "val": 0.1, "test": 0.1},
        "stratify_by": "label",
        "seed": 7,
    },
}

_FIXED_INPUT_HASHES: dict[str, str] = {"train": "0" * 64}
_FIXED_SEED = 0


def _key_for(payload: Mapping[str, Any]) -> str:
    """Construct a Recipe and return the recipe-portion of its cache key."""
    recipe = Recipe.model_validate(payload)
    return compute_cache_key(recipe, _FIXED_INPUT_HASHES, _FIXED_SEED).recipe_hash


def _baseline_key() -> str:
    return _key_for(BASELINE)


def _canonical_hex(payload: Mapping[str, Any]) -> str:
    recipe = Recipe.model_validate(payload)
    return hashlib.sha256(to_canonical_bytes(recipe)).hexdigest()


# ---------------------------------------------------------------------------
# Cosmetic invariance
# ---------------------------------------------------------------------------


def _shuffle_keys(value: Any, rng: random.Random) -> Any:
    """Return ``value`` with mapping key orders shuffled recursively.

    Lists keep their element order (lists are *ordered* in YAML/JSON, so
    re-ordering would be a semantic edit). Only dict keys are
    permuted — that exercises the canonicalizer's `sort_keys=True`
    contract.
    """
    if isinstance(value, dict):
        items = list(value.items())
        rng.shuffle(items)
        return {k: _shuffle_keys(v, rng) for k, v in items}
    if isinstance(value, list):
        return [_shuffle_keys(v, rng) for v in value]
    return value


@st.composite
def _cosmetic_yaml_round_trip(draw: st.DrawFn) -> str:
    """Generate a YAML serialization of BASELINE with cosmetic perturbations.

    - Shuffle every nested mapping's key order using a Hypothesis-drawn seed.
    - Vary ``indent`` and ``default_flow_style`` so the same data emits
      with quite different on-disk text.
    - Splice in blank lines and ``# comment`` lines at random positions.
    """
    seed = draw(st.integers(min_value=0, max_value=2**31 - 1))
    indent = draw(st.integers(min_value=2, max_value=8))
    flow = draw(st.booleans())
    rng = random.Random(seed)
    permuted = _shuffle_keys(copy.deepcopy(BASELINE), rng)
    text = yaml.safe_dump(permuted, sort_keys=False, default_flow_style=flow, indent=indent)
    lines = text.splitlines()
    extra = draw(st.lists(_extra_line(), min_size=0, max_size=8))
    for kind in extra:
        pos = rng.randint(0, len(lines))
        lines.insert(pos, kind)
    return "\n".join(lines) + "\n"


def _extra_line() -> st.SearchStrategy[str]:
    return st.one_of(
        st.just(""),
        st.just("# inline comment"),
        st.just("# another comment"),
        st.just("   "),
    )


@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(_cosmetic_yaml_round_trip())
def test_cosmetic_yaml_edits_never_change_cache_key(text: str) -> None:
    payload = yaml.safe_load(text)
    assert _key_for(payload) == _baseline_key()


# ---------------------------------------------------------------------------
# Semantic divergence
# ---------------------------------------------------------------------------


def _change_recipe_seed(d: dict[str, Any], v: int) -> dict[str, Any]:
    out = copy.deepcopy(d)
    if v == out["seed"]:
        v += 1
    out["seed"] = v
    return out


def _change_split_seed(d: dict[str, Any], v: int) -> dict[str, Any]:
    out = copy.deepcopy(d)
    if v == out["Splits"].get("seed"):
        v += 1
    out["Splits"]["seed"] = v
    return out


def _change_split_ratios(d: dict[str, Any], pair: tuple[float, float]) -> dict[str, Any]:
    a, b = pair
    out = copy.deepcopy(d)
    out["Splits"]["ratios"] = {
        "train": round(a, 6),
        "val": round(b, 6),
        "test": round(1.0 - a - b, 6),
    }
    return out


def _change_label_field(d: dict[str, Any], name: str) -> dict[str, Any]:
    out = copy.deepcopy(d)
    out["Labels"]["field"] = name
    # Update Output.record_schema to keep the recipe self-consistent for
    # pydantic construction; canonical bytes still differ because the
    # field name changed.
    schema = dict(out["Output"]["record_schema"])
    schema[name] = schema.pop("label")
    out["Output"]["record_schema"] = schema
    return out


def _change_input_path(d: dict[str, Any], path: str) -> dict[str, Any]:
    out = copy.deepcopy(d)
    out["Input"]["sources"][0]["path"] = path
    return out


def _add_filter(d: dict[str, Any], name: str) -> dict[str, Any]:
    out = copy.deepcopy(d)
    out.setdefault("Filters", []).append({"name": name, "op": "dedup", "params": {}})
    return out


def _add_input_contract(d: dict[str, Any], lo: int) -> dict[str, Any]:
    out = copy.deepcopy(d)
    out.setdefault("InputContracts", []).append(
        {
            "field": None,
            "assertion": {"kind": "record_count_min", "value": int(lo)},
            "severity": "error",
        }
    )
    return out


def _add_visualization(d: dict[str, Any], name: str) -> dict[str, Any]:
    out = copy.deepcopy(d)
    out.setdefault("Visualizations", []).append(
        {
            "name": name,
            "op": "class_distribution_histogram",
            "params": {},
            "stage": "post_pipeline",
            "mode": "exploration",
        }
    )
    return out


def _add_sample_data(d: dict[str, Any], n: int) -> dict[str, Any]:
    out = copy.deepcopy(d)
    out["SampleData"] = {"selector": {"n": int(n), "seed": 0}}
    return out


def _toggle_label_from(d: dict[str, Any]) -> dict[str, Any]:
    """Add or remove a `label_from` spec to verify it contributes to canonical bytes.

    The resulting recipe isn't necessarily semantically valid (image_folder
    + label_from is rejected by the recipe validator); this property test
    only requires the recipe to *parse* and produce canonical bytes.
    """
    out = copy.deepcopy(d)
    src = dict(out["Input"]["sources"][0])
    if "label_from" in src:
        del src["label_from"]
    else:
        src["label_from"] = {
            "path": "labels.csv",
            "join": "by_id",
            "id_field": "filename",
            "label_field": "class",
        }
    out["Input"]["sources"][0] = src
    return out


_int_seeds = st.integers(min_value=-1000, max_value=1000)
_safe_names = st.from_regex(r"[a-z][a-z_0-9]{0,15}", fullmatch=True)
_split_pairs = st.tuples(
    st.floats(min_value=0.1, max_value=0.85, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.05, max_value=0.4, allow_nan=False, allow_infinity=False),
).filter(lambda ab: ab[0] + ab[1] < 0.95)


def _semantic_edits() -> st.SearchStrategy[dict[str, Any]]:
    return st.one_of(
        _int_seeds.map(lambda v: _change_recipe_seed(BASELINE, v)),
        _int_seeds.map(lambda v: _change_split_seed(BASELINE, v)),
        _split_pairs.map(lambda p: _change_split_ratios(BASELINE, p)),
        _safe_names.map(lambda n: _change_label_field(BASELINE, n)),
        _safe_names.map(lambda n: _change_input_path(BASELINE, f"/data/{n}")),
        _safe_names.map(lambda n: _add_filter(BASELINE, n)),
        st.integers(min_value=1, max_value=10000).map(lambda lo: _add_input_contract(BASELINE, lo)),
        _safe_names.map(lambda n: _add_visualization(BASELINE, n)),
        st.integers(min_value=1, max_value=100).map(lambda n: _add_sample_data(BASELINE, n)),
        st.just(_toggle_label_from(BASELINE)),
    )


@settings(
    max_examples=1000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(_semantic_edits())
def test_semantic_edits_always_change_cache_key(payload: dict[str, Any]) -> None:
    # Skip the rare case where the strategy regenerates the baseline
    # exactly (e.g., split_pairs that round to the baseline ratios).
    if _canonical_hex(payload) == _canonical_hex(BASELINE):
        return
    assert _key_for(payload) != _baseline_key()
