# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
"""image_classification augmentation submodule (Story H.p, FR-11 extension).

Concrete augmentation ops land in H.q (``random_crop``, ``horizontal_flip``)
and H.r (``color_jitter``, ``random_erasing``). This submodule's H.p job
is to expose the shared aggressive-mode scaffolding via :mod:`_realizer`.
"""
