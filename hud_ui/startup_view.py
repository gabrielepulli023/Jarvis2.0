"""Monochrome pre-start surface with the same orb and window chrome as Home."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QWidget

from .orb_widget import OrbWidget
from .theme import BACKGROUND, CONTROL_BUTTON, HAIRLINE, MUTED, TEXT, font, scaled_style
from .viewport import (
    STARTUP_BAR,
    STARTUP_CLOSE,
    STARTUP_FOOTER,
    STARTUP_MINIMIZE,
    STARTUP_ORB,
    STARTUP_PERCENT,
    STARTUP_SUBTITLE,
    STARTUP_TITLE,
    design_transform,
    mapped_geometry,
)


class StartupView(QWidget):
    """Fullscreen preload surface with deterministic 0–100% progress."""

    minimize_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.progress = 0.0
        self.target = 0.0
        self.status = "INITIALIZING SYSTEMS"
        self.failed = False

        self.orb = OrbWidget(self)
        self.orb.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.orb.set_state("idle")

        self.min_button = QPushButton("-", self)
        self.close_button = QPushButton("\N{MULTIPLICATION SIGN}", self)
        for button, tooltip in (
            (self.min_button, "Minimizza JARVIS"),
            (self.close_button, "Chiudi JARVIS"),
        ):
            button.setStyleSheet(CONTROL_BUTTON)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
        self.min_button.clicked.connect(self.minimize_requested)
        self.close_button.clicked.connect(self.close_requested)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.resizeEvent(None)

    def _content_transform(self):
        return design_transform(self.width(), self.height())

    def _apply_layout(self) -> None:
        transform = self._content_transform()
        self.orb.setGeometry(*mapped_geometry(transform, STARTUP_ORB))
        self.min_button.setGeometry(*mapped_geometry(transform, STARTUP_MINIMIZE))
        self.close_button.setGeometry(*mapped_geometry(transform, STARTUP_CLOSE))
        self.min_button.setStyleSheet(scaled_style(CONTROL_BUTTON, transform.scale))
        self.close_button.setStyleSheet(scaled_style(CONTROL_BUTTON, transform.scale))
        self.min_button.setFont(font(13 * transform.scale, weight=QFont.Light))
        self.close_button.setFont(font(13 * transform.scale, weight=QFont.Light))
        self.orb.raise_()
        self.min_button.raise_()
        self.close_button.raise_()

    def resize(self, *args):  # noqa: A003 - Qt API
        super().resize(*args)
        if not self.isVisible():
            self._apply_layout()

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        self._apply_layout()
        if event is not None:
            super().resizeEvent(event)

    def set_status(self, status):
        self.status = str(status or "INITIALIZING SYSTEMS").strip().upper()
        self.failed = "FAIL" in self.status or "ERROR" in self.status
        self.update()

    def set_progress(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        self.target = max(0.0, min(100.0, value))
        self.update()

    def _tick(self):
        delta = self.target - self.progress
        self.progress += delta * 0.18
        if abs(delta) < 0.04:
            self.progress = self.target
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt API
        del event
        width, height = self.width(), self.height()
        transform = self._content_transform()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        background = QLinearGradient(0, 0, width, height)
        background.setColorAt(0.0, QColor("#0c0d10"))
        background.setColorAt(0.48, QColor(BACKGROUND))
        background.setColorAt(1.0, QColor("#040506"))
        painter.fillRect(self.rect(), background)
        painter.setPen(QPen(QColor(HAIRLINE), max(1, round(transform.scale))))
        painter.drawRect(QRectF(0.5, 0.5, max(0.0, width - 1.0), max(0.0, height - 1.0)))

        painter.save()
        painter.translate(transform.offset_x, transform.offset_y)
        painter.scale(transform.scale, transform.scale)

        painter.setPen(QColor(TEXT if not self.failed else "#ffffff"))
        painter.setFont(font(12 * transform.scale, 2.2 * transform.scale, weight=QFont.Normal))
        painter.drawText(STARTUP_TITLE, Qt.AlignCenter, self.status)

        painter.setPen(QColor(MUTED))
        painter.setFont(font(8 * transform.scale, 2.8 * transform.scale, weight=QFont.Normal))
        painter.drawText(STARTUP_SUBTITLE, Qt.AlignCenter, "JARVIS  //  SYSTEM BOOT")

        bar = STARTUP_BAR
        bar_path = QRectF(bar)
        painter.setPen(QPen(QColor(126, 130, 136, 130), 1.0))
        painter.setBrush(QColor(8, 9, 11, 230))
        painter.drawRoundedRect(bar_path, 5, 5)

        fill_width = max(0.0, min(bar.width(), bar.width() * self.progress / 100.0))
        if fill_width > 0.0:
            fill = QRectF(bar.left() + 1, bar.top() + 1, max(1.0, fill_width - 2), max(1.0, bar.height() - 2))
            fill_gradient = QLinearGradient(fill.topLeft(), fill.bottomLeft())
            fill_gradient.setColorAt(0.0, QColor("#f7f7f8"))
            fill_gradient.setColorAt(1.0, QColor("#969aa1"))
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill_gradient)
            painter.drawRoundedRect(fill, 4, 4)

        painter.setPen(QColor(TEXT))
        painter.setFont(font(15 * transform.scale, 0.8 * transform.scale, weight=QFont.Light))
        painter.drawText(STARTUP_PERCENT, Qt.AlignCenter, f"{round(self.progress):d}%")

        painter.setPen(QColor(MUTED))
        painter.setFont(font(8 * transform.scale, 2.5 * transform.scale, weight=QFont.Normal))
        painter.drawText(STARTUP_FOOTER, Qt.AlignCenter, "PLEASE WAIT")
        painter.restore()
        painter.end()

    def closeEvent(self, event):  # noqa: N802 - Qt API
        self._timer.stop()
        self.orb.close()
        super().closeEvent(event)
