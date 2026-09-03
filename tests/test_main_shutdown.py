import unittest
from unittest.mock import patch

import main
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication
from hud_ui.main_window import MainWindow


class MainShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_shutdown_routes_to_core_runtime(self):
        with patch.object(main.CORE_RUNTIME, "stop") as stop:
            main._shutdown_runtime()
        stop.assert_called_once_with()

    def test_gui_close_emits_application_shutdown_signal(self):
        window = MainWindow()
        emitted = []
        window.chiudi_programma.connect(lambda: emitted.append(True))
        event = QCloseEvent()
        window.closeEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(emitted, [True])
        window.shutdown_services()


if __name__ == "__main__":
    unittest.main()
