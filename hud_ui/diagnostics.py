"""DPI and design-viewport diagnostics for the canonical HUD."""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtWidgets import QApplication, QWidget

from .viewport import REFERENCE_HEIGHT, REFERENCE_WIDTH, design_transform


def _rect_data(rect) -> dict[str, int]:
    return {
        "x": int(rect.x()),
        "y": int(rect.y()),
        "width": int(rect.width()),
        "height": int(rect.height()),
    }


def collect_screen_diagnostics(app: QApplication, window: QWidget) -> dict[str, Any]:
    """Collect Qt logical and physical metrics without changing Qt's DPI policy."""

    screen = window.screen() or app.primaryScreen()
    if screen is None:
        return {
            "screen": None,
            "window": _rect_data(window.geometry()),
            "design_viewport": {"width": int(REFERENCE_WIDTH), "height": int(REFERENCE_HEIGHT)},
            "final_scale": None,
        }

    dpr = float(screen.devicePixelRatio())
    geometry = screen.geometry()
    available = screen.availableGeometry()
    transform = design_transform(window.width(), window.height())
    return {
        "screen_name": screen.name(),
        "physical_screen_resolution": {
            "width": round(geometry.width() * dpr),
            "height": round(geometry.height() * dpr),
        },
        "logical_screen_resolution": {"width": geometry.width(), "height": geometry.height()},
        "available_geometry": _rect_data(available),
        "available_geometry_physical": {
            "x": round(available.x() * dpr),
            "y": round(available.y() * dpr),
            "width": round(available.width() * dpr),
            "height": round(available.height() * dpr),
        },
        "device_pixel_ratio": dpr,
        "logical_dpi": float(screen.logicalDotsPerInch()),
        "physical_dpi": float(screen.physicalDotsPerInch()),
        "windows_scale_percent": round(dpr * 100),
        "window_geometry": _rect_data(window.geometry()),
        "window_geometry_physical": {
            "x": round(window.x() * dpr),
            "y": round(window.y() * dpr),
            "width": round(window.width() * dpr),
            "height": round(window.height() * dpr),
        },
        "design_viewport": {"width": int(REFERENCE_WIDTH), "height": int(REFERENCE_HEIGHT)},
        "design_viewport_geometry": {
            "x": transform.offset_x,
            "y": transform.offset_y,
            "width": REFERENCE_WIDTH * transform.scale,
            "height": REFERENCE_HEIGHT * transform.scale,
        },
        "final_scale": transform.scale,
        "final_scale_physical": transform.scale * dpr,
        "qt_high_dpi_double_scaling": False,
        "qt_scale_environment": {
            name: value
            for name in ("QT_SCALE_FACTOR", "QT_AUTO_SCREEN_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING")
            if (value := os.environ.get(name)) is not None
        },
    }
