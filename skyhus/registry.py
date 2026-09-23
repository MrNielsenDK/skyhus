"""Read and write ``~/.config/skyhus/accounts.json``.

The file keeps the display name, ``confdir`` and ``service`` for each account.
The folders on disk decide which accounts exist. The registry only gives
them names.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import sideeffects
from .accounts import CONFDIR_PREFIX, DEFAULT_CONFDIR_NAME, gui_dir

log = logging.getLogger(__name__)


def default_name(confdir: Path) -> str:
    """The name for an account without an entry in the registry."""
    name = Path(confdir).name
    if name == DEFAULT_CONFDIR_NAME:
        return "OneDrive"
    return name.removeprefix(CONFDIR_PREFIX)


class Registry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._entries: dict[str, dict[str, str]] = {}
        self.load()

    @classmethod
    def for_home(cls, home: Path | None = None) -> Registry:
        return cls(gui_dir(home) / "accounts.json")

    def load(self) -> None:
        self._entries = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("Cannot read %s: %s", self.path, exc)
            return
        accounts = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(accounts, list):
            log.warning("Unknown format in %s", self.path)
            return
        for entry in accounts:
            if not isinstance(entry, dict):
                continue
            confdir, name = entry.get("confdir"), entry.get("name")
            if not isinstance(confdir, str) or not isinstance(name, str):
                continue
            service = entry.get("service")
            self._entries[_key(confdir)] = {
                "name": name,
                "confdir": confdir,
                "service": service if isinstance(service, str) else "",
            }

    def save(self) -> None:
        if not sideeffects.guard_write(self.path):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"accounts": list(self._entries.values())}
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def name_for(self, confdir: Path) -> str | None:
        entry = self._entries.get(_key(confdir))
        return entry["name"] if entry else None

    def service_for(self, confdir: Path) -> str:
        entry = self._entries.get(_key(confdir))
        return entry["service"] if entry else ""

    def add(self, confdir: Path, name: str, service: str = "") -> None:
        self._entries[_key(confdir)] = {"name": name, "confdir": str(confdir), "service": service}
        self.save()

    def set_name(self, confdir: Path, name: str) -> None:
        entry = self._entries.get(_key(confdir))
        if entry is None:
            self.add(confdir, name)
            return
        entry["name"] = name
        self.save()

    def set_service(self, confdir: Path, service: str) -> None:
        entry = self._entries.get(_key(confdir))
        if entry is None:
            self.add(confdir, default_name(confdir), service)
            return
        entry["service"] = service
        self.save()


def _key(confdir: Path | str) -> str:
    return os.path.normpath(os.path.expanduser(str(confdir)))
