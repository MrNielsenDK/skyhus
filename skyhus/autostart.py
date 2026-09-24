"""The check box "Start Skyhus at login" (feature 0020).

The file ``~/.config/autostart/skyhus.desktop`` starts Skyhus with
``--background``. Skyhus only writes and removes the file when it has the
marker ``X-Skyhus-Installer=true``. It needs the start script from
``python3 -m skyhus.install``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import sideeffects
from .accounts import home_dir
from .install import APP_ID, DESKTOP_MARKER, autostart_path, script_path

log = logging.getLogger(__name__)

ON = "on"
OFF = "off"
FOREIGN = "foreign"
"""The file exists, but Skyhus did not write it."""
NOT_INSTALLED = "not_installed"
"""The start script ``~/.local/bin/skyhus`` does not exist."""
BACKGROUND_FLAG = "--background"


def render(home: Path) -> str:
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Skyhus\n"
            "Comment=Multiple OneDrive accounts on Linux\n"
            f"Exec={script_path(home)} {BACKGROUND_FLAG}\n"
            f"Icon={APP_ID}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            f"{DESKTOP_MARKER}\n")


def _ours(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return DESKTOP_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def state(home: Path | None = None) -> str:
    home = home_dir(home)
    path = autostart_path(home)
    if path.exists() or path.is_symlink():
        return ON if _ours(path) else FOREIGN
    return OFF if script_path(home).is_file() else NOT_INSTALLED


def enable(home: Path | None = None) -> bool:
    """Write the file. Returns true if the file was written."""
    home = home_dir(home)
    if state(home) != OFF:
        return False
    path = autostart_path(home)
    if not sideeffects.guard_write(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(home), encoding="utf-8")
    log.info("Wrote %s", path)
    return True


def disable(home: Path | None = None) -> bool:
    """Remove the file. Returns true if the file was removed."""
    home = home_dir(home)
    if state(home) != ON:
        return False
    path = autostart_path(home)
    if not sideeffects.guard_write(path):
        return False
    path.unlink()
    log.info("Removed %s", path)
    return True
