from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from jarvis_integrations.langgraph_backend import LangGraphBackend
from jarvis_integrations.models import IntegrationResult
from jarvis_integrations.safety import contains_secret, guard_external_task
from jarvis_integrations.service import IntegrationService
from jarvis_integrations.ufo_backend import UFOBackend


def _service(tmp_path: Path) -> IntegrationService:
    service = IntegrationService(tmp_path)
    service.config.enabled = True
    service.config.browser_use_enabled = True
    service.config.ufo_enabled = True
    service.config.ui_tars_enabled = True
    service.config.langgraph_enabled = True
    return service


def test_routing_browser_prefers_browser_use(tmp_path):
    service = _service(tmp_path)
    assert service.route_candidates("Apri il browser e cerca GitHub")[0] == "browser_use"


def test_routing_windows_prefers_ufo(tmp_path):
    service = _service(tmp_path)
    assert service.route_candidates("Apri Excel su Windows e crea un foglio")[0] == "ufo"


def test_routing_visual_prefers_ui_tars(tmp_path):
    service = _service(tmp_path)
    assert service.route_candidates("Guarda lo schermo e trova il pulsante Continua")[0] == "ui_tars"


def test_external_guard_blocks_credentials_and_payments():
    assert guard_external_task("Inserisci la password nel sito")[0] is False
    assert guard_external_task("Completa il pagamento")[0] is False
    assert guard_external_task("Cerca tre documenti pubblici su GitHub")[0] is True


def test_secret_detector():
    assert contains_secret("api_key=abcdef123456789")
    assert contains_secret("password=segreta")
    assert not contains_secret("preferisco VS Code")


def test_langgraph_deterministic_fallback_when_dependency_missing():
    graph = LangGraphBackend()
    calls = []

    def execute(backend, task):
        calls.append((backend, task))
        if backend == "ufo":
            return IntegrationResult.fail("ufo", "offline")
        return IntegrationResult.ok(backend, "ok")

    with patch.object(LangGraphBackend, "available", return_value=False):
        result = graph.run("task", ["ufo", "browser_use"], execute)
    assert result.success is True
    assert result.backend == "browser_use"
    assert [row[0] for row in calls] == ["ufo", "browser_use"]


def test_ufo_dispatch_and_polling_without_network():
    backend = UFOBackend("http://127.0.0.1:5000", "jarvis_windows", poll_seconds=0.001, timeout_seconds=1)
    responses = iter([
        {"status": "dispatched"},
        {"status": "pending"},
        {"status": "done", "result": {"observation": "completato"}},
    ])

    with patch.object(backend, "_json_request", side_effect=lambda *args, **kwargs: next(responses)):
        result = backend.run("Apri Blocco note")
    assert result.success is True
    assert result.backend == "ufo"
    assert "completato" in result.message


def test_forced_backend_respects_feature_flag(tmp_path):
    service = _service(tmp_path)
    service.config.ufo_enabled = False
    assert service.route_candidates("Apri Excel", preferred="ufo") == []


def test_external_agent_tools_require_confirmation():
    from permission_engine import RiskClassifier, RiskLevel

    classifier = RiskClassifier()
    for tool in ("delegate_agent_task", "browser_agent_task", "ufo_agent_task", "ui_tars_agent_task", "mem0_remember"):
        policy = classifier.classify(tool)
        assert policy.risk is RiskLevel.SENSITIVE
        assert policy.confirmation_required is True
