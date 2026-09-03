"""Render the production startup surface offscreen for visual QA."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from hud_ui import StartupView


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--progress", type=float, default=62.0)
    parser.add_argument("--settle-ms", type=int, default=500)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    startup = StartupView()
    startup.resize(1280, 720)
    startup.set_status("INITIALIZING SYSTEMS")
    startup.set_progress(args.progress)
    startup.show()
    result = {"saved": False}

    def capture() -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result["saved"] = bool(startup.grab().save(str(args.output), "PNG"))
        startup.close()
        app.quit()

    QTimer.singleShot(max(100, args.settle_ms), capture)
    app.exec()
    if not result["saved"]:
        raise RuntimeError(f"Unable to save startup render to {args.output}")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
