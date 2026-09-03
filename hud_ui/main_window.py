"""Canonical frameless desktop window for the JARVIS minimal HUD."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLineEdit, QMainWindow, QStackedWidget, QWidget

from .console_view import ConsoleView
from .diagnostics import collect_screen_diagnostics
from .home_view import HomeView
from .log_view import LogView
from .minimized_orb import MinimizedOrb
from .theme import BACKGROUND


class _CommandInput(QWidget):
    """Compatibility input used by the optional keyboard shortcuts."""

    submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QWidget { background: #0d0f12; border: 1px solid rgba(225,225,230,100); }"
            "QLineEdit { background: transparent; color: #f4f4f5; border: none; padding: 8px; }"
        )
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Scrivi un comando")
        self.input.returnPressed.connect(self._submit)

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        self.input.setGeometry(8, 6, max(1, self.width() - 16), max(1, self.height() - 12))
        super().resizeEvent(event)

    def _submit(self):
        value = self.input.text().strip()
        if value:
            self.input.clear()
            self.submitted.emit(value)


class MainWindow(QMainWindow):
    """One window with a quiet Home and two focused utility surfaces."""

    chiudi_programma = Signal()
    messaggio_inviato = Signal(str)
    routine_comando = Signal(str)
    event_comando = Signal(str)
    PAGE_NAMES = ["ASSISTENTE", "CONSOLE", "COMMAND_CENTER"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setMinimumSize(760, 520)
        self.resize(1400, 820)
        self.setStyleSheet(f"QMainWindow {{ background: {BACKGROUND}; }}")
        self._current_page = "ASSISTENTE"
        self._current_state = "standby"
        self._shutdown = False
        self._close_emitted = False
        self._last_viewport_diagnostics = {}
        self._minimized_orb = MinimizedOrb()
        self._minimized_orb.restore_requested.connect(self._restore_from_minimized_orb)

        self.virtual_keyboard = _CommandInput(self)
        self.virtual_keyboard.setFixedSize(560, 58)
        self.virtual_keyboard.hide()
        self.compact_keyboard = _CommandInput()
        self.compact_keyboard.setFixedSize(620, 320)
        self.compact_keyboard.hide()
        self.virtual_keyboard.submitted.connect(self.messaggio_inviato)
        self.virtual_keyboard.submitted.connect(self.virtual_keyboard.hide)
        self.compact_keyboard.submitted.connect(self.messaggio_inviato)
        self.compact_keyboard.submitted.connect(self.compact_keyboard.hide)
        self.keyboard_shortcut = QShortcut(QKeySequence("Space"), self)
        self.keyboard_shortcut.activated.connect(self._toggle_virtual_keyboard)

        self.stack = QStackedWidget(self)
        self.home_page = HomeView()
        self.log_page = LogView()
        self.command_center_page = ConsoleView()
        self.console_page = self.command_center_page
        self.pages = {
            "ASSISTENTE": self.home_page,
            "CONSOLE": self.log_page,
            "COMMAND_CENTER": self.command_center_page,
        }
        for view in self.pages.values():
            self.stack.addWidget(view)
        self.setCentralWidget(self.stack)

        self.home_page.log_requested.connect(lambda: self.apri_scheda("CONSOLE"))
        self.home_page.console_requested.connect(lambda: self.apri_scheda("COMMAND_CENTER"))
        self.home_page.minimize_requested.connect(self.showMinimized)
        self.home_page.close_requested.connect(self._request_shutdown)
        for view in (self.log_page, self.command_center_page):
            view.back_requested.connect(lambda: self.apri_scheda("ASSISTENTE"))
            view.minimize_requested.connect(self.showMinimized)
            view.close_requested.connect(self._request_shutdown)

    def show_initial(self):
        self._minimized_orb.hide()
        self.showFullScreen()

    def attiva(self):
        self._minimized_orb.hide()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def viewport_diagnostics(self):
        self._last_viewport_diagnostics = collect_screen_diagnostics(QApplication.instance(), self)
        return dict(self._last_viewport_diagnostics)

    def nascondi(self):
        self.showMinimized()

    @property
    def minimized_orb(self):
        """Expose the compact restore surface for diagnostics and tests."""

        return self._minimized_orb

    def _restore_from_minimized_orb(self):
        self._minimized_orb.hide()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event):  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() != QEvent.WindowStateChange:
            return
        if self.windowState() & Qt.WindowMinimized:
            self._minimized_orb.set_state(self._current_state)
            self._minimized_orb.show_bottom_right()
        else:
            self._minimized_orb.hide()

    def apri_scheda(self, name):
        target = {
            "HOME": "ASSISTENTE",
            "LOG": "CONSOLE",
            "REGISTRO": "CONSOLE",
            "SYSTEM": "COMMAND_CENTER",
            "SISTEMA": "COMMAND_CENTER",
        }.get(str(name).upper(), str(name).upper())
        if target in self.pages:
            self._current_page = target
            self.stack.setCurrentWidget(self.pages[target])

    def set_stato_assistente(self, state):
        self._current_state = str(state or "standby")
        self.home_page.set_state(self._current_state)

    def ascolto(self):
        self.set_stato_assistente("listening")

    def elaborazione(self):
        self.set_stato_assistente("thinking")

    def risposta_in_corso(self):
        self.set_stato_assistente("speaking")

    def aggiorna_trascrizione(self, text):
        self.log_page.add_entry("VOCE", "TU", text)

    def aggiorna_risposta(self, text):
        self.log_page.add_entry("VOCE", "JARVIS", text)

    def append_console(self, text):
        self.command_center_page.append(text)
        for line in str(text).splitlines():
            if line.strip():
                self.log_page.add_entry("SISTEMA", "SISTEMA", line)

    def aggiorna_news_mercati(self, text):
        self.append_console(text)

    def set_modulo(self, name, active=True):
        self.append_console(f"{name}: {'attivo' if active else 'errore'}")

    def notify(self, title, message):
        self.append_console(f"[{title}] {message}")

    def imposta_pin_sicurezza(self):
        return None

    def toggle_compact_keyboard(self):
        if self.isMinimized():
            self.compact_keyboard.setVisible(not self.compact_keyboard.isVisible())

    def _toggle_virtual_keyboard(self):
        if not self.isFullScreen():
            return
        if self.virtual_keyboard.isVisible():
            self.virtual_keyboard.hide()
            return
        self.virtual_keyboard.move(max(0, (self.width() - self.virtual_keyboard.width()) // 2), max(0, self.height() - 92))
        self.virtual_keyboard.show()
        self.virtual_keyboard.raise_()
        self.virtual_keyboard.input.setFocus()

    def _request_shutdown(self):
        if not self._shutdown:
            self._shutdown = True
            self.close()

    def shutdown_services(self):
        self.virtual_keyboard.hide()
        self.compact_keyboard.hide()
        self._minimized_orb.close()

    def closeEvent(self, event):  # noqa: N802 - Qt API
        self.shutdown_services()
        if not self._close_emitted:
            self._close_emitted = True
            self.chiudi_programma.emit()
        event.accept()
