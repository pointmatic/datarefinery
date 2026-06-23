# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Story K.d: check 30 — `npy_per_record` sink must persist a pre-normalize field.

Egress analogue of check 26. An `npy_per_record` sink rewrites a per-record
`feature_path`; the blessed audio consumption contract persists the raw `mel`
(pre-normalize) so the consumer applies the fit-on-train `audio_normalize`
statistics at load. Targeting the already-normalized `feature` (the output of a
fit-on-train Featurization) would double-normalize at the consumer — refused here.
"""

from __future__ import annotations

from typing import Any

from datarefinery.plugins.audio_classification import PLUGIN as AUDIO_PLUGIN
from datarefinery.recipe.models import Recipe
from datarefinery.recipe.validator import CheckResult, ValidationReport, validate

_CHECK_ID = 30


def _base_dict(sinks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "plugin": "audio_classification",
        "seed": 0,
        "Input": {
            "sources": [
                {
                    "name": "clips",
                    "type": "audio_folder",
                    "path": "/data/clips",
                    "target_sample_rate": 16000,
                }
            ]
        },
        "Output": {
            "record_schema": {"sample_array": {"dtype": "float32"}, "label": {"dtype": "str"}}
        },
        "Labels": {"field": "label", "source": {"kind": "direct"}},
        "Splits": {"ratios": {"train": 0.5, "val": 0.5}},
        "Featurizations": [
            {
                "name": "logmel",
                "op": "log_mel_spectrogram",
                "inputs": ["sample_array"],
                "output_field": "mel",
                "params": {
                    "n_fft": 512,
                    "hop_length": 256,
                    "n_mels": 8,
                    "f_min": 0.0,
                    "power": 2.0,
                },
                "splits": ["train", "val"],
            },
            {
                "name": "norm",
                "op": "audio_normalize",
                "inputs": ["mel"],
                "output_field": "feature",
                "fit_source": "train",
                "splits": ["train", "val"],
            },
        ],
        "Sinks": sinks,
    }


def _npy_sink(field: str) -> dict[str, Any]:
    return {
        "name": "feats",
        "stage": "post_Featurizations",
        "field": field,
        "format": "npy_per_record",
        "path_template": "features/{split}/{record_id}.npy",
    }


def _results(report: ValidationReport, check_id: int) -> list[CheckResult]:
    return [r for r in report.results if r.check_id == check_id]


def test_check_30_passes_when_sink_targets_pre_normalize_mel() -> None:
    report = validate(Recipe.model_validate(_base_dict([_npy_sink("mel")])), AUDIO_PLUGIN)
    failures = [r for r in _results(report, _CHECK_ID) if r.status == "fail"]
    assert failures == []


def test_check_30_fails_when_sink_targets_normalized_feature() -> None:
    report = validate(Recipe.model_validate(_base_dict([_npy_sink("feature")])), AUDIO_PLUGIN)
    failures = [r for r in _results(report, _CHECK_ID) if r.status == "fail"]
    assert len(failures) == 1
    msg = failures[0].message
    # Message names the offending op so the author can fix it.
    assert "norm" in msg and "feature" in msg


def test_check_30_ignores_png_sinks() -> None:
    # A png_per_record sink targeting a normalized field is not this check's
    # concern (it does not rewrite feature_path).
    png = {
        "name": "imgs",
        "stage": "post_Featurizations",
        "field": "feature",
        "format": "png_per_record",
        "path_template": "imgs/{split}/{record_id}.png",
    }
    report = validate(Recipe.model_validate(_base_dict([png])), AUDIO_PLUGIN)
    failures = [r for r in _results(report, _CHECK_ID) if r.status == "fail"]
    assert failures == []


def test_check_30_passes_with_no_sinks() -> None:
    report = validate(Recipe.model_validate(_base_dict([])), AUDIO_PLUGIN)
    failures = [r for r in _results(report, _CHECK_ID) if r.status == "fail"]
    assert failures == []
