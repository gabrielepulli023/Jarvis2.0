"""Small always-on-top restore surface shown while the main HUD is minimized."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QWidget

from .orb_widget import OrbWidget


MINIMIZED_ORB_SIZE = 72


class MinimizedOrb(QWidget):
    """Reuse the canonical orb artwork as a compact bottom-right affordance."""

    restore_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(MINIMIZED_ORB_SIZE, MINIMIZED_ORB_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Ripristina JARVIS")
        self.setAccessibleName("Ripristina JARVIS")

        self.orb = OrbWidget(self)
        self.orb.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.orb.setGeometry(0, 0, self.width(), self.height())
        self.orb.set_state("idle")
        self.hide()

    def show_bottom_right(self, margin: int = 22):
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - int(margin) + 1,
            area.bottom() - self.height() - int(margin) + 1,
        )
        self.show()
        self.raise_()

    def set_state(self, state):
        self.orb.set_state(state)

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            self.restore_requested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def closeEvent(self, event):  # noqa: N802 - Qt API
        self.orb.close()
        super().closeEvent(event)
