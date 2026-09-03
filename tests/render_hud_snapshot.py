"""Render the production HUD offscreen for deterministic visual validation."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from hud import JarvisHUD


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--settle-ms", type=int, default=2800)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    hud = JarvisHUD()
    hud.resize(1672, 941)
    hud.show()

    result = {"saved": False}

    def capture() -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result["saved"] = bool(hud.grab().save(str(args.output), "PNG"))
        hud.shutdown_services()
        hud.close()
        app.quit()

    QTimer.singleShot(max(250, args.settle_ms), capture)
    app.exec()
    if not result["saved"]:
        raise RuntimeError(f"Unable to save HUD render to {args.output}")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
