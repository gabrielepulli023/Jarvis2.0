"""Repeatable real-world evaluation pack for JARVIS.

The automatic portion evaluates decisions and policies without executing
destructive desktop actions. Interactive gates are represented explicitly and
can be filled by the Windows acceptance runner.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app_paths import data_path
from automation_intelligence import ActionMode, choose_policy
from decision_layer import IntentKind, Strategy, decide
from performance_metrics import report as metrics_report
from provider_router import decide_route


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    category: str
    prompt: str
    expected_kind: str
    expected_strategy: str
    expected_tools: bool
    manual_gate: str | None = None


SCENARIOS = (
    Scenario("conversation.answer", "conversation", "Come funziona la memoria di Jarvis?", IntentKind.INFORMATION.value, Strategy.ANSWER.value, False),
    Scenario("capability.no_side_effect", "conversation", "Puoi usare la webcam?", IntentKind.CAPABILITY.value, Strategy.ANSWER.value, False),
    Scenario("desktop.direct", "desktop", "Apri la calcolatrice", IntentKind.OPERATION.value, Strategy.USE_TOOLS.value, True, "calculator_uia"),
    Scenario("desktop.structured_ui", "desktop", "Clicca il pulsante play nella finestra", IntentKind.OPERATION.value, Strategy.OBSERVE_THEN_ACT.value, True, "desktop_uia"),
    Scenario("browser.dom_first", "browser", "Clicca il risultato nella pagina Chrome", IntentKind.OPERATION.value, Strategy.OBSERVE_THEN_ACT.value, True, "browser_dom"),
    Scenario("compound.plan_verify", "automation", "Apri Chrome e poi verifica il risultato", IntentKind.COMPOSITE.value, Strategy.PLAN_AND_VERIFY.value, True, "compound_desktop"),
    Scenario("ambiguity.ask", "safety", "Apri quello di prima", IntentKind.CONVERSATION.value, Strategy.ANSWER.value, False),
    Scenario("local_file.operation", "desktop", "Cerca questo file sul computer", IntentKind.OPERATION.value, Strategy.USE_TOOLS.value, True, "file_search"),
    Scenario("current.web", "information", "Quali sono le ultime notizie oggi?", IntentKind.INFORMATION.value, Strategy.ANSWER.value, False, "web_current_info"),
    Scenario("recovery.unverified", "recovery", "Esegui il controllo e verifica che sia riuscito", IntentKind.OPERATION.value, Strategy.USE_TOOLS.value, True, "verified_recovery"),
)


def run_automatic() -> dict:
    started = time.perf_counter()
    rows = []
    for scenario in SCENARIOS:
        decision = decide(scenario.prompt, has_context=False)
        policy = choose_policy(scenario.prompt, has_context=False)
        # The ambiguity scenario is intentionally a conversational clarification
        # at the decision layer and an ASK policy at the automation layer.
        if scenario.id == "ambiguity.ask":
            passed = policy.mode == ActionMode.ASK and policy.requires_clarification
        else:
            passed = (
                decision.kind.value == scenario.expected_kind
                and decision.strategy.value == scenario.expected_strategy
                and decision.needs_tools == scenario.expected_tools
            )
        route = decide_route(scenario.prompt, requires_tools=scenario.expected_tools)
        rows.append({
            "id": scenario.id,
            "category": scenario.category,
            "status": "PASS" if passed else "FAIL",
            "decision": {"kind": decision.kind.value, "strategy": decision.strategy.value, "needs_tools": decision.needs_tools},
            "policy": {"mode": policy.mode.value, "needs_observation": policy.needs_observation, "needs_verification": policy.needs_verification, "requires_clarification": policy.requires_clarification},
            "provider": {"provider": route.provider, "task_kind": route.task_kind},
            "manual_gate": scenario.manual_gate,
        })
    passed = sum(row["status"] == "PASS" for row in rows)
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "automatic": {"passed": passed, "total": len(rows), "status": "PASS" if passed == len(rows) else "FAIL"},
        "scenarios": rows,
        "manual_gates": sorted({row["manual_gate"] for row in rows if row["manual_gate"]}),
        "kpi_snapshot": metrics_report().get("dati", {}),
        "sensitive_data_persisted": False,
    }


def write_report(report: dict, path: Path | None = None) -> Path:
    target = path or (data_path("evaluation_reports") / f"real-world-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def main() -> int:
    report = run_automatic()
    path = write_report(report)
    print(json.dumps({"report": str(path), "automatic": report["automatic"], "manual_gates": report["manual_gates"]}, ensure_ascii=False))
    return 0 if report["automatic"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
