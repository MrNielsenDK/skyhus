"""Find de OneDrive-konti, der allerede findes på maskinen."""

from __future__ import annotations

import logging
import os
import re
import shlex
from pathlib import Path

from .accounts import (
    CONFDIR_PREFIX,
    DEFAULT_CONFDIR_NAME,
    DEFAULT_SYNC_DIR,
    GUI_DIR_NAME,
    Account,
    config_home,
    home_dir,
    unit_dir,
)
from .registry import Registry, default_name

log = logging.getLogger(__name__)

ACCOUNT_MARKERS = ("config", "refresh_token", "items.sqlite3")
_CONFIG_LINE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*(?:"(.*)"|(\S.*?))\s*$')


def is_account_dir(path: Path) -> bool:
    return path.is_dir() and any((path / marker).exists() for marker in ACCOUNT_MARKERS)


def find_confdirs(home: Path | None = None) -> list[Path]:
    """Mapperne ``~/.config/onedrive`` og ``~/.config/onedrive-*``, der er konti."""
    base = config_home(home)
    try:
        entries = list(base.iterdir())
    except FileNotFoundError:
        return []
    found = []
    for path in entries:
        name = path.name
        if name != DEFAULT_CONFDIR_NAME and not name.startswith(CONFDIR_PREFIX):
            continue
        if name == GUI_DIR_NAME:
            continue
        if is_account_dir(path):
            found.append(path)
    # ~/.config/onedrive først, derefter alfabetisk.
    return sorted(found, key=lambda p: (p.name != DEFAULT_CONFDIR_NAME, p.name))


def read_config_value(confdir: Path, key: str) -> str | None:
    """Læs en værdi fra kontoens ``config``. Linjer med ``#`` tæller ikke."""
    try:
        text = (Path(confdir) / "config").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    value = None
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _CONFIG_LINE.match(line)
        if match and match.group(1) == key:
            value = match.group(2) if match.group(2) is not None else match.group(3)
    return value


def read_sync_dir(confdir: Path) -> str:
    return read_config_value(confdir, "sync_dir") or DEFAULT_SYNC_DIR


def _expand(value: str, home: Path) -> str:
    value = value.replace("%h", str(home))
    value = value.replace("${HOME}", str(home)).replace("$HOME", str(home))
    if value == "~" or value.startswith("~/"):
        value = str(home) + value[1:]
    return os.path.normpath(value)


def _confdirs_in_exec_start(value: str, home: Path) -> list[str]:
    try:
        words = shlex.split(value)
    except ValueError:
        return []
    found = []
    for i, word in enumerate(words):
        if word.startswith("--confdir="):
            found.append(_expand(word.split("=", 1)[1], home))
        elif word == "--confdir" and i + 1 < len(words):
            found.append(_expand(words[i + 1], home))
    return found


def find_service(confdir: Path, home: Path | None = None) -> str:
    """Navnet på den user-unit, der kører kontoen, eller tom."""
    confdir = Path(confdir)
    if confdir.name == DEFAULT_CONFDIR_NAME:
        return "onedrive.service"
    home = home_dir(home)
    target = os.path.normpath(str(confdir))
    try:
        units = sorted(unit_dir(home).glob("*.service"))
    except OSError:
        return ""
    for unit in units:
        if not unit.is_file():
            continue
        try:
            text = unit.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.warning("Kan ikke læse %s: %s", unit, exc)
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("ExecStart="):
                continue
            value = line.split("=", 1)[1].lstrip("-@+!:")
            if target in _confdirs_in_exec_start(value, home):
                return unit.name
    return ""


def discover_accounts(home: Path | None = None, registry: Registry | None = None) -> list[Account]:
    if registry is None:
        registry = Registry.for_home(home)
    accounts = []
    for confdir in find_confdirs(home):
        accounts.append(Account(
            name=registry.name_for(confdir) or default_name(confdir),
            confdir=confdir,
            sync_dir=read_sync_dir(confdir),
            service=find_service(confdir, home),
            logged_in=(confdir / "refresh_token").is_file(),
        ))
    return accounts
