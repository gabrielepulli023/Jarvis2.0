import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import chrome_bridge
import tools
import main
from main import SingleActionAnnouncement, deve_allegare_contesto_operazione, frase_sicurezza_valida, preload_startup_components, scheda_per_richiesta, startup_identity_check


class CommandExecutionRegressionTests(unittest.TestCase):
    def setUp(self):
        with chrome_bridge._LOCK: chrome_bridge._SNAPSHOT.clear()
        chrome_bridge._discard_pending_commands()

    def tearDown(self):
        import permission_manager
        permission_manager.clear_session()
        with chrome_bridge._LOCK: chrome_bridge._SNAPSHOT.clear()
        chrome_bridge._discard_pending_commands()

    def test_one_request_can_announce_only_once(self):
        gate = SingleActionAnnouncement()
        self.assertTrue(gate.claim())
        self.assertFalse(gate.claim())
        self.assertFalse(gate.claim())

    def test_startup_greeting_is_claimed_only_once_per_process(self):
        main._reset_startup_greeting_gate()
        self.addCleanup(main._reset_startup_greeting_gate)
        self.assertTrue(main._claim_startup_greeting())
        self.assertFalse(main._claim_startup_greeting())

    def test_global_ctrl_m_callback_emits_compact_keyboard_signal(self):
        worker = main.JarvisWorker()
        emitted = []
        worker.toggle_tastiera_compatta.connect(lambda: emitted.append(True))
        worker.tastiera_compatta_da_hotkey()
        self.assertEqual(emitted, [True])

    def test_independent_command_does_not_receive_old_context(self):
        self.assertFalse(deve_allegare_contesto_operazione(False))
        self.assertTrue(deve_allegare_contesto_operazione(True))

    def test_disconnected_bridge_uses_cdp_fallback_and_discards_stale_command(self):
        chrome_bridge._COMMANDS.put({"action": "navigate", "target": "stale"})
        fallback = {"success": True, "message": "Scheda aperta tramite CDP.", "data": {"fallback": "cdp"}}
        with patch("jarvis_browser.ChromeDevToolsClient.action", return_value=fallback) as action:
            result = chrome_bridge.chrome_action("navigate", "https://tradingview.com")
        self.assertTrue(result["successo"])
        action.assert_called_once_with("open_tab", target="https://tradingview.com", value="")
        self.assertTrue(chrome_bridge._COMMANDS.empty())

    def test_connected_bridge_accepts_command(self):
        with chrome_bridge._LOCK: chrome_bridge._SNAPSHOT["received_at"] = time.time()
        result = chrome_bridge.chrome_action("navigate", "https://tradingview.com")
        self.assertTrue(result["successo"])
        self.assertEqual(chrome_bridge._COMMANDS.get_nowait()["action"], "navigate")

    def test_open_tradingview_uses_native_browser_without_bridge(self):
        with patch.object(tools.webbrowser, "open", return_value=True) as opened:
            success, message = tools.apri_programma("TradingView")
        self.assertTrue(success); self.assertIn("tradingview", message.lower())
        opened.assert_called_once_with("https://www.tradingview.com/chart/")

    def test_unknown_known_installed_app_uses_start_menu_shortcut(self):
        shortcut = Mock(stem="Paint")
        with patch.object(tools, "_trova_collegamento_menu_start", return_value=shortcut), \
             patch.object(tools.os, "startfile", create=True) as opened:
            success, message = tools.apri_programma("Paint")
        self.assertTrue(success)
        self.assertIn("Paint", message)
        opened.assert_called_once_with(str(shortcut))

    def test_notepad_open_requires_real_process_and_window(self):
        with patch.object(tools.subprocess, "Popen"), \
             patch.object(tools.psutil, "process_iter", return_value=[Mock(info={"name": "notepad.exe"})]), \
             patch.object(tools.gw, "getWindowsWithTitle", return_value=[]):
            success, message = tools.apri_programma("Blocco note")
        self.assertFalse(success)
        self.assertIn("non risulta realmente aperto", message)

    def test_notepad_does_not_announce_before_verified_execution(self):
        import brain

        callback = Mock()
        brain._notifica_prima_azione(callback, "apri_programma", {"nome": "Blocco note"})
        callback.assert_not_called()

    def test_chrome_launch_loads_local_bridge_in_dedicated_profile(self):
        extension = Mock()
        extension.exists.return_value = True
        extension.__str__ = Mock(return_value="C:/jarvis/chrome_extension")
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(tools, "_chrome_extension_directory", return_value=extension), \
             patch("chrome_bridge.ensure_server", return_value=True), \
             patch("chrome_bridge.write_extension_config") as configured, \
             patch.object(tools, "_processo_presente", return_value=False), \
             patch("app_paths.data_path", return_value=Path(folder)), \
             patch.object(tools.subprocess, "Popen") as opened:
            controlled = tools._avvia_chrome_controllato("chrome.exe")
        self.assertTrue(controlled)
        configured.assert_called_once_with(extension)
        args = opened.call_args.args[0]
        self.assertIn("--load-extension=C:/jarvis/chrome_extension", args)
        self.assertIn("--remote-debugging-port=9222", args)
        self.assertTrue(any(arg.startswith("--user-data-dir=") and arg.endswith("chrome-profile") for arg in args))

    def test_chrome_fallback_is_reported_as_a_real_launch(self):
        extension = Mock()
        extension.exists.return_value = False
        with patch.object(tools, "_chrome_extension_directory", return_value=extension), \
             patch("chrome_bridge.ensure_server", return_value=False), \
             patch.object(tools.subprocess, "Popen") as opened:
            controlled = tools._avvia_chrome_controllato("chrome.exe")
        self.assertTrue(controlled)
        opened.assert_called_once_with(["chrome.exe"])

    def test_chrome_open_with_existing_process_uses_native_os_launch(self):
        extension = Mock()
        extension.exists.return_value = True
        with patch.object(tools, "_processo_presente", return_value=True), \
             patch.object(tools, "_chrome_extension_directory", return_value=extension), \
             patch("chrome_bridge.ensure_server") as ensure_server, \
             patch.object(tools.subprocess, "Popen") as opened:
            controlled = tools._avvia_chrome_controllato("chrome.exe")
        self.assertTrue(controlled)
        opened.assert_called_once_with(["chrome.exe"])
        ensure_server.assert_not_called()

    def test_chrome_open_reports_controlled_launcher_failure(self):
        with patch.object(tools, "_avvia_chrome_controllato", return_value=False):
            success, message = tools.apri_programma("Chrome")
        self.assertFalse(success)
        self.assertIn("Chrome", message)

    def test_close_notepad_uses_graceful_window_close_and_verifies(self):
        state = {"running": True, "windows": []}
        window = Mock(title="Documento senza nome - Blocco note")
        state["windows"] = [window]

        def process_iter(_attrs):
            return [Mock(info={"name": "notepad.exe"})] if state["running"] else []

        def windows(_title):
            return list(state["windows"])

        def close_window():
            state["running"] = False
            state["windows"] = []

        window.close.side_effect = close_window
        with patch.object(tools.psutil, "process_iter", side_effect=process_iter), \
             patch.object(tools.gw, "getWindowsWithTitle", side_effect=windows), \
             patch.object(tools.gw, "getAllWindows", return_value=[]), \
             patch.object(tools.subprocess, "run") as taskkill:
            success, message = tools.chiudi_programma("Blocco note")
        self.assertTrue(success)
        self.assertIn("verificato", message)
        taskkill.assert_not_called()
        window.close.assert_called_once_with()

    def test_close_notepad_does_not_claim_success_when_windows_keeps_process_alive(self):
        window = Mock(title="Blocco note")
        with patch.object(tools.psutil, "process_iter", return_value=[Mock(info={"name": "notepad.exe"})]), \
             patch.object(tools.gw, "getWindowsWithTitle", return_value=[window]), \
             patch.object(tools.gw, "getAllWindows", return_value=[]), \
             patch.object(tools.subprocess, "run", return_value=Mock(returncode=0, stdout="", stderr="")) as taskkill:
            success, message = tools.chiudi_programma("Blocco note")
        self.assertFalse(success)
        self.assertIn("non conferma", message)
        taskkill.assert_called_once()

    def test_operational_router_has_no_spoken_pre_action_claim(self):
        import inspect

        source = inspect.getsource(main.JarvisWorker.processa_domanda)
        self.assertNotIn("jarvis-pre-action-voice", source)
        self.assertNotIn("_annuncio_per_azione", source)

    def test_every_request_stays_on_assistant_tab(self):
        for text in ("Mostra desktop", "diagnostica", "analizza EUR USD", "impostazioni microfono", "errore console"):
            self.assertEqual(scheda_per_richiesta(text), "ASSISTENTE")

    def test_startup_preloads_critical_path_before_ready(self):
        stages = []
        with patch("main.CORE_RUNTIME.start"), patch("main.recover_interrupted"), \
             patch("main.start_chrome_bridge"), patch("main._load_runtime_components"), \
             patch("wakeword.carica_modello"), patch("main.CORE_RUNTIME.voice.start"):
            result = preload_startup_components(stages.append)
        self.assertTrue(result["ready"]); self.assertFalse(result["errors"])
        self.assertEqual(stages[-1], "Sistema pronto")
        self.assertEqual(result["identity"]["role"], "CEO")
        self.assertEqual(result["identity"]["name"], "OWNER")
        self.assertTrue(result["identity"]["authenticated"])
        self.assertEqual(result["identity"]["method"], "development_auto_ceo")

    def test_startup_identity_always_activates_development_ceo_without_hardware(self):
        service = Mock()
        result = startup_identity_check(service)
        self.assertEqual(
            result,
            {
                "role": "CEO",
                "name": "OWNER",
                "authenticated": True,
                "method": "development_auto_ceo",
                "confidence": 1.0,
                "status": "authenticated",
            },
        )
        service.status.assert_not_called()
        service.recognize_face.assert_not_called()

    def test_identity_commands_are_disabled_in_development_mode(self):
        worker = main.JarvisWorker()
        with patch.object(worker, "_risposta_locale"), patch.object(main.IDENTITY, "create_profile") as create_profile, \
                patch.object(main.IDENTITY, "recognize_face") as recognize_face, patch.object(main.IDENTITY, "recognize_voice") as recognize_voice:
            self.assertTrue(worker._comando_memoria_o_conferma("crea profilo CEO Gabriele"))
            self.assertTrue(worker._comando_memoria_o_conferma("Jarvis sono io"))
            self.assertTrue(worker._comando_memoria_o_conferma("riconosci il mio volto"))
            self.assertTrue(worker._comando_memoria_o_conferma("riconosci la mia voce"))
        create_profile.assert_not_called()
        recognize_face.assert_not_called()
        recognize_voice.assert_not_called()

    def test_voice_fallback_requires_the_complete_configured_phrase(self):
        self.assertTrue(frase_sicurezza_valida("Jarvis, sono io", "jarvis sono io"))
        self.assertFalse(frase_sicurezza_valida("sono io", "jarvis sono io"))
        self.assertFalse(frase_sicurezza_valida("jarvis apri", "jarvis sono io"))


if __name__ == "__main__": unittest.main()
