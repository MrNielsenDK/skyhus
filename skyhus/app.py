"""Start applikationen: ``python3 -m skyhus.app`` eller ``skyhus``."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QCoreApplication, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickControls2 import QQuickStyle

from . import sideeffects
from . import theme  # noqa: F401 - registrerer singletonen Theme i QML
from .viewmodels import AppController

PACKAGE_DIR = Path(__file__).resolve().parent
QML_DIR = PACKAGE_DIR / "qml"
ASSETS_DIR = PACKAGE_DIR / "assets"
FONT_FILES = ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf")
DEFAULT_ICON_SIZE = 16
log = logging.getLogger(__name__)


def load_fonts() -> None:
    """Indlæs Inter fra ``assets/fonts``. Et kald mere gør ingenting."""
    if theme.FONT_FAMILY in QFontDatabase.families():
        return
    for name in FONT_FILES:
        if QFontDatabase.addApplicationFont(str(ASSETS_DIR / "fonts" / name)) < 0:
            log.warning("Kan ikke indlæse skriften %s", name)


def use_default_font(app: QGuiApplication) -> None:
    font = QFont(theme.FONT_FAMILY)
    font.setPixelSize(theme.FONTS["body"][0])
    app.setFont(font)


class IconProvider(QQuickImageProvider):
    """Tegn et Lucide-ikon i en farve: ``image://icon/<navn>/<rrggbb>``.

    Ikonerne bruger ``currentColor``. Farven kommer fra teksten ved siden af ikonet.
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
        # SVG kender ikke #AARRGGBB. Gennemsigtigheden kommer på bagefter.
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
    """Klargør QtWebEngine. Det skal ske, før ``QGuiApplication`` findes."""
    try:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick
    except ImportError:
        log.warning("PySide6.QtWebEngineQuick mangler. Login-vinduet virker ikke.")
        return False
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    QtWebEngineQuick.initialize()
    return True


def load_main(engine: QQmlApplicationEngine, controller: AppController) -> None:
    engine.addImageProvider("icon", IconProvider())
    engine.setInitialProperties({"controller": controller, "safeMode": sideeffects.safe_mode()})
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Sikker tilstand ligger fast herfra. --safe er en af betingelserne.
    sideeffects.init(sys.argv)
    init_webengine()
    app = QGuiApplication(sys.argv)
    app.setApplicationName("skyhus")
    app.setApplicationDisplayName("Skyhus")
    load_fonts()
    use_default_font(app)
    # Kontrollerne tegner selv designet. Stilen "Basic" holder KDE's stil ude.
    QQuickStyle.setStyle("Basic")

    controller = AppController()
    engine = QQmlApplicationEngine()
    load_main(engine, controller)
    if not engine.rootObjects():
        return 1
    code = app.exec()
    controller.shutdown()
    # Vinduet skal forsvinde før controlleren, som QML binder til.
    del engine
    return code


if __name__ == "__main__":
    sys.exit(main())
