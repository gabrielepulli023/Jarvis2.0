"""Controlled target-PC smoke check for the elevated broker; not part of pytest."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis_broker import BrokerManager  # noqa: E402


def main() -> int:
    manager = BrokerManager()
    preexisting = manager.health()
    started = preexisting or manager.ensure_available(timeout=30)
    results = {}
    try:
        if not started:
            print(
                json.dumps(
                    {
                        "success": False,
                        "stage": "elevation",
                        "preexisting": preexisting,
                        "diagnostics": manager.diagnostics(),
                    }
                )
            )
            return 2
        for action in ("system.info", "driver.list", "software.list"):
            started_at = time.monotonic()
            response = manager.client.execute(action, {})
            results[action] = {
                "success": response.success,
                "exit_code": response.data.get("exit_code"),
                "stdout_chars": len(str(response.data.get("stdout") or "")),
                "error": response.data.get("error"),
                "message": response.message,
                "duration_seconds": round(time.monotonic() - started_at, 3),
            }
        success = all(row["success"] for row in results.values())
        print(json.dumps({"success": success, "preexisting": preexisting, "queries": results}, sort_keys=True))
        return 0 if success else 3
    finally:
        if started and not preexisting:
            manager.stop(confirmed=True)


if __name__ == "__main__":
    raise SystemExit(main())
