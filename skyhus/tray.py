"""The tray icon (feature 0020). Like ``viewmodels.py``, this module uses Qt.

The icon is the Skyhus icon with a dot for the total state. The menu has
"Open Skyhus", 1 line per account with its action, "Start Skyhus at login"
and "Quit Skyhus". The logic is in ``tray_state.py`` and ``autostart.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import autostart, tray_state
from .theme import DARK, parse_color

log = logging.getLogger(__name__)

ICON_SOURCE = Path(__file__).resolve().parent / "assets" / "skyhus.svg"
ICON_SIZES = (16, 22, 32, 64)
DOT_FRACTION = 0.44
"""The size of the dot as a part of the icon size."""
# The dot uses the bright colors of the dark theme. At 16 px, the darker orange of the
# light theme looks almost the same as the red.
MESSAGE_MS = 8000
AUTOSTART_TEXT = "Start Skyhus at login"
AUTOSTART_TIPS = {
    autostart.FOREIGN: "The file ~/.config/autostart/skyhus.desktop exists, but Skyhus did not write it.",
    autostart.NOT_INSTALLED: "Install Skyhus first: python3 -m skyhus.install",
}


def render_icon(tone: str) -> QIcon:
    """The Skyhus icon with a dot in the lower right corner for ``danger`` and ``warning``."""
    renderer = QSvgRenderer(str(ICON_SOURCE))
    icon = QIcon()
    for size in ICON_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        if tone in (tray_state.DANGER, tray_state.WARNING):
            dot = size * DOT_FRACTION
            ring = max(1.0, size / 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("white"))
            painter.drawEllipse(QRectF(size - dot - ring, size - dot - ring, dot + ring, dot + ring))
            painter.setBrush(parse_color(DARK[tone]))
            painter.drawEllipse(QRectF(size - dot - ring / 2, size - dot - ring / 2, dot, dot))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class Tray(QObject):
    """The tray icon for 1 ``AppController``."""

    def __init__(self, controller, home: Path | None = None, parent: QObject | None = None, *,
                 tray_icon: QSystemTrayIcon | None = None):
        super().__init__(parent)
        self._controller = controller
        self._home = home
        self._icon = tray_icon if tray_icon is not None else QSystemTrayIcon(self)
        self._menu = QMenu()
        self._menu.setToolTipsVisible(True)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._tone = ""
        self._menu_key: tuple = ()
        controller.statusesChanged.connect(self.update)
        controller.trayMessageRequested.connect(self._show_message)
        self.update()

    @property
    def icon(self) -> QSystemTrayIcon:
        return self._icon

    @property
    def menu(self) -> QMenu:
        return self._menu

    @property
    def tone(self) -> str:
        return self._tone

    def show(self) -> None:
        self._icon.show()

    @Slot()
    def update(self) -> None:
        accounts, statuses = self._controller.tray_snapshot()
        tone = tray_state.total_tone(statuses.values())
        if tone != self._tone:
            self._tone = tone
            self._icon.setIcon(render_icon(tone))
        self._icon.setToolTip(tray_state.tooltip(accounts, statuses))
        items = tray_state.menu_items(accounts, statuses)
        start_state = autostart.state(self._home)
        key = (tuple(items), start_state)
        # The menu is built again only when it changes. Then an open menu does not close every 3 seconds.
        if key != self._menu_key:
            self._menu_key = key
            self._build_menu(items, start_state)

    def _build_menu(self, items: list[tray_state.MenuItem], start_state: str) -> None:
        self._menu.clear()
        open_action = self._menu.addAction("Open Skyhus")
        font = open_action.font()
        font.setBold(True)
        open_action.setFont(font)
        open_action.triggered.connect(self._controller.showWindow)
        if items:
            self._menu.addSeparator()
        for item in items:
            action = self._menu.addAction(item.text)
            if item.kind == tray_state.LABEL:
                action.setEnabled(False)
            else:
                action.triggered.connect(lambda _checked=False, confdir=item.confdir:
                                         self._controller.trayAction(confdir))
        self._menu.addSeparator()
        start = QAction(AUTOSTART_TEXT, self._menu)
        start.setCheckable(True)
        start.setChecked(start_state == autostart.ON)
        start.setEnabled(start_state in (autostart.ON, autostart.OFF))
        start.setToolTip(AUTOSTART_TIPS.get(start_state, ""))
        start.toggled.connect(self._toggle_autostart)
        self._menu.addAction(start)
        self._menu.addSeparator()
        quit_action = self._menu.addAction("Quit Skyhus")
        quit_action.triggered.connect(self._controller.quit)

    @Slot(bool)
    def _toggle_autostart(self, checked: bool) -> None:
        changed = autostart.enable(self._home) if checked else autostart.disable(self._home)
        if not changed:
            log.warning("Skyhus did not change the file for \"%s\"", AUTOSTART_TEXT)
        self._menu_key = ()
        self.update()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._controller.toggleWindow()

    @Slot(str, str)
    def _show_message(self, title: str, text: str) -> None:
        self._icon.showMessage(title, text, QSystemTrayIcon.Information, MESSAGE_MS)
