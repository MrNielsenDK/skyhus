"""Installér Skyhus for den aktuelle bruger (feature 0013).

``python3 -m skyhus.install`` skriver 3 filer under ``~/.local``: et script,
der starter Skyhus fra projektmappen, en ``.desktop``-fil til programmenuen og
ikonet. ``--uninstall`` fjerner dem igen. Installationen bruger ikke pip.

Hver fil har en markering. Applikationen overskriver eller fjerner aldrig en
fil uden markeringen.
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
from typing import Callable

from . import sideeffects

log = logging.getLogger(__name__)

APP_ID = "skyhus"
MARKER = "Installeret af Skyhus"
DESKTOP_MARKER = "X-Skyhus-Installer=true"
ICON_SOURCE = Path(__file__).resolve().parent / "assets" / "skyhus.svg"
REPO_DIR = Path(__file__).resolve().parent.parent
APT_LINE = ("sudo apt install onedrive python3-pyside6.qtquick python3-pyside6.qtquickcontrols2 "
            "python3-pyside6.qtwebenginequick python3-pyside6.qtsvg")

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


def icon_path(home: Path) -> Path:
    return home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"


def _script(repo: Path, python: str) -> str:
    return ("#!/bin/sh\n"
            f"# {MARKER}. Kør \"python3 -m skyhus.install\" igen, hvis projektmappen flytter.\n"
            f"PYTHONPATH={shlex.quote(str(repo))}${{PYTHONPATH:+:$PYTHONPATH}} "
            f"exec {shlex.quote(python)} -m skyhus.app \"$@\"\n")


def _desktop_exec(path: Path) -> str:
    text = str(path)
    return f'"{text}"' if " " in text else text


def _desktop(home: Path) -> str:
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Skyhus\n"
            "GenericName=OneDrive-konti\n"
            "Comment=Flere OneDrive-konti på Linux\n"
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
    """De 3 filer, som installationen skriver. Funktionen ændrer intet."""
    return [
        InstallFile(script_path(home), _script(repo, python), 0o755, MARKER),
        InstallFile(desktop_path(home), _desktop(home), 0o644, DESKTOP_MARKER),
        InstallFile(icon_path(home), _icon(), 0o644, MARKER),
    ]


def _is_ours(path: Path, marker: str) -> bool:
    """Har Skyhus skrevet filen? Et symlink tæller aldrig som vores."""
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return marker in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _foreign(path: Path, marker: str) -> bool:
    return (path.exists() or path.is_symlink()) and not _is_ours(path, marker)


def _refresh_menu(home: Path, run: Run | None) -> list[str]:
    """Bed skrivebordet om at læse programmenuen igen. En fejl giver kun en advarsel."""
    run = run or sideeffects.run
    warnings = []
    for cmd in (["update-desktop-database", str(desktop_path(home).parent)], ["kbuildsycoca6"]):
        try:
            result = run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            log.info("%s findes ikke. Springer over.", cmd[0])
            continue
        except (OSError, subprocess.TimeoutExpired) as exc:
            warnings.append(f"{cmd[0]} fejlede: {exc}")
            continue
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            warnings.append(f"{cmd[0]} fejlede med exit-kode {result.returncode}. {message}".strip())
    return warnings


def install(home: Path | None = None, repo: Path = REPO_DIR, *, python: str | None = None,
            run: Run | None = None, find_spec: FindSpec | None = None) -> Result:
    """Skriv de 3 filer. Stop før den første skrivning, hvis noget er galt."""
    home = Path(home) if home is not None else Path.home()
    python = python or sys.executable
    find_spec = find_spec or importlib.util.find_spec
    result = Result()

    if find_spec("PySide6.QtQuick") is None:
        result.error = f"PySide6 med QtQuick mangler. Installér systempakkerne:\n  {APT_LINE}"
        return result
    if find_spec("PySide6.QtWebEngineQuick") is None:
        result.warnings.append("QtWebEngine mangler. Skyhus starter, men login-vinduet virker ikke. "
                               "Installér python3-pyside6.qtwebenginequick.")

    files = plan(home, Path(repo), python)
    foreign = [f.path for f in files if _foreign(f.path, f.marker)]
    if foreign:
        names = "\n".join(f"  {p}" for p in foreign)
        result.error = f"Filen findes allerede, og Skyhus har ikke skrevet den. Intet er ændret:\n{names}"
        return result

    for f in files:
        if not sideeffects.guard_write(f.path):
            continue
        f.path.parent.mkdir(parents=True, exist_ok=True)
        f.path.write_text(f.content, encoding="utf-8")
        os.chmod(f.path, f.mode)
        result.written.append(f.path)

    result.warnings += _refresh_menu(home, run)
    return result


def uninstall(home: Path | None = None, *, run: Run | None = None) -> Result:
    """Fjern de filer, som Skyhus har skrevet. Konti og indstillinger bliver liggende."""
    home = Path(home) if home is not None else Path.home()
    result = Result()
    targets = [(script_path(home), MARKER), (desktop_path(home), DESKTOP_MARKER), (icon_path(home), MARKER)]
    for path, marker in targets:
        if not (path.exists() or path.is_symlink()):
            continue
        if not _is_ours(path, marker):
            result.warnings.append(f"{path} er ikke skrevet af Skyhus og bliver liggende.")
            continue
        if not sideeffects.guard_write(path):
            continue
        path.unlink()
        result.removed.append(path)
    if result.removed:
        result.warnings += _refresh_menu(home, run)
    return result


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python3 -m skyhus.install",
                                     description="Installér Skyhus i programmenuen for din bruger.")
    parser.add_argument("--uninstall", action="store_true", help="fjern Skyhus fra programmenuen igen")
    parser.add_argument("--safe", action="store_true", help="sikker tilstand: skriv intet")
    args = parser.parse_args(argv[1:])
    sideeffects.init(argv)

    if args.uninstall:
        result = uninstall()
        for path in result.removed:
            print(f"Fjernet: {path}")
        if not result.removed and not result.error:
            print("Der var intet at fjerne.")
    else:
        result = install()
        for path in result.written:
            print(f"Skrevet: {path}")
        if result.written:
            print("Start Skyhus fra programmenuen eller med kommandoen: skyhus")
    for warning in result.warnings:
        print(f"Advarsel: {warning}")
    if result.error:
        print(f"Fejl: {result.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
