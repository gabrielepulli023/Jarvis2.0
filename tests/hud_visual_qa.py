r"""Non-destructive visual QA for the production JARVIS HUD.

The tool compares a real HUD screenshot (or an in-memory capture of a visible
Windows window) with a reference image.  It intentionally avoids pixel-perfect
comparison: dynamic text, telemetry, clocks and camera content are expected to
change.  Instead it measures visual density, palette, regional distribution and
the position/scale of the dominant circular core.

Examples::

    .runtime-env\Scripts\python.exe tests\hud_visual_qa.py \
        --reference C:\path\reference.png --candidate C:\path\hud.png

    .runtime-env\Scripts\python.exe tests\hud_visual_qa.py \
        --reference C:\path\reference.png --capture-window JARVIS --timeout 20

Window captures remain in memory unless ``--save-capture`` is explicitly used.
This is important because the HUD can contain private desktop or camera data.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageGrab


REGIONS: dict[str, tuple[float, float, float, float]] = {
    "top_status": (0.00, 0.00, 1.00, 0.085),
    "camera": (0.025, 0.095, 0.230, 0.340),
    "system": (0.025, 0.345, 0.230, 0.650),
    "left_orb": (0.025, 0.645, 0.230, 0.950),
    "core": (0.225, 0.055, 0.755, 0.750),
    "openai": (0.775, 0.080, 0.995, 0.400),
    "task": (0.745, 0.400, 0.995, 0.600),
    "context": (0.745, 0.600, 0.995, 0.930),
    "micro_modules": (0.270, 0.615, 0.720, 0.815),
    "command": (0.310, 0.815, 0.700, 0.895),
    "bottom_nav": (0.265, 0.875, 0.730, 1.000),
}

REGION_WEIGHTS = {
    "top_status": 1.15,
    "camera": 0.65,  # A real inactive camera must not be penalised like fake imagery.
    "system": 1.0,
    "left_orb": 0.9,
    "core": 1.45,
    "openai": 1.05,
    "task": 0.9,
    "context": 1.0,
    "micro_modules": 1.0,
    "command": 0.85,
    "bottom_nav": 0.9,
}

ESSENTIAL_REGIONS = (
    "top_status",
    "system",
    "core",
    "openai",
    "task",
    "context",
    "micro_modules",
    "command",
    "bottom_nav",
)


def _rgb_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8)


def _luminance(rgb: np.ndarray) -> np.ndarray:
    values = rgb.astype(np.float32)
    return values[..., 0] * 0.2126 + values[..., 1] * 0.7152 + values[..., 2] * 0.0722


def _ratio(value: np.ndarray) -> float:
    return float(np.mean(value)) if value.size else 0.0


def _region_metrics(
    luminance: np.ndarray,
    edges: np.ndarray,
    cyan: np.ndarray,
    bounds: tuple[float, float, float, float],
) -> dict[str, float]:
    height, width = luminance.shape
    x0, y0, x1, y1 = bounds
    left = max(0, min(width - 1, int(round(x0 * width))))
    top = max(0, min(height - 1, int(round(y0 * height))))
    right = max(left + 1, min(width, int(round(x1 * width))))
    bottom = max(top + 1, min(height, int(round(y1 * height))))
    light = luminance[top:bottom, left:right]
    edge = edges[top:bottom, left:right]
    cyan_region = cyan[top:bottom, left:right]
    return {
        "mean_luminance": round(float(light.mean()), 4),
        "visible_ratio": round(_ratio(light > 15.0), 6),
        "bright_ratio": round(_ratio(light > 40.0), 6),
        "edge_ratio": round(_ratio(edge > 0), 6),
        "cyan_ratio": round(_ratio(cyan_region), 6),
    }


def _palette_histogram(rgb: np.ndarray) -> np.ndarray:
    """HSV histogram of visible pixels, excluding the dominant black field."""

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    visible = _luminance(rgb) > 12.0
    pixels = hsv[visible]
    if not pixels.size:
        return np.zeros(18 * 4 * 4, dtype=np.float32)
    histogram, _ = np.histogramdd(
        pixels.astype(np.float32),
        bins=(18, 4, 4),
        range=((0, 180), (0, 256), (0, 256)),
    )
    flat = histogram.astype(np.float32).ravel()
    total = float(flat.sum())
    return flat / total if total else flat


def _normalised_bounds(
    bounds: tuple[float, float, float, float], width: int, height: int
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bounds
    return (
        max(0, min(width - 1, int(round(x0 * width)))),
        max(0, min(height - 1, int(round(y0 * height)))),
        max(1, min(width, int(round(x1 * width)))),
        max(1, min(height, int(round(y1 * height)))),
    )


def _typography_metrics(rgb: np.ndarray, luminance: np.ndarray) -> dict[str, Any]:
    """Measure real text-scale and detect repeated missing-glyph boxes.

    OCR would be fragile with dynamic Italian content.  Connected bright-stroke
    components are enough to catch the two failures relevant here: typography
    that is much smaller/sparser than the reference, and Qt tofu squares.
    Camera and core areas are excluded because their imagery is not typography.
    """

    height, width = luminance.shape
    allowed = np.zeros((height, width), dtype=bool)
    for name in ("top_status", "system", "openai", "task", "context", "micro_modules", "command"):
        left, top, right, bottom = _normalised_bounds(REGIONS[name], width, height)
        allowed[top:bottom, left:right] = True
    mask = ((luminance > 58.0) & allowed).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    scale = 941.0 / max(1, height)
    components: list[tuple[float, float, float, float]] = []
    dimensions: dict[tuple[int, int], int] = {}
    box_dimensions: dict[tuple[int, int], int] = {}
    for index in range(1, count):
        x, y, component_width, component_height, area = [int(value) for value in stats[index]]
        normal_width, normal_height = component_width * scale, component_height * scale
        if area < 2 or not (1.5 <= normal_height <= 46.0) or normal_width > 95.0:
            continue
        if normal_width > max(12.0, normal_height * 10.0):
            continue
        fill = area / max(1.0, component_width * component_height)
        components.append((normal_width, normal_height, float(area) * scale * scale, fill))
        key = (max(1, int(round(normal_width))), max(1, int(round(normal_height))))
        dimensions[key] = dimensions.get(key, 0) + 1
        aspect = normal_width / max(normal_height, 1e-6)
        if 0.62 <= aspect <= 1.45 and 0.12 <= fill <= 0.72:
            box_dimensions[key] = box_dimensions.get(key, 0) + 1

    heights = np.asarray([item[1] for item in components], dtype=np.float32)
    histogram, _ = np.histogram(heights, bins=(0, 4, 6, 8, 10, 12, 16, 22, 32, 48))
    histogram = histogram.astype(np.float32)
    if histogram.sum():
        histogram /= histogram.sum()
    dimension_counts = np.asarray(list(dimensions.values()), dtype=np.float64)
    entropy = 0.0
    if dimension_counts.size:
        probabilities = dimension_counts / dimension_counts.sum()
        entropy = float(-(probabilities * np.log2(probabilities)).sum())
    repeated_boxes = max(box_dimensions.values(), default=0)
    component_count = len(components)
    analysed_area = int(allowed.sum())
    return {
        "text_pixel_ratio": round(float(mask.sum()) / max(1, analysed_area), 6),
        "components_per_megapixel": round(component_count / max(1e-9, width * height / 1_000_000), 4),
        "median_height_941": round(float(np.median(heights)) if heights.size else 0.0, 4),
        "p90_height_941": round(float(np.percentile(heights, 90)) if heights.size else 0.0, 4),
        "size_entropy": round(entropy, 6),
        "repeated_box_ratio": round(repeated_boxes / max(1, component_count), 6),
        "component_count": component_count,
        "height_profile": [round(float(value), 6) for value in histogram],
    }


def _core_label_metrics(rgb: np.ndarray, luminance: np.ndarray) -> dict[str, float]:
    """Measure the ice-white JARVIS label without treating cyan rings as text."""

    height, width = luminance.shape
    left, top, right, bottom = _normalised_bounds((0.385, 0.300, 0.615, 0.515), width, height)
    crop = rgb[top:bottom, left:right]
    crop_luminance = luminance[top:bottom, left:right]
    chroma = crop.max(axis=2).astype(np.int16) - crop.min(axis=2).astype(np.int16)
    mask = ((crop_luminance > 105.0) & (chroma < 82)).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    scale = 941.0 / max(1, height)
    heights: list[float] = []
    widths: list[float] = []
    for index in range(1, count):
        _, _, component_width, component_height, area = [int(value) for value in stats[index]]
        normal_height = component_height * scale
        normal_width = component_width * scale
        if area >= 3 and 3.0 <= normal_height <= 70.0 and normal_width <= 110.0:
            heights.append(normal_height)
            widths.append(normal_width)
    return {
        "max_component_height_941": round(max(heights, default=0.0), 4),
        "p90_component_height_941": round(float(np.percentile(heights, 90)) if heights else 0.0, 4),
        "white_pixel_ratio": round(float(mask.mean()), 6),
        "component_count": len(heights),
        "component_width_sum_941": round(float(sum(widths)), 4),
    }


def _circle_edge_strength(edges: np.ndarray, x: float, y: float, radius: float) -> float:
    angles = np.linspace(0.0, math.tau, 240, endpoint=False)
    height, width = edges.shape
    strengths: list[float] = []
    for offset in (-2.0, 0.0, 2.0):
        rr = max(1.0, radius + offset)
        xx = np.clip(np.rint(x + np.cos(angles) * rr).astype(np.int32), 0, width - 1)
        yy = np.clip(np.rint(y + np.sin(angles) * rr).astype(np.int32), 0, height - 1)
        strengths.append(float(np.mean(edges[yy, xx] > 0)))
    return max(strengths, default=0.0)


def detect_core(rgb: np.ndarray) -> dict[str, Any] | None:
    """Locate the dominant circular HUD core using real image edges.

    Hough candidates are scored by circumference edge coverage and by a broad
    centre-screen prior.  The prior only rejects side gauges; it does not force
    an exact reference coordinate.
    """

    source_height, source_width = rgb.shape[:2]
    # 640 px is enough for the large HUD rings and keeps a live QA iteration
    # comfortably below the startup time of the application.
    scale = min(1.0, 640.0 / max(1, source_width))
    if scale < 1.0:
        sample = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        sample = rgb
    gray = cv2.cvtColor(sample, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 1.1)
    edges = cv2.Canny(blurred, 24, 78)
    height, width = gray.shape
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.35,
        minDist=max(10, int(height * 0.025)),
        param1=78,
        param2=24,
        minRadius=max(24, int(height * 0.095)),
        maxRadius=max(30, int(height * 0.39)),
    )
    if circles is None:
        return None

    ranked: list[tuple[float, float, float, float, float]] = []
    for raw_x, raw_y, raw_radius in circles[0]:
        x, y, radius = float(raw_x), float(raw_y), float(raw_radius)
        nx, ny = x / width, y / height
        if not (0.30 <= nx <= 0.70 and 0.16 <= ny <= 0.69):
            continue
        edge_strength = _circle_edge_strength(edges, x, y, radius)
        centre_prior = math.exp(-(((nx - 0.50) / 0.22) ** 2 + ((ny - 0.43) / 0.27) ** 2))
        score = edge_strength * 0.78 + centre_prior * 0.22
        ranked.append((score, x, y, radius, edge_strength))
    if not ranked:
        return None

    ranked.sort(reverse=True)
    best = ranked[0]
    nearby = [
        item
        for item in ranked[:40]
        if abs(item[1] - best[1]) <= width * 0.065
        and abs(item[2] - best[2]) <= height * 0.075
    ]
    weights = np.asarray([max(item[0], 1e-6) ** 3 for item in nearby], dtype=np.float64)
    xs = np.asarray([item[1] for item in nearby], dtype=np.float64)
    ys = np.asarray([item[2] for item in nearby], dtype=np.float64)
    centre_x = float(np.average(xs, weights=weights))
    centre_y = float(np.average(ys, weights=weights))

    local = [
        item
        for item in ranked
        if abs(item[1] - centre_x) <= width * 0.075
        and abs(item[2] - centre_y) <= height * 0.085
    ]
    strongest_edge = max((item[4] for item in local), default=best[4])
    supported = [item for item in local if item[4] >= max(0.08, strongest_edge * 0.48)]
    outer = max(supported or [best], key=lambda item: item[3])
    inverse_scale = 1.0 / scale
    return {
        "center_x": round(centre_x * inverse_scale, 2),
        "center_y": round(centre_y * inverse_scale, 2),
        "center_x_ratio": round(centre_x / width, 6),
        "center_y_ratio": round(centre_y / height, 6),
        "dominant_radius": round(outer[3] * inverse_scale, 2),
        "dominant_radius_height_ratio": round(outer[3] / height, 6),
        "edge_support": round(float(outer[4]), 6),
        "candidate_count": len(ranked),
    }


def _radial_complexity(
    luminance: np.ndarray, edges: np.ndarray, core: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not core:
        return None
    height, width = luminance.shape
    centre_x, centre_y = float(core["center_x"]), float(core["center_y"])
    max_radius = min(height * 0.39, width * 0.28)
    radii = np.linspace(max(3.0, height * 0.012), max_radius, 144)
    angles = np.linspace(0.0, math.tau, 300, endpoint=False)
    cosines, sines = np.cos(angles), np.sin(angles)
    edge_profile: list[float] = []
    bright_profile: list[float] = []
    for radius in radii:
        xx = np.clip(np.rint(centre_x + cosines * radius).astype(np.int32), 0, width - 1)
        yy = np.clip(np.rint(centre_y + sines * radius).astype(np.int32), 0, height - 1)
        edge_profile.append(float(np.mean(edges[yy, xx] > 0)))
        bright_profile.append(float(np.mean(luminance[yy, xx] > 40.0)))
    edge_values = np.asarray(edge_profile, dtype=np.float32)
    bright_values = np.asarray(bright_profile, dtype=np.float32)
    smooth = np.convolve(edge_values, np.ones(5, dtype=np.float32) / 5.0, mode="same")
    threshold = max(0.018, float(np.percentile(smooth, 68)) * 0.72)
    candidates = [
        index
        for index in range(2, len(smooth) - 2)
        if smooth[index] >= threshold
        and smooth[index] == max(smooth[index - 2 : index + 3])
    ]
    selected: list[int] = []
    for index in sorted(candidates, key=lambda item: float(smooth[item]), reverse=True):
        if all(abs(index - prior) >= 4 for prior in selected):
            selected.append(index)
    selected.sort()

    def compress(values: np.ndarray, bins: int = 18) -> list[float]:
        chunks = np.array_split(values, bins)
        return [round(float(chunk.mean()) if chunk.size else 0.0, 6) for chunk in chunks]

    inner_radius = min(height * 0.16, max_radius)
    y_grid, x_grid = np.ogrid[:height, :width]
    inner = (x_grid - centre_x) ** 2 + (y_grid - centre_y) ** 2 <= inner_radius**2
    return {
        "ring_peak_count": len(selected),
        "radial_edge_mean": round(float(edge_values.mean()), 6),
        "radial_bright_mean": round(float(bright_values.mean()), 6),
        "active_radius_ratio": round(float(np.mean(smooth >= threshold)), 6),
        "inner_bright_ratio": round(float(np.mean(luminance[inner] > 40.0)), 6),
        "edge_profile": compress(edge_values),
        "bright_profile": compress(bright_values),
    }


def analyze_image(image: Image.Image, source: str = "image") -> dict[str, Any]:
    rgb = _rgb_array(image)
    height, width = rgb.shape[:2]
    luminance = _luminance(rgb)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0.8), 24, 78)
    red = rgb[..., 0].astype(np.int16)
    green = rgb[..., 1].astype(np.int16)
    blue = rgb[..., 2].astype(np.int16)
    cyan = (green > 65) & (blue > 85) & (blue >= green - 12) & (red < green * 0.72)
    regions = {
        name: _region_metrics(luminance, edges, cyan, bounds)
        for name, bounds in REGIONS.items()
    }
    core = detect_core(rgb)
    return {
        "source": source,
        "width": width,
        "height": height,
        "aspect_ratio": round(width / max(1, height), 6),
        "metrics": {
            "mean_luminance": round(float(luminance.mean()), 4),
            "dark_ratio": round(_ratio(luminance < 12.0), 6),
            "visible_ratio": round(_ratio(luminance > 15.0), 6),
            "bright_ratio": round(_ratio(luminance > 40.0), 6),
            "highlight_ratio": round(_ratio(luminance > 80.0), 6),
            "edge_ratio": round(_ratio(edges > 0), 6),
            "cyan_ratio": round(_ratio(cyan), 6),
        },
        "regions": regions,
        "typography": _typography_metrics(rgb, luminance),
        "core_label": _core_label_metrics(rgb, luminance),
        "core": core,
        "radial": _radial_complexity(luminance, edges, core),
        "_palette": _palette_histogram(rgb),
        "_rgb": rgb,
    }


def _strict_similarity(first: float, second: float, floor: float = 1e-7) -> float:
    """Ratio similarity: half the target now scores .5 rather than .67."""

    first, second = abs(float(first)), abs(float(second))
    if first <= floor and second <= floor:
        return 1.0
    if first <= floor or second <= floor:
        return 0.0
    return min(first, second) / max(first, second)


def _density_similarity(reference: dict[str, Any], candidate: dict[str, Any]) -> float:
    keys = (
        "mean_luminance",
        "visible_ratio",
        "bright_ratio",
        "highlight_ratio",
        "edge_ratio",
        "cyan_ratio",
    )
    values = [
        _strict_similarity(reference["metrics"][key], candidate["metrics"][key])
        for key in keys
    ]
    return float(np.mean(values))


def _regional_similarity(
    reference: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float, dict[str, float]]:
    scores: dict[str, float] = {}
    metric_weights = {
        "visible_ratio": 0.22,
        "bright_ratio": 0.31,
        "edge_ratio": 0.30,
        "cyan_ratio": 0.17,
    }
    for region_name in REGIONS:
        scores[region_name] = sum(
            _strict_similarity(
                reference["regions"][region_name][metric_name],
                candidate["regions"][region_name][metric_name],
            )
            * weight
            for metric_name, weight in metric_weights.items()
        )
    total_weight = sum(REGION_WEIGHTS.values())
    overall = sum(scores[name] * REGION_WEIGHTS[name] for name in scores) / total_weight
    return overall, scores


def _palette_similarity(reference: dict[str, Any], candidate: dict[str, Any]) -> float:
    first = reference["_palette"].astype(np.float32)
    second = candidate["_palette"].astype(np.float32)
    if not first.any() and not second.any():
        return 1.0
    if not first.any() or not second.any():
        return 0.0
    distance = float(cv2.compareHist(first, second, cv2.HISTCMP_BHATTACHARYYA))
    return max(0.0, min(1.0, 1.0 - distance))


def _core_similarity(reference: dict[str, Any], candidate: dict[str, Any]) -> float | None:
    first, second = reference.get("core"), candidate.get("core")
    if not first or not second:
        return None
    centre_distance = math.hypot(
        first["center_x_ratio"] - second["center_x_ratio"],
        first["center_y_ratio"] - second["center_y_ratio"],
    )
    centre_score = max(0.0, 1.0 - centre_distance / 0.18)
    radius_score = _strict_similarity(
        first["dominant_radius_height_ratio"], second["dominant_radius_height_ratio"]
    )
    return centre_score * 0.72 + radius_score * 0.28


def _profile_similarity(first: list[float], second: list[float]) -> float:
    if len(first) != len(second) or not first:
        return 0.0
    return float(np.mean([_strict_similarity(a, b, 1e-5) for a, b in zip(first, second)]))


def _radial_similarity(reference: dict[str, Any], candidate: dict[str, Any]) -> float | None:
    first, second = reference.get("radial"), candidate.get("radial")
    if not first or not second:
        return None
    return (
        _profile_similarity(first["edge_profile"], second["edge_profile"]) * 0.34
        + _profile_similarity(first["bright_profile"], second["bright_profile"]) * 0.28
        + _strict_similarity(first["ring_peak_count"], second["ring_peak_count"]) * 0.12
        + _strict_similarity(first["radial_edge_mean"], second["radial_edge_mean"]) * 0.10
        + _strict_similarity(first["radial_bright_mean"], second["radial_bright_mean"]) * 0.08
        + _strict_similarity(first["inner_bright_ratio"], second["inner_bright_ratio"]) * 0.08
    )


def _core_visual_similarity(reference: dict[str, Any], candidate: dict[str, Any]) -> float:
    core_region = np.mean(
        [
            _strict_similarity(
                reference["regions"]["core"][name], candidate["regions"]["core"][name]
            )
            for name in ("visible_ratio", "bright_ratio", "edge_ratio", "cyan_ratio")
        ]
    )
    radial = _radial_similarity(reference, candidate)
    if radial is None:
        return float(core_region)
    support = _strict_similarity(
        (reference.get("core") or {}).get("edge_support", 0.0),
        (candidate.get("core") or {}).get("edge_support", 0.0),
    )
    label = np.mean(
        [
            _strict_similarity(reference["core_label"][name], candidate["core_label"][name])
            for name in (
                "max_component_height_941",
                "p90_component_height_941",
                "white_pixel_ratio",
                "component_width_sum_941",
            )
        ]
    )
    return float(core_region * 0.48 + radial * 0.34 + support * 0.08 + label * 0.10)


def _typography_similarity(reference: dict[str, Any], candidate: dict[str, Any]) -> float:
    first, second = reference["typography"], candidate["typography"]
    scalar = sum(
        _strict_similarity(first[name], second[name]) * weight
        for name, weight in {
            "text_pixel_ratio": 0.25,
            "components_per_megapixel": 0.32,
            "median_height_941": 0.08,
            "p90_height_941": 0.18,
            "size_entropy": 0.17,
        }.items()
    )
    first_profile = np.asarray(first["height_profile"], dtype=np.float64)
    second_profile = np.asarray(second["height_profile"], dtype=np.float64)
    profile = float(np.sqrt(first_profile * second_profile).sum())
    repeated_excess = max(0.0, second["repeated_box_ratio"] - first["repeated_box_ratio"] - 0.06)
    return max(0.0, min(1.0, (float(scalar) * 0.76 + profile * 0.24) * (1.0 - repeated_excess * 2.4)))


def _structural_alignment(reference_rgb: np.ndarray, candidate_rgb: np.ndarray) -> float:
    size = (480, 270)

    def prepare(rgb: np.ndarray) -> np.ndarray:
        resized = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0.7), 28, 84)
        # Ignore the real/fake camera content but retain its bezel.
        left, top, right, bottom = _normalised_bounds((0.050, 0.145, 0.215, 0.300), size[0], size[1])
        edges[top:bottom, left:right] = 0
        return edges

    first, second = prepare(reference_rgb), prepare(candidate_rgb)
    if not first.any() or not second.any():
        return 1.0 if not first.any() and not second.any() else 0.0
    distance_to_first = cv2.distanceTransform((first == 0).astype(np.uint8), cv2.DIST_L2, 3)
    distance_to_second = cv2.distanceTransform((second == 0).astype(np.uint8), cv2.DIST_L2, 3)
    first_distances = distance_to_second[first > 0]
    second_distances = distance_to_first[second > 0]
    mean_distance = (float(first_distances.mean()) + float(second_distances.mean())) / 2.0
    coverage = (
        float(np.mean(first_distances <= 2.0)) + float(np.mean(second_distances <= 2.0))
    ) / 2.0
    return max(0.0, min(1.0, math.exp(-mean_distance / 3.0) * 0.55 + coverage * 0.45))


def _clean_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in analysis.items() if not key.startswith("_")}


def compare_images(
    reference_image: Image.Image,
    candidate_image: Image.Image,
    *,
    reference_source: str = "reference",
    candidate_source: str = "candidate",
) -> dict[str, Any]:
    reference = analyze_image(reference_image, reference_source)
    candidate = analyze_image(candidate_image, candidate_source)
    density = _density_similarity(reference, candidate)
    regional, region_scores = _regional_similarity(reference, candidate)
    palette = _palette_similarity(reference, candidate)
    core_geometry = _core_similarity(reference, candidate)
    core_visual = _core_visual_similarity(reference, candidate)
    typography = _typography_similarity(reference, candidate)
    structure = _structural_alignment(reference["_rgb"], candidate["_rgb"])
    weighted = [
        (core_visual, 0.24),
        (regional, 0.22),
        (density, 0.15),
        (structure, 0.15),
        (typography, 0.12),
        (palette, 0.07),
    ]
    if core_geometry is not None:
        weighted.append((core_geometry, 0.05))
    total_weight = sum(weight for _, weight in weighted)
    raw_score = sum(value * weight for value, weight in weighted) / total_weight * 100.0

    ref_metrics, cand_metrics = reference["metrics"], candidate["metrics"]
    visible_ratio = cand_metrics["visible_ratio"] / max(ref_metrics["visible_ratio"], 1e-9)
    bright_ratio = cand_metrics["bright_ratio"] / max(ref_metrics["bright_ratio"], 1e-9)
    essential_coverage = float(
        np.mean([region_scores[name] >= 0.65 for name in ESSENTIAL_REGIONS])
    )
    repeated_boxes = candidate["typography"]["repeated_box_ratio"]
    reference_boxes = reference["typography"]["repeated_box_ratio"]
    tofu_suspected = repeated_boxes > max(0.20, reference_boxes + 0.12)
    gates = [
        {"name": "visible_density", "value": visible_ratio, "minimum": 0.85},
        {"name": "bright_density", "value": bright_ratio, "minimum": 0.78},
        {"name": "core_visual", "value": core_visual, "minimum": 0.78},
        {"name": "typography", "value": typography, "minimum": 0.78},
        {"name": "structural_alignment", "value": structure, "minimum": 0.68},
        {"name": "essential_region_coverage", "value": essential_coverage, "minimum": 0.78},
    ]
    for gate in gates:
        gate["value"] = round(float(gate["value"]), 4)
        gate["passed"] = gate["value"] >= gate["minimum"]

    caps: list[tuple[str, float]] = []
    if bright_ratio < 0.75:
        caps.append(("bright_density_below_75_percent", 72.0))
    if bright_ratio < 0.60:
        caps.append(("bright_density_below_60_percent", 62.0))
    if visible_ratio < 0.80:
        caps.append(("visible_density_below_80_percent", 72.0))
    if core_visual < 0.72:
        caps.append(("core_visual_below_target", 70.0))
    if typography < 0.72:
        caps.append(("typography_below_target", 70.0))
    if structure < 0.58:
        caps.append(("structure_below_target", 68.0))
    if essential_coverage < 0.75:
        caps.append(("too_many_sparse_regions", 70.0))
    if tofu_suspected:
        caps.append(("missing_glyph_boxes_detected", 35.0))
    score_cap = min((cap for _, cap in caps), default=100.0)
    score = min(raw_score, score_cap)

    if score >= 93.0 and all(gate["passed"] for gate in gates):
        verdict = "allineamento_visivo_forte"
    elif score >= 86.0:
        verdict = "vicino_ma_rifinitura_necessaria"
    elif score >= 75.0:
        verdict = "differenze_materiali"
    elif score >= 60.0:
        verdict = "visivamente_lontano"
    else:
        verdict = "non_allineato"

    return {
        "reference": _clean_analysis(reference),
        "candidate": _clean_analysis(candidate),
        "comparison": {
            "overall_score": round(score, 2),
            "raw_score_before_gates": round(raw_score, 2),
            "verdict": verdict,
            "density_similarity": round(density * 100.0, 2),
            "regional_similarity": round(regional * 100.0, 2),
            "palette_similarity": round(palette * 100.0, 2),
            "typography_similarity": round(typography * 100.0, 2),
            "structural_alignment": round(structure * 100.0, 2),
            "core_visual_similarity": round(core_visual * 100.0, 2),
            "core_geometry_similarity": None if core_geometry is None else round(core_geometry * 100.0, 2),
            "region_scores": {name: round(value * 100.0, 2) for name, value in region_scores.items()},
            "candidate_to_reference_visible_density": round(visible_ratio, 4),
            "candidate_to_reference_bright_density": round(bright_ratio, 4),
            "tofu_suspected": tofu_suspected,
            "quality_gates": gates,
            "score_caps": [{"reason": reason, "cap": cap} for reason, cap in caps],
            "aspect_ratio_delta": round(
                abs(reference["aspect_ratio"] - candidate["aspect_ratio"]), 6
            ),
        },
    }


def _enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def _matching_windows(title_fragment: str) -> list[dict[str, Any]]:
    if os.name != "nt":
        raise RuntimeError("La cattura per titolo finestra è disponibile solo su Windows.")
    user32 = ctypes.windll.user32
    matches: list[dict[str, Any]] = []
    query = title_fragment.casefold()
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd: int, _parameter: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if query not in title.casefold():
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width > 1 and height > 1:
            matches.append(
                {
                    "handle": int(hwnd),
                    "title": title,
                    "rect": (rect.left, rect.top, rect.right, rect.bottom),
                    "area": width * height,
                }
            )
        return True

    user32.EnumWindows(callback_type(visit), 0)
    matches.sort(key=lambda item: item["area"], reverse=True)
    return matches


def capture_window(title_fragment: str, timeout: float = 15.0) -> tuple[Image.Image, dict[str, Any]]:
    _enable_dpi_awareness()
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        matches = _matching_windows(title_fragment)
        if matches:
            selected = matches[0]
            image = ImageGrab.grab(bbox=selected["rect"], all_screens=True).convert("RGB")
            metadata = {
                "title": selected["title"],
                "rect": list(selected["rect"]),
                "capture_persisted": False,
            }
            return image, metadata
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Nessuna finestra visibile contenente {title_fragment!r} trovata entro {timeout:.1f}s."
            )
        time.sleep(0.25)


def _load_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path, help="PNG/JPG di riferimento reale")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candidate", type=Path, help="Screenshot HUD reale da confrontare")
    source.add_argument(
        "--capture-window",
        nargs="?",
        const="JARVIS",
        metavar="TITOLO",
        help="Cattura in memoria la più grande finestra visibile che contiene il titolo",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="Attesa massima della finestra")
    parser.add_argument(
        "--save-capture",
        type=Path,
        help="Salva esplicitamente la cattura; per default non viene persistita",
    )
    parser.add_argument("--min-score", type=float, help="Esce con codice 2 se lo score è inferiore")
    parser.add_argument("--compact", action="store_true", help="JSON su una singola riga")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.reference.is_file():
        raise SystemExit(f"Riferimento non trovato: {arguments.reference}")
    reference = _load_image(arguments.reference)
    capture_metadata: dict[str, Any] | None = None
    if arguments.candidate:
        if not arguments.candidate.is_file():
            raise SystemExit(f"Screenshot candidato non trovato: {arguments.candidate}")
        candidate = _load_image(arguments.candidate)
        candidate_source = str(arguments.candidate.resolve())
    else:
        candidate, capture_metadata = capture_window(arguments.capture_window, arguments.timeout)
        candidate_source = f"window:{capture_metadata['title']}"
        if arguments.save_capture:
            arguments.save_capture.parent.mkdir(parents=True, exist_ok=True)
            candidate.save(arguments.save_capture)
            capture_metadata["capture_persisted"] = True
            capture_metadata["saved_to"] = str(arguments.save_capture.resolve())

    result = compare_images(
        reference,
        candidate,
        reference_source=str(arguments.reference.resolve()),
        candidate_source=candidate_source,
    )
    if capture_metadata:
        result["capture"] = capture_metadata
    print(json.dumps(result, ensure_ascii=False, indent=None if arguments.compact else 2))
    score = result["comparison"]["overall_score"]
    if arguments.min_score is not None and score < arguments.min_score:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        print(json.dumps({"error": f"{type(error).__name__}: {error}"}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
