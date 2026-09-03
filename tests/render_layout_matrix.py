"""Render the canonical Home/Startup layout at fixed logical resolutions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run_capture(widget, output: Path, size: tuple[int, int], settle_ms: int, app, fullscreen: bool = False) -> None:
    if fullscreen:
        widget.showFullScreen()
    else:
        widget.resize(*size)
        widget.show()
    saved = {"value": False}

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        saved["value"] = bool(widget.grab().save(str(output), "PNG"))
        widget.close()
        app.quit()

    QTimer.singleShot(max(150, settle_ms), save)
    app.exec()
    if not saved["value"]:
        raise RuntimeError(f"Unable to save {output}")


def _metrics(size: tuple[int, int]) -> dict:
    from hud_ui.viewport import HOME_ORB, STARTUP_MARK, design_transform, mapped_geometry

    transform = design_transform(*size)
    orb = mapped_geometry(transform, HOME_ORB)
    mark = mapped_geometry(transform, STARTUP_MARK)
    return {
        "resolution": list(size),
        "design_viewport": [1672, 941],
        "final_scale": transform.scale,
        "viewport_offset": [transform.offset_x, transform.offset_y],
        "orb_display_size": [orb[2], orb[3]],
        "orb_aspect": orb[2] / orb[3],
        "startup_mark_display_size": [mark[2], mark[3]],
        "startup_mark_aspect": mark[2] / mark[3],
        "letterboxed": bool(transform.offset_x or transform.offset_y),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settle-ms", type=int, default=450)
    parser.add_argument("--actual-monitor", action="store_true")
    args = parser.parse_args()
    if not args.actual_monitor:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from hud_ui import HomeView, StartupView
    from hud_ui.main_window import MainWindow
    from hud_ui.diagnostics import collect_screen_diagnostics

    app = QApplication.instance() or QApplication([])
    sizes = [(1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440)]
    diagnostics = ROOT / "diagnostics"
    all_metrics = []
    for width, height in sizes:
        size = (width, height)
        home = HomeView()
        startup = StartupView()
        startup.set_status("INITIALIZING SYSTEMS")
        startup.set_progress(78)
        _run_capture(home, diagnostics / f"layout_{width}x{height}.png", size, args.settle_ms, app)
        _run_capture(startup, diagnostics / f"layout_{width}x{height}_startup.png", size, args.settle_ms, app)
        all_metrics.append(_metrics(size))

    if args.actual_monitor:
        screen = app.primaryScreen()
        if screen is None:
            raise RuntimeError("No primary screen available")
        size = (screen.geometry().width(), screen.geometry().height())
        monitor_home = MainWindow()
        monitor_home.showFullScreen()
        app.processEvents()
        monitor_data = collect_screen_diagnostics(app, monitor_home)
        _run_capture(monitor_home, diagnostics / "layout_actual_monitor.png", size, args.settle_ms, app, fullscreen=True)
        monitor_data["rendered_resolution"] = [monitor_home.width(), monitor_home.height()]
    else:
        monitor_data = None

    (diagnostics / "layout_diagnostics.json").write_text(
        json.dumps({"resolutions": all_metrics, "actual_monitor": monitor_data}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"resolutions": all_metrics, "actual_monitor": monitor_data}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
