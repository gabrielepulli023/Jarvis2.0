"""Monochrome visual language shared by every JARVIS surface."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase


BACKGROUND = "#07080a"
SURFACE = "#0d0f12"
TEXT = "#f4f4f5"
MUTED = "#8c9097"
SUBTLE = "#62666d"
HAIRLINE = "#48dcdee2"


BUTTON = f"""
QPushButton {{
    background: transparent;
    color: {TEXT};
    border: 1px solid rgba(222, 224, 230, 110);
    border-radius: 3px;
    padding: 0 11px;
}}
QPushButton:hover {{
    background: rgba(255, 255, 255, 17);
    border-color: rgba(245, 245, 248, 190);
}}
QPushButton:pressed {{
    background: rgba(255, 255, 255, 30);
}}
QPushButton:focus {{
    outline: none;
}}
"""


CONTROL_BUTTON = """
QPushButton {
    background: transparent;
    color: rgba(226, 228, 232, 215);
    border: none;
    border-radius: 3px;
    padding: 0;
}
QPushButton:hover {
    background: rgba(255, 255, 255, 20);
    color: #ffffff;
}
QPushButton:pressed {
    background: rgba(255, 255, 255, 34);
}
"""


TEXT_EDIT = """
QTextEdit {
    background: rgba(11, 13, 16, 235);
    color: #d9dbe0;
    border: 1px solid rgba(218, 220, 226, 78);
    border-radius: 4px;
    padding: 16px;
    selection-background-color: rgba(240, 240, 244, 72);
    selection-color: #ffffff;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 4px 2px 4px 0;
}
QScrollBar::handle:vertical {
    background: rgba(210, 212, 218, 92);
    min-height: 28px;
    border-radius: 3px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0;
}
"""


_FONT_FAMILIES: dict[str, str] = {}


def _resolve_family(requested: str) -> str:
    if requested in _FONT_FAMILIES:
        return _FONT_FAMILIES[requested]
    available = set(QFontDatabase.families())
    candidates = {
        "Segoe UI": ("Segoe UI", "Arial Nova", "Arial"),
        "Cascadia Mono": ("Cascadia Mono", "Consolas", "Arial Nova", "Arial"),
    }.get(requested, (requested, "Arial Nova", "Arial"))
    chosen = next((name for name in candidates if name in available), None)
    if chosen is None:
        for filename in ("ArialNova.ttf", "arial.ttf", "segoeui.ttf", "consola.ttf"):
            path = Path(r"C:\Windows\Fonts") / filename
            if not path.is_file():
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                loaded = QFontDatabase.applicationFontFamilies(font_id)
                if loaded:
                    chosen = loaded[0]
                    if requested == "Cascadia Mono" and filename != "consola.ttf":
                        continue
                    break
    chosen = chosen or requested
    _FONT_FAMILIES[requested] = chosen
    return chosen


def font(size: float, tracking: float = 0.0, family: str = "Segoe UI", weight: int = QFont.Normal) -> QFont:
    """Return a DPI-neutral font with explicit letter spacing."""

    result = QFont(_resolve_family(family), max(1, int(size)), weight)
    result.setLetterSpacing(QFont.AbsoluteSpacing, float(tracking))
    return result


def scaled_style(style: str, scale: float) -> str:
    """Scale the small amount of geometry embedded in a Qt stylesheet."""

    factor = max(0.1, float(scale))

    def radius(match):
        return f"border-radius: {max(1, round(float(match.group(1)) * factor))}px"

    def padding(match):
        return f"padding: 0 {max(1, round(float(match.group(1)) * factor))}px"

    value = re.sub(r"border-radius:\s*([0-9.]+)px", radius, style)
    return re.sub(r"padding:\s*0\s+([0-9.]+)px", padding, value)
