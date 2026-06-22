# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story J.n.4: no-implicit-defaults discipline guard.

The interpreting code supplies no behavior-affecting value for an omitted op
parameter — a param is either ``required=True`` (the author writes it; the
scaffolder emits a recommended value) or a **mode-selecting optional** (absence
is itself the documented behavior). This file is the CI regression guard: it
fails if a ``ParameterSpec`` reintroduces a ``default`` (the silent-default
trapdoor) and pins the recommended-value home (``recommended_params``).

See the [design memo](../../docs/specs/phase-j-recipe-architecture-design.md) Q7
and ``project-essentials.md`` "Cache identity is the reproducibility contract".
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from datarefinery.plugins.base import OperationSpec, ParameterSpec
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.tabular import PLUGIN as TABULAR_PLUGIN
from datarefinery.plugins.text import PLUGIN as TEXT_PLUGIN

_ALL_PLUGINS = [IMAGE_PLUGIN, TEXT_PLUGIN, TABULAR_PLUGIN]


def test_parameter_spec_has_no_default_field() -> None:
    # The `default` field is gone — there is structurally nowhere for a
    # code-supplied default to live on a param declaration.
    assert "default" not in ParameterSpec.model_fields


def test_parameter_spec_rejects_a_default_kwarg() -> None:
    # extra="forbid" turns any reintroduced `default=` into a hard error at
    # construction — so a plugin author cannot silently re-add one.
    with pytest.raises(ValidationError):
        ParameterSpec(type="int", default=5)  # type: ignore[call-arg]


def test_no_registered_op_declares_a_parameter_default() -> None:
    for plugin in _ALL_PLUGINS:
        ops: dict[str, OperationSpec] = plugin.supported_operations
        for op_name, spec in ops.items():
            for param_name, param in spec.parameters.items():
                assert not hasattr(param, "default"), (
                    f"{plugin.name}:{op_name}.{param_name} reintroduced a "
                    f"ParameterSpec.default — that is the silent-default trapdoor "
                    f"no-implicit-defaults (J.n.4) exists to close."
                )


def test_recommended_params_is_the_home_for_removed_defaults() -> None:
    # The values that used to be ParameterSpec.default now live here.
    assert IMAGE_PLUGIN.recommended_params("Transformations", "resize") == {"method": "bilinear"}
    assert IMAGE_PLUGIN.recommended_params("Augmentations", "color_jitter") == {
        "brightness": 0.0,
        "contrast": 0.0,
        "saturation": 0.0,
        "hue": 0.0,
    }


def test_recommended_params_is_empty_for_ops_without_recommendations() -> None:
    # `normalize` is all-optional (mode-selecting mean/std); no recommendations.
    assert IMAGE_PLUGIN.recommended_params("Transformations", "normalize") == {}
    assert IMAGE_PLUGIN.recommended_params("Filters", "does_not_exist") == {}


def test_normalize_mean_std_stay_mode_selecting_optionals() -> None:
    # The lone kept optionals: absence ⇒ "fit from train" (a documented mode,
    # not a substituted value).
    normalize = IMAGE_PLUGIN.supported_operations["normalize"]
    assert normalize.parameters["mean"].required is False
    assert normalize.parameters["std"].required is False
