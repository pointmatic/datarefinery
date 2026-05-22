# Copyright (c) 2026 Pointmatic
# SPDX-License-Identifier: Apache-2.0
#
# mypy: ignore-errors
#
# This module is derived from `imagecorruptions` v1.1.2 (Apache-2.0)
# by Claudio Michaelis, originally accompanying the Hendrycks &
# Dietterich ICLR 2019 "Benchmarking Neural Network Robustness to Common
# Corruptions and Perturbations" reference implementation. The upstream
# package is unmaintained and incompatible with NumPy 2.x, scikit-image
# 0.21+, and setuptools 81+. We vendor a patched copy here per the H.i
# spike findings (see `docs/specs/stories.md` § Story H.i).
#
# Modifications by Pointmatic 2026 (Story H.m.1):
#   - All randomness is threaded through an explicit
#     `rng: numpy.random.Generator` parameter. Global `np.random.X` calls
#     are replaced with `rng.X` (with the `Generator` API:
#     `np.random.randint` -> `rng.integers`).
#   - `np.float_` -> `np.float64` (NumPy 2.x removal).
#   - `skimage.filters.gaussian(..., multichannel=True)` ->
#     `gaussian(..., channel_axis=-1)`; `multichannel=False` ->
#     `channel_axis=None` (scikit-image 0.21+ kwarg rename).
#   - `sk.util.random_noise(..., rng=rng)` for `impulse_noise`
#     determinism (skimage 0.21+ uses an internal PCG64 generator that
#     is not bound to legacy `np.random.seed()`).
#   - `pkg_resources.resource_filename` -> `importlib.resources` for the
#     frost JPEG textures (removes the legacy `setuptools<81`
#     dependency).
#   - `from scipy.ndimage.interpolation import map_coordinates` ->
#     `from scipy.ndimage import map_coordinates` (scipy deprecation).
#
# Upstream Apache-2.0 LICENSE and the frost texture provenance are
# preserved in `_corruption_data/NOTICE.md`.
"""Vendored image-corruption functions for FR-GEN-1 (Hendrycks-Dietterich).

Public API:
    get_corruption_names(subset="all" | "common" | "validation" | "noise"
                                | "blur" | "weather" | "digital") -> list[str]
    corrupt(image, *, corruption_name, severity, rng) -> numpy.ndarray
"""

from __future__ import annotations

import math
from importlib import resources
from io import BytesIO

import cv2
import numpy as np
import skimage as sk
from PIL import Image
from scipy.ndimage import map_coordinates
from scipy.ndimage import zoom as scizoom
from skimage.filters import gaussian

# /////////////// Corruption Helpers ///////////////


def disk(radius: float, alias_blur: float = 0.1, dtype: type = np.float32) -> np.ndarray:
    if radius <= 8:
        L = np.arange(-8, 8 + 1)
        ksize = (3, 3)
    else:
        L = np.arange(-radius, radius + 1)
        ksize = (5, 5)
    X, Y = np.meshgrid(L, L)
    aliased_disk = np.array((X**2 + Y**2) <= radius**2, dtype=dtype)
    aliased_disk /= np.sum(aliased_disk)
    # supersample disk to antialias
    return cv2.GaussianBlur(aliased_disk, ksize=ksize, sigmaX=alias_blur)


# modification of https://github.com/FLHerne/mapgen/blob/master/diamondsquare.py
def plasma_fractal(
    rng: np.random.Generator, mapsize: int = 256, wibbledecay: float = 3
) -> np.ndarray:
    """Generate a heightmap via the diamond-square algorithm."""
    assert mapsize & (mapsize - 1) == 0
    maparray = np.empty((mapsize, mapsize), dtype=np.float64)
    maparray[0, 0] = 0
    stepsize = mapsize
    wibble = 100

    def wibbledmean(array: np.ndarray) -> np.ndarray:
        return array / 4 + wibble * rng.uniform(-wibble, wibble, array.shape)

    def fillsquares() -> None:
        cornerref = maparray[0:mapsize:stepsize, 0:mapsize:stepsize]
        squareaccum = cornerref + np.roll(cornerref, shift=-1, axis=0)
        squareaccum += np.roll(squareaccum, shift=-1, axis=1)
        maparray[stepsize // 2 : mapsize : stepsize, stepsize // 2 : mapsize : stepsize] = (
            wibbledmean(squareaccum)
        )

    def filldiamonds() -> None:
        ms = maparray.shape[0]
        drgrid = maparray[stepsize // 2 : ms : stepsize, stepsize // 2 : ms : stepsize]
        ulgrid = maparray[0:ms:stepsize, 0:ms:stepsize]
        ldrsum = drgrid + np.roll(drgrid, 1, axis=0)
        lulsum = ulgrid + np.roll(ulgrid, -1, axis=1)
        ltsum = ldrsum + lulsum
        maparray[0:ms:stepsize, stepsize // 2 : ms : stepsize] = wibbledmean(ltsum)
        tdrsum = drgrid + np.roll(drgrid, 1, axis=1)
        tulsum = ulgrid + np.roll(ulgrid, -1, axis=0)
        ttsum = tdrsum + tulsum
        maparray[stepsize // 2 : ms : stepsize, 0:ms:stepsize] = wibbledmean(ttsum)

    while stepsize >= 2:
        fillsquares()
        filldiamonds()
        stepsize //= 2
        wibble /= wibbledecay

    maparray -= maparray.min()
    return maparray / maparray.max()


def clipped_zoom(img: np.ndarray, zoom_factor: float) -> np.ndarray:
    ch0 = int(np.ceil(img.shape[0] / float(zoom_factor)))
    top0 = (img.shape[0] - ch0) // 2
    ch1 = int(np.ceil(img.shape[1] / float(zoom_factor)))
    top1 = (img.shape[1] - ch1) // 2
    img = scizoom(img[top0 : top0 + ch0, top1 : top1 + ch1], (zoom_factor, zoom_factor, 1), order=1)
    return img


def _gauss_function(x: np.ndarray, mean: float, sigma: float) -> np.ndarray:
    return (np.exp(-(x**2) / (2 * (sigma**2)))) / (np.sqrt(2 * np.pi) * sigma)


def _motion_blur_kernel(width: int, sigma: float) -> np.ndarray:
    k = _gauss_function(np.arange(width), 0, sigma)
    Z = np.sum(k)
    return k / Z


def _shift(image: np.ndarray, dx: int, dy: int) -> np.ndarray:
    if dx < 0:
        shifted = np.roll(image, shift=image.shape[1] + dx, axis=1)
        shifted[:, dx:] = shifted[:, dx - 1 : dx]
    elif dx > 0:
        shifted = np.roll(image, shift=dx, axis=1)
        shifted[:, :dx] = shifted[:, dx : dx + 1]
    else:
        shifted = image

    if dy < 0:
        shifted = np.roll(shifted, shift=image.shape[0] + dy, axis=0)
        shifted[dy:, :] = shifted[dy - 1 : dy, :]
    elif dy > 0:
        shifted = np.roll(shifted, shift=dy, axis=0)
        shifted[:dy, :] = shifted[dy : dy + 1, :]
    return shifted


def _apply_motion_blur(x: np.ndarray, radius: int, sigma: float, angle: float) -> np.ndarray:
    width = radius * 2 + 1
    kernel = _motion_blur_kernel(width, sigma)
    point = (width * np.sin(np.deg2rad(angle)), width * np.cos(np.deg2rad(angle)))
    hypot = math.hypot(point[0], point[1])

    blurred = np.zeros_like(x, dtype=np.float32)
    for i in range(width):
        dy = -math.ceil(((i * point[0]) / hypot) - 0.5)
        dx = -math.ceil(((i * point[1]) / hypot) - 0.5)
        if np.abs(dy) >= x.shape[0] or np.abs(dx) >= x.shape[1]:
            break
        shifted = _shift(x, dx, dy)
        blurred = blurred + kernel[i] * shifted
    return blurred


def _rgb2gray(rgb: np.ndarray) -> np.ndarray:
    return np.dot(rgb[..., :3], [0.2989, 0.5870, 0.1140])


def _next_power_of_2(x: int) -> int:
    return 1 if x == 0 else 2 ** (x - 1).bit_length()


# /////////////// Corruptions ///////////////


def gaussian_noise(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    c = [0.08, 0.12, 0.18, 0.26, 0.38][severity - 1]
    arr = np.array(x) / 255.0
    return np.clip(arr + rng.normal(size=arr.shape, scale=c), 0, 1) * 255


def shot_noise(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    c = [60, 25, 12, 5, 3][severity - 1]
    arr = np.array(x) / 255.0
    return np.clip(rng.poisson(arr * c) / float(c), 0, 1) * 255


def impulse_noise(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    c = [0.03, 0.06, 0.09, 0.17, 0.27][severity - 1]
    arr = sk.util.random_noise(np.array(x) / 255.0, mode="s&p", amount=c, rng=rng)
    return np.clip(arr, 0, 1) * 255


def speckle_noise(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    c = [0.15, 0.2, 0.35, 0.45, 0.6][severity - 1]
    arr = np.array(x) / 255.0
    return np.clip(arr + arr * rng.normal(size=arr.shape, scale=c), 0, 1) * 255


def gaussian_blur(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    del rng  # deterministic
    c = [1, 2, 3, 4, 6][severity - 1]
    arr = gaussian(np.array(x) / 255.0, sigma=c, channel_axis=-1)
    return np.clip(arr, 0, 1) * 255


def glass_blur(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    c = [(0.7, 1, 2), (0.9, 2, 1), (1, 2, 3), (1.1, 3, 2), (1.5, 4, 2)][severity - 1]
    arr = np.uint8(gaussian(np.array(x) / 255.0, sigma=c[0], channel_axis=-1) * 255)
    x_shape = np.array(arr).shape

    # locally shuffle pixels
    for _ in range(c[2]):
        for h in range(x_shape[0] - c[1], c[1], -1):
            for w in range(x_shape[1] - c[1], c[1], -1):
                dx, dy = rng.integers(-c[1], c[1], size=(2,))
                h_prime, w_prime = h + dy, w + dx
                arr[h, w], arr[h_prime, w_prime] = (
                    arr[h_prime, w_prime].copy(),
                    arr[h, w].copy(),
                )

    return np.clip(gaussian(arr / 255.0, sigma=c[0], channel_axis=-1), 0, 1) * 255


def defocus_blur(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    del rng  # deterministic
    c = [(3, 0.1), (4, 0.5), (6, 0.5), (8, 0.5), (10, 0.5)][severity - 1]
    arr = np.array(x) / 255.0
    kernel = disk(radius=c[0], alias_blur=c[1])

    if len(arr.shape) < 3 or arr.shape[2] < 3:
        channels = np.array(cv2.filter2D(arr, -1, kernel))
    else:
        channels_list = []
        for d in range(3):
            channels_list.append(cv2.filter2D(arr[:, :, d], -1, kernel))
        channels = np.array(channels_list).transpose((1, 2, 0))

    return np.clip(channels, 0, 1) * 255


def motion_blur(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    shape = np.array(x).shape
    c = [(10, 3), (15, 5), (15, 8), (15, 12), (20, 15)][severity - 1]
    arr = np.array(x)

    angle = rng.uniform(-45, 45)
    arr = _apply_motion_blur(arr, radius=c[0], sigma=c[1], angle=angle)

    if len(arr.shape) < 3 or arr.shape[2] < 3:
        gray = np.clip(np.array(arr).transpose((0, 1)), 0, 255)
        if len(shape) >= 3 and shape[2] >= 3:
            return np.stack([gray, gray, gray], axis=2)
        return gray
    return np.clip(arr, 0, 255)


def zoom_blur(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    del rng  # deterministic
    c = [
        np.arange(1, 1.11, 0.01),
        np.arange(1, 1.16, 0.01),
        np.arange(1, 1.21, 0.02),
        np.arange(1, 1.26, 0.02),
        np.arange(1, 1.31, 0.03),
    ][severity - 1]

    arr = (np.array(x) / 255.0).astype(np.float32)
    out = np.zeros_like(arr)

    set_exception = False
    for zoom_factor in c:
        if len(arr.shape) < 3 or arr.shape[2] < 3:
            x_channels = np.array([arr, arr, arr]).transpose((1, 2, 0))
            zoom_layer = clipped_zoom(x_channels, zoom_factor)
            zoom_layer = zoom_layer[: arr.shape[0], : arr.shape[1], 0]
        else:
            zoom_layer = clipped_zoom(arr, zoom_factor)
            zoom_layer = zoom_layer[: arr.shape[0], : arr.shape[1], :]

        try:
            out += zoom_layer
        except ValueError:
            set_exception = True
            out[: zoom_layer.shape[0], : zoom_layer.shape[1]] += zoom_layer

    if set_exception:
        # upstream printed here; we keep silent — the shape mismatch is a
        # known artifact of the diamond-square zoom path at small images.
        pass
    arr = (arr + out) / (len(c) + 1)
    return np.clip(arr, 0, 1) * 255


def fog(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    c = [(1.5, 2), (2.0, 2), (2.5, 1.7), (2.5, 1.5), (3.0, 1.4)][severity - 1]

    shape = np.array(x).shape
    max_side = np.max(shape)
    map_size = _next_power_of_2(int(max_side))

    arr = np.array(x) / 255.0
    max_val = arr.max()

    x_shape = np.array(arr).shape
    if len(x_shape) < 3 or x_shape[2] < 3:
        arr += (
            c[0] * plasma_fractal(rng, mapsize=map_size, wibbledecay=c[1])[: shape[0], : shape[1]]
        )
    else:
        arr += (
            c[0]
            * plasma_fractal(rng, mapsize=map_size, wibbledecay=c[1])[: shape[0], : shape[1]][
                ..., np.newaxis
            ]
        )
    return np.clip(arr * max_val / (max_val + c[0]), 0, 1) * 255


_FROST_FILES = (
    "frost1.png",
    "frost2.png",
    "frost3.png",
    "frost4.jpg",
    "frost5.jpg",
    "frost6.jpg",
)


def _load_frost_texture(idx: int) -> np.ndarray:
    """Load one of the vendored frost textures via importlib.resources."""
    frost_dir = resources.files(__package__).joinpath("_corruption_data", "frost")
    target = frost_dir.joinpath(_FROST_FILES[idx])
    with resources.as_file(target) as path:
        frost_img = cv2.imread(str(path))
    if frost_img is None:
        raise RuntimeError(f"failed to load vendored frost texture {target!s}")
    return frost_img


def frost(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    c = [(1, 0.4), (0.8, 0.6), (0.7, 0.7), (0.65, 0.7), (0.6, 0.75)][severity - 1]

    # Upstream draws from `randint(5)`, which selects only indices 0..4
    # of the 6-entry frost file list (frost6 is never used). Preserve
    # exact upstream selection probabilities.
    idx = int(rng.integers(5))
    frost_img = _load_frost_texture(idx)
    frost_shape = frost_img.shape
    x_shape = np.array(x).shape

    scaling_factor: float = 1.0
    if frost_shape[0] >= x_shape[0] and frost_shape[1] >= x_shape[1]:
        scaling_factor = 1.0
    elif frost_shape[0] < x_shape[0] and frost_shape[1] >= x_shape[1]:
        scaling_factor = x_shape[0] / frost_shape[0]
    elif frost_shape[0] >= x_shape[0] and frost_shape[1] < x_shape[1]:
        scaling_factor = x_shape[1] / frost_shape[1]
    elif frost_shape[0] < x_shape[0] and frost_shape[1] < x_shape[1]:
        scaling_factor_0 = x_shape[0] / frost_shape[0]
        scaling_factor_1 = x_shape[1] / frost_shape[1]
        scaling_factor = float(np.maximum(scaling_factor_0, scaling_factor_1))

    scaling_factor *= 1.1
    new_shape = (
        int(np.ceil(frost_shape[1] * scaling_factor)),
        int(np.ceil(frost_shape[0] * scaling_factor)),
    )
    frost_rescaled = cv2.resize(frost_img, dsize=new_shape, interpolation=cv2.INTER_CUBIC)

    x_start = int(rng.integers(0, frost_rescaled.shape[0] - x_shape[0]))
    y_start = int(rng.integers(0, frost_rescaled.shape[1] - x_shape[1]))

    if len(x_shape) < 3 or x_shape[2] < 3:
        frost_rescaled = frost_rescaled[
            x_start : x_start + x_shape[0], y_start : y_start + x_shape[1]
        ]
        frost_rescaled = _rgb2gray(frost_rescaled)
    else:
        frost_rescaled = frost_rescaled[
            x_start : x_start + x_shape[0], y_start : y_start + x_shape[1]
        ][..., [2, 1, 0]]
    return np.clip(c[0] * np.array(x) + c[1] * frost_rescaled, 0, 255)


def snow(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    c = [
        (0.1, 0.3, 3, 0.5, 10, 4, 0.8),
        (0.2, 0.3, 2, 0.5, 12, 4, 0.7),
        (0.55, 0.3, 4, 0.9, 12, 8, 0.7),
        (0.55, 0.3, 4.5, 0.85, 12, 8, 0.65),
        (0.55, 0.3, 2.5, 0.85, 12, 12, 0.55),
    ][severity - 1]

    arr = np.array(x, dtype=np.float32) / 255.0
    snow_layer = rng.normal(size=arr.shape[:2], loc=c[0], scale=c[1])

    snow_layer = clipped_zoom(snow_layer[..., np.newaxis], c[2])
    snow_layer[snow_layer < c[3]] = 0

    snow_layer = np.clip(snow_layer.squeeze(), 0, 1)

    snow_layer = _apply_motion_blur(
        snow_layer, radius=c[4], sigma=c[5], angle=rng.uniform(-135, -45)
    )

    snow_layer = np.round(snow_layer * 255).astype(np.uint8) / 255.0
    snow_layer = snow_layer[..., np.newaxis]
    snow_layer = snow_layer[: arr.shape[0], : arr.shape[1], :]

    if len(arr.shape) < 3 or arr.shape[2] < 3:
        arr = c[6] * arr + (1 - c[6]) * np.maximum(
            arr, arr.reshape(arr.shape[0], arr.shape[1]) * 1.5 + 0.5
        )
        snow_layer = snow_layer.squeeze(-1)
    else:
        arr = c[6] * arr + (1 - c[6]) * np.maximum(
            arr,
            cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY).reshape(arr.shape[0], arr.shape[1], 1) * 1.5
            + 0.5,
        )
    try:
        return np.clip(arr + snow_layer + np.rot90(snow_layer, k=2), 0, 1) * 255
    except ValueError:
        arr[: snow_layer.shape[0], : snow_layer.shape[1]] += snow_layer + np.rot90(snow_layer, k=2)
        return np.clip(arr, 0, 1) * 255


def spatter(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    c = [
        (0.65, 0.3, 4, 0.69, 0.6, 0),
        (0.65, 0.3, 3, 0.68, 0.6, 0),
        (0.65, 0.3, 2, 0.68, 0.5, 0),
        (0.65, 0.3, 1, 0.65, 1.5, 1),
        (0.67, 0.4, 1, 0.65, 1.5, 1),
    ][severity - 1]
    x_PIL = x
    arr = np.array(x, dtype=np.float32) / 255.0

    liquid_layer = rng.normal(size=arr.shape[:2], loc=c[0], scale=c[1])

    liquid_layer = gaussian(liquid_layer, sigma=c[2])
    liquid_layer[liquid_layer < c[3]] = 0
    if c[5] == 0:
        liquid_layer = (liquid_layer * 255).astype(np.uint8)
        dist = 255 - cv2.Canny(liquid_layer, 50, 150)
        dist = cv2.distanceTransform(dist, cv2.DIST_L2, 5)
        _, dist = cv2.threshold(dist, 20, 20, cv2.THRESH_TRUNC)
        dist = cv2.blur(dist, (3, 3)).astype(np.uint8)
        dist = cv2.equalizeHist(dist)
        ker = np.array([[-2, -1, 0], [-1, 1, 1], [0, 1, 2]])
        dist = cv2.filter2D(dist, cv2.CV_8U, ker)
        dist = cv2.blur(dist, (3, 3)).astype(np.float32)

        m = cv2.cvtColor(liquid_layer * dist, cv2.COLOR_GRAY2BGRA)
        m /= np.max(m, axis=(0, 1))
        m *= c[4]
        # water is pale turquoise
        color = np.concatenate(
            (
                175 / 255.0 * np.ones_like(m[..., :1]),
                238 / 255.0 * np.ones_like(m[..., :1]),
                238 / 255.0 * np.ones_like(m[..., :1]),
            ),
            axis=2,
        )

        color = cv2.cvtColor(color, cv2.COLOR_BGR2BGRA)

        if len(arr.shape) < 3 or arr.shape[2] < 3:
            add_spatter_color = cv2.cvtColor(np.clip(m * color, 0, 1), cv2.COLOR_BGRA2BGR)
            add_spatter_gray = _rgb2gray(add_spatter_color)
            return np.clip(arr + add_spatter_gray, 0, 1) * 255

        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2BGRA)
        return cv2.cvtColor(np.clip(arr + m * color, 0, 1), cv2.COLOR_BGRA2BGR) * 255

    m = np.where(liquid_layer > c[3], 1, 0)
    m = gaussian(m.astype(np.float32), sigma=c[4])
    m[m < 0.8] = 0

    x_rgb = np.array(x_PIL.convert("RGB"))

    # mud brown
    color = np.concatenate(
        (
            63 / 255.0 * np.ones_like(x_rgb[..., :1]),
            42 / 255.0 * np.ones_like(x_rgb[..., :1]),
            20 / 255.0 * np.ones_like(x_rgb[..., :1]),
        ),
        axis=2,
    )
    color *= m[..., np.newaxis]
    if len(arr.shape) < 3 or arr.shape[2] < 3:
        arr *= 1 - m
        return np.clip(arr + _rgb2gray(color), 0, 1) * 255

    arr *= 1 - m[..., np.newaxis]
    return np.clip(arr + color, 0, 1) * 255


def contrast(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    del rng  # deterministic
    c = [0.4, 0.3, 0.2, 0.1, 0.05][severity - 1]
    arr = np.array(x) / 255.0
    means = np.mean(arr, axis=(0, 1), keepdims=True)
    return np.clip((arr - means) * c + means, 0, 1) * 255


def brightness(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    del rng  # deterministic
    c = [0.1, 0.2, 0.3, 0.4, 0.5][severity - 1]
    arr = np.array(x) / 255.0

    if len(arr.shape) < 3 or arr.shape[2] < 3:
        arr = np.clip(arr + c, 0, 1)
    else:
        arr = sk.color.rgb2hsv(arr)
        arr[:, :, 2] = np.clip(arr[:, :, 2] + c, 0, 1)
        arr = sk.color.hsv2rgb(arr)

    return np.clip(arr, 0, 1) * 255


def saturate(x: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    del rng  # deterministic
    c = [(0.3, 0), (0.1, 0), (2, 0), (5, 0.1), (20, 0.2)][severity - 1]
    arr = np.array(x) / 255.0

    gray_scale = False
    if len(arr.shape) < 3 or arr.shape[2] < 3:
        arr = np.array([arr, arr, arr]).transpose((1, 2, 0))
        gray_scale = True
    arr = sk.color.rgb2hsv(arr)
    arr[:, :, 1] = np.clip(arr[:, :, 1] * c[0] + c[1], 0, 1)
    arr = sk.color.hsv2rgb(arr)
    if gray_scale:
        arr = arr[:, :, 0]

    return np.clip(arr, 0, 1) * 255


def jpeg_compression(x: Image.Image, severity: int, rng: np.random.Generator) -> Image.Image:
    del rng  # deterministic
    c = [25, 18, 15, 10, 7][severity - 1]
    output = BytesIO()
    gray_scale = False
    if x.mode != "RGB":
        gray_scale = True
        x = x.convert("RGB")
    x.save(output, "JPEG", quality=c)
    result = Image.open(output)
    if gray_scale:
        result = result.convert("L")
    return result


def pixelate(x: Image.Image, severity: int, rng: np.random.Generator) -> Image.Image:
    del rng  # deterministic
    c = [0.6, 0.5, 0.4, 0.3, 0.25][severity - 1]
    x_shape = np.array(x).shape
    x = x.resize((int(x_shape[1] * c), int(x_shape[0] * c)), Image.BOX)
    x = x.resize((x_shape[1], x_shape[0]), Image.NEAREST)
    return x


# mod of https://gist.github.com/erniejunior/601cdf56d2b424757de5
def elastic_transform(image: Image.Image, severity: int, rng: np.random.Generator) -> np.ndarray:
    arr = np.array(image, dtype=np.float32) / 255.0
    shape = arr.shape
    shape_size = shape[:2]

    sigma = np.array(shape_size) * 0.01
    alpha = [250 * 0.05, 250 * 0.065, 250 * 0.085, 250 * 0.1, 250 * 0.12][severity - 1]
    max_dx = shape[0] * 0.005
    max_dy = shape[0] * 0.005

    dx = (
        gaussian(rng.uniform(-max_dx, max_dx, size=shape[:2]), sigma, mode="reflect", truncate=3)
        * alpha
    ).astype(np.float32)
    dy = (
        gaussian(rng.uniform(-max_dy, max_dy, size=shape[:2]), sigma, mode="reflect", truncate=3)
        * alpha
    ).astype(np.float32)

    if len(arr.shape) < 3 or arr.shape[2] < 3:
        xg, yg = np.meshgrid(np.arange(shape[1]), np.arange(shape[0]))
        indices = np.reshape(yg + dy, (-1, 1)), np.reshape(xg + dx, (-1, 1))
    else:
        dx_e, dy_e = dx[..., np.newaxis], dy[..., np.newaxis]
        xg, yg, zg = np.meshgrid(np.arange(shape[1]), np.arange(shape[0]), np.arange(shape[2]))
        indices = (
            np.reshape(yg + dy_e, (-1, 1)),
            np.reshape(xg + dx_e, (-1, 1)),
            np.reshape(zg, (-1, 1)),
        )
    return (
        np.clip(map_coordinates(arr, indices, order=1, mode="reflect").reshape(shape), 0, 1) * 255
    )


# /////////////// Dispatcher ///////////////

_CORRUPTION_TUPLE = (
    gaussian_noise,
    shot_noise,
    impulse_noise,
    defocus_blur,
    glass_blur,
    motion_blur,
    zoom_blur,
    snow,
    frost,
    fog,
    brightness,
    contrast,
    elastic_transform,
    pixelate,
    jpeg_compression,
    speckle_noise,
    gaussian_blur,
    spatter,
    saturate,
)

_CORRUPTION_DICT = {f.__name__: f for f in _CORRUPTION_TUPLE}


def get_corruption_names(subset: str = "all") -> list[str]:
    """Return the corruption names for the requested subset.

    Subsets match upstream `imagecorruptions`: `"common"` (15 names),
    `"validation"` (4 names), `"all"` (19 names), plus the four
    category subsets `"noise"`, `"blur"`, `"weather"`, `"digital"`.
    """
    if subset == "common":
        return [f.__name__ for f in _CORRUPTION_TUPLE[:15]]
    if subset == "validation":
        return [f.__name__ for f in _CORRUPTION_TUPLE[15:]]
    if subset == "all":
        return [f.__name__ for f in _CORRUPTION_TUPLE]
    if subset == "noise":
        return [f.__name__ for f in _CORRUPTION_TUPLE[0:3]]
    if subset == "blur":
        return [f.__name__ for f in _CORRUPTION_TUPLE[3:7]]
    if subset == "weather":
        return [f.__name__ for f in _CORRUPTION_TUPLE[7:11]]
    if subset == "digital":
        return [f.__name__ for f in _CORRUPTION_TUPLE[11:15]]
    raise ValueError(
        "subset must be one of ['common', 'validation', 'all', 'noise', 'blur', 'weather', "
        "'digital']"
    )


def corrupt(
    image: np.ndarray, *, corruption_name: str, severity: int, rng: np.random.Generator
) -> np.ndarray:
    """Apply ``corruption_name`` at ``severity`` (1..5) using ``rng``.

    Input must be a ``uint8`` array of shape ``(H, W)`` or ``(H, W, C)``
    with ``H, W >= 32`` and ``C in {1, 3}``. Output is ``uint8`` with the
    same shape as the (possibly broadcast-to-3-channel) input.
    """
    if not isinstance(image, np.ndarray):
        raise TypeError("image must be a numpy.ndarray")
    if image.dtype != np.uint8:
        raise TypeError(f"image dtype must be uint8 (got {image.dtype})")
    if image.ndim not in (2, 3):
        raise ValueError("image must be 2- or 3-dimensional")
    if image.ndim == 2:
        image = np.stack((image,) * 3, axis=-1)
    height, width, channels = image.shape
    if height < 32 or width < 32:
        raise ValueError("image height and width must each be at least 32 pixels")
    if channels not in (1, 3):
        raise ValueError("image must have 1 or 3 channels")
    if channels == 1:
        image = np.stack((np.squeeze(image),) * 3, axis=-1)
    if severity not in (1, 2, 3, 4, 5):
        raise ValueError("severity must be an integer in [1, 5]")
    if corruption_name not in _CORRUPTION_DICT:
        raise ValueError(
            f"unknown corruption_name {corruption_name!r}; "
            f"call get_corruption_names('all') for the canonical list"
        )

    fn = _CORRUPTION_DICT[corruption_name]
    out = fn(Image.fromarray(image), severity, rng)
    return np.asarray(out, dtype=np.uint8)
