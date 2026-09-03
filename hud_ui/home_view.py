"""The single, quiet home surface: one orb, four controls, one clock."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from .orb_widget import OrbWidget
from .theme import BACKGROUND, BUTTON, HAIRLINE, MUTED, TEXT, CONTROL_BUTTON, font, scaled_style
from .viewport import (
    HOME_CLOSE,
    HOME_CLOCK,
    HOME_CONSOLE,
    HOME_DATE,
    HOME_LOG,
    HOME_MINIMIZE,
    HOME_ORB,
    HOME_ORB_LINE,
    design_transform,
)


class HomeView(QWidget):
    """Minimal home view kept deliberately free of dashboard telemetry."""

    log_requested = Signal()
    console_requested = Signal()
    minimize_requested = Signal()
    close_requested = Signal()

    _STATE_COPY = {
        "idle": "READY",
        "standby": "READY",
        "listening": "LISTENING",
        "thinking": "THINKING",
        "speaking": "SPEAKING",
    }
    _ITALIAN_DAYS = (
        "LUNEDÌ",
        "MARTEDÌ",
        "MERCOLEDÌ",
        "GIOVEDÌ",
        "VENERDÌ",
        "SABATO",
        "DOMENICA",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(640, 420)
        self.orb = OrbWidget(self)
        self.state = "idle"
        self.phase = 0.0

        self.log_button = self._make_button("LOG", BUTTON, "Apri il registro attività", self)
        self.console_button = self._make_button("CONSOLE", BUTTON, "Apri la console runtime", self)
        self.min_button = self._make_button("-", CONTROL_BUTTON, "Minimizza JARVIS", self)
        self.close_button = self._make_button("\N{MULTIPLICATION SIGN}", CONTROL_BUTTON, "Chiudi JARVIS", self)

        # Kept as hidden compatibility attributes for integrations that used
        # the old surface; the new home never paints duplicate wordmarks.
        self.orb_title = QLabel("", self)
        self.orb_hint = QLabel("", self)
        for label in (self.orb_title, self.orb_hint):
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            label.hide()

        self.log_button.clicked.connect(self.log_requested)
        self.console_button.clicked.connect(self.console_requested)
        self.min_button.clicked.connect(self.minimize_requested)
        self.close_button.clicked.connect(self.close_requested)

        self.clock = QTimer(self)
        self.clock.timeout.connect(self.update)
        self.clock.start(1000)

    @staticmethod
    def _make_button(text: str, style: str, tooltip: str, parent=None) -> QPushButton:
        button = QPushButton(text, parent)
        button.setStyleSheet(style)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        return button

    def _content_transform(self):
        return design_transform(self.width(), self.height())

    @staticmethod
    def _geometry(transform, rect: QRectF):
        mapped = transform.rect(rect)
        return (round(mapped.x()), round(mapped.y()), max(1, round(mapped.width())), max(1, round(mapped.height())))

    def _apply_layout(self) -> None:
        transform = self._content_transform()
        self.log_button.setStyleSheet(scaled_style(BUTTON, transform.scale))
        self.console_button.setStyleSheet(scaled_style(BUTTON, transform.scale))
        self.min_button.setStyleSheet(scaled_style(CONTROL_BUTTON, transform.scale))
        self.close_button.setStyleSheet(scaled_style(CONTROL_BUTTON, transform.scale))
        self.log_button.setGeometry(*self._geometry(transform, HOME_LOG))
        self.console_button.setGeometry(*self._geometry(transform, HOME_CONSOLE))
        self.min_button.setGeometry(*self._geometry(transform, HOME_MINIMIZE))
        self.close_button.setGeometry(*self._geometry(transform, HOME_CLOSE))
        self.log_button.setFont(font(8.5 * transform.scale, 2.0 * transform.scale))
        self.console_button.setFont(font(8.5 * transform.scale, 2.0 * transform.scale))
        self.min_button.setFont(font(13 * transform.scale, 0.0, weight=QFont.Light))
        self.close_button.setFont(font(13 * transform.scale, 0.0, weight=QFont.Light))
        self.orb.setGeometry(*self._geometry(transform, HOME_ORB))
        self.orb.raise_()
        for button in (self.log_button, self.console_button, self.min_button, self.close_button):
            button.raise_()

    def resize(self, *args):  # noqa: A003 - Qt API
        super().resize(*args)
        if not self.isVisible():
            self._apply_layout()

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        self._apply_layout()
        super().resizeEvent(event)

    def set_state(self, state):
        requested = str(state or "idle").strip().lower()
        self.state = requested if requested in self._STATE_COPY else "idle"
        self.orb.set_state(self.state)
        self.update()

    def _advance(self):
        """Compatibility hook used by the lightweight HUD tests."""

        self.phase = (self.phase + 0.016) % 1.0
        self.orb.phase = self.phase
        self.orb.update()

    def set_audio_level(self, level):
        self.orb.set_audio_level(level)

    def paintEvent(self, event):  # noqa: N802 - Qt API
        del event
        width, height = self.width(), self.height()
        transform = self._content_transform()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        background = QLinearGradient(0, 0, width, height)
        background.setColorAt(0.0, QColor("#0c0d10"))
        background.setColorAt(0.45, QColor(BACKGROUND))
        background.setColorAt(1.0, QColor("#040506"))
        painter.fillRect(self.rect(), background)

        # A single hairline keeps the frameless window legible without turning
        # the home surface into a card or a decorative dashboard.
        painter.setPen(QPen(QColor(HAIRLINE), max(1, round(transform.scale))))
        painter.drawRect(QRectF(0.5, 0.5, max(0.0, width - 1.0), max(0.0, height - 1.0)))

        painter.save()
        painter.translate(transform.offset_x, transform.offset_y)
        painter.scale(transform.scale, transform.scale)

        # The line is intentionally quiet: a soft fade at both ends and a
        # slightly brighter centre create a precise futuristic baseline under
        # the orb without turning the Home surface into a dashboard.
        line = HOME_ORB_LINE
        line_gradient = QLinearGradient(line.left(), 0.0, line.right(), 0.0)
        line_gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
        line_gradient.setColorAt(0.18, QColor(205, 211, 218, 42))
        line_gradient.setColorAt(0.50, QColor(245, 247, 249, 145))
        line_gradient.setColorAt(0.82, QColor(205, 211, 218, 42))
        line_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(line, line_gradient)

        now = datetime.now()
        painter.setPen(QColor(TEXT))
        painter.setFont(font(23 * transform.scale, 0.8 * transform.scale, weight=QFont.Light))
        painter.drawText(HOME_CLOCK, Qt.AlignRight | Qt.AlignVCenter, now.strftime("%H:%M"))
        painter.setPen(QColor(MUTED))
        painter.setFont(font(8 * transform.scale, 2.2 * transform.scale, weight=QFont.Normal))
        day = self._ITALIAN_DAYS[now.weekday()]
        painter.drawText(HOME_DATE, Qt.AlignRight | Qt.AlignVCenter, f"{day}  {now:%d.%m.%Y}")

        painter.restore()
        painter.end()

    def closeEvent(self, event):  # noqa: N802 - Qt API
        self.clock.stop()
        super().closeEvent(event)
