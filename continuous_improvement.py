"""Bounded analysis of real-world evaluation history and runtime KPIs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app_paths import data_path


def _reports() -> list[dict]:
    root = data_path("evaluation_reports")
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.glob("real-world-*.json"), key=lambda item: item.stat().st_mtime)[-20:]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                rows.append({"path": str(path), "report": value})
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def analyze_evaluations() -> dict:
    rows = _reports()
    latest = rows[-1]["report"] if rows else None
    previous = rows[-2]["report"] if len(rows) > 1 else None
    current_pass = float((latest or {}).get("automatic", {}).get("passed", 0))
    current_total = float((latest or {}).get("automatic", {}).get("total", 0))
    previous_pass = float((previous or {}).get("automatic", {}).get("passed", 0))
    previous_total = float((previous or {}).get("automatic", {}).get("total", 0))
    regressions = []
    if previous and current_pass < previous_pass:
        regressions.append({"kind": "automatic_pass_count", "previous": previous_pass, "current": current_pass})
    previous_ids = {row.get("id"): row.get("status") for row in (previous or {}).get("scenarios", [])}
    for row in (latest or {}).get("scenarios", []):
        if previous_ids.get(row.get("id")) == "PASS" and row.get("status") == "FAIL":
            regressions.append({"kind": "scenario", "id": row.get("id")})
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "reports_considered": len(rows),
        "latest": {"passed": int(current_pass), "total": int(current_total), "status": (latest or {}).get("automatic", {}).get("status", "NO_DATA")},
        "previous": {"passed": int(previous_pass), "total": int(previous_total)},
        "regressions": regressions,
        "status": "REGRESSION" if regressions else ("HEALTHY" if latest else "NO_DATA"),
        "recommendations": (["Ripetere gli scenari falliti prima di aggiornare l'EXE."] if regressions else []),
    }


def write_analysis(value: dict, path: Path | None = None) -> Path:
    target = path or (data_path("evaluation_reports") / "trend-analysis.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target
