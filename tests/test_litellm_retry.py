import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import brain
from jarvis_skills import Capability, SkillManifest, SkillRegistry
from jarvis_expansion.routing import litellm_arguments
from pathlib import Path
import tempfile


class LiteLLMAndRetryTests(unittest.TestCase):
    def test_deterministic_litellm_request_has_required_model_and_prompt(self):
        arguments = litellm_arguments(
            'Usa LiteLLM con il modello "openai/gpt-4o-mini" e rispondi esattamente con JARVIS_LITELLM_OK'
        )
        self.assertEqual("openai/gpt-4o-mini", arguments["model"])
        self.assertEqual("Respond exactly with: JARVIS_LITELLM_OK", arguments["prompt"])
    def test_registry_reports_missing_required_arguments_without_invoking_handler(self):
        calls = []

        def handler(model, prompt, max_tokens=512):
            calls.append(True)
            return {"success": True}

        with tempfile.TemporaryDirectory() as folder:
            registry = SkillRegistry(Path(folder) / "metrics.db", lambda _capability: True)
            registry.register(SkillManifest("litellm.complete", "1", "test", ("litellm",), frozenset({Capability.NETWORK}), "jarvis_expansion:litellm"), handler)
            result = registry.execute("litellm.complete")

        self.assertFalse(result.success)
        self.assertEqual(["model", "prompt"], result.data["missing_required_arguments"])
        self.assertEqual("invalid_tool_arguments", result.data["error"])
        self.assertTrue(result.data["invocation_not_started"])
        self.assertEqual([], calls)

    def test_schema_error_retry_is_correlated_by_tool_and_skill(self):
        failures, pending, unverified, successes, schema_errors = [], [], [], [], []
        brain._record_tool_result(
            "expansion_call", {"skill": "litellm.complete", "arguments_json": "{}"},
            {"successo": False, "messaggio": "Argomenti tool non validi", "dati": {"error": "invalid_tool_arguments", "invocation_not_started": True}},
            failures, pending, unverified, successes, schema_errors,
        )
        brain._record_tool_result(
            "expansion_call", {"skill": "litellm.complete", "arguments_json": '{"model":"m","prompt":"p"}'},
            {"successo": True, "messaggio": "ok", "skill": "litellm.complete", "dati": {"text": "ok"}, "verification": {"status": "verified"}},
            failures, pending, unverified, successes, schema_errors,
        )
        self.assertEqual([], failures)
        self.assertEqual([], schema_errors)
    def test_litellm_uses_prompt_schema_and_normalizes_legacy_input_alias(self):
        calls = []

        class Registry:
            def manifest(self, name):
                return SimpleNamespace(entrypoint="jarvis_expansion:litellm") if name == "litellm.complete" else None

            def execute(self, name, **arguments):
                calls.append((name, arguments))
                return SimpleNamespace(
                    success=True,
                    message="Operazione completata.",
                    data={"model": arguments["model"], "text": "JARVIS_LITELLM_OK"},
                )

        with patch.object(brain.CORE_RUNTIME, "skills", Registry()):
            result = brain._tool_expansion_call(
                "litellm.complete",
                json.dumps({"model": "openai/gpt-4o-mini", "input": "Respond exactly with: JARVIS_LITELLM_OK", "max_tokens": 32}),
            )

        self.assertTrue(result["successo"])
        self.assertEqual("JARVIS_LITELLM_OK", result["dati"]["text"])
        self.assertEqual(
            ("litellm.complete", {"model": "openai/gpt-4o-mini", "prompt": "Respond exactly with: JARVIS_LITELLM_OK", "max_tokens": 32}),
            calls[0],
        )

    def test_litellm_rejects_unknown_arguments_before_python_handler(self):
        calls = []

        class Registry:
            def manifest(self, _name):
                return SimpleNamespace(entrypoint="jarvis_expansion:litellm")

            def execute(self, *_args, **_kwargs):
                calls.append(True)
                raise AssertionError("handler must not be called")

        with patch.object(brain.CORE_RUNTIME, "skills", Registry()):
            result = brain._tool_expansion_call("litellm.complete", json.dumps({"model": "m", "prompt": "p", "input_schema": {}}))
        self.assertFalse(result["successo"])
        self.assertIn("input_schema", result["messaggio"])
        self.assertEqual([], calls)

    def test_correlated_verified_retry_supersedes_previous_failure(self):
        failures, pending, unverified, successes = [], [], [], []
        arguments = {"skill": "litellm.complete", "arguments_json": json.dumps({"model": "m", "input": "p"})}
        brain._record_tool_result(
            "expansion_call", arguments, {"successo": False, "messaggio": "unexpected keyword argument 'input'"},
            failures, pending, unverified, successes,
        )
        brain._record_tool_result(
            "expansion_call",
            {"skill": "litellm.complete", "arguments_json": json.dumps({"model": "m", "prompt": "p"})},
            {"successo": True, "messaggio": "ok", "skill": "litellm.complete", "dati": {"text": "JARVIS_LITELLM_OK"}},
            failures, pending, unverified, successes,
        )
        self.assertEqual([], failures)
        self.assertEqual("JARVIS_LITELLM_OK", successes[-1]["result"]["dati"]["text"])

    def test_unrelated_failure_is_not_hidden_by_success(self):
        failures, pending, unverified, successes = [], [], [], []
        brain._record_tool_result("tool_a", {"x": 1}, {"successo": False, "messaggio": "A failed"}, failures, pending, unverified, successes)
        brain._record_tool_result(
            "tool_b", {"x": 2}, {"successo": True, "messaggio": "B ok", "verification": {"status": "verified"}},
            failures, pending, unverified, successes,
        )
        self.assertEqual(["A failed"], [row["message"] for row in failures])


if __name__ == "__main__":
    unittest.main()
