# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-17 deterministic image-classification scaffolder.

Produces a starter recipe from a raw image directory with the
ImageFolder convention (``<root>/<class_name>/<file>.{png,jpg,jpeg}``).
The deterministic path is offline and never imports the optional
``lmentry`` extra (per features.md FR-17 #2 + tech-spec); LLM
enhancement is opt-in and lives in ``scaffolder.llm``.

The scaffolded recipe is sufficient for CIFAR-10-scale data unaided
(features.md FR-17 #1): it declares ``Input``, ``Output`` (record
schema inferred from the first image's dimensions and dtype),
``Labels`` (derived via the ``label_from_path`` featurization),
``Splits`` (70/15/15 stratified by label), reporting visualizations,
and ships a commented-out block of suggested ``Transformations`` for
the user to uncomment and tune.

v1 supports image_classification only; tabular and text recipes are
written by hand against the stub plugins.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from datarefinery.core.errors import PluginError, RecipeError

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

_NON_IMAGE_REFUSAL = (
    "init scaffolder not available for this category in v1; "
    "write recipe manually against the stub plugin sections."
)


def scaffold(
    input_path: Path,
    output_path: Path,
    *,
    plugin: str = "image_classification",
    enhance: bool = False,
) -> None:
    """Top-level scaffold entry point dispatching on plugin category."""
    if plugin != "image_classification":
        raise PluginError(_NON_IMAGE_REFUSAL)
    scaffold_image_classification(input_path, output_path, enhance=enhance)


def scaffold_image_classification(
    input_path: Path,
    output_path: Path,
    *,
    enhance: bool = False,
) -> None:
    """Inspect ``input_path`` and emit a starter recipe to ``output_path``.

    On ``enhance=True`` the optional ``lmentry`` layer is invoked via
    lazy import (``scaffolder.llm.enhance``); ``lmentry`` is never
    imported on the deterministic path.
    """
    classes, image_shape, image_dtype = _inspect_image_folder(Path(input_path))
    recipe = _build_recipe(Path(input_path), classes, image_shape, image_dtype)
    notes: list[str] = []

    if enhance:
        from datarefinery.scaffolder.llm import enhance as llm_enhance

        recipe, llm_notes = llm_enhance(recipe)
        notes.extend(llm_notes)

    yaml_text = _to_yaml(recipe, notes=notes)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def _inspect_image_folder(
    input_path: Path,
) -> tuple[list[str], list[int], str]:
    """Return ``(class_names, first_image_shape, first_image_dtype)``.

    Raises :class:`RecipeError` if the directory layout doesn't look
    like an ImageFolder (no class subdirs, or no images).
    """
    if not input_path.is_dir():
        raise RecipeError(f"scaffolder: input path {input_path!s} is not a directory")
    classes = sorted(p.name for p in input_path.iterdir() if p.is_dir())
    if not classes:
        raise RecipeError(
            f"scaffolder: no class subdirectories found under "
            f"{input_path!s}; expected ImageFolder layout "
            f"(<root>/<class>/<file>.png)"
        )

    first_image: Path | None = None
    for cls in classes:
        cls_dir = input_path / cls
        for ext in _IMAGE_EXTENSIONS:
            for candidate in sorted(cls_dir.glob(f"*{ext}")):
                first_image = candidate
                break
            if first_image is not None:
                break
        if first_image is not None:
            break
    if first_image is None:
        raise RecipeError(
            f"scaffolder: no image files (.png/.jpg/.jpeg) found under {input_path!s}"
        )

    arr = np.asarray(Image.open(first_image))
    shape = list(arr.shape)
    dtype = str(arr.dtype)
    return classes, shape, dtype


# ---------------------------------------------------------------------------
# Recipe construction
# ---------------------------------------------------------------------------


def _build_recipe(
    input_path: Path,
    classes: list[str],
    image_shape: list[int],
    image_dtype: str,
) -> dict[str, Any]:
    """Assemble the deterministic starter recipe dict."""
    return {
        "schema_version": 1,
        "plugin": "image_classification",
        "seed": 0,
        "Input": {
            "sources": [
                {
                    "name": "train",
                    "type": "image_folder",
                    "path": str(input_path),
                }
            ]
        },
        "Output": {
            "record_schema": {
                "image": {"dtype": image_dtype, "shape": image_shape},
                "label": {"dtype": "str"},
                # `path` is the input-source filesystem reference; the
                # `label_from_path` featurization reads it. Declared
                # here so validator check 7 sees it in the field
                # universe and so it survives into the persisted
                # dataset for downstream traceability.
                "path": {"dtype": "str"},
            }
        },
        "Labels": {
            "field": "label",
            "source": {
                "kind": "derived",
                "derivation": "parent_directory_name",
            },
        },
        "Splits": {
            "ratios": {"train": 0.7, "val": 0.15, "test": 0.15},
            "seed": 11,
            "stratify_by": "label",
        },
        "Featurizations": [
            {
                "name": "derive_label",
                "inputs": ["path"],
                "output_field": "label",
                "op": "label_from_path",
                "params": {"source": "parent_directory_name"},
                "splits": ["train", "val", "test"],
            }
        ],
        "Visualizations": [
            {
                "name": "class_distribution",
                "op": "class_distribution_histogram",
                "params": {},
                "stage": "post_pipeline",
                "mode": "reporting",
            },
            {
                "name": "samples",
                "op": "sample_grid",
                "params": {"n": 16, "per_class": True},
                "stage": "post_pipeline",
                "mode": "reporting",
            },
        ],
    }


# ---------------------------------------------------------------------------
# YAML serialization with commented-out Transformations stubs
# ---------------------------------------------------------------------------


_SUGGESTED_TRANSFORMATIONS = """\
# ---------------------------------------------------------------------------
# Suggested Transformations (uncomment & adjust as needed):
# ---------------------------------------------------------------------------
# Transformations:
#   - name: resize
#     op: resize
#     params: { size: 32, method: bilinear }
#     splits: [train, val, test]
#   - name: normalize
#     op: normalize
#     fit_source: train
#     splits: [train, val, test]
"""


def _to_yaml(recipe: Mapping[str, Any], *, notes: list[str]) -> str:
    """Serialize the recipe with a commented header + suggestions footer."""
    header_lines = [
        "# Generated by datarefinery scaffolder (FR-17, image_classification).",
        "# Edit and re-run `datarefinery validate` after changes.",
    ]
    for note in notes:
        header_lines.append(f"# Note: {note}")
    header = "\n".join(header_lines) + "\n\n"

    body = yaml.safe_dump(dict(recipe), sort_keys=False, default_flow_style=False, indent=2)
    return header + body + "\n" + _SUGGESTED_TRANSFORMATIONS
