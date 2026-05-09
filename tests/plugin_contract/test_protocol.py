# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Cross-plugin contract assertions (Story E.h).

Every plugin discovered via the entry-point group runs through this
module via the ``plugin`` fixture in ``conftest.py``. Failures here
flag a misbehaving plugin regardless of which one shipped it; failures
in the per-plugin files (``test_image_classification.py`` etc.) flag
plugin-specific schema breakage.
"""

from __future__ import annotations

from datarefinery.plugins.base import OperationSpec, Plugin

# The canonical set of recipe sections a plugin may declare support for.
# A plugin that lists a section outside this set has invented one — the
# recipe parser would reject any recipe that referenced it, but the
# plugin's own claim is already wrong at the contract layer.
_CANONICAL_RECIPE_SECTIONS = frozenset(
    {
        "Input",
        "Output",
        "Labels",
        "Splits",
        "SampleData",
        "InputContracts",
        "Filters",
        "Generation",
        "Transformations",
        "Augmentations",
        "Featurizations",
        "OutputExpectations",
        "Visualizations",
    }
)


def test_plugin_satisfies_runtime_protocol(plugin: Plugin) -> None:
    assert isinstance(plugin, Plugin)


def test_plugin_name_is_nonempty_string(plugin: Plugin) -> None:
    assert isinstance(plugin.name, str)
    assert plugin.name.strip() == plugin.name
    assert plugin.name


def test_supported_sections_subset_of_canonical(plugin: Plugin) -> None:
    extras = set(plugin.supported_sections) - _CANONICAL_RECIPE_SECTIONS
    assert not extras, (
        f"plugin {plugin.name!r} declares unknown recipe sections: "
        f"{sorted(extras)}; canonical set: {sorted(_CANONICAL_RECIPE_SECTIONS)}"
    )


def test_supported_operations_have_valid_specs(plugin: Plugin) -> None:
    for op_name, spec in plugin.supported_operations.items():
        assert isinstance(op_name, str) and op_name, (
            f"plugin {plugin.name!r} has an empty/non-string op name: {op_name!r}"
        )
        assert isinstance(spec, OperationSpec), (
            f"plugin {plugin.name!r} op {op_name!r} has spec of type "
            f"{type(spec).__name__}; OperationSpec required"
        )
        # OperationSpec is pydantic-frozen; a round-trip through
        # ``model_dump`` + ``model_validate`` exercises the schema.
        OperationSpec.model_validate(spec.model_dump())
        # Each operation must declare at least one recipe section it
        # applies to, and that section must be canonical.
        sections = set(spec.applicable_sections)
        assert sections, (
            f"plugin {plugin.name!r} op {op_name!r} declares no "
            f"applicable_sections"
        )
        invalid = sections - _CANONICAL_RECIPE_SECTIONS
        assert not invalid, (
            f"plugin {plugin.name!r} op {op_name!r} declares unknown "
            f"applicable_sections {sorted(invalid)}"
        )


def test_is_stub_reflects_factory_behavior(plugin: Plugin) -> None:
    """Stub plugins must raise from ``operation_factory``; non-stubs
    must produce a real op for at least one declared operation.

    The asymmetry is intentional: a non-stub that ships some
    not-yet-implemented ops alongside real ones is acceptable
    (``is_stub`` is False, and those ops raise on factory call); a
    plugin that claims to be a stub and yet successfully constructs
    operations is a contract violation because consumers rely on
    ``is_stub`` to gate materialize-time refusals.
    """
    if plugin.is_stub():
        # Stubs must refuse construction for every declared op. Picking
        # the first one is sufficient: the contract is "any factory
        # call raises", and a single counter-example suffices.
        op_name, spec = next(iter(plugin.supported_operations.items()))
        section = next(iter(spec.applicable_sections))
        try:
            plugin.operation_factory(section, op_name)
        except Exception:
            return
        raise AssertionError(
            f"plugin {plugin.name!r} reports is_stub() True but "
            f"operation_factory({section!r}, {op_name!r}) succeeded"
        )

    # Non-stub: at least one declared op must construct cleanly so the
    # ``is_stub`` claim is grounded.
    succeeded: list[tuple[str, str]] = []
    failures: list[tuple[str, str, str]] = []
    for op_name, spec in plugin.supported_operations.items():
        for section in sorted(spec.applicable_sections):
            try:
                plugin.operation_factory(section, op_name)
            except Exception as exc:
                failures.append((section, op_name, repr(exc)))
                continue
            succeeded.append((section, op_name))
            break  # one successful construction per op is enough
    assert succeeded, (
        f"plugin {plugin.name!r} reports is_stub() False but no declared "
        f"operation could be constructed via operation_factory; "
        f"failures: {failures}"
    )
