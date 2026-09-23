"""Tema, kontrast, avatarer, skrift og ikoner (feature 0003)."""

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtGui = pytest.importorskip("PySide6.QtGui")
from PySide6.QtCore import QEasingCurve, QObject, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFontDatabase, QPalette  # noqa: E402

from onedrive_gui import theme  # noqa: E402
from onedrive_gui.accounts import Account  # noqa: E402
from onedrive_gui.app import ASSETS_DIR, QML_DIR, load_fonts  # noqa: E402

COLOR_TOKENS = ["windowBg", "sidebarBg", "cardBg", "separator", "textPrimary", "textSecondary",
                "accent", "onAccent", "accentText", "success", "warning", "danger"]
AVATAR_TOKENS = [f"avatar{i}" for i in range(1, 9)]
FONT_TOKENS = {"largeTitle": (26, 700), "title": (17, 600), "headline": (13, 600),
               "body": (13, 400), "caption": (11, 400)}
METRIC_TOKENS = {"radiusCard": 10, "radiusControl": 6, "rowHeight": 44, "sidebarWidth": 220,
                 "animFast": 150, "animSheet": 250, "windowWidth": 960, "windowHeight": 620,
                 "windowMinWidth": 820, "windowMinHeight": 540}
SPACING_TOKENS = {"spacingXS": 4, "spacingS": 8, "spacingM": 12, "spacingL": 16, "spacingXL": 24}


class FakeHints(QObject):
    """Erstatning for QStyleHints. Testen bestemmer farveskemaet."""

    colorSchemeChanged = Signal(Qt.ColorScheme)

    def __init__(self, scheme):
        super().__init__()
        self.scheme = scheme

    def colorScheme(self):
        return self.scheme

    def switch(self, scheme):
        self.scheme = scheme
        self.colorSchemeChanged.emit(scheme)


def palette_with_window(color):
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(color))
    return palette


def make_theme(scheme, window="#FFFFFF"):
    hints = FakeHints(scheme)
    return theme.Theme(hints=hints, palette=lambda: palette_with_window(window)), hints


def luminance(color: QColor) -> float:
    def channel(value):
        value = value / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def contrast(a: QColor, b: QColor) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def color(t, token) -> QColor:
    return t.property(token)


# Tema

@pytest.mark.parametrize("scheme", [Qt.ColorScheme.Light, Qt.ColorScheme.Dark])
def test_every_token_exists_in_both_themes(app, scheme):
    t, _ = make_theme(scheme)
    for token in COLOR_TOKENS + AVATAR_TOKENS:
        value = t.property(token)
        assert isinstance(value, QColor) and value.isValid(), token
    for token, (size, weight) in FONT_TOKENS.items():
        font = t.property(token)
        assert font.pixelSize() == size, token
        assert int(font.weight()) == weight, token
        assert font.family() == "Inter", token
    for token, value in {**METRIC_TOKENS, **SPACING_TOKENS}.items():
        assert t.property(token) == value, token
    assert t.property("animEasing") == QEasingCurve.Type.OutCubic.value


def test_every_color_token_is_defined_for_light_and_dark():
    assert set(COLOR_TOKENS) <= set(theme.LIGHT)
    assert set(COLOR_TOKENS) <= set(theme.DARK)
    assert set(theme.LIGHT) == set(theme.DARK)


def test_window_background_follows_color_scheme(app):
    dark, _ = make_theme(Qt.ColorScheme.Dark)
    light, _ = make_theme(Qt.ColorScheme.Light)

    assert color(dark, "windowBg").name().upper() == "#1E1E1E"
    assert color(light, "windowBg").name().upper() == "#F5F5F7"


def test_unknown_scheme_uses_palette_lightness(app):
    dark, _ = make_theme(Qt.ColorScheme.Unknown, window="#202020")
    light, _ = make_theme(Qt.ColorScheme.Unknown, window="#EFEFEF")

    assert dark.property("dark") is True
    assert color(dark, "windowBg").name().upper() == "#1E1E1E"
    assert light.property("dark") is False
    assert color(light, "windowBg").name().upper() == "#F5F5F7"


def test_switch_from_light_to_dark_emits_signal(app):
    t, hints = make_theme(Qt.ColorScheme.Light)
    emitted = []
    t.changed.connect(lambda: emitted.append(True))

    hints.switch(Qt.ColorScheme.Dark)

    assert emitted
    assert color(t, "windowBg").name().upper() == "#1E1E1E"


def test_separator_is_translucent(app):
    t, _ = make_theme(Qt.ColorScheme.Light)
    separator = color(t, "separator")
    assert separator.alpha() == round(0.10 * 255)


# Kontrast (WCAG 2.1 AA)

SCHEMES = [Qt.ColorScheme.Light, Qt.ColorScheme.Dark]


@pytest.mark.parametrize("scheme", SCHEMES)
def test_text_contrast(app, scheme):
    t, _ = make_theme(scheme)
    for fg in ("textPrimary", "textSecondary"):
        for bg in ("windowBg", "sidebarBg", "cardBg"):
            assert contrast(color(t, fg), color(t, bg)) >= 4.5, (fg, bg)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_on_accent_contrast(app, scheme):
    t, _ = make_theme(scheme)
    assert contrast(color(t, "onAccent"), color(t, "accent")) >= 4.5


@pytest.mark.parametrize("scheme", SCHEMES)
def test_accent_text_contrast(app, scheme):
    t, _ = make_theme(scheme)
    for bg in ("windowBg", "cardBg"):
        assert contrast(color(t, "accentText"), color(t, bg)) >= 4.5, bg


@pytest.mark.parametrize("scheme", SCHEMES)
def test_status_color_contrast(app, scheme):
    t, _ = make_theme(scheme)
    for fg in ("success", "warning", "danger"):
        for bg in ("cardBg", "sidebarBg"):
            assert contrast(color(t, fg), color(t, bg)) >= 3.0, (fg, bg)


def test_avatar_text_contrast():
    assert len(theme.AVATARS) == 8
    for background, text in theme.AVATARS:
        assert contrast(QColor(text), QColor(background)) >= 3.0, background


# Avatar

def account(confdir, name="Firma"):
    return Account(name=name, confdir=Path(confdir), sync_dir="~/OneDrive", service="", logged_in=True)


def test_avatar_color_is_fixed_for_confdir():
    first = theme.avatar_color(account("/home/k/.config/onedrive-firma"))
    again = theme.avatar_color(account("/home/k/.config/onedrive-firma", name="Nyt navn"))

    assert first == again
    assert first in [background for background, _ in theme.AVATARS]
    # En fast værdi viser, at farven ikke afhænger af Pythons tilfældige hash.
    assert theme.avatar_index(Path("/home/k/.config/onedrive-firma")) == \
        theme.avatar_index(Path("/home/k/.config/onedrive-firma"))
    assert theme.avatar_index(Path("/home/k/.config/onedrive")) == 1 + int(
        __import__("hashlib").sha256(b"/home/k/.config/onedrive").hexdigest(), 16) % 8


def test_avatar_colors_differ_between_accounts():
    colors = {theme.avatar_color(account(f"/home/k/.config/onedrive-{i}")) for i in range(20)}
    assert len(colors) > 1


def test_avatar_text_color_matches_avatar_color():
    a = account("/home/k/.config/onedrive-firma")
    assert (theme.avatar_color(a), theme.avatar_text_color(a)) in theme.AVATARS


@pytest.mark.parametrize("name, expected", [
    ("Firma 2", "F2"),
    ("Privat", "P"),
    ("Søren Ærø", "SÆ"),
    ("x", "X"),
    ("  ", ""),
    ("anna berg olsen", "AB"),
])
def test_initials(name, expected):
    assert theme.initials(name) == expected


# Skrift og filer

def test_inter_is_known_after_start(app):
    load_fonts()
    assert "Inter" in QFontDatabase.families()


def test_font_and_license_files_exist():
    fonts = ASSETS_DIR / "fonts"
    for name in ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf", "OFL.txt"):
        assert (fonts / name).is_file(), name
    assert (ASSETS_DIR / "icons" / "LICENSE").is_file()


ICON_REFERENCE = re.compile(r"^\s*(?:iconName|name)\s*:\s*([^\n]+)", re.MULTILINE)
STRING = re.compile(r'"([^"]*)"')


def qml_files():
    return sorted(QML_DIR.rglob("*.qml"))


def test_every_referenced_icon_exists():
    referenced = set()
    for path in qml_files():
        for match in ICON_REFERENCE.finditer(path.read_text()):
            referenced.update(STRING.findall(match.group(1)))
    referenced.discard("")
    assert referenced, "QML-filerne henviser ikke til nogen ikoner"
    missing = [name for name in referenced if not (ASSETS_DIR / "icons" / f"{name}.svg").is_file()]
    assert missing == []


def test_icons_use_thin_strokes():
    for path in (ASSETS_DIR / "icons").glob("*.svg"):
        assert 'stroke-width="1.5"' in path.read_text(), path.name


def test_no_color_codes_in_qml():
    offenders = [str(p) for p in qml_files() if re.search(r"#[0-9A-Fa-f]{6}\b", p.read_text())]
    assert offenders == []


def test_no_named_colors_in_qml():
    """Farver kommer fra Theme. En farve som "red" i QML er også en fast farve."""
    offenders = []
    for path in qml_files():
        for line in path.read_text().splitlines():
            if re.search(r'\b[cC]olor\s*:\s*"', line):
                offenders.append(f"{path.name}: {line.strip()}")
    assert offenders == []
