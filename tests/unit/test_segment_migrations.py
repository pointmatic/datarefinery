# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.7: per-segment migration registry + loader dispatch.

The flat ``schema_version`` stays the on-disk era marker (Option 1 — the recipe
is flat on disk); per-segment versions live as build constants, and the loader
replays the registered ``(segment, from, to)`` migrations to bring each segment
up to the current build version on the read path. While every segment sits at
the current era (the steady state for the whole pre-1.0 lifetime so far) the
dispatch is an exact pass-through, so the read path never perturbs canonical
bytes while the registry is dormant. See the
[design memo](../../docs/specs/phase-j-recipe-architecture-design.md) Q4.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from datarefinery.recipe import segments as seg


@contextmanager
def _registered(key: tuple[str, int, int], fn: Any) -> Iterator[None]:
    """Temporarily register a per-segment migration, restoring the registry."""
    seg.SEGMENT_MIGRATIONS[key] = fn
    try:
        yield
    finally:
        seg.SEGMENT_MIGRATIONS.pop(key, None)


# ---------------------------------------------------------------------------
# Version maps
# ---------------------------------------------------------------------------


def test_current_segment_versions_are_all_one() -> None:
    assert seg.current_segment_versions() == {
        "core": 1,
        "plugin:image": 1,
        "plugin:audio": 1,
        "overlays": 1,
        "extensions": 1,
    }


def test_segment_versions_for_the_segmented_era() -> None:
    assert seg.segment_versions_for_era(seg.SEGMENTED_ERA) == seg.current_segment_versions()


def test_segment_versions_for_unknown_era_raises() -> None:
    with pytest.raises(KeyError):
        seg.segment_versions_for_era(999)


# ---------------------------------------------------------------------------
# apply_segment_migrations — steady-state pass-through
# ---------------------------------------------------------------------------


def _flat() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "plugin": "image_classification",
        "seed": 7,
        "Input": {"sources": [{"name": "t", "type": "image_folder", "path": "/d"}]},
        "Filters": [{"name": "f", "op": "drop_by_label", "params": {"labels": ["x"]}}],
    }


def test_pass_through_when_versions_match_returns_input_unchanged() -> None:
    flat = _flat()
    same = seg.current_segment_versions()
    out = seg.apply_segment_migrations(flat, same, same)
    assert out is flat  # exact identity — no copy, no perturbation


# ---------------------------------------------------------------------------
# apply_segment_migrations — replaying a registered migration
# ---------------------------------------------------------------------------


def test_core_migration_runs_and_leaves_other_segments_untouched() -> None:
    def _bump_seed(core: dict[str, Any]) -> dict[str, Any]:
        out = dict(core)
        out["seed"] = out["seed"] + 100
        return out

    frm = seg.current_segment_versions()
    to = {**frm, "core": 2}
    with _registered(("core", 1, 2), _bump_seed):
        out = seg.apply_segment_migrations(_flat(), frm, to)
    assert out["seed"] == 107  # core field migrated
    assert out["Filters"] == _flat()["Filters"]  # plugin segment untouched


def test_plugin_family_migration_only_applies_to_its_own_family() -> None:
    def _tag_filters(plugin_seg: dict[str, Any]) -> dict[str, Any]:
        out = dict(plugin_seg)
        out["Filters"] = [{**f, "migrated": True} for f in out.get("Filters", [])]
        return out

    frm = seg.current_segment_versions()
    to = {**frm, "plugin:image": 2}
    with _registered(("plugin:image", 1, 2), _tag_filters):
        # image recipe → migration applies
        image_out = seg.apply_segment_migrations(_flat(), frm, to)
        assert image_out["Filters"][0]["migrated"] is True
        # audio recipe → the image-family migration is skipped
        audio_flat = {**_flat(), "plugin": "audio_classification"}
        audio_out = seg.apply_segment_migrations(audio_flat, frm, to)
        assert "migrated" not in audio_out["Filters"][0]


def test_missing_migration_for_a_version_gap_raises() -> None:
    frm = seg.current_segment_versions()
    to = {**frm, "core": 2}  # no ("core", 1, 2) registered
    with pytest.raises(ValueError, match="no segment migration registered"):
        seg.apply_segment_migrations(_flat(), frm, to)


def test_overlays_migration_drops_to_nothing_when_emptied() -> None:
    def _empty_overlays(_overlays: dict[str, Any]) -> dict[str, Any]:
        return {}

    flat = {**_flat(), "overlays": {"fast": {"Augmentations": []}}}
    frm = seg.current_segment_versions()
    to = {**frm, "overlays": 2}
    with _registered(("overlays", 1, 2), _empty_overlays):
        out = seg.apply_segment_migrations(flat, frm, to)
    assert "overlays" not in out  # emptied segment is dropped, not left as {}


# ---------------------------------------------------------------------------
# Loader read-path integration
# ---------------------------------------------------------------------------


def test_loader_replays_a_registered_segment_migration(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A core bump + registered migration is applied on the read path, so the
    loaded recipe reflects the latest segmented shape."""
    from pathlib import Path

    import yaml

    from datarefinery.recipe import loader

    def _bump_seed(core: dict[str, Any]) -> dict[str, Any]:
        out = dict(core)
        out["seed"] = out["seed"] + 100
        return out

    # Simulate a core v1 -> v2 bump in this build.
    bumped = {**seg.current_segment_versions(), "core": 2}
    monkeypatch.setattr(loader, "current_segment_versions", lambda: bumped)
    path = Path(tmp_path) / "recipe.yaml"
    recipe_dict = {**_flat(), "schema_version": 3}
    recipe_dict["Output"] = {"record_schema": {"label": {"dtype": "int32"}}}
    recipe_dict["Labels"] = {"field": "label", "source": {"kind": "direct"}}
    recipe_dict["Splits"] = {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}}
    path.write_text(yaml.safe_dump(recipe_dict), encoding="utf-8")

    with _registered(("core", 1, 2), _bump_seed):
        recipe = loader.load(path)
    assert recipe.seed == 107  # 7 + 100 — the migration ran on load


def test_loader_is_a_pass_through_in_the_steady_state(tmp_path: Any) -> None:
    """With no segment bumped (today), the read path applies no segment
    migration — the loaded recipe matches a direct model_validate."""
    from pathlib import Path

    import yaml

    from datarefinery.recipe import loader
    from datarefinery.recipe.models import Recipe

    recipe_dict = {**_flat(), "schema_version": 3}
    recipe_dict["Output"] = {"record_schema": {"label": {"dtype": "int32"}}}
    recipe_dict["Labels"] = {"field": "label", "source": {"kind": "direct"}}
    recipe_dict["Splits"] = {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}}
    path = Path(tmp_path) / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe_dict), encoding="utf-8")

    assert loader.load(path) == Recipe.model_validate(recipe_dict)
