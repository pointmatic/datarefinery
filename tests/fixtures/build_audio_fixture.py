# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""Synthetic audio-classification fixture builder for tests (Story J.v).

The audio acceptance gate needs a tiny but realistic dataset exercising every
R1-R7 capability: multiple classes, varied clip durations, mixed *source* sample
rates (so decode-time canonicalization is exercised), and one unlabeled
partition (Kaggle-style heldout test). Real audio is far too large to vendor and
adds a licensing surface; this builder synthesizes deterministic sine
tones/sweeps with a seeded NumPy RNG so every machine produces byte-identical
WAVs at test time.

DO NOT check in real audio recordings here. The synthesizer keeps the suite
self-contained, fast, and license-free.

Layout produced::

    <root>/
      train/                      # labeled partition (audio_folder: class subdirs)
        alpha/ alpha_0.wav alpha_1.wav
        beta/  beta_0.wav  beta_1.wav
        gamma/ gamma_0.wav gamma_1.wav
      test/                       # unlabeled partition (audio_flat: bare files)
        clip_0.wav clip_1.wav clip_2.wav

6 labeled clips (3 classes x 2) + 3 unlabeled = 9 clips. Durations vary
(0.3s-0.6s) and source sample rates vary per class (22050 / 16000 / 8000 in
train; 11025 in test) so the loader's resample-to-`target_sample_rate` path is
exercised. `soundfile` is imported lazily so this module stays importable
without the `[audio]` extra; callers `pytest.importorskip("soundfile")` first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_SEED = 2026
DEFAULT_TARGET_RATE = 16000

#: (class_name, source_sample_rate, [clip_durations_seconds]) for the labeled
#: train partition. Durations are >= 0.3s so non-overlapping 0.1s windows yield
#: multiple windows per clip.
_TRAIN_CLASSES: list[tuple[str, int, list[float]]] = [
    ("alpha", 22050, [0.4, 0.6]),
    ("beta", 16000, [0.5, 0.3]),
    ("gamma", 8000, [0.6, 0.4]),
]
#: (filename_stem, source_sample_rate, duration_seconds) for the unlabeled test
#: partition (flat directory, no class subdirs).
_TEST_CLIPS: list[tuple[str, int, float]] = [
    ("clip_0", 11025, 0.5),
    ("clip_1", 11025, 0.3),
    ("clip_2", 11025, 0.4),
]


def _tone(rng: np.random.Generator, *, rate: int, seconds: float) -> np.ndarray:
    """A deterministic mono float32 sine tone + light noise (in [-1, 1])."""
    n = int(rate * seconds)
    t = np.arange(n, dtype=np.float64) / rate
    freq = float(rng.integers(200, 2000))
    signal = 0.6 * np.sin(2.0 * np.pi * freq * t)
    signal += 0.02 * rng.standard_normal(n)  # a touch of texture
    return np.clip(signal, -1.0, 1.0).astype(np.float32)


def build_audio_fixture(root: Path, *, seed: int = DEFAULT_SEED) -> Path:
    """Synthesize the audio fixture at ``root`` and return ``root``.

    Deterministic for a fixed ``seed`` (byte-identical WAVs across machines), so
    the materialized instance's input hash and dataset bytes are stable.
    """
    import soundfile as sf  # lazy: keeps the module importable without [audio]

    rng = np.random.default_rng(seed)
    train = root / "train"
    for class_name, rate, durations in _TRAIN_CLASSES:
        class_dir = train / class_name
        class_dir.mkdir(parents=True, exist_ok=True)
        for i, seconds in enumerate(durations):
            clip = _tone(rng, rate=rate, seconds=seconds)
            sf.write(class_dir / f"{class_name}_{i}.wav", clip, rate)

    test = root / "test"
    test.mkdir(parents=True, exist_ok=True)
    for stem, rate, seconds in _TEST_CLIPS:
        sf.write(test / f"{stem}.wav", _tone(rng, rate=rate, seconds=seconds), rate)

    return root


def fixture_summary() -> dict[str, Any]:
    """Static facts about the fixture, for test assertions."""
    return {
        "classes": [c for c, _, _ in _TRAIN_CLASSES],
        "n_labeled_clips": sum(len(d) for _, _, d in _TRAIN_CLASSES),
        "n_unlabeled_clips": len(_TEST_CLIPS),
        "target_rate": DEFAULT_TARGET_RATE,
    }
