"""Install Skyhus for the current user (feature 0013).

``python3 -m skyhus.install`` writes 3 files under ``~/.local``: a script
that starts Skyhus from the project folder, a ``.desktop`` file for the program menu and
the icon. ``--uninstall`` removes them again. The installation does not use pip.

Each file has a marker. The application never overwrites or removes a
file without the marker.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from . import desktop, sideeffects

log = logging.getLogger(__name__)

APP_ID = "skyhus"
MARKER = "Installed by Skyhus"
LEGACY_MARKER = "Installeret af Skyhus"  # allow-danish: marker from version 0.9.0
"""The marker from version 0.9.0. The application also overwrites and removes those files."""
DESKTOP_MARKER = "X-Skyhus-Installer=true"
ICON_SOURCE = Path(__file__).resolve().parent / "assets" / "skyhus.svg"
REPO_DIR = Path(__file__).resolve().parent.parent
APT_LINE = ("sudo apt install onedrive python3-pyside6.qtquick python3-pyside6.qtquickcontrols2 "
            "python3-pyside6.qtwebenginequick python3-pyside6.qtsvg python3-pyside6.qtwidgets "
            "python3-pyside6.qtnetwork")
REQUIRED_MODULES = ("PySide6.QtQuick", "PySide6.QtWidgets", "PySide6.QtNetwork")
"""QtWidgets and QtNetwork are for the tray icon and the single instance (feature 0020)."""

Run = Callable[..., subprocess.CompletedProcess]
FindSpec = Callable[[str], object]


@dataclass
class Result:
    written: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""


@dataclass(frozen=True)
class InstallFile:
    path: Path
    content: str
    mode: int
    marker: str


def script_path(home: Path) -> Path:
    return home / ".local" / "bin" / APP_ID


def desktop_path(home: Path) -> Path:
    return home / ".local" / "share" / "applications" / f"{APP_ID}.desktop"


def autostart_path(home: Path) -> Path:
    """The file for "Start Skyhus at login" (feature 0020)."""
    return home / ".config" / "autostart" / f"{APP_ID}.desktop"


def icon_path(home: Path) -> Path:
    return home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"


def _script(repo: Path, python: str) -> str:
    return ("#!/bin/sh\n"
            f"# {MARKER}. Run \"python3 -m skyhus.install\" again if the project folder moves.\n"
            f"PYTHONPATH={shlex.quote(str(repo))}${{PYTHONPATH:+:$PYTHONPATH}} "
            f"exec {shlex.quote(python)} -m skyhus.app \"$@\"\n")


def _desktop_exec(path: Path) -> str:
    text = str(path)
    return f'"{text}"' if " " in text else text


def _desktop(home: Path) -> str:
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Skyhus\n"
            "GenericName=OneDrive accounts\n"
            "Comment=Multiple OneDrive accounts on Linux\n"
            f"Exec={_desktop_exec(script_path(home))}\n"
            f"Icon={APP_ID}\n"
            "Terminal=false\n"
            "Categories=Network;FileTransfer;Qt;\n"
            f"StartupWMClass={APP_ID}\n"
            f"{DESKTOP_MARKER}\n")


def _icon() -> str:
    text = ICON_SOURCE.read_text(encoding="utf-8")
    head, sep, rest = text.partition("?>\n")
    marker = f"<!-- {MARKER} -->\n"
    return f"{head}{sep}{marker}{rest}" if sep else marker + text


def plan(home: Path, repo: Path, python: str) -> list[InstallFile]:
    """The 3 files that the installation writes. The function changes nothing."""
    return [
        InstallFile(script_path(home), _script(repo, python), 0o755, MARKER),
        InstallFile(desktop_path(home), _desktop(home), 0o644, DESKTOP_MARKER),
        InstallFile(icon_path(home), _icon(), 0o644, MARKER),
    ]


def _is_ours(path: Path, marker: str) -> bool:
    """Did Skyhus write the file? A symlink never counts as ours.

    The script and the icon from version 0.9.0 have ``LEGACY_MARKER``. They also count as ours.
    """
    if path.is_symlink() or not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if marker == MARKER:
        return MARKER in text or LEGACY_MARKER in text
    return marker in text


def _foreign(path: Path, marker: str) -> bool:
    return (path.exists() or path.is_symlink()) and not _is_ours(path, marker)


def _run_tool(cmd: list[str], run: Run) -> tuple[bool, str]:
    """Run a desktop tool. Returns (found, warning). An error gives only a warning."""
    try:
        result = run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        log.info("%s does not exist. Skipping it.", cmd[0])
        return False, ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return True, f"{cmd[0]} failed: {exc}"
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        return True, f"{cmd[0]} failed with exit code {result.returncode}. {message}".strip()
    return True, ""


def icon_cache_path(home: Path) -> Path:
    return home / ".local" / "share" / "icons" / "hicolor" / "icon-theme.cache"


def _refresh_icon_cache(home: Path, run: Run | None) -> list[str]:
    """Update the GTK icon cache, if one exists (feature 0016).

    Qt uses the cache when it exists and does not look in the folder. A cache
    without the Skyhus icon hides the icon in the program menu. The function
    does not make a cache that does not exist.
    """
    cache = icon_cache_path(home)
    if not cache.is_file():
        return []
    found, warning = _run_tool(["gtk-update-icon-cache", "-f", "-t", str(cache.parent)], run or sideeffects.run)
    if not found:
        return [f"The icon cache {cache} does not contain the Skyhus icon, and gtk-update-icon-cache is missing. "
                "Install the package that contains gtk-update-icon-cache and run the install again."]
    return [warning] if warning else []


def _refresh_menu(home: Path, run: Run | None) -> list[str]:
    """Ask the desktop to read the program menu again. An error gives only a warning."""
    run = run or sideeffects.run
    warnings = []
    for cmd in (["update-desktop-database", str(desktop_path(home).parent)], ["kbuildsycoca6"]):
        _, warning = _run_tool(cmd, run)
        if warning:
            warnings.append(warning)
    return warnings


KDE_ICON_SIGNAL = ["dbus-send", "--session", "--type=signal", "/KIconLoader",
                   "org.kde.KIconLoader.iconChanged", "int32:0"]


def _reload_kde_icons(environ: Mapping[str, str], run: Run | None) -> list[str]:
    """Ask KDE to look for icons again (feature 0017).

    Plasma remembers an icon that it did not find, until it restarts. KDE sends
    the same signal when the user changes the icon theme. Other desktops do not
    listen to it.
    """
    if not desktop.is_kde(environ):
        return []
    found, warning = _run_tool(KDE_ICON_SIGNAL, run or sideeffects.run)
    if found and warning:
        log.warning("%s", warning)
        return ["KDE did not get the message to reload icons. "
                "If the menu shows no icon for Skyhus, log out and log in again."]
    return []


def install(home: Path | None = None, repo: Path = REPO_DIR, *, python: str | None = None,
            run: Run | None = None, find_spec: FindSpec | None = None,
            environ: Mapping[str, str] | None = None) -> Result:
    """Write the 3 files. Stop before the first write if something is wrong."""
    home = Path(home) if home is not None else Path.home()
    environ = os.environ if environ is None else environ
    python = python or sys.executable
    find_spec = find_spec or importlib.util.find_spec
    result = Result()

    missing = [name for name in REQUIRED_MODULES if find_spec(name) is None]
    if missing:
        result.error = (f"{', '.join(missing)} is missing. Install the system packages:\n  {APT_LINE}")
        return result
    if find_spec("PySide6.QtWebEngineQuick") is None:
        result.warnings.append("QtWebEngine is missing. Skyhus starts, but the sign-in window does not work. "
                               "Install python3-pyside6.qtwebenginequick.")

    files = plan(home, Path(repo), python)
    foreign = [f.path for f in files if _foreign(f.path, f.marker)]
    if foreign:
        names = "\n".join(f"  {p}" for p in foreign)
        result.error = f"The file already exists, and Skyhus did not write it. Nothing was changed:\n{names}"
        return result

    for f in files:
        if not sideeffects.guard_write(f.path):
            continue
        f.path.parent.mkdir(parents=True, exist_ok=True)
        f.path.write_text(f.content, encoding="utf-8")
        os.chmod(f.path, f.mode)
        result.written.append(f.path)

    result.warnings += _refresh_icon_cache(home, run)
    result.warnings += _refresh_menu(home, run)
    result.warnings += _reload_kde_icons(environ, run)
    return result


def uninstall(home: Path | None = None, *, run: Run | None = None,
              environ: Mapping[str, str] | None = None) -> Result:
    """Remove the files that Skyhus wrote. Accounts and settings stay."""
    home = Path(home) if home is not None else Path.home()
    result = Result()
    targets = [(script_path(home), MARKER), (desktop_path(home), DESKTOP_MARKER), (icon_path(home), MARKER),
               (autostart_path(home), DESKTOP_MARKER)]
    for path, marker in targets:
        if not (path.exists() or path.is_symlink()):
            continue
        if not _is_ours(path, marker):
            result.warnings.append(f"{path} was not written by Skyhus. It stays.")
            continue
        if not sideeffects.guard_write(path):
            continue
        path.unlink()
        result.removed.append(path)
    if icon_path(home) in result.removed:
        result.warnings += _refresh_icon_cache(home, run)
    if result.removed:
        result.warnings += _refresh_menu(home, run)
    if icon_path(home) in result.removed:
        result.warnings += _reload_kde_icons(os.environ if environ is None else environ, run)
    return result


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python3 -m skyhus.install",
                                     description="Install Skyhus in the program menu for your user.")
    parser.add_argument("--uninstall", action="store_true", help="remove Skyhus from the program menu again")
    parser.add_argument("--safe", action="store_true", help="safe mode: write nothing")
    args = parser.parse_args(argv[1:])
    sideeffects.init(argv)

    if args.uninstall:
        result = uninstall()
        for path in result.removed:
            print(f"Removed: {path}")
        if not result.removed and not result.error:
            print("There was nothing to remove.")
    else:
        result = install()
        for path in result.written:
            print(f"Written: {path}")
        if result.written:
            print("Start Skyhus from the program menu or with the command: skyhus")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    if result.error:
        print(f"Error: {result.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
