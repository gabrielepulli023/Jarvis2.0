"""DPI-neutral geometry for the minimal JARVIS surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize


REFERENCE_WIDTH = 1672.0
REFERENCE_HEIGHT = 941.0
REFERENCE_ASPECT = REFERENCE_WIDTH / REFERENCE_HEIGHT

# Public compatibility bounds; the new design uses the entire canvas rather
# than the former two-panel composition.
HOME_PANEL = QRectF(0.0, 0.0, REFERENCE_WIDTH, REFERENCE_HEIGHT)
STARTUP_PANEL = HOME_PANEL

# One uncluttered canvas. The orb is deliberately kept on the same 465px
# asset family; the larger host box gives it air without changing the asset.
HOME_ORB = QRectF(586.0, 220.0, 500.0, 500.0)
HOME_LOG = QRectF(34.0, 28.0, 70.0, 30.0)
HOME_CONSOLE = QRectF(114.0, 28.0, 98.0, 30.0)
HOME_MINIMIZE = QRectF(1572.0, 22.0, 38.0, 30.0)
HOME_CLOSE = QRectF(1614.0, 22.0, 38.0, 30.0)
HOME_CLOCK = QRectF(1390.0, 845.0, 262.0, 38.0)
HOME_DATE = QRectF(1350.0, 882.0, 302.0, 22.0)
# A restrained accent line gives the orb a visual baseline without adding a
# second panel or competing with the wordmark.
HOME_ORB_LINE = QRectF(666.0, 754.0, 340.0, 2.0)

STARTUP_ORB = QRectF(666.0, 150.0, 340.0, 340.0)
STARTUP_MINIMIZE = HOME_MINIMIZE
STARTUP_CLOSE = HOME_CLOSE
STARTUP_TITLE = QRectF(480.0, 505.0, 712.0, 32.0)
STARTUP_SUBTITLE = QRectF(430.0, 545.0, 812.0, 24.0)
STARTUP_BAR = QRectF(536.0, 598.0, 600.0, 10.0)
STARTUP_PERCENT = QRectF(480.0, 630.0, 712.0, 30.0)
STARTUP_FOOTER = QRectF(480.0, 790.0, 712.0, 22.0)

# Compatibility names retained for older integrations/tests. The new startup
# surface no longer paints decorative rings or a split panel.
STARTUP_MARK = STARTUP_ORB
STARTUP_CENTER = QPointF(836.0, 320.0)
STARTUP_LINE = (QPointF(810.0, 576.0), QPointF(862.0, 576.0))
STARTUP_DOTS = (QPointF(824.0, 824.0), QPointF(836.0, 824.0), QPointF(848.0, 824.0))

LOG_BACK = QRectF(34.0, 28.0, 92.0, 30.0)
LOG_CLEAR = QRectF(136.0, 28.0, 72.0, 30.0)
LOG_MINIMIZE = HOME_MINIMIZE
LOG_CLOSE = HOME_CLOSE
LOG_TEXT = QRectF(34.0, 112.0, 1604.0, 760.0)

CONSOLE_BACK = LOG_BACK
CONSOLE_MINIMIZE = LOG_MINIMIZE
CONSOLE_CLOSE = LOG_CLOSE
CONSOLE_OUTPUT = LOG_TEXT


@dataclass(frozen=True)
class DesignTransform:
    """Uniform mapping from the reference canvas to a real Qt widget."""

    scale: float
    offset_x: float
    offset_y: float

    def rect(self, rect: QRectF) -> QRectF:
        return QRectF(
            self.offset_x + rect.x() * self.scale,
            self.offset_y + rect.y() * self.scale,
            rect.width() * self.scale,
            rect.height() * self.scale,
        )

    def point(self, point: QPointF) -> QPointF:
        return QPointF(self.offset_x + point.x() * self.scale, self.offset_y + point.y() * self.scale)


def design_transform(width: float, height: float) -> DesignTransform:
    """Letterbox the design canvas without stretching the orb or typography."""

    scale = min(float(width) / REFERENCE_WIDTH, float(height) / REFERENCE_HEIGHT)
    scale = max(0.01, scale)
    return DesignTransform(
        scale=scale,
        offset_x=(float(width) - REFERENCE_WIDTH * scale) / 2.0,
        offset_y=(float(height) - REFERENCE_HEIGHT * scale) / 2.0,
    )


def logical_size_to_physical(size: QSize, device_pixel_ratio: float) -> QSize:
    """Convert a Qt logical size to physical raster pixels."""

    return QSize(round(size.width() * device_pixel_ratio), round(size.height() * device_pixel_ratio))


def mapped_geometry(transform: DesignTransform, rect: QRectF) -> tuple[int, int, int, int]:
    """Return integer QWidget geometry mapped from reference pixels."""

    mapped = transform.rect(rect)
    return (
        round(mapped.x()),
        round(mapped.y()),
        max(1, round(mapped.width())),
        max(1, round(mapped.height())),
    )
