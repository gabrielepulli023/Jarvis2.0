"""Validate the production Qt HUD entirely in memory; no screenshot is saved."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from hud import JarvisHUD
from tests.hud_visual_qa import compare_images


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("--settle-ms", type=int, default=3200)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    hud = JarvisHUD()
    # Match the production launcher: Qt chooses the real monitor geometry and
    # applies its DPI scale before the in-memory grab.
    hud.showFullScreen()
    result: dict = {}

    def validate() -> None:
        image = hud.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
        size = image.width() * image.height() * 4
        candidate = Image.frombytes(
            "RGBA", (image.width(), image.height()), bytes(image.bits()[:size])
        ).convert("RGB")
        with Image.open(args.reference) as source:
            reference = source.convert("RGB")
        result.update(compare_images(reference, candidate, candidate_source="live-memory"))
        hud.shutdown_services()
        hud.close()
        app.quit()

    QTimer.singleShot(max(250, args.settle_ms), validate)
    app.exec()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
