"""Dedicated activity log surface for the minimal HUD."""

from __future__ import annotations

import html
import re
from collections import deque
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QTextBrowser, QWidget

from .theme import BACKGROUND, BUTTON, CONTROL_BUTTON, HAIRLINE, MUTED, TEXT, TEXT_EDIT, font, scaled_style
from .viewport import LOG_BACK, LOG_CLEAR, LOG_CLOSE, LOG_MINIMIZE, LOG_TEXT, design_transform, mapped_geometry


class LogView(QWidget):
    """Bounded, quiet stream of voice and runtime activity."""

    back_requested = Signal()
    minimize_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.entries = deque(maxlen=800)
        self._render_scheduled = False

        self.text = QTextBrowser(self)
        self.log = self.text
        self.text.setReadOnly(True)
        self.text.setOpenExternalLinks(True)
        self.text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.text.setFont(font(10, 0.3, "Cascadia Mono"))
        self._apply_text_style(1.0)

        self.back = self._make_button("HOME", BUTTON, "Torna alla home", self)
        self.clear = self._make_button("CLEAR", BUTTON, "Svuota il log", self)
        self.min_button = self._make_button("-", CONTROL_BUTTON, "Minimizza JARVIS", self)
        self.close_button = self._make_button("\N{MULTIPLICATION SIGN}", CONTROL_BUTTON, "Chiudi JARVIS", self)

        self.back.clicked.connect(self.back_requested)
        self.clear.clicked.connect(self._clear)
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
        self.clear.setStyleSheet(scaled_style(BUTTON, transform.scale))
        self.min_button.setStyleSheet(scaled_style(CONTROL_BUTTON, transform.scale))
        self.close_button.setStyleSheet(scaled_style(CONTROL_BUTTON, transform.scale))
        self.back.setGeometry(*mapped_geometry(transform, LOG_BACK))
        self.clear.setGeometry(*mapped_geometry(transform, LOG_CLEAR))
        self.min_button.setGeometry(*mapped_geometry(transform, LOG_MINIMIZE))
        self.close_button.setGeometry(*mapped_geometry(transform, LOG_CLOSE))
        self.back.setFont(font(8.5 * transform.scale, 2.0 * transform.scale))
        self.clear.setFont(font(8.5 * transform.scale, 2.0 * transform.scale))
        self.min_button.setFont(font(13 * transform.scale, weight=QFont.Light))
        self.close_button.setFont(font(13 * transform.scale, weight=QFont.Light))
        self.text.setFont(font(10 * transform.scale, 0.3 * transform.scale, "Cascadia Mono"))
        self.text.setGeometry(*mapped_geometry(transform, LOG_TEXT))
        self._apply_text_style(transform.scale)
        super().resizeEvent(event)

    def _apply_text_style(self, scale):
        style = scaled_style(TEXT_EDIT, scale)
        style = style.replace("padding: 16px", f"padding: {max(8, round(16 * float(scale)))}px")
        self.text.setStyleSheet(style)

    def add_entry(self, category, actor, text, timestamp=None):
        del actor  # The category already identifies the source in the quiet log format.
        self.entries.append((timestamp or datetime.now().strftime("%H:%M:%S"), str(category).upper(), str(text)))
        # Small hidden updates remain immediately observable to integrations;
        # larger bursts are coalesced into one Qt turn.
        if not self.isVisible() and len(self.entries) <= 2:
            self._render_entries()
        else:
            self._schedule_render()

    def _schedule_render(self):
        if self._render_scheduled:
            return
        self._render_scheduled = True
        QTimer.singleShot(0, self._flush_render)

    def _flush_render(self):
        self._render_scheduled = False
        self._render_entries()

    def _render_entries(self):
        lines = []
        for timestamp, category, message in self.entries:
            escaped = html.escape(f"{timestamp}  {category:<10} {message}")
            escaped = re.sub(
                r"(https?://[^\s<]+)",
                r'<a href="\1">\1</a>',
                escaped,
                flags=re.IGNORECASE,
            )
            lines.append(escaped)
        self.text.setHtml("<br>".join(lines))
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    # Compatibility alias for older extensions that explicitly refreshed the log.
    _render = _render_entries

    def _clear(self):
        self.entries.clear()
        if self.isVisible():
            self._render_entries()

    def showEvent(self, event):  # noqa: N802 - Qt API
        self._render_entries()
        super().showEvent(event)

    def paintEvent(self, event):  # noqa: N802 - Qt API
        del event
        self._paint_chrome("LOG", "LIVE ACTIVITY")

    def _paint_chrome(self, title: str, detail: str):
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
        painter.drawText(QRectF(34, 70, 420, 24), Qt.AlignLeft | Qt.AlignVCenter, title)
        painter.setPen(QColor(MUTED))
        painter.setFont(font(8 * transform.scale, 2.1 * transform.scale))
        painter.drawText(QRectF(34, 91, 420, 18), Qt.AlignLeft | Qt.AlignVCenter, detail)
        painter.setPen(QColor(145, 148, 154, 100))
        painter.drawLine(QRectF(34, 98, 1638, 98).topLeft(), QRectF(34, 98, 1638, 98).topRight())
        painter.restore()
        painter.end()

    def closeEvent(self, event):  # noqa: N802 - Qt API
        super().closeEvent(event)
