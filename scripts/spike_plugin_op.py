# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
#
# Spike (Phase C kickoff) — exercises the Plugin protocol from
# `datarefinery.plugins.base` end-to-end before the production
# image_classification plugin lands in C.b. Importing
# `OperationSpec`/`ParameterSpec` from src/ is intentional here: the
# point is to validate the abstraction against a real operation.
#
# Throwaway: don't import this script from src/. It's a one-off
# learning vehicle whose discoveries inform C.b (image plugin) and
# C.h (transformations stage runner).

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from datarefinery.plugins.base import OperationSpec, ParameterSpec

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRATCH = REPO_ROOT / "scratch" / "spike"
INPUTS = SCRATCH / "inputs"
OUTPUTS = SCRATCH / "outputs"

Record = dict[str, Any]


class _ResizeOperation:
    """Stateless resize: stores params at construction; record-in/record-out."""

    def __init__(self, size: int) -> None:
        self.size = size

    def __call__(self, record: Record) -> Record:
        img = record["image"]
        if not isinstance(img, np.ndarray):
            raise TypeError(
                f"expected numpy array for 'image', got {type(img).__name__}"
            )
        pil = Image.fromarray(img)
        resized = pil.resize((self.size, self.size), Image.Resampling.BILINEAR)
        return {**record, "image": np.asarray(resized)}


class _ImagePlugin:
    """Minimal in-memory `Plugin` satisfying the runtime protocol."""

    name = "spike_image"
    schema_version = 1
    supported_sections = frozenset(
        {"Input", "Output", "Labels", "Splits", "Transformations"}
    )

    def __init__(self) -> None:
        self.supported_operations = {
            "resize": OperationSpec(
                parameters={"size": ParameterSpec(type="int", required=True)},
                applicable_sections=frozenset({"Transformations"}),
            ),
        }

    def operation_factory(
        self, section: str, op_name: str
    ) -> Callable[[dict[str, Any]], Callable[[Record], Record]]:
        if (section, op_name) != ("Transformations", "resize"):
            raise KeyError(f"unsupported (section, op): {(section, op_name)}")
        return lambda params: _ResizeOperation(size=int(params["size"]))

    def is_stub(self) -> bool:
        return False


def _make_random_pngs(count: int = 3, edge: int = 64) -> list[Path]:
    if INPUTS.exists():
        shutil.rmtree(INPUTS)
    INPUTS.mkdir(parents=True)
    rng = np.random.default_rng(seed=42)
    paths: list[Path] = []
    for i in range(count):
        arr = rng.integers(0, 256, size=(edge, edge, 3), dtype=np.uint8)
        path = INPUTS / f"img_{i}.png"
        Image.fromarray(arr).save(path)
        paths.append(path)
    return paths


def main() -> int:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)

    paths = _make_random_pngs()
    plugin = _ImagePlugin()
    spec = plugin.supported_operations["resize"]
    required = [k for k, v in spec.parameters.items() if v.required]
    print(f"plugin={plugin.name!r} schema_version={plugin.schema_version}")
    print(f"resize required params: {required}")

    factory = plugin.operation_factory("Transformations", "resize")
    op = factory({"size": 16})

    for path in paths:
        img = np.asarray(Image.open(path))
        record_in: Record = {"image": img, "filename": path.name}
        record_out = op(record_in)
        out_arr = record_out["image"]
        Image.fromarray(out_arr).save(OUTPUTS / path.name)
        print(
            f"  {path.name}: in shape={img.shape} dtype={img.dtype} "
            f"-> out shape={out_arr.shape} dtype={out_arr.dtype}"
        )

    print(f"wrote {len(paths)} images under {OUTPUTS.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# Discoveries / friction notes for C.b (image plugin) and C.h
# (transformations stage runner)
# ---------------------------------------------------------------------------
#
# 1. Two-step factory: operation_factory(section, op_name) returns a
#    *params-binder*, not an Operation directly. The actual signature ended up
#    `factory(params: dict) -> Callable[[Record], Record]`. The recipe declares
#    params per op-instance, so the stage runner needs to bind them at runtime.
#    plugins/base.py currently aliases `Operation = Any`. C.b should formalize
#    this two-step shape — likely:
#       Operation = Callable[[Record], Record]
#       OperationFactory = Callable[[dict[str, Any]], Operation]
#    and tighten Plugin.operation_factory's return type accordingly.
#
# 2. Record convention. The spike uses dict[str, np.ndarray | str] keyed by
#    field name (matching recipe.Output.record_schema keys). C.h's runner will
#    iterate records through stages; sticking with the dict-flavored convention
#    keeps the field-name surface uniform from the recipe through the runner.
#    Consider a `Record = MutableMapping[str, Any]` type alias when this lands.
#
# 3. Pillow resampling. Image.Resampling.BILINEAR is the modern enum
#    (Image.BILINEAR is the deprecated alias). The image plugin's resize
#    should standardize on Image.Resampling.* across all resampling ops.
#
# 4. numpy/Pillow round-trip. np.asarray(PIL.Image) -> HxWxC uint8, and
#    Image.fromarray(uint8) reconstructs cleanly. dtype/shape preserved.
#
# 5. Error mapping. The spike raises plain TypeError on a non-array input
#    and KeyError on an unsupported (section, op_name). Production should
#    raise PluginError on unsupported requests (so the CLI maps to exit 2)
#    and a domain-specific error on per-record type violations during
#    materialize (likely MaterializeError so the CLI maps to exit 1).
#
# 6. Operation purity. Operations are pure record -> record functions in this
#    spike. They do NOT manage their own output paths; the runner owns the
#    temp dir and writes the materialized dataset. Document this contract on
#    the Plugin protocol so plugin authors don't bake in I/O inside ops.
#
# 7. operation_factory could equally be designed to take params directly:
#    `operation_factory(section, op_name, params) -> Operation`. The spike's
#    two-step binding is more flexible (you could cache the binder), but the
#    one-step form is simpler. C.b/C.h should pick one and document it.
