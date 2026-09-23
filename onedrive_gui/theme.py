"""Designværdierne fra feature 0003: farver, skrift, mål og tider.

QML-filerne må ikke indeholde farvekoder eller faste størrelser. De bruger
singletonen ``Theme`` fra modulet ``OneDriveGui``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from PySide6.QtCore import Property, QEasingCurve, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtQml import QmlElement, QmlSingleton

from .accounts import Account

QML_IMPORT_NAME = "OneDriveGui"
QML_IMPORT_MAJOR_VERSION = 1

FONT_FAMILY = "Inter"

LIGHT = {
    "windowBg": "#F5F5F7",
    "sidebarBg": "#E8E8ED",
    "cardBg": "#FFFFFF",
    "separator": "rgba(0,0,0,0.10)",
    "textPrimary": "#1D1D1F",
    "textSecondary": "#636366",
    "accent": "#0066CC",
    "onAccent": "#FFFFFF",
    "accentText": "#0066CC",
    "success": "#248A3D",
    "warning": "#C93400",
    "danger": "#D70015",
    # Tokens, som dokumentet ikke nævner, men som kontrollerne har brug for.
    "controlFill": "rgba(120,120,128,0.20)",
    "controlBorder": "rgba(0,0,0,0.16)",
    "hover": "rgba(0,0,0,0.05)",
    "knob": "#FFFFFF",
    "scrim": "rgba(0,0,0,0.20)",
    "shadow": "rgba(0,0,0,0.10)",
}

DARK = {
    "windowBg": "#1E1E1E",
    "sidebarBg": "#252527",
    "cardBg": "#2C2C2E",
    "separator": "rgba(255,255,255,0.10)",
    "textPrimary": "#F5F5F7",
    "textSecondary": "#98989D",
    "accent": "#0071E3",
    "onAccent": "#FFFFFF",
    "accentText": "#4DA3FF",
    "success": "#30D158",
    "warning": "#FF9F0A",
    "danger": "#FF6961",
    "controlFill": "rgba(120,120,128,0.36)",
    "controlBorder": "rgba(255,255,255,0.14)",
    "hover": "rgba(255,255,255,0.06)",
    "knob": "#FFFFFF",
    "scrim": "rgba(0,0,0,0.45)",
    "shadow": "rgba(0,0,0,0.40)",
}

AVATARS = [
    ("#0A7AFF", "#FFFFFF"),
    ("#AF52DE", "#FFFFFF"),
    ("#E0356B", "#FFFFFF"),
    ("#E5352B", "#FFFFFF"),
    ("#E66A00", "#FFFFFF"),
    ("#FFCC00", "#1D1D1F"),
    ("#28A745", "#FFFFFF"),
    ("#0E8FA8", "#FFFFFF"),
]
"""Baggrund og tekst for ``avatar1`` … ``avatar8``. Ens i lyst og mørkt tema."""

FONTS = {
    "largeTitle": (26, 700),
    "title": (17, 600),
    "headline": (13, 600),
    "body": (13, 400),
    "caption": (11, 400),
}

METRICS = {
    "radiusCard": 10,
    "radiusControl": 6,
    "rowHeight": 44,
    "sidebarWidth": 220,
    "spacingXS": 4,
    "spacingS": 8,
    "spacingM": 12,
    "spacingL": 16,
    "spacingXL": 24,
    "animFast": 150,
    "animSheet": 250,
    "windowWidth": 960,
    "windowHeight": 620,
    "windowMinWidth": 820,
    "windowMinHeight": 540,
    # Mål, som dokumentet ikke nævner, men som kontrollerne har brug for.
    "hairline": 1,
    "focusRing": 3,
    "controlHeight": 28,
    "checkBoxSize": 14,
    "toggleWidth": 32,
    "toggleHeight": 18,
    "toggleInset": 2,
    "avatarSmall": 26,
    "avatarLarge": 56,
    "statusDot": 8,
    "iconSmall": 12,
    "iconMedium": 16,
    "iconLarge": 44,
    "sidebarRowHeight": 38,
    "contentWidth": 620,
    "sheetWidth": 460,
    "sheetWideWidth": 620,
    "treeIndent": 20,
    "fieldWidth": 220,
    "radiusCheck": 4,
    "checkStroke": 2,
    "treeRowHeight": 30,
}

DISABLED_OPACITY = 0.4
FOCUS_RING_ALPHA = 0.5
AVATAR_TEXT_SCALE = 0.4

_RGBA = re.compile(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)")


def parse_color(value: str) -> QColor:
    """Omsæt ``#RRGGBB`` eller ``rgba(r,g,b,a)`` til en ``QColor``."""
    match = _RGBA.fullmatch(value.replace(" ", ""))
    if match:
        r, g, b, a = match.groups()
        return QColor(int(r), int(g), int(b), round(float(a) * 255))
    return QColor(value)


def avatar_index(confdir: Path) -> int:
    """Et fast tal fra 1 til 8 ud fra config-mappen. Tallet er ens efter en genstart."""
    digest = hashlib.sha256(str(confdir).encode()).hexdigest()
    return 1 + int(digest, 16) % len(AVATARS)


def avatar_color(account: Account) -> str:
    return AVATARS[avatar_index(account.confdir) - 1][0]


def avatar_text_color(account: Account) -> str:
    return AVATARS[avatar_index(account.confdir) - 1][1]


def initials(name: str) -> str:
    """Forbogstaverne i de 2 første ord, fx "Firma 2" -> "F2"."""
    return "".join(word[0] for word in name.split()[:2]).upper()


def _font(size: int, weight: int) -> QFont:
    font = QFont(FONT_FAMILY)
    font.setPixelSize(size)
    font.setWeight(QFont.Weight(weight))
    return font


def _color_property(token: str, notify: Signal) -> Property:
    return Property(QColor, lambda self: self._color(token), notify=notify)


def _metric_property(token: str) -> Property:
    return Property(int, lambda self: METRICS[token], constant=True)


def _font_property(token: str) -> Property:
    return Property(QFont, lambda self: _font(*FONTS[token]), constant=True)


def _avatar_property(index: int, part: int) -> Property:
    return Property(QColor, lambda self: QColor(AVATARS[index][part]), constant=True)


@QmlElement
@QmlSingleton
class Theme(QObject):
    """Lyst eller mørkt tema efter systemet. Skifter uden en genstart."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None, *, hints=None, palette=None):
        super().__init__(parent)
        self._hints = hints if hints is not None else QGuiApplication.styleHints()
        self._palette = palette if palette is not None else QGuiApplication.palette
        self._dark = self._detect()
        self._hints.colorSchemeChanged.connect(self._update)

    def _detect(self) -> bool:
        scheme = self._hints.colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
        return self._palette().color(QPalette.Window).lightness() < 128

    def _update(self, *args) -> None:
        dark = self._detect()
        if dark != self._dark:
            self._dark = dark
            self.changed.emit()

    def _color(self, token: str) -> QColor:
        return parse_color((DARK if self._dark else LIGHT)[token])

    def _get_dark(self) -> bool:
        return self._dark

    dark = Property(bool, _get_dark, notify=changed)

    windowBg = _color_property("windowBg", changed)
    sidebarBg = _color_property("sidebarBg", changed)
    cardBg = _color_property("cardBg", changed)
    separator = _color_property("separator", changed)
    textPrimary = _color_property("textPrimary", changed)
    textSecondary = _color_property("textSecondary", changed)
    accent = _color_property("accent", changed)
    onAccent = _color_property("onAccent", changed)
    accentText = _color_property("accentText", changed)
    success = _color_property("success", changed)
    warning = _color_property("warning", changed)
    danger = _color_property("danger", changed)
    controlFill = _color_property("controlFill", changed)
    controlBorder = _color_property("controlBorder", changed)
    hover = _color_property("hover", changed)
    knob = _color_property("knob", changed)
    scrim = _color_property("scrim", changed)
    shadow = _color_property("shadow", changed)

    avatar1 = _avatar_property(0, 0)
    avatar2 = _avatar_property(1, 0)
    avatar3 = _avatar_property(2, 0)
    avatar4 = _avatar_property(3, 0)
    avatar5 = _avatar_property(4, 0)
    avatar6 = _avatar_property(5, 0)
    avatar7 = _avatar_property(6, 0)
    avatar8 = _avatar_property(7, 0)

    largeTitle = _font_property("largeTitle")
    title = _font_property("title")
    headline = _font_property("headline")
    body = _font_property("body")
    caption = _font_property("caption")

    radiusCard = _metric_property("radiusCard")
    radiusControl = _metric_property("radiusControl")
    rowHeight = _metric_property("rowHeight")
    sidebarWidth = _metric_property("sidebarWidth")
    spacingXS = _metric_property("spacingXS")
    spacingS = _metric_property("spacingS")
    spacingM = _metric_property("spacingM")
    spacingL = _metric_property("spacingL")
    spacingXL = _metric_property("spacingXL")
    animFast = _metric_property("animFast")
    animSheet = _metric_property("animSheet")
    windowWidth = _metric_property("windowWidth")
    windowHeight = _metric_property("windowHeight")
    windowMinWidth = _metric_property("windowMinWidth")
    windowMinHeight = _metric_property("windowMinHeight")
    hairline = _metric_property("hairline")
    focusRing = _metric_property("focusRing")
    controlHeight = _metric_property("controlHeight")
    checkBoxSize = _metric_property("checkBoxSize")
    toggleWidth = _metric_property("toggleWidth")
    toggleHeight = _metric_property("toggleHeight")
    toggleInset = _metric_property("toggleInset")
    avatarSmall = _metric_property("avatarSmall")
    avatarLarge = _metric_property("avatarLarge")
    statusDot = _metric_property("statusDot")
    iconSmall = _metric_property("iconSmall")
    iconMedium = _metric_property("iconMedium")
    iconLarge = _metric_property("iconLarge")
    sidebarRowHeight = _metric_property("sidebarRowHeight")
    contentWidth = _metric_property("contentWidth")
    sheetWidth = _metric_property("sheetWidth")
    sheetWideWidth = _metric_property("sheetWideWidth")
    treeIndent = _metric_property("treeIndent")
    fieldWidth = _metric_property("fieldWidth")
    radiusCheck = _metric_property("radiusCheck")
    checkStroke = _metric_property("checkStroke")
    treeRowHeight = _metric_property("treeRowHeight")

    animEasing = Property(int, lambda self: QEasingCurve.Type.OutCubic.value, constant=True)
    disabledOpacity = Property(float, lambda self: DISABLED_OPACITY, constant=True)
    avatarTextScale = Property(float, lambda self: AVATAR_TEXT_SCALE, constant=True)
    transparent = Property(QColor, lambda self: QColor(0, 0, 0, 0), constant=True)

    def _get_focus_ring_color(self) -> QColor:
        color = self._color("accent")
        color.setAlphaF(FOCUS_RING_ALPHA)
        return color

    focusRingColor = Property(QColor, _get_focus_ring_color, notify=changed)
    """Ringen om et fokuseret element: ``accent`` med 50 % gennemsigtighed."""
