# Plugin authoring guide

A DataRefinery **plugin** specializes the recipe pipeline for one data category. The plugin declares which recipe sections it supports, which operations are available within those sections, and the parameter schema for each operation; it then supplies the operation implementations at materialize time.

v1 ships three plugins out of the box (see [`src/datarefinery/plugins/`](../../src/datarefinery/plugins/)):

- `image_classification` — full implementation (Filters, Generation, Transformations, Featurizations, Augmentations, Visualizations).
- `tabular` — stub: schemas declared, `operation_factory` refuses.
- `text` — stub: schemas declared, `operation_factory` refuses.

This guide walks through writing a third-party plugin from scratch. For background on the recipe surface plugins target, see the [recipe authoring guide](recipe-authoring.md) and [`features.md`](../specs/features.md) (FR-16). For the protocol itself, see [`plugins/base.py`](../../src/datarefinery/plugins/base.py).

## The Plugin protocol

Every plugin satisfies the runtime-checkable `Plugin` protocol declared in [`plugins/base.py`](../../src/datarefinery/plugins/base.py):

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Plugin(Protocol):
    name: str
    supported_sections: frozenset[str]
    supported_operations: dict[str, OperationSpec]
    schema_version: int

    def operation_factory(self, section: str, op_name: str) -> Operation: ...
    def is_stub(self) -> bool: ...
    def recommended_params(self, section: str, op_name: str) -> dict[str, Any]: ...
```

Required attributes:

| Attribute | Type | Purpose |
|-----------|------|---------|
| `name` | `str` | Globally unique plugin name. The recipe's top-level `plugin:` field refers to this. Discovery rejects duplicate names. |
| `supported_sections` | `frozenset[str]` | The recipe section names this plugin handles. Must be a subset of the 13 canonical recipe sections (see below). |
| `supported_operations` | `dict[str, OperationSpec]` | Per-operation parameter and section metadata. The validator cross-checks every recipe operation against this map (FR-2 check 18). |
| `schema_version` | `int` | The plugin's schema version. Bumped when the operation set, parameter schema, or supported-section list changes in a way recipes need to opt into. |
| `operation_factory(section, op_name)` | callable | Returns the runtime handle for one operation. The pipeline runner calls this at materialize time. |
| `is_stub()` | `bool` | `True` if the plugin declares schemas but does not implement operations; consumers gate materialize-time refusals on this. |
| `recommended_params(section, op_name)` | callable → `dict` | Recommended starting values for an op's parameters (Story J.n.4) — the home for the values the scaffolder bakes into a scaffolded recipe, replacing the removed `ParameterSpec.default`. Return `{}` for an op with no recommendations. |

The 13 canonical recipe sections (asserted by the plugin contract test
suite in
[`tests/plugin_contract/test_protocol.py`](../../tests/plugin_contract/test_protocol.py)):

```text
Input  Output  Labels  Splits  SampleData
InputContracts  Filters  Generation  Transformations
Augmentations  Featurizations  OutputExpectations  Visualizations
```

A plugin declaring a section outside this set is wrong at the contract layer — the recipe parser will refuse any recipe that references the invented section, and the plugin contract tests will fail.

## `OperationSpec` schema

Each entry in `supported_operations` is an `OperationSpec` (pydantic v2, frozen, `extra="forbid"`):

```python
from pydantic import BaseModel, ConfigDict, Field

class ParameterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: str                    # e.g. "int", "float", "str", "bool", "list[int]"
    required: bool = True        # no `default` field — see "No implicit defaults" below
    description: str | None = None

class OperationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
    fit_on_train: bool = False
    applicable_splits: frozenset[str] = frozenset({"train", "val", "test"})
    applicable_sections: frozenset[str]      # required, non-empty
```

Field-by-field:

- **`parameters`** — per-parameter type and required-ness. The validator (check 18) refuses a recipe op whose `params` references an unknown key, omits a required key, or supplies a value whose Python type does not match `ParameterSpec.type`. Keep parameter names stable across plugin versions; renaming one is a breaking change for every recipe that uses it.

  **No implicit defaults (the required-vs-mode-selecting rule).** `ParameterSpec` has no `default` field — the interpreting code must never substitute a value for an omitted param. Classify every parameter as exactly one of:
  - **Required** (`required=True`) — the author must write a value. This is the default classification. The recommended starting value lives in your plugin's `recommended_params(section, op)` (below), which the scaffolder emits into recipe text. Adding a *new* required param to an existing op is **breaking** (existing recipes omit it) → bump your plugin segment version.
  - **Mode-selecting optional** (`required=False`) — only when *absence is itself the documented behavior* (e.g. `normalize.mean`/`std` absent ⇒ "fit from train"), never as a stand-in for a value the code would otherwise fill in. The "absent ⇒ behavior" mapping is part of your versioned contract. Adding a mode-selecting optional is **free** (non-adopting recipes are untouched; sparse hashing).

  This dissolves the silent-default trapdoor: with no implicit defaults there are no omitting recipes, so a code change can never move a recipe's outcome without changing its canonical bytes. (Story J.n.4; the regression guard `tests/unit/test_no_implicit_defaults.py` fails CI if any `ParameterSpec` reintroduces a `default`.)
- **`fit_on_train`** — set to `True` for ops that compute statistics from the training split (normalize, standardize, encoders). Once `fit_on_train` is set, the recipe's `fit_source` must be exactly `"train"` (validator check 6). The pipeline writes the fitted output to `fitted_statistics/<op_name>/`.
- **`applicable_splits`** — restricts which splits a recipe may target with this operation. Augmentations are typically declared `frozenset({"train"})` so the validator rejects any recipe that applies them to val/test (check 5). For ops that legitimately apply to every split, leave the default.
- **`applicable_sections`** — required and non-empty. Names the recipe sections this operation may appear in. A normalize op declares `frozenset({"Transformations"})`; a histogram declares `frozenset({"Visualizations"})`. Operations may declare more than one section, but the runner dispatches per `(section, op_name)` pair via `operation_factory`.

## Operation handles

`operation_factory(section, op_name)` returns the *handle* for one operation. Different pipeline stages expect different handle shapes; the pipeline modules under [`src/datarefinery/pipeline/stages/`](../../src/datarefinery/pipeline/stages/) declare the per-stage Protocol classes.

A non-exhaustive summary:

| Section | Handle shape |
|---------|--------------|
| `Filters` | Callable: `(records, params, *, label_field) -> list[Record]`. See [`filters.py`](../../src/datarefinery/pipeline/stages/filters.py). |
| `Generation` | Callable returning generated records. See [`generation.py`](../../src/datarefinery/pipeline/stages/generation.py). |
| `Transformations` | Object with `fit(records, params, *, label_field) -> FittedValues` and `apply(records, params, fitted, *, label_field) -> list[Record]`, plus a class-level `fit_on_train: bool` mirroring the `OperationSpec`. See [`transformations.py`](../../src/datarefinery/pipeline/stages/transformations.py). |
| `Featurizations` | Same shape as Transformations, plus `inputs: list[str]` and `output_field: str` passed through `fit`/`apply`. See [`featurizations.py`](../../src/datarefinery/pipeline/stages/featurizations.py). |
| `Augmentations` | Declaration-only at materialize time — the recipe captures policy; ModelFoundry applies augmentation on-the-fly during training. See [`augmentations.py`](../../src/datarefinery/pipeline/stages/augmentations.py). |
| `Visualizations` | Object with `render(splits, *, params, stage, ...) -> bytes | None`. See [`visualizations.py`](../../src/datarefinery/pipeline/stages/visualizations.py). |

The `image_classification` plugin under
[`src/datarefinery/plugins/image_classification/operations/`](../../src/datarefinery/plugins/image_classification/operations/)
is the reference implementation for each handle shape — read
`filters.py` for a stateless-callable example, `transformations.py`
for the fit/apply convention, and `featurizations.py` for the
`inputs`/`output_field` extension.

## Discovery and registration

Plugins are discovered through two mechanisms — pick whichever fits the distribution model:

### 1. Entry-point group (production installs)

Declare the plugin in `pyproject.toml` under the `datarefinery.plugins` entry-point group. The entry-point value points to a module attribute that exposes a `Plugin`-conforming object (or a class that returns one when called with no arguments):

```toml
# In your plugin package's pyproject.toml
[project.entry-points."datarefinery.plugins"]
my_plugin = "my_plugin_package.plugin:PLUGIN"
```

DataRefinery's bundled plugins use exactly this form — see this project's [`pyproject.toml`](../../pyproject.toml) for the `image_classification`, `tabular`, and `text` entries.

After installing your package (`pip install your-plugin`), the plugin is discovered automatically; no DataRefinery configuration is needed.

### 2. `--plugin-path` (development and ad-hoc use)

For local development or one-off use without packaging, point `--plugin-path` at a `.py` file (or a directory of `.py` files). Each file must expose a top-level `PLUGIN` attribute satisfying the `Plugin` protocol; `discovery.py` imports the module in isolation and registers its `PLUGIN`.

```bash
datarefinery --plugin-path /path/to/my_plugin.py check
```

`--plugin-path` is repeatable; the equivalent environment variable is `DATAREFINERY_PLUGIN_PATH` (PATH-style colon-separated). Files whose name starts with `_` are skipped when scanning a directory.

### Discovery rules

- Plugin names must be globally unique across all discovery sources. Duplicates raise `PluginError("duplicate plugin name: ...")` at discovery time.
- Every discovered object is checked for the seven required attributes; missing any of them raises `PluginError("... does not satisfy the Plugin protocol")`.
- `datarefinery check` lists every discovered plugin with its `schema_version` and stub/active status — use it to confirm your plugin is loading before invoking `validate` or `materialize`.

## Stub vs. real plugins

The `is_stub()` method is part of the contract — consumers use it to distinguish "schemas declared, no implementation" plugins from real ones.

- **Real plugin (`is_stub() -> False`).** `operation_factory` returns a working handle for every declared operation (or raises `NotImplementedError` for ones not yet implemented, which is still a legitimate state — the bundled `image_classification` plugin initially shipped this way). Recipes targeting the plugin can materialize.
- **Stub plugin (`is_stub() -> True`).** `operation_factory` must raise `PluginError("stub plugin; not implemented")` for every declared operation. Recipes targeting a stub plugin **validate** clean (FR-2) but **refuse** at materialize time. The bundled `tabular` and `text` plugins are stubs and serve as starting templates for full third-party implementations of those categories.

The plugin contract test suite asserts both directions:

- A stub that successfully constructs an operation is a contract violation.
- A non-stub that raises from every operation is acceptable (it is legitimately in-progress), but `is_stub()` should return `False` only when the operations the recipe *uses* are real.

## Hello plugin walk-through

The minimal plugin below declares one Featurization op named `echo` that copies an input field to an output field. It is intentionally trivial — every contract surface is exercised, no domain logic distracts from the protocol.

Save the following as `hello_plugin.py`:

```python
# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Minimal `hello` plugin."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datarefinery.core.errors import PluginError
from datarefinery.pipeline.stages.transformations import FittedValues
from datarefinery.plugins.base import Operation, OperationSpec, ParameterSpec


class _EchoOp:
    """Featurization op: copy `inputs[0]` into `output_field`."""

    fit_on_train: bool = False

    def fit(
        self,
        records: list[Mapping[str, Any]],
        params: Mapping[str, Any],
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> FittedValues:
        del records, params, inputs, output_field, label_field
        return FittedValues()

    def apply(
        self,
        records: list[Mapping[str, Any]],
        params: Mapping[str, Any],
        fitted: FittedValues,
        *,
        inputs: list[str],
        output_field: str,
        label_field: str | None,
    ) -> list[Mapping[str, Any]]:
        del fitted, params, label_field
        if not inputs:
            raise PluginError("echo requires one input field")
        src = inputs[0]
        out: list[Mapping[str, Any]] = []
        for r in records:
            new = dict(r)
            new[output_field] = r.get(src)
            out.append(new)
        return out


class HelloPlugin:
    """Reference plugin: one Featurization op."""

    name = "hello"
    schema_version = 1
    supported_sections = frozenset(
        {"Input", "Output", "Labels", "Splits", "Featurizations"}
    )

    def __init__(self) -> None:
        self.supported_operations: dict[str, OperationSpec] = {
            "echo": OperationSpec(
                parameters={
                    # Required (the default classification) — no implicit
                    # default; the recommended value lives in recommended_params.
                    "_marker": ParameterSpec(type="str", required=True),
                },
                applicable_sections=frozenset({"Featurizations"}),
            ),
        }

    def operation_factory(self, section: str, op_name: str) -> Operation:
        if section == "Featurizations" and op_name == "echo":
            return _EchoOp()
        raise NotImplementedError(
            f"hello plugin has no op (section={section!r}, op={op_name!r})"
        )

    def is_stub(self) -> bool:
        return False

    def recommended_params(self, section: str, op_name: str) -> dict[str, Any]:
        # Recommended starting value the scaffolder emits for `echo._marker`.
        if (section, op_name) == ("Featurizations", "echo"):
            return {"_marker": "echo"}
        return {}


PLUGIN: Any = HelloPlugin()
```

And a minimal recipe at `hello-recipe.yaml` (substitute a real image-folder path under `Input.sources[0].path`):

```yaml
schema_version: 1
plugin: hello
seed: 0

Input:
  sources:
    - name: train
      type: image_folder
      path: /tmp/my-images

Output:
  record_schema:
    image: { dtype: uint8, shape: [8, 8, 3] }
    path:  { dtype: str }
    label: { dtype: str }

Labels:
  field: label
  source:
    kind: derived
    derivation: parent_directory_name

Splits:
  ratios: { train: 0.7, val: 0.15, test: 0.15 }
  seed: 11

Featurizations:
  - name: derive_label
    inputs: [path]
    output_field: label
    op: echo
    params: { _marker: hi }
    splits: [train, val, test]
```

Discover and validate:

```bash
datarefinery --plugin-path ./hello_plugin.py check
datarefinery --plugin-path ./hello_plugin.py validate hello-recipe.yaml
```

`check` lists `hello` alongside the bundled plugins with `status = active`; `validate` reports `20/20 checks passed`.

## Starting templates

The tabular and text stub plugins are the recommended starting points for a third-party plugin targeting those categories:

- [`src/datarefinery/plugins/tabular/plugin.py`](../../src/datarefinery/plugins/tabular/plugin.py)
  — section list and operation outlines for tabular pipelines (`filter_by_value`, `standardize`, `one_hot_encode`, `polynomial_features`, `field_summary_table`, etc.).
- [`src/datarefinery/plugins/text/plugin.py`](../../src/datarefinery/plugins/text/plugin.py) 
  — section list and operation outlines for text pipelines.

To turn either stub into a working plugin, copy it into your own package, flip `is_stub()` to `False`, and supply real `operation_factory` dispatch + handles for the operations you implement. Ops you have not implemented yet can stay in `supported_operations` and raise `NotImplementedError` from `operation_factory` — recipes that reference those particular ops will fail at materialize time with a clear message, while recipes that avoid them work normally.

## Versioning and stability

The plugin contract has three stability tiers:

- **`Plugin` protocol** — the seven required attributes. Changes here are coordinated across DataRefinery and every plugin.
- **`OperationSpec` / `ParameterSpec` shape** — adding fields is backwards-compatible; removing or renaming is breaking.
- **A specific plugin's `supported_operations`** — adding ops is backwards-compatible for that plugin's own recipes; renaming parameters or changing required-ness breaks recipes that reference them. Bump `schema_version` when this happens.

Prior to DataRefinery's production release (Story F.d), stub plugin section lists and operation outlines are explicitly free to change as image-plugin development reveals what the category-agnostic abstractions actually need. Post-production, those become part of the plugin-interface contract and change only via documented schema versioning.

## Where to go next

- The [recipe authoring guide](recipe-authoring.md) covers the recipe surface plugins target.
- [`plugins/base.py`](../../src/datarefinery/plugins/base.py) is the canonical Plugin / OperationSpec / ParameterSpec definition.
- [`plugins/discovery.py`](../../src/datarefinery/plugins/discovery.py) documents the discovery rules and error modes.
- [`tests/plugin_contract/`](../../tests/plugin_contract/) is the cross-plugin test harness. Its `conftest.py` parametrizes the generic contract assertions across every plugin discovered through the `datarefinery.plugins` entry-point group, so once your plugin is `pip install`-able your plugin is automatically opted into the suite. The generic assertions ([`test_protocol.py`](../../tests/plugin_contract/test_protocol.py)) are the cheapest way to verify your plugin satisfies the protocol-layer contract before any recipe exercises it.
