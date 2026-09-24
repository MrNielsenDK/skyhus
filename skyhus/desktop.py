"""The desktop that Skyhus runs on (feature 0015).

On GNOME on Wayland, the compositor does not draw title bars. Qt then draws
its own. The QtWayland plugin ``adwaita`` draws a title bar that looks like
the title bars of GNOME applications. The module does not use Qt, so the tests
can give their own environment and plugin folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

DECORATION_VAR = "QT_WAYLAND_DECORATION"
ADWAITA = "adwaita"
ADWAITA_PLUGIN = Path("wayland-decoration-client") / "libadwaita.so"


def _desktops(environ: Mapping[str, str]) -> set[str]:
    """``XDG_CURRENT_DESKTOP`` can be a list such as ``ubuntu:GNOME``."""
    return {d.strip().casefold() for d in environ.get("XDG_CURRENT_DESKTOP", "").split(":")}


def is_kde(environ: Mapping[str, str]) -> bool:
    """Is the session KDE Plasma? (feature 0017)"""
    return "kde" in _desktops(environ)


def is_gnome_wayland(environ: Mapping[str, str]) -> bool:
    """Is the session GNOME on Wayland?"""
    return "gnome" in _desktops(environ) and bool(environ.get("WAYLAND_DISPLAY"))


def wayland_decoration(environ: Mapping[str, str], plugin_dir: Path | str | None) -> str | None:
    """The title bar plugin for Qt, or ``None`` to keep the default. The function changes nothing."""
    if not is_gnome_wayland(environ) or environ.get(DECORATION_VAR):
        return None
    if plugin_dir is None or not (Path(plugin_dir) / ADWAITA_PLUGIN).is_file():
        return None
    return ADWAITA
