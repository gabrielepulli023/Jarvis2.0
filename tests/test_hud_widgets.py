import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from hud import CommandPalette, JarvisHUD, ReferenceDataPanel, SystemReferencePanel
from main import StartupScreen
from hud_ui.minimized_orb import MINIMIZED_ORB_SIZE
from hud_ui.viewport import HOME_ORB, HOME_ORB_LINE, design_transform, mapped_geometry


class HUDWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _render(widget):
        image = QImage(widget.size(), QImage.Format_ARGB32)
        image.fill(0)
        widget.render(image)
        return image

    def test_reference_data_panel_accepts_runtime_rows_and_renders(self):
        panel = ReferenceDataPanel()
        self.addCleanup(panel.close)
        panel.resize(300, 210)
        rows = [("model", "gpt-test"), ("latency", "120 ms", "#35e879")]
        panel.set_rows(rows, footer="DATI REALI", progress=.5)

        self.assertEqual(panel.rows, rows)
        self.assertEqual(panel.footer, "DATI REALI")
        self.assertEqual(panel.progress, .5)
        self.assertFalse(self._render(panel).isNull())

    def test_system_reference_panel_keeps_bounded_numeric_history(self):
        panel = SystemReferencePanel()
        self.addCleanup(panel.close)
        panel.resize(270, 220)
        for value in range(40):
            panel.set_data({
                "cpu": value,
                "ram": 64,
                "download_mbps": 18.4,
                "uptime": "1 giorno",
                "gpu": {"usage": 41},
            })

        self.assertEqual(len(panel.history["cpu"]), 28)
        self.assertEqual(panel.history["cpu"][-1], 39.0)
        self.assertFalse(self._render(panel).isNull())

    def test_persistent_command_palette_submits_without_disappearing(self):
        palette = CommandPalette()
        self.addCleanup(palette.close)
        palette.resize(700, 58)
        submitted = []
        palette.submit.connect(submitted.append)
        palette.set_persistent(True)
        palette.input.setText("Mostra desktop")

        palette._send()

        self.assertEqual(submitted, ["Mostra desktop"])
        self.assertEqual(palette.input.text(), "")
        self.assertTrue(palette.persistent)
        self.assertTrue(palette.isVisible())
        self.assertFalse(palette.auto_hide_timer.isActive())

    def test_startup_screen_status_remains_available_during_preload(self):
        screen = StartupScreen()
        self.addCleanup(screen.close)
        screen.resize(1280, 720)
        screen.set_status("Verifica identita CEO")

        self.assertEqual(screen.state.text(), "VERIFICA IDENTITA CEO")
        self.assertFalse(self._render(screen).isNull())

    def test_startup_screen_shows_no_profile_without_fake_camera_activity(self):
        screen = StartupScreen()
        self.addCleanup(screen.close)

        screen.show_identity_result({"status": "setup_required", "authenticated": False})

        self.assertEqual(screen._stage, "setup_required")
        self.assertFalse(screen.preview._active)
        self.assertIn("PROFILO NON CONFIGURATO", screen.identity_state.text())
        self.assertIn("CAMERA NON APERTA", screen.privacy.text())

    def test_startup_screen_tracks_real_camera_lifecycle(self):
        screen = StartupScreen()
        self.addCleanup(screen.close)

        screen.handle_runtime_event("camera.started", {"camera": 0})
        self.assertEqual(screen._stage, "scanning")
        self.assertTrue(screen.preview._active)
        self.assertIn("CAM 01 LIVE", screen.privacy.text())

        screen.handle_runtime_event("camera.stopped", {"camera": 0})
        self.assertEqual(screen._stage, "verifying")
        self.assertFalse(screen.preview._active)
        self.assertIn("CAMERA RILASCIATA", screen.privacy.text())

    def test_startup_screen_uses_minimal_visual_gate(self):
        screen = StartupScreen()
        self.addCleanup(screen.close)
        screen.resize(1280, 720)
        self.assertEqual(type(screen).__name__, "MinimalStartupScreen")
        self.assertFalse(self._render(screen).isNull())

    def test_hud_exposes_home_log_and_required_command_center(self):
        hud = JarvisHUD()
        self.addCleanup(hud.shutdown_services)
        self.addCleanup(hud.close)

        self.assertEqual(hud.PAGE_NAMES, ["ASSISTENTE", "CONSOLE", "COMMAND_CENTER"])
        self.assertEqual(hud.stack.count(), 3)
        self.assertEqual(tuple(hud.command_center_page.CATEGORIES),("System","Performance","AI","Tools","Memory","Permissions","Automation","Events","Logs","Debug","Processes","Apps","Network","Voice"))

    def test_minimal_home_keeps_controls_attached_and_surfaces_dedicated(self):
        hud = JarvisHUD()
        self.addCleanup(hud.shutdown_services)
        self.addCleanup(hud.close)
        hud.home_page.resize(1672, 941)

        self.assertIs(hud.home_page.log_button.parent(), hud.home_page)
        self.assertIs(hud.home_page.console_button.parent(), hud.home_page)
        self.assertEqual(hud.home_page.min_button.text(), "-")
        self.assertEqual(hud.home_page.close_button.text(), "×")
        self.assertEqual(hud.home_page.orb.geometry().getRect(), mapped_geometry(design_transform(1672, 941), HOME_ORB))
        self.assertGreater(HOME_ORB_LINE.top(), HOME_ORB.bottom())

        hud.home_page.log_button.click()
        self.assertIs(hud.stack.currentWidget(), hud.log_page)
        hud.home_page.console_button.click()
        self.assertIs(hud.stack.currentWidget(), hud.command_center_page)

    def test_space_toggles_clickable_keyboard_only_in_fullscreen(self):
        hud = JarvisHUD()
        self.addCleanup(hud.shutdown_services)
        self.addCleanup(hud.close)
        submitted = []
        hud.messaggio_inviato.connect(submitted.append)

        hud.showNormal()
        self.app.processEvents()
        hud._toggle_virtual_keyboard()
        self.assertFalse(hud.virtual_keyboard.isVisible())

        hud.showFullScreen()
        self.app.processEvents()
        self.assertEqual(hud.keyboard_shortcut.key().toString(), "Space")
        hud._toggle_virtual_keyboard()
        self.assertTrue(hud.virtual_keyboard.isVisible())
        self.assertLessEqual(hud.virtual_keyboard.width(), 760)
        self.assertLessEqual(hud.virtual_keyboard.height(), 350)
        hud.virtual_keyboard.input.setText("mostra desktop")
        hud.virtual_keyboard._submit()
        self.assertEqual(submitted, ["mostra desktop"])
        self.assertFalse(hud.virtual_keyboard.isVisible())

        hud._toggle_virtual_keyboard()
        self.assertTrue(hud.virtual_keyboard.isVisible())
        hud._toggle_virtual_keyboard()
        self.assertFalse(hud.virtual_keyboard.isVisible())

    def test_ctrl_m_target_toggles_small_keyboard_only_when_minimized(self):
        hud = JarvisHUD()
        self.addCleanup(hud.shutdown_services)
        self.addCleanup(hud.close)
        self.addCleanup(hud.compact_keyboard.close)
        submitted = []
        hud.messaggio_inviato.connect(submitted.append)

        hud.showFullScreen()
        self.app.processEvents()
        hud.toggle_compact_keyboard()
        self.assertFalse(hud.compact_keyboard.isVisible())

        hud.showMinimized()
        self.app.processEvents()
        hud.toggle_compact_keyboard()
        self.assertTrue(hud.compact_keyboard.isVisible())
        self.assertEqual(hud.compact_keyboard.size().width(), 620)
        self.assertEqual(hud.compact_keyboard.size().height(), 320)
        hud.compact_keyboard.input.setText("apri chrome")
        hud.compact_keyboard._submit()
        self.assertEqual(submitted, ["apri chrome"])
        self.assertFalse(hud.compact_keyboard.isVisible())

        hud.toggle_compact_keyboard()
        self.assertTrue(hud.compact_keyboard.isVisible())
        hud.toggle_compact_keyboard()
        self.assertFalse(hud.compact_keyboard.isVisible())

    def test_minimized_window_shows_canonical_restore_orb_bottom_right(self):
        hud = JarvisHUD()
        self.addCleanup(hud.shutdown_services)
        self.addCleanup(hud.close)

        hud.showFullScreen()
        self.app.processEvents()
        hud.showMinimized()
        self.app.processEvents()

        mini = hud.minimized_orb
        self.assertTrue(hud.isMinimized())
        self.assertTrue(mini.isVisible())
        self.assertEqual(mini.size().width(), MINIMIZED_ORB_SIZE)
        self.assertEqual(mini.size().height(), MINIMIZED_ORB_SIZE)
        self.assertIs(mini.orb.idle_pixmap, hud.home_page.orb.idle_pixmap)

        rendered = self._render(mini)
        self.assertFalse(rendered.isNull())
        self.assertGreater(len(mini.orb._render_cache), 0)

        mini.restore_requested.emit()
        self.app.processEvents()
        self.assertFalse(hud.isMinimized())
        self.assertFalse(mini.isVisible())

    def test_voice_transcript_is_written_only_to_log(self):
        hud = JarvisHUD()
        self.addCleanup(hud.shutdown_services)
        self.addCleanup(hud.close)
        hud.aggiorna_trascrizione("Che tempo farà domani?")
        hud.aggiorna_risposta("Domani sarà sereno.")

        rendered = hud.log_page.log.toPlainText()
        self.assertIn("Che tempo farà domani?", rendered)
        self.assertIn("Domani sarà sereno.", rendered)
        self.assertFalse(hasattr(hud.home_page, "transcription_label"))
        self.assertFalse(hasattr(hud.home_page, "response_label"))

    def test_listening_state_animates_circle_without_status_copy(self):
        hud = JarvisHUD()
        self.addCleanup(hud.shutdown_services)
        self.addCleanup(hud.close)
        phase = hud.home_page.phase
        hud.set_stato_assistente("listening")
        hud.home_page._advance()

        self.assertEqual(hud.home_page.state, "listening")
        self.assertNotEqual(hud.home_page.phase, phase)
        self.assertFalse(hasattr(hud.home_page, "listening_label"))


if __name__ == "__main__":
    unittest.main()
