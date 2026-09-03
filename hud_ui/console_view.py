"""Dedicated runtime console surface sharing the home visual language."""

from __future__ import annotations

import json
import threading
from collections import deque

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QTextEdit, QWidget

from .theme import BACKGROUND, BUTTON, CONTROL_BUTTON, HAIRLINE, MUTED, TEXT, TEXT_EDIT, font, scaled_style
from .viewport import CONSOLE_BACK, CONSOLE_CLOSE, CONSOLE_MINIMIZE, CONSOLE_OUTPUT, design_transform, mapped_geometry


class ConsoleView(QWidget):
    """Bounded stdout/stderr console with non-blocking snapshot refresh."""

    snapshot_ready = Signal(str)
    CATEGORIES = (
        "System",
        "Performance",
        "AI",
        "Tools",
        "Memory",
        "Permissions",
        "Automation",
        "Events",
        "Logs",
        "Debug",
        "Processes",
        "Apps",
        "Network",
        "Voice",
    )
    back_requested = Signal()
    minimize_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.output = QTextEdit(self)
        self.content = self.output
        self.output.setReadOnly(True)
        self.output.setFont(font(10, 0.3, "Cascadia Mono"))
        self._apply_output_style(1.0)
        self._lines = deque(maxlen=1200)
        self._refresh_inflight = False
        self._value = lambda name: {}

        self.back = self._make_button("HOME", BUTTON, "Torna alla home", self)
        self.min_button = self._make_button("-", CONTROL_BUTTON, "Minimizza JARVIS", self)
        self.close_button = self._make_button("\N{MULTIPLICATION SIGN}", CONTROL_BUTTON, "Chiudi JARVIS", self)

        self.snapshot_ready.connect(self._apply)
        self.back.clicked.connect(self.back_requested)
        self.min_button.clicked.connect(self.minimize_requested)
        self.close_button.clicked.connect(self.close_requested)

    @staticmethod
    def _make_button(text: str, style: str, tooltip: str, parent=None) -> QPushButton:
        button = QPushButton(text, parent)
        button.setStyleSheet(style)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        return button

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        transform = design_transform(self.width(), self.height())
        self.back.setStyleSheet(scaled_style(BUTTON, transform.scale))
        self.min_button.setStyleSheet(scaled_style(CONTROL_BUTTON, transform.scale))
        self.close_button.setStyleSheet(scaled_style(CONTROL_BUTTON, transform.scale))
        self.back.setGeometry(*mapped_geometry(transform, CONSOLE_BACK))
        self.min_button.setGeometry(*mapped_geometry(transform, CONSOLE_MINIMIZE))
        self.close_button.setGeometry(*mapped_geometry(transform, CONSOLE_CLOSE))
        self.back.setFont(font(8.5 * transform.scale, 2.0 * transform.scale))
        self.min_button.setFont(font(13 * transform.scale, weight=QFont.Light))
        self.close_button.setFont(font(13 * transform.scale, weight=QFont.Light))
        self.output.setFont(font(10 * transform.scale, 0.3 * transform.scale, "Cascadia Mono"))
        self.output.setGeometry(*mapped_geometry(transform, CONSOLE_OUTPUT))
        self._apply_output_style(transform.scale)
        super().resizeEvent(event)

    def _apply_output_style(self, scale):
        style = scaled_style(TEXT_EDIT, scale)
        style = style.replace("padding: 16px", f"padding: {max(8, round(16 * float(scale)))}px")
        self.output.setStyleSheet(style)

    def append(self, text):
        for line in str(text).splitlines() or [str(text)]:
            if line.strip():
                self._lines.append(line)
        self._render_output()

    def _render_output(self):
        self.output.setPlainText("\n".join(self._lines))
        self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())

    def refresh(self, *_):
        if self._refresh_inflight:
            return
        self._refresh_inflight = True

        def work():
            try:
                value = self._value("System")
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                value = {"error": str(exc)}
            self.snapshot_ready.emit(json.dumps(value, indent=2, default=str))

        threading.Thread(target=work, daemon=True, name="jarvis-console-refresh").start()

    def _apply(self, payload):
        self.output.setPlainText(payload)
        self._refresh_inflight = False

    def showEvent(self, event):  # noqa: N802 - Qt API
        self.refresh()
        super().showEvent(event)

    def paintEvent(self, event):  # noqa: N802 - Qt API
        del event
        width, height = self.width(), self.height()
        transform = design_transform(width, height)
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
        painter.setPen(QColor(TEXT))
        painter.setFont(font(17 * transform.scale, 3.4 * transform.scale, weight=QFont.Light))
        painter.drawText(QRectF(34, 70, 520, 24), Qt.AlignLeft | Qt.AlignVCenter, "CONSOLE")
        painter.setPen(QColor(MUTED))
        painter.setFont(font(8 * transform.scale, 2.1 * transform.scale))
        painter.drawText(QRectF(34, 91, 520, 18), Qt.AlignLeft | Qt.AlignVCenter, "RUNTIME OUTPUT")
        painter.setPen(QColor(145, 148, 154, 100))
        painter.drawLine(QRectF(34, 98, 1638, 98).topLeft(), QRectF(34, 98, 1638, 98).topRight())
        painter.restore()
        painter.end()
