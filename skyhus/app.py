"""Start the application: ``python3 -m skyhus.app`` or ``skyhus``."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QCoreApplication, QLibraryInfo, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QImage, QPainter
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickControls2 import QQuickStyle

from . import desktop, sideeffects
from . import theme  # noqa: F401 - registers the Theme singleton in QML
from .viewmodels import AppController

PACKAGE_DIR = Path(__file__).resolve().parent
QML_DIR = PACKAGE_DIR / "qml"
ASSETS_DIR = PACKAGE_DIR / "assets"
FONT_FILES = ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf")
DEFAULT_ICON_SIZE = 16
log = logging.getLogger(__name__)


def load_fonts() -> None:
    """Load Inter from ``assets/fonts``. A second call does nothing."""
    if theme.FONT_FAMILY in QFontDatabase.families():
        return
    for name in FONT_FILES:
        if QFontDatabase.addApplicationFont(str(ASSETS_DIR / "fonts" / name)) < 0:
            log.warning("Cannot load the font %s", name)


def use_default_font(app: QGuiApplication) -> None:
    font = QFont(theme.FONT_FAMILY)
    font.setPixelSize(theme.FONTS["body"][0])
    app.setFont(font)


class IconProvider(QQuickImageProvider):
    """Draw a Lucide icon in a color: ``image://icon/<name>/<rrggbb>``.

    The icons use ``currentColor``. The color comes from the text next to the icon.
    """

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._svgs: dict[str, str] = {}

    def requestImage(self, id: str, size: QSize, requested: QSize) -> QImage:
        from PySide6.QtSvg import QSvgRenderer

        name, _, color = id.partition("/")
        svg = self._svgs.get(name)
        if svg is None:
            svg = (ASSETS_DIR / "icons" / f"{name}.svg").read_text()
            self._svgs[name] = svg
        tint = QColor("#" + color) if color else QColor(Qt.black)
        # SVG does not know #AARRGGBB. The opacity is applied afterwards.
        data = svg.replace("currentColor", tint.name(QColor.HexRgb))
        width = requested.width() if requested.width() > 0 else DEFAULT_ICON_SIZE
        height = requested.height() if requested.height() > 0 else DEFAULT_ICON_SIZE
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(tint.alphaF())
        QSvgRenderer(QByteArray(data.encode())).render(painter, QRectF(0, 0, width, height))
        painter.end()
        return image


def init_webengine() -> bool:
    """Prepare QtWebEngine. This must occur before ``QGuiApplication`` exists."""
    try:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick
    except ImportError:
        log.warning("PySide6.QtWebEngineQuick is missing. The sign-in window does not work.")
        return False
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    QtWebEngineQuick.initialize()
    return True


def load_main(engine: QQmlApplicationEngine, controller: AppController) -> None:
    engine.addImageProvider("icon", IconProvider())
    engine.setInitialProperties({"controller": controller, "safeMode": sideeffects.safe_mode()})
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))


def use_gnome_title_bar(environ=None) -> None:
    """On GNOME on Wayland, use the title bar plugin ``adwaita`` (feature 0015).

    Qt reads the variable when it makes the application, so this must run before.
    """
    environ = os.environ if environ is None else environ
    plugin_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    decoration = desktop.wayland_decoration(environ, plugin_dir)
    if decoration is not None:
        environ[desktop.DECORATION_VAR] = decoration
    elif desktop.is_gnome_wayland(environ) and not environ.get(desktop.DECORATION_VAR):
        log.info("GNOME: the adwaita title bar plugin is missing. Qt draws its default title bar.")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Safe mode is fixed from here. --safe is one of the conditions.
    sideeffects.init(sys.argv)
    init_webengine()
    use_gnome_title_bar()
    app = QGuiApplication(sys.argv)
    app.setApplicationName("skyhus")
    app.setApplicationDisplayName("Skyhus")
    # On Wayland, the panel finds the icon through skyhus.desktop (feature 0013).
    app.setDesktopFileName("skyhus")
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "skyhus.svg")))
    load_fonts()
    use_default_font(app)
    # The controls draw the design themselves. The "Basic" style keeps the KDE style out.
    QQuickStyle.setStyle("Basic")

    controller = AppController()
    engine = QQmlApplicationEngine()
    load_main(engine, controller)
    if not engine.rootObjects():
        return 1
    code = app.exec()
    controller.shutdown()
    # The window must go before the controller that QML binds to.
    del engine
    return code


if __name__ == "__main__":
    sys.exit(main())
