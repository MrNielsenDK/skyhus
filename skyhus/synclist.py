"""Kontoens ``sync_list`` og valget i mappevælgeren.

Applikationen styrer kun regler af formen ``/sti/``. Alle andre linjer er
ukendte regler. Applikationen beholder dem uændret og i samme rækkefølge
øverst i filen. Findes filen ikke, synkroniserer klienten alle mapper.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Callable, Iterable

from . import sideeffects

log = logging.getLogger(__name__)

SYNC_LIST = "sync_list"
_MANAGED = re.compile(r"^/([^*?]+?)/$")


class SelectionError(ValueError):
    """Valget kan ikke blive til en ``sync_list``."""


class CheckState(IntEnum):
    """Samme værdier som ``Qt.CheckState``."""
    UNCHECKED = 0
    PARTIAL = 1
    CHECKED = 2


@dataclass
class SyncList:
    exists: bool
    folders: list[str] = field(default_factory=list)
    """Stierne fra reglerne ``/sti/`` uden ``/`` i enderne."""
    unknown: list[str] = field(default_factory=list)
    """Alle andre linjer, også tomme linjer og kommentarer."""


def _managed_path(line: str) -> str | None:
    match = _MANAGED.match(line.strip())
    if not match:
        return None
    path = match.group(1)
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    return path


def parse_sync_list(text: str) -> SyncList:
    result = SyncList(exists=True)
    for line in text.splitlines():
        path = _managed_path(line)
        if path is None:
            result.unknown.append(line)
        elif path not in result.folders:
            result.folders.append(path)
    return result


def read_sync_list(confdir: Path) -> SyncList:
    try:
        text = (Path(confdir) / SYNC_LIST).read_text(encoding="utf-8")
    except FileNotFoundError:
        return SyncList(exists=False)
    return parse_sync_list(text)


def rules_for(paths: Iterable[str]) -> list[str]:
    return [f"/{path}/" for path in sorted(set(paths), key=str.casefold)]


def write_sync_list(confdir: Path, sync_all: bool, paths: Iterable[str], unknown: list[str]) -> None:
    """Skriv valget. ``sync_all`` fjerner filen, så klienten synkroniserer alt."""
    target = Path(confdir) / SYNC_LIST
    if sync_all:
        if not sideeffects.guard_write(target):
            return
        try:
            target.unlink()
            log.info("Fjernede %s", target)
        except FileNotFoundError:
            pass
        return
    rules = rules_for(paths)
    if not rules:
        raise SelectionError("Vælg mindst 1 mappe, eller vælg \"Synkroniser alle mapper\".")
    for path in paths:
        if "\n" in path or "\r" in path:
            raise SelectionError(f"Mappenavnet kan ikke stå i sync_list: {path!r}")
    text = "".join(f"{line}\n" for line in [*unknown, *rules])
    if not sideeffects.guard_write(target):
        return
    tmp = target.with_name(SYNC_LIST + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    log.info("Skrev %s", target)


def _is_under(path: str, parent: str) -> bool:
    return path.startswith(parent + "/")


class Selection:
    """Valget i træet som en mængde af helt valgte mapper.

    En mappe er valgt, hvis den selv eller en overmappe er i mængden. En
    mappe er delvist valgt, hvis en af dens undermapper er i mængden.
    """

    def __init__(self, paths: Iterable[str] = ()):
        self._paths = set(paths)

    @property
    def paths(self) -> list[str]:
        return sorted(self._paths, key=str.casefold)

    def state(self, path: str) -> CheckState:
        for selected in self._paths:
            if selected == path or _is_under(path, selected):
                return CheckState.CHECKED
        if any(_is_under(selected, path) for selected in self._paths):
            return CheckState.PARTIAL
        return CheckState.UNCHECKED

    def toggle(self, path: str, children: Callable[[str], list[str] | None]) -> None:
        """Skift en mappe mellem valgt og ikke valgt.

        ``children`` giver stierne på de hentede undermapper, eller ``None``,
        hvis applikationen ikke har hentet dem. Roden er ``""``.
        """
        if self.state(path) is CheckState.CHECKED:
            self._uncheck(path, children)
        else:
            self._check(path, children)

    def _check(self, path: str, children: Callable[[str], list[str] | None]) -> None:
        self._paths = {p for p in self._paths if not _is_under(p, path)}
        self._paths.add(path)
        # Er alle søskende valgt, er overmappen helt valgt. Roden tæller ikke.
        while "/" in path:
            parent = path.rsplit("/", 1)[0]
            siblings = children(parent)
            if not siblings or not all(s in self._paths for s in siblings):
                break
            self._paths -= set(siblings)
            self._paths.add(parent)
            path = parent

    def _uncheck(self, path: str, children: Callable[[str], list[str] | None]) -> None:
        if path in self._paths:
            self._paths.discard(path)
            return
        ancestor = next(p for p in self._paths if _is_under(path, p))
        # Erstat overmappen med dens undermapper, undtagen dem på vejen til path.
        new_paths = set()
        current = ancestor
        while current != path:
            below = children(current)
            if below is None:
                raise SelectionError(f"Undermapperne i {current} er ikke hentet.")
            step = next((c for c in below if c == path or _is_under(path, c)), None)
            if step is None:
                raise SelectionError(f"{path} findes ikke i {current}.")
            new_paths.update(c for c in below if c != step)
            current = step
        self._paths.discard(ancestor)
        self._paths |= new_paths
