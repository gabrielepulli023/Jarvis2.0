import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from model_selector import reasoning_options


class _FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls)
        if index == 1:
            return SimpleNamespace(
                output=[SimpleNamespace(type="function_call", name="apri_programma", arguments='{"nome":"Chrome"}', call_id="c1")],
                output_text="",
            )
        if index == 2:
            return SimpleNamespace(
                output=[SimpleNamespace(type="function_call", name="apri_sito", arguments='{"nome":"YouTube"}', call_id="c2")],
                output_text="",
            )
        return SimpleNamespace(output=[], output_text="Fatto. Ho aperto Chrome e YouTube.")


class _FailedActionResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                output=[SimpleNamespace(type="function_call", name="apri_programma", arguments='{"nome":"Chrome"}', call_id="failed-1")],
                output_text="",
            )
        return SimpleNamespace(output=[], output_text="Fatto, Chrome è aperto.")


class AgentRouterTests(unittest.TestCase):
    def test_volume_request_is_operational(self):
        import main
        import provider_router

        phrase = "Alza il volume"
        self.assertTrue(main.deve_usare_router_operativo(phrase))
        self.assertEqual(provider_router.classify_task(phrase), "tool_execution")

    def test_standalone_write_focuses_notepad_and_requires_verification(self):
        import brain

        calls = []

        def fake_tool(name, arguments):
            calls.append((name, arguments))
            if name == "scrivi_testo":
                return {"successo": True, "messaggio": "Testo inserito."}
            if name == "copia_selezione":
                return {"successo": True, "dati": {"clipboard": "ciao"}}
            return {"successo": True, "messaggio": "ok"}

        with patch.object(brain, "finestra_attiva", return_value={"successo": True, "dati": {"titolo": "Chrome"}}), \
             patch.object(brain, "porta_finestra_davanti", return_value={"successo": True, "messaggio": "ok"}) as focus, \
             patch.object(brain, "esegui_tool", side_effect=fake_tool):
            result = brain._interpreta_comando_locale("Scrivi ciao")

        self.assertEqual(result[0], True)
        self.assertIn("verificato", result[1])
        focus.assert_called_once_with("Blocco note")
        self.assertEqual(calls[0], ("scrivi_testo", {"testo": "ciao"}))

    def test_local_commands_ignore_wake_prefix_politeness_and_punctuation(self):
        import brain
        phrases = [
            "Mostra desktop.", "Jarvis, mostra il desktop!", "Per favore mostra desktop",
            "Apri TradingView.", "Apri la calcolatrice!", "Puoi aprire Chrome?",
            "Volume 50.", "Metti in muto.", "Vai su YouTube.", "Chiudi Spotify.",
        ]
        with patch.object(brain, "esegui_tool", return_value={"successo": True, "messaggio": "ok"}) as execute:
            results = [brain._interpreta_comando_locale(phrase) for phrase in phrases]
        self.assertTrue(all(result is not None and result[0] for result in results))
        self.assertEqual(execute.call_count, len(phrases))

    def test_local_commands_are_not_disabled_by_performance_mode(self):
        import brain
        with patch.object(brain, "get_setting", side_effect=lambda key, default=None: False if key == "performance_mode" else default), patch.object(brain, "esegui_tool", return_value={"successo": True, "messaggio": "ok"}) as execute:
            result = brain.interpreta_comando("Apri Chrome")
        self.assertTrue(result[0])
        execute.assert_called_once_with("apri_programma", {"nome": "Chrome"})

    def test_local_command_returns_tool_failure_instead_of_done(self):
        import brain
        failure = {"successo": False, "messaggio": "Chrome non è stato avviato."}
        with patch.object(brain, "esegui_tool", return_value=failure):
            handled, message, _minimized = brain.interpreta_comando("Apri Chrome")
        self.assertTrue(handled)
        self.assertIn("Chrome non è stato avviato", message)
        self.assertNotIn("Fatto", message)

    def test_reasoning_effort_is_model_compatible(self):
        self.assertEqual(reasoning_options("gpt-5-mini", "none"), {"effort": "minimal"})
        self.assertEqual(reasoning_options("gpt-5.6-luna", "minimal"), {"effort": "none"})
        self.assertEqual(reasoning_options("gpt-5.6-luna", "low"), {"effort": "low"})
        self.assertIsNone(reasoning_options("gpt-4o-mini", "low"))
        self.assertEqual(reasoning_options("gpt-5-mini", "minimal", tools=[{"type": "web_search"}]), {"effort": "low"})

    def test_research_bypasses_operational_router(self):
        import main
        prompt = "Puoi creare per me una ricerca completa sull'intelligenza artificiale e sul futuro?"
        self.assertFalse(main.deve_usare_router_operativo(prompt))
        self.assertTrue(main.deve_usare_router_operativo("Mostra desktop"))

    def test_generic_search_does_not_trigger_desktop_actions(self):
        import main

        self.assertFalse(main.deve_usare_router_operativo("Cerca informazioni sui vulcani"))
        self.assertTrue(main.deve_usare_router_operativo("Cerca questo file sul computer"))

    def test_health_command_uses_local_diagnostics(self):
        import brain
        brain.CORE_RUNTIME.health.report("core", "HEALTHY", "test")
        handled, message, minimized = brain._interpreta_comando_locale("/health")
        self.assertTrue(handled)
        self.assertIn("core: HEALTHY", message)
        self.assertFalse(minimized)

    def test_evaluation_command_is_local_and_reports_trend(self):
        import brain
        with patch("continuous_improvement.analyze_evaluations", return_value={"status": "HEALTHY", "reports_considered": 3, "regressions": []}):
            handled, message, minimized = brain._interpreta_comando_locale("controlla le regressioni")
        self.assertTrue(handled)
        self.assertIn("nessuna regressione", message)
        self.assertFalse(minimized)

    def test_tool_errors_are_redacted_before_returning_to_model(self):
        import brain
        original = brain.FUNZIONI["performance_report"]
        brain.FUNZIONI["performance_report"] = lambda: (_ for _ in ()).throw(RuntimeError("token=secret-value"))
        try:
            result = brain.esegui_tool("performance_report", {})
        finally:
            brain.FUNZIONI["performance_report"] = original
        self.assertFalse(result["successo"])
        self.assertNotIn("secret-value", result["errore"])
        self.assertIn("[REDACTED]", result["errore"])

    def test_router_cannot_turn_failed_tool_into_success(self):
        import brain

        responses = _FailedActionResponses()
        failed = {"successo": False, "messaggio": "Chrome non è stato avviato."}
        with patch.object(brain, "client", SimpleNamespace(responses=responses)), \
             patch.object(brain, "esegui_tool", return_value=failed), \
             patch.object(brain, "agent_begin", return_value=None), \
             patch.object(brain, "agent_add_step"), \
             patch.object(brain, "select_model", return_value="test-model"):
            handled, message, _minimized = brain.interpreta_comando("Apri Chrome e massimizzalo")

        self.assertTrue(handled)
        self.assertIn("Non ho completato", message)
        self.assertIn("Chrome non è stato avviato", message)
        self.assertNotIn("Fatto, Chrome è aperto", message)

    def test_computer_error_helper_redacts_details(self):
        import computer
        result = computer.errore("fallimento", "token=secret-value")
        self.assertNotIn("secret-value", result["errore"])
        self.assertIn("[REDACTED]", result["errore"])

    def test_multi_action_keeps_original_request(self):
        import brain
        executed = []

        def fake_execute(name, arguments):
            executed.append((name, arguments))
            return {"successo": True, "messaggio": "ok"}

        with patch.object(brain, "esegui_tool", fake_execute):
            result = brain.interpreta_comando("Apri Chrome e vai su YouTube")

        self.assertTrue(result[0])
        self.assertEqual([row[0] for row in executed], ["apri_programma", "apri_sito"])

    def test_common_multi_actions_are_local_and_deterministic(self):
        import brain

        with patch.object(brain, "esegui_tool", return_value={"successo": True, "messaggio": "ok"}) as execute:
            browser = brain._interpreta_comando_locale("Apri Chrome e vai su TradingView")
            editor = brain._interpreta_comando_locale("Apri Blocco Note e scrivi ciao mondo")

        self.assertTrue(browser[0])
        self.assertTrue(editor[0])
        self.assertEqual(
            [call.args for call in execute.call_args_list],
            [
                ("apri_programma", {"nome": "Chrome"}),
                ("apri_sito", {"nome": "TradingView"}),
                ("apri_programma", {"nome": "Blocco Note"}),
                ("scrivi_testo", {"testo": "ciao mondo"}),
            ],
        )

    def test_open_chrome_is_os_app_action_not_browser_dom_action(self):
        import brain

        with patch.object(brain, "esegui_tool", return_value={"successo": True, "messaggio": "Chrome aperto"}) as execute:
            result = brain._interpreta_comando_locale("Apri Chrome")
        self.assertTrue(result[0])
        execute.assert_called_once_with("apri_programma", {"nome": "Chrome"})

    def test_windows_settings_is_a_local_command(self):
        import brain

        with patch.object(brain, "esegui_tool", return_value={"successo": True, "messaggio": "ok"}) as execute:
            result = brain._interpreta_comando_locale("Apri le impostazioni di Windows")
        self.assertTrue(result[0])
        execute.assert_called_once_with("apri_impostazioni", {})

    def test_capability_questions_never_fall_back_to_chatbot_disclaimer(self):
        import brain

        for phrase in (
            "Cosa sai fare?",
            "Puoi controllare direttamente il mio computer?",
            "Puoi usare mouse e tastiera sul PC?",
        ):
            handled, message, minimized = brain._interpreta_comando_locale(phrase)
            self.assertTrue(handled, phrase)
            self.assertIn("posso controllare", message.lower())
            self.assertNotIn("non posso controllare", message.lower())
            self.assertFalse(minimized)

    def test_capability_report_exposes_available_and_blocked_actions(self):
        from capability_registry import capability_report

        report = capability_report()
        self.assertIn("disponibili", report["dati"])
        self.assertIn("condizionate", report["dati"])
        self.assertIn("non_disponibili", report["dati"])
        self.assertTrue(any("ordini" in item for item in report["dati"]["non_disponibili"]))

    def test_operational_capability_terms_are_routed_to_brain(self):
        import main

        for phrase in ("Accedi al microfono", "Gestisci i miei file", "Controllare direttamente il computer", "Usa mouse e tastiera"):
            self.assertTrue(main.deve_usare_router_operativo(phrase), phrase)
        self.assertFalse(main.deve_usare_router_operativo("Puoi usare la webcam?"))

    def test_shutdown_uses_protected_local_tool(self):
        import brain

        with patch.object(brain, "esegui_tool", return_value={"successo": False, "richiede_conferma": True, "messaggio": "Conferma richiesta"}) as execute:
            result = brain._interpreta_comando_locale("spegni il pc")
        self.assertTrue(result[0])
        execute.assert_called_once_with("spegni_pc", {})

    def test_ambiguous_search_receives_active_window_context(self):
        import brain

        active = {"successo": True, "dati": {"titolo": "Jakidale - YouTube - Google Chrome"}}
        with patch.object(brain, "finestra_attiva", return_value=active):
            enriched = brain._with_active_window_context("cerca Jakidale")
        self.assertIn("YouTube", enriched)
        self.assertIn("cerca Jakidale", enriched)


class ProjectBuilderTests(unittest.TestCase):
    def test_creates_multifile_project_inside_root(self):
        import project_builder

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "projects"
            manifest = Path(folder) / "projects.json"
            with patch.object(project_builder, "ROOT", root), patch.object(project_builder, "MANIFEST", manifest):
                result = project_builder.create_project(
                    "Demo Bot", "python bot", "test",
                    [{"path": "main.py", "content": "print('ok')"}, {"path": "README.md", "content": "Demo"}],
                )
            self.assertTrue(result["successo"])
            self.assertTrue((root / "Demo Bot" / "main.py").exists())

    def test_rejects_parent_traversal(self):
        import project_builder

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(project_builder, "ROOT", Path(folder) / "projects"), patch.object(project_builder, "MANIFEST", Path(folder) / "projects.json"):
                with self.assertRaises(ValueError):
                    project_builder.create_project("Bad", "bot", "test", [{"path": "../escape.py", "content": "x"}])


class VisualAgentTests(unittest.TestCase):
    def test_closed_loop_observes_after_each_action(self):
        import visual_agent

        planned = [
            ({"action": "click", "x": 400, "y": 80, "confidence": .95, "description": "campo ricerca"}, 1280, 720),
            ({"action": "type", "text": "Jakidale", "confidence": .99, "description": "scrive ricerca"}, 1280, 720),
            ({"action": "keypress", "key": "enter", "confidence": .99, "description": "avvia ricerca"}, 1280, 720),
            ({"action": "done", "message": "Ricerca completata", "confidence": .95, "description": "risultati visibili"}, 1280, 720),
        ]
        with patch.object(visual_agent, "_next_action", side_effect=planned) as observe, patch.object(visual_agent, "_execute", return_value=(True, "ok")) as execute, patch.object(visual_agent.time, "sleep"):
            result = visual_agent.visual_task("Cerca Jakidale su YouTube", max_steps=8)
        self.assertTrue(result["successo"])
        self.assertEqual(observe.call_count, 4)
        self.assertEqual(execute.call_count, 3)

    def test_low_confidence_click_is_rejected(self):
        import visual_agent

        ok, _ = visual_agent._execute({"action": "click", "x": 10, "y": 10, "confidence": .2}, 1280, 720)
        self.assertFalse(ok)

    def test_visual_agent_cannot_click_jarvis_window(self):
        import visual_agent
        action = {"action": "click", "x": 100, "y": 100, "confidence": .99}
        with patch.object(visual_agent, "_point_in_jarvis_window", return_value=True), patch.object(visual_agent.pyautogui, "click") as click:
            ok, message = visual_agent._execute(action, 1280, 720)
        self.assertFalse(ok); self.assertIn("JARVIS", message); click.assert_not_called()

    def test_visual_agent_stops_repeated_action_loop(self):
        import visual_agent
        repeated = ({"action": "scroll", "amount": 2, "confidence": .9, "description": "scroll"}, 1280, 720)
        with patch.object(visual_agent, "_next_action", return_value=repeated), patch.object(visual_agent, "_execute", return_value=(True, "ok")) as execute, patch.object(visual_agent.time, "sleep"):
            result = visual_agent.visual_task("find rectangle", max_steps=10)
        self.assertFalse(result["successo"]); self.assertIn("Ciclo", result["messaggio"])
        self.assertEqual(execute.call_count, 3)


if __name__ == "__main__":
    unittest.main()
