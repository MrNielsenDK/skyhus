"""Find de lokale stier, der forsvinder, når mappevalget ændrer sig.

En sti forsvinder, hvis klienten synkroniserede den med de gamle regler, og
ikke synkroniserer den med de nye regler. Reglerne er alle regler i
``sync_list`` og ``config``. Se ``rules.py``.

En mappe forsvinder kun, hvis alle stier i den forsvinder. Ellers går
funktionen ned i mappen og finder de stier, der forsvinder. Mappen og de
andre stier bliver liggende.

Stier, som de gamle regler ikke inkluderede, forsvinder ikke. Klienten
synkroniserede dem ikke, så de findes måske kun lokalt. Symlinks og mapper
med filen ``.nosync`` forsvinder aldrig.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .rules import RuleSet, is_skipped  # noqa: F401 - is_skipped bruges af viewmodels

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rules:
    folders: list[str] | None
    """De valgte mapper uden ``/`` i enderne, eller ``None`` for alle mapper."""
    root_files: bool
    """``sync_root_files``. Tæller kun, når ``folders`` ikke er ``None``."""


@dataclass(frozen=True)
class RemovedPath:
    path: Path
    is_dir: bool
    size: int
    """Den samlede størrelse i bytes. For en mappe tæller alle filer i den."""


def _size(path: Path) -> int:
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not os.path.isdir(path) or os.path.islink(path):
        return st.st_size
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


NOSYNC = ".nosync"


def _rule_set(rules: Rules | RuleSet, skip_dirs: list[str], strict: bool) -> RuleSet:
    if isinstance(rules, RuleSet):
        return rules
    return RuleSet(rules.folders, rules.root_files, skip_dirs=skip_dirs, skip_dir_strict=strict)


def find_removed(sync_path: Path, old: Rules | RuleSet, new: Rules | RuleSet, *,
                 skip_dirs: Iterable[str] = (), strict: bool = False) -> list[RemovedPath]:
    """De øverste lokale stier, der forsvinder. Mapper står før filer.

    ``skip_dirs`` og ``strict`` gælder kun, når reglerne er ``Rules``.
    """
    skip_dirs = list(skip_dirs)
    old = _rule_set(old, skip_dirs, strict)
    new = _rule_set(new, skip_dirs, strict)

    def walk(directory: Path, rel_dir: str) -> tuple[bool, list[RemovedPath]]:
        """Om alle stier i mappen forsvinder, og de øverste stier, der forsvinder."""
        try:
            entries = sorted(os.scandir(directory), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name))
        except OSError as exc:
            log.warning("Kan ikke læse %s: %s", directory, exc)
            return False, []
        all_gone = True
        found: list[RemovedPath] = []
        for entry in entries:
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            path = Path(entry.path)
            if entry.is_symlink():
                all_gone = False
                continue
            if not entry.is_dir(follow_symlinks=False):
                if old.includes(rel, False) and not new.includes(rel, False):
                    found.append(RemovedPath(path, False, _size(path)))
                else:
                    all_gone = False
                continue
            gone, below = folder(path, rel)
            if gone:
                found.append(RemovedPath(path, True, _size(path)))
            else:
                all_gone = False
                found.extend(below)
        return all_gone, found

    def folder(path: Path, rel: str) -> tuple[bool, list[RemovedPath]]:
        """Om hele mappen forsvinder, og ellers de stier i den, der forsvinder."""
        if new.keeps_all_below(rel, old):
            return False, []
        synced = old.includes(rel, True)
        if not synced and not old.may_contain(rel):
            return False, []
        if os.path.lexists(path / NOSYNC):
            return False, []
        all_gone, below = walk(path, rel)
        # En mappe, som klienten kun havde som overmappe, forsvinder kun,
        # hvis den indeholdt noget, der forsvinder.
        if all_gone and (synced or below):
            return True, below
        return False, below

    return walk(Path(sync_path), "")[1]


def total_size(removed: Iterable[RemovedPath]) -> int:
    return sum(r.size for r in removed)


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "kB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} B"
    return f"{value:.1f} {unit}".replace(".", ",")
