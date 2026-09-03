"""The single public Orb renderer shared by Home and the startup gate."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QSize, QRectF
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget


CANONICAL_IDLE_ASSET = "orb_idle_realistic_4k_transparent.png"


class OrbWidget(QWidget):
    """Render the same clean, high-resolution 3D master everywhere.

    The orb is intentionally static: its depth comes from the approved
    glass/chrome artwork, internal shadows and contact shadow. Keeping one
    master in both Home and Startup prevents any visual jump between screens.
    """

    FRAME_STATES = frozenset({"listening", "thinking", "speaking"})
    _asset_cache: dict[Path, dict[str, list[QPixmap]]] = {}
    _ALIASES = {
        "standby": "idle",
        "ready": "idle",
        "processing": "thinking",
        "working": "thinking",
        "error": "idle",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.state = "idle"
        self.level = 0.0
        self.phase = 0.0
        self._frame_index = 0

        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        self._asset_root = root / "assets" / "orb"
        self._frames = self._asset_cache.setdefault(self._asset_root, self._load_assets(self._asset_root))
        # Keep a small per-widget cache of physical-pixel renderings.  The
        # minimized surface is deliberately compact, but it must still use
        # the 4K master at the monitor's real pixel density instead of first
        # reducing it to a low-density 72px bitmap.
        self._render_cache: dict[tuple[int, int], QPixmap] = {}

        # Kept as a stopped compatibility timer so integrations can continue
        # to query animation_active while the visual itself remains stable.
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def _load(path: Path) -> QPixmap:
        pixmap = QPixmap(str(path))
        return pixmap if not pixmap.isNull() else QPixmap()

    @classmethod
    def _load_assets(cls, asset_root: Path) -> dict[str, list[QPixmap]]:
        # Prefer the 4K transparent master; older approved masters remain
        # available as safe fallbacks for rollback or incomplete packages.
        idle = QPixmap()
        for filename in (
            CANONICAL_IDLE_ASSET,
            "orb_idle_realistic_v3_transparent.png",
            "orb_idle_realistic_v2_transparent.png",
            "orb_idle_realistic_transparent.png",
            "orb_idle_realistic.png",
            "orb_idle.png",
        ):
            idle = cls._load(asset_root / filename)
            if not idle.isNull():
                break
        frames: dict[str, list[QPixmap]] = {"idle": [] if idle.isNull() else [idle]}
        for state in sorted(cls.FRAME_STATES):
            frames[state] = list(frames["idle"])
        return frames

    @property
    def idle_pixmap(self) -> QPixmap:
        """Return the exact canonical frame used by every surface."""

        frames = self._frames.get("idle") or []
        return frames[0] if frames else QPixmap()

    @property
    def frame_index(self) -> int:
        return self._frame_index

    @property
    def animation_active(self) -> bool:
        return self._timer.isActive()

    def set_state(self, state) -> None:
        requested = str(state or "idle").strip().lower()
        self.state = self._ALIASES.get(requested, requested if requested in self._frames else "idle")
        self._frame_index = 0
        self.phase = 0.0
        self.update()

    def set_audio_level(self, level) -> None:
        try:
            self.level = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            self.level = 0.0

    def _tick(self) -> None:
        """Compatibility hook; the clean master deliberately does not move."""

        self.update()

    def _animated_pixmap(self, pixmap: QPixmap) -> QPixmap:
        """Compatibility name returning the untouched master."""

        return pixmap

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        pixmap = self.idle_pixmap
        if pixmap.isNull() or self.width() <= 0 or self.height() <= 0:
            return

        side = min(self.width(), self.height())
        dpr = max(1.0, float(self.devicePixelRatioF()))
        physical_side = max(1, round(side * dpr))
        cache_key = (physical_side, round(dpr * 100))
        rendered = self._render_cache.get(cache_key)
        if rendered is None:
            rendered = pixmap.scaled(
                QSize(physical_side, physical_side),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            rendered.setDevicePixelRatio(dpr)
            self._render_cache[cache_key] = rendered
            # Keep the cache bounded if a widget is moved between displays
            # with different scale factors or resized repeatedly.
            if len(self._render_cache) > 8:
                oldest_key = next(iter(self._render_cache))
                if oldest_key != cache_key:
                    self._render_cache.pop(oldest_key, None)

        logical_size = rendered.deviceIndependentSize()
        left = (self.width() - logical_size.width()) / 2.0
        top = (self.height() - logical_size.height()) / 2.0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(QRectF(left, top, logical_size.width(), logical_size.height()), rendered, QRectF(rendered.rect()))
        painter.end()
