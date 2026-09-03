"""Render the two reference-sized production surfaces and their QA boards."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageChops, ImageEnhance, ImageDraw
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from hud_ui import HomeView, StartupView
from hud_ui.viewport import HOME_PANEL, STARTUP_PANEL


def _capture(widget, size: tuple[int, int], output: Path, settle_ms: int) -> None:
    widget.resize(*size)
    widget.show()
    result = {"saved": False}

    def save() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        result["saved"] = bool(widget.grab().save(str(output), "PNG"))
        widget.close()
        QApplication.instance().quit()

    QTimer.singleShot(settle_ms, save)
    QApplication.instance().exec()
    if not result["saved"]:
        raise RuntimeError(f"Unable to save render to {output}")


def _crop_panel(source: Path, target: Path, box: tuple[int, int, int, int]) -> None:
    with Image.open(source) as image:
        x, y, width, height = box
        panel = image.crop((x, y, x + width, y + height))
        target.parent.mkdir(parents=True, exist_ok=True)
        panel.save(target, "PNG", optimize=True)


def _comparison(target_path: Path, actual_path: Path, output: Path) -> None:
    with Image.open(target_path) as target_source, Image.open(actual_path) as actual_source:
        target = target_source.convert("RGB")
        actual = actual_source.convert("RGB").resize(target.size, Image.Resampling.LANCZOS)
    diff = ImageEnhance.Contrast(ImageChops.difference(target, actual)).enhance(4.0)
    board = Image.new("RGB", (target.width * 3 + 2, target.height), (4, 4, 6))
    board.paste(target, (0, 0))
    board.paste(actual, (target.width + 1, 0))
    board.paste(diff, (target.width * 2 + 2, 0))
    draw = ImageDraw.Draw(board)
    draw.line((target.width, 0, target.width, target.height), fill=(170, 170, 178), width=1)
    draw.line((target.width * 2 + 1, 0, target.width * 2 + 1, target.height), fill=(170, 170, 178), width=1)
    output.parent.mkdir(parents=True, exist_ok=True)
    board.save(output, "PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settle-ms", type=int, default=900)
    args = parser.parse_args()
    diagnostics = ROOT / "diagnostics"
    app = QApplication.instance() or QApplication([])

    home_target = diagnostics / "reference_target_home.png"
    startup_target = diagnostics / "reference_target_startup.png"
    home_actual = diagnostics / "actual_home_final.png"
    startup_actual = diagnostics / "actual_startup_final.png"

    with tempfile.TemporaryDirectory(prefix="jarvis_reference_render_") as temp_dir:
        home_full = Path(temp_dir) / "home.png"
        _capture(HomeView(), (1672, 941), home_full, max(250, args.settle_ms))
        _crop_panel(home_full, home_actual, tuple(round(value) for value in HOME_PANEL.getRect()))

        startup = StartupView()
        startup.set_status("INITIALIZING SYSTEMS")
        startup.set_progress(78)
        startup_full = Path(temp_dir) / "startup.png"
        _capture(startup, (1672, 941), startup_full, max(250, args.settle_ms))
        _crop_panel(startup_full, startup_actual, tuple(round(value) for value in STARTUP_PANEL.getRect()))

    _comparison(home_target, home_actual, diagnostics / "home_reference_comparison.png")
    _comparison(startup_target, startup_actual, diagnostics / "startup_reference_comparison.png")
    preview = ROOT / "assets" / "preview"
    preview.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(home_actual, preview / "home_reference_match.png")
    shutil.copyfile(startup_actual, preview / "startup_reference_match.png")
    print(home_actual.resolve())
    print(startup_actual.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
