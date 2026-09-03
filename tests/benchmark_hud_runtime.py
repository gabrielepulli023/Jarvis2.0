"""Short live benchmark for the production HUD; stores no frames or screenshots."""

from __future__ import annotations

import json
import argparse
import sys
import time
from collections import deque
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psutil
from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication

from hud import JarvisHUD
from hud_ui.orb_widget import OrbWidget


class PaintCounter(QObject):
    def __init__(self):
        super().__init__()
        self.samples = deque(maxlen=600)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Paint:
            self.samples.append(time.perf_counter())
        return False

    def fps(self, window_seconds=4.0):
        if len(self.samples) < 2:
            return 0.0
        cutoff = self.samples[-1] - window_seconds
        values = [value for value in self.samples if value >= cutoff]
        return (len(values) - 1) / max(values[-1] - values[0], 1e-6) if len(values) > 1 else 0.0


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--core-only",action="store_true")
    parser.add_argument("--ui-only",action="store_true")
    parser.add_argument("--duration",type=float,default=7.5,help="durata del test in secondi (1-3600)")
    args=parser.parse_args()
    duration = max(1.0, min(float(args.duration), 3600.0))
    app = QApplication.instance() or QApplication([])
    process = psutil.Process()
    process.cpu_percent(None)
    rss_before = process.memory_info().rss
    hud = OrbWidget() if args.core_only else JarvisHUD()
    hud.resize(870,625) if args.core_only else hud.resize(1672, 941)
    if args.ui_only and not args.core_only:
        hud.shutdown_services()
        for page in hud.pages.values():
            clock = getattr(page, "clock", None)
            if clock is not None:
                clock.stop()
            orb = getattr(page, "orb", None)
            if orb is not None:
                orb._timer.stop()
    counter = PaintCounter()
    target = hud if args.core_only or not hasattr(hud, "core") else hud.core
    target.installEventFilter(counter)
    hud.show()
    hud.raise_()
    hud.activateWindow()
    result = {}

    def finish():
        memory = process.memory_info()
        result.update({
            "core_paint_fps": round(counter.fps(), 2),
            "rss_mb": round(memory.rss / 1024 / 1024, 2),
            "rss_before_mb": round(rss_before / 1024 / 1024, 2),
            "rss_growth_mb": round((memory.rss - rss_before) / 1024 / 1024, 2),
            "private_mb": round(getattr(memory, "private", memory.rss) / 1024 / 1024, 2),
            "cpu_percent_process": round(process.cpu_percent(None), 2),
            "resolution": [hud.width(), hud.height()],
            "core_only": args.core_only,
            "ui_only": args.ui_only,
        })
        if not args.core_only:
            hud.shutdown_services()
        hud.close()
        app.quit()

    QTimer.singleShot(int(duration * 1000), finish)
    app.exec()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
