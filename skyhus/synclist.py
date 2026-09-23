"""The account's ``sync_list`` and the selection in the folder picker.

The application manages only rules of the form ``/path/``. All other lines are
unknown rules. The application keeps them unchanged and in the same order
at the top of the file. If the file does not exist, the client syncs all folders.
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
    """The selection cannot become a ``sync_list``."""


class CheckState(IntEnum):
    """The same values as ``Qt.CheckState``."""
    UNCHECKED = 0
    PARTIAL = 1
    CHECKED = 2


@dataclass
class SyncList:
    exists: bool
    folders: list[str] = field(default_factory=list)
    """The paths from the rules ``/path/`` without ``/`` at the ends."""
    unknown: list[str] = field(default_factory=list)
    """All other lines, also empty lines and comments."""


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
    """Write the selection. ``sync_all`` removes the file, so the client syncs everything."""
    target = Path(confdir) / SYNC_LIST
    if sync_all:
        if not sideeffects.guard_write(target):
            return
        try:
            target.unlink()
            log.info("Removed %s", target)
        except FileNotFoundError:
            pass
        return
    rules = rules_for(paths)
    if not rules:
        raise SelectionError("Choose at least 1 folder, or choose \"Sync all folders\".")
    for path in paths:
        if "\n" in path or "\r" in path:
            raise SelectionError(f"The folder name cannot be in sync_list: {path!r}")
    text = "".join(f"{line}\n" for line in [*unknown, *rules])
    if not sideeffects.guard_write(target):
        return
    tmp = target.with_name(SYNC_LIST + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    log.info("Wrote %s", target)


def _is_under(path: str, parent: str) -> bool:
    return path.startswith(parent + "/")


class Selection:
    """The selection in the tree as a set of fully selected folders.

    A folder is selected if it or a parent folder is in the set. A folder
    is partly selected if one of its subfolders is in the set.
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
        """Switch a folder between selected and not selected.

        ``children`` gives the paths of the loaded subfolders, or ``None``
        if the application has not loaded them. The root is ``""``.
        """
        if self.state(path) is CheckState.CHECKED:
            self._uncheck(path, children)
        else:
            self._check(path, children)

    def _check(self, path: str, children: Callable[[str], list[str] | None]) -> None:
        self._paths = {p for p in self._paths if not _is_under(p, path)}
        self._paths.add(path)
        # If all siblings are selected, the parent folder is fully selected. The root does not count.
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
        # Replace the parent folder with its subfolders, except the ones on the way to path.
        new_paths = set()
        current = ancestor
        while current != path:
            below = children(current)
            if below is None:
                raise SelectionError(f"The subfolders in {current} are not loaded.")
            step = next((c for c in below if c == path or _is_under(path, c)), None)
            if step is None:
                raise SelectionError(f"{path} does not exist in {current}.")
            new_paths.update(c for c in below if c != step)
            current = step
        self._paths.discard(ancestor)
        self._paths |= new_paths
