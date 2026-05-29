# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""FR-GEN-1 / Story H.m.2 tests for `imagecorruptions_apply`.

Exercises determinism, output count formula, ``preserve_original``,
tag-field writes, recipe-level validation, and the extras-missing
``ImportError`` path. Determinism across workers=1/2/4 is checked
end-to-end via the `pipeline.workers.run_parallel` contract.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping
from typing import Any, cast
from unittest.mock import patch

import numpy as np
import pytest
from pydantic import ValidationError

# Most tests in this module invoke `imagecorruptions_apply`, which lazily
# imports `_corruptions` (cv2 / skimage). Skip cleanly when the
# `[corruptions]` extras aren't installed. The `test_friendly_import_error_…`
# test mocks the failure so it does not actually need extras absent; running it
# in CI (where extras *are* installed) still exercises the error path via the
# mock. Story H.n.4.
pytest.importorskip("cv2", reason="requires the [corruptions] extras (opencv-python-headless)")

from datarefinery.core.errors import MaterializeError
from datarefinery.pipeline.stages.generation import apply_generation
from datarefinery.pipeline.workers import run_parallel
from datarefinery.plugins.image_classification import PLUGIN as IMAGE_PLUGIN
from datarefinery.plugins.image_classification.generation_imagecorruptions import (
    CORRUPTIONS_EXTRAS_INSTALL_HINT,
    imagecorruptions_apply,
)
from datarefinery.recipe.models import (
    FieldSpec,
    GenerationOp,
    ImageCorruptionsApplyParams,
)

Record = Mapping[str, Any]


def _output_schema() -> dict[str, FieldSpec]:
    return {
        "record_id": FieldSpec(dtype="str"),
        "image": FieldSpec(dtype="uint8", shape=[64, 64, 3]),
        "path": FieldSpec(dtype="str"),
    }


def _input_records(n: int = 3) -> list[Record]:
    base_rng = np.random.default_rng(42)
    out: list[Record] = []
    for i in range(n):
        img = base_rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)
        out.append({"record_id": f"img_{i}", "image": img, "path": f"/data/{i}.png"})
    return out


def _gen_op(
    *,
    seed: int = 42,
    corruption_types: list[str] | None = None,
    severities: list[int] | None = None,
    preserve_original: bool = False,
    tag_fields: list[str] | None = None,
) -> GenerationOp:
    params: dict[str, Any] = {
        "corruption_types": corruption_types or ["gaussian_noise", "fog"],
        "severities": severities or [1, 3],
        "preserve_original": preserve_original,
    }
    if tag_fields is not None:
        params["tag_fields"] = tag_fields
    return GenerationOp(
        name="imagecorruptions_apply",
        inputs=["image"],
        output_schema=_output_schema(),
        seed=seed,
        params=params,
    )


# ---------------------------------------------------------------------------
# Output count formula
# ---------------------------------------------------------------------------


def test_output_count_matches_inputs_times_types_times_severities() -> None:
    records = _input_records(n=3)
    op = _gen_op(corruption_types=["gaussian_noise", "shot_noise"], severities=[1, 3])
    new = imagecorruptions_apply(
        records,
        seed=cast(int, op.seed),
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    assert len(new) == 3 * 2 * 2  # inputs * types * severities


def test_preserve_original_adds_one_extra_per_input() -> None:
    records = _input_records(n=3)
    op = _gen_op(
        corruption_types=["gaussian_noise"],
        severities=[3],
        preserve_original=True,
    )
    new = imagecorruptions_apply(
        records,
        seed=cast(int, op.seed),
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    # 3 inputs * 1 type * 1 severity + 3 preserved-originals.
    assert len(new) == 3 + 3
    preserved = [r for r in new if r.get("corruption") == "none"]
    assert len(preserved) == 3
    for r in preserved:
        assert r["severity"] == 0


# ---------------------------------------------------------------------------
# replace_input_records via the stage (Story I.q / G18)
# ---------------------------------------------------------------------------


def test_replace_input_records_replaces_split_via_stage() -> None:
    records = _input_records(n=3)
    op = _gen_op(corruption_types=["gaussian_noise", "shot_noise"], severities=[1, 3])
    op = op.model_copy(update={"replace_input_records": True})
    result = apply_generation(
        {"train": list(records)},
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
    )
    # replace=True → split holds only generated records: inputs * types * severities.
    assert result.counts_before == {"train": 3}
    assert result.counts_after == {"train": 3 * 2 * 2}


def test_replace_input_records_default_false_appends_via_stage() -> None:
    records = _input_records(n=3)
    op = _gen_op(corruption_types=["gaussian_noise", "shot_noise"], severities=[1, 3])
    assert op.replace_input_records is False
    result = apply_generation(
        {"train": list(records)},
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=_output_schema(),
    )
    # default → originals retained + generated appended.
    assert result.counts_after == {"train": 3 + 3 * 2 * 2}


# ---------------------------------------------------------------------------
# Tag-field writes
# ---------------------------------------------------------------------------


def test_tag_fields_default_written_on_each_output() -> None:
    records = _input_records(n=2)
    op = _gen_op(corruption_types=["gaussian_noise"], severities=[3])
    new = imagecorruptions_apply(
        records,
        seed=cast(int, op.seed),
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    for r in new:
        assert r["corruption"] == "gaussian_noise"
        assert r["severity"] == 3
        assert r["source_path"] in ("/data/0.png", "/data/1.png")


def test_tag_fields_dict_form_writes_under_authored_keys() -> None:
    records = _input_records(n=1)
    params: dict[str, Any] = {
        "corruption_types": ["gaussian_noise"],
        "severities": [3],
        "preserve_original": False,
        "tag_fields": {"corruption_kind": "corruption", "lvl": "severity"},
    }
    op = GenerationOp(
        name="imagecorruptions_apply",
        inputs=["image"],
        output_schema=_output_schema(),
        seed=42,
        params=params,
    )
    new = imagecorruptions_apply(
        records,
        seed=cast(int, op.seed),
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    assert new[0]["corruption_kind"] == "gaussian_noise"
    assert new[0]["lvl"] == 3
    # Canonical names are NOT used as keys when the dict form renames them.
    assert "corruption" not in new[0]
    assert "severity" not in new[0]
    # source_path was not declared in the dict, so it must not appear.
    assert "source_path" not in new[0]


def test_tag_fields_subset_only_writes_named() -> None:
    records = _input_records(n=1)
    op = _gen_op(
        corruption_types=["gaussian_noise"],
        severities=[3],
        tag_fields=["corruption"],
    )
    new = imagecorruptions_apply(
        records,
        seed=cast(int, op.seed),
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    assert new[0]["corruption"] == "gaussian_noise"
    assert "severity" not in new[0]
    assert "source_path" not in new[0]


def test_output_record_ids_are_unique_across_corruption_sweep() -> None:
    records = _input_records(n=3)
    op = _gen_op(corruption_types=["gaussian_noise", "fog"], severities=[1, 3])
    new = imagecorruptions_apply(
        records,
        seed=cast(int, op.seed),
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    ids = [r["record_id"] for r in new]
    assert len(set(ids)) == len(ids)  # all unique


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def _hash_corrupted_outputs(new_records: list[Record]) -> str:
    h = hashlib.sha256()
    for r in new_records:
        h.update(str(r["record_id"]).encode("utf-8"))
        h.update(b"|")
        h.update(np.asarray(r["image"]).tobytes())
    return h.hexdigest()


def test_same_seed_yields_byte_identical_outputs() -> None:
    records = _input_records(n=3)
    op = _gen_op()
    a = imagecorruptions_apply(
        records,
        seed=cast(int, op.seed),
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    b = imagecorruptions_apply(
        records,
        seed=cast(int, op.seed),
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    assert _hash_corrupted_outputs(a) == _hash_corrupted_outputs(b)


def test_different_seeds_change_outputs() -> None:
    records = _input_records(n=3)
    op_a = _gen_op(seed=1)
    op_b = _gen_op(seed=999)
    a = imagecorruptions_apply(
        records,
        seed=cast(int, op_a.seed),
        inputs=list(op_a.inputs),
        output_schema=op_a.output_schema,
        params=dict(op_a.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    b = imagecorruptions_apply(
        records,
        seed=cast(int, op_b.seed),
        inputs=list(op_b.inputs),
        output_schema=op_b.output_schema,
        params=dict(op_b.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    assert _hash_corrupted_outputs(a) != _hash_corrupted_outputs(b)


# ---------------------------------------------------------------------------
# Workers byte-identical (downstream determinism contract)
# ---------------------------------------------------------------------------


def _identity_worker(record: Record, prs: int) -> Record:
    del prs
    return dict(record)


@pytest.mark.slow
def test_workers_byte_identical_after_imagecorruptions_apply() -> None:
    """Generated records threaded through ``run_parallel`` at three
    worker counts must produce identical sequences.
    """
    records = _input_records(n=3)
    op = _gen_op()
    new = imagecorruptions_apply(
        records,
        seed=cast(int, op.seed),
        inputs=list(op.inputs),
        output_schema=op.output_schema,
        params=dict(op.params),
        label_field=None,
        op_name="imagecorruptions_apply",
    )
    # workers downstream needs each record to carry record_id; the op
    # already assigns unique IDs.
    baseline = [
        (r["record_id"], np.asarray(r["image"]).tobytes())
        for r in run_parallel(seed=cast(int, op.seed), fn=_identity_worker, items=new, workers=1)
    ]
    for workers in (2, 4):
        out = [
            (r["record_id"], np.asarray(r["image"]).tobytes())
            for r in run_parallel(
                seed=cast(int, op.seed), fn=_identity_worker, items=new, workers=workers
            )
        ]
        assert out == baseline


# ---------------------------------------------------------------------------
# End-to-end via the Generation stage
# ---------------------------------------------------------------------------


def test_generation_stage_concatenates_corrupted_records_into_split() -> None:
    records = _input_records(n=3)
    op = _gen_op(corruption_types=["gaussian_noise"], severities=[3])
    splits = {"train": list(records)}
    result = apply_generation(
        splits,
        [op],
        plugin=IMAGE_PLUGIN,
        output_record_schema=op.output_schema,
        label_field=None,
    )
    # Stage concatenates: train ends with 3 originals + 3 corruptions.
    assert result.counts_before == {"train": 3}
    assert result.counts_after == {"train": 6}


# ---------------------------------------------------------------------------
# Recipe-level validation
# ---------------------------------------------------------------------------


def test_unknown_corruption_name_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown corruption_types"):
        ImageCorruptionsApplyParams(corruption_types=["bogus"], severities=[1])


def test_duplicate_corruption_types_rejected() -> None:
    with pytest.raises(ValidationError, match="corruption_types contains duplicates"):
        ImageCorruptionsApplyParams(
            corruption_types=["gaussian_noise", "gaussian_noise"], severities=[1]
        )


def test_severity_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError, match=r"\[1, 5\]"):
        ImageCorruptionsApplyParams(corruption_types=["gaussian_noise"], severities=[6])


def test_duplicate_severities_rejected() -> None:
    with pytest.raises(ValidationError, match="severities contains duplicates"):
        ImageCorruptionsApplyParams(corruption_types=["gaussian_noise"], severities=[3, 3])


def test_empty_corruption_types_rejected() -> None:
    with pytest.raises(ValidationError):
        ImageCorruptionsApplyParams(corruption_types=[], severities=[1])


def test_empty_severities_rejected() -> None:
    with pytest.raises(ValidationError):
        ImageCorruptionsApplyParams(corruption_types=["gaussian_noise"], severities=[])


# --- G13 (Story I.u): tag_fields dict-rename form ---


def test_tag_fields_dict_form_accepts_canonical_values() -> None:
    parsed = ImageCorruptionsApplyParams(
        corruption_types=["gaussian_noise"],
        severities=[1],
        tag_fields={"corruption_kind": "corruption", "lvl": "severity", "src": "source_path"},
    )
    assert parsed.tag_fields == {
        "corruption_kind": "corruption",
        "lvl": "severity",
        "src": "source_path",
    }


def test_tag_fields_dict_form_rejects_unknown_canonical_value() -> None:
    with pytest.raises(ValidationError, match="bogus"):
        ImageCorruptionsApplyParams(
            corruption_types=["gaussian_noise"],
            severities=[1],
            tag_fields={"a": "corruption", "b": "bogus"},
        )


def test_tag_fields_dict_form_rejects_duplicate_canonical_values() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        ImageCorruptionsApplyParams(
            corruption_types=["gaussian_noise"],
            severities=[1],
            tag_fields={"a": "corruption", "b": "corruption"},
        )


# ---------------------------------------------------------------------------
# Input shape validation at op-call time
# ---------------------------------------------------------------------------


def test_record_missing_image_field_raises() -> None:
    records: list[Record] = [{"record_id": "x", "path": "/p"}]
    op = _gen_op(corruption_types=["gaussian_noise"], severities=[3])
    with pytest.raises(MaterializeError, match="missing 'image'"):
        imagecorruptions_apply(
            records,
            seed=cast(int, op.seed),
            inputs=list(op.inputs),
            output_schema=op.output_schema,
            params=dict(op.params),
            label_field=None,
            op_name="imagecorruptions_apply",
        )


def test_record_with_non_uint8_image_raises() -> None:
    bad_img = np.zeros((64, 64, 3), dtype=np.float32)
    records: list[Record] = [{"record_id": "x", "image": bad_img, "path": "/p"}]
    op = _gen_op(corruption_types=["gaussian_noise"], severities=[3])
    with pytest.raises(MaterializeError, match="uint8"):
        imagecorruptions_apply(
            records,
            seed=cast(int, op.seed),
            inputs=list(op.inputs),
            output_schema=op.output_schema,
            params=dict(op.params),
            label_field=None,
            op_name="imagecorruptions_apply",
        )


# ---------------------------------------------------------------------------
# Extras-missing ImportError path
# ---------------------------------------------------------------------------


def test_friendly_import_error_when_backend_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """If `_corruptions` cannot be imported (e.g., extras absent), the
    op call surfaces a friendly install-pointer message rather than the
    bare module-not-found.
    """
    real_import = (
        __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
    )

    def _fail_corruptions(name: str, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        if name.endswith("_corruptions") or "_corruptions" in fromlist:
            raise ImportError("No module named 'cv2'")
        return real_import(name, globals, locals, fromlist, level)

    # Drop the already-imported backend so the lazy reimport runs.
    monkeypatch.delitem(
        sys.modules, "datarefinery.plugins.image_classification._corruptions", raising=False
    )

    with patch("builtins.__import__", side_effect=_fail_corruptions):
        records = _input_records(n=1)
        op = _gen_op(corruption_types=["gaussian_noise"], severities=[3])
        with pytest.raises(ImportError, match="ml-datarefinery\\[corruptions\\]"):
            imagecorruptions_apply(
                records,
                seed=cast(int, op.seed),
                inputs=list(op.inputs),
                output_schema=op.output_schema,
                params=dict(op.params),
                label_field=None,
                op_name="imagecorruptions_apply",
            )


def test_install_hint_string_mentions_extras() -> None:
    assert "ml-datarefinery[corruptions]" in CORRUPTIONS_EXTRAS_INSTALL_HINT
