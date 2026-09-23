"""Udfør en ændring af mappevalget for en konto.

``prepare()`` kontrollerer valget og finder de lokale stier, der forsvinder.
Den ændrer intet. ``execute()`` udfører ændringen i denne rækkefølge:

1. stop kontoens service,
2. upload lokale ændringer med ``--upload-only --no-remote-delete``,
3. skriv ``sync_list`` og ``sync_root_files``,
4. flyt de lokale stier, der forsvinder, til papirkurven,
5. start servicen én gang med ``--resync --resync-auth``.

Servicen stopper, før applikationen skriver noget. Så kan klienten ikke se en
lokal sletning og sende den videre til OneDrive.

Før første synkronisering findes ``items.sqlite3`` ikke. Så skriver
``execute()`` kun ``sync_list`` og ``sync_root_files``.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import service_control, sideeffects
from .accounts import ONEDRIVE, Account
from .config import (
    read_skip_dir_strict,
    read_skip_dirs,
    read_skip_dotfiles,
    read_skip_files,
    read_sync_root_files,
    write_sync_root_files,
)
from .process import PROC_ROOT, find_processes
from .removal import RemovedPath, find_removed
from .rules import RuleSet, UnknownRuleError
from .service import SystemctlError
from .synclist import SelectionError, read_sync_list, write_sync_list

log = logging.getLogger(__name__)

Run = Callable[..., subprocess.CompletedProcess]
Trash = Callable[[Path], bool]


class ApplyError(RuntimeError):
    """Ændringen kan ikke udføres. Beskeden kan vises for brugeren."""


@dataclass
class Change:
    account: Account
    synced: bool
    """``items.sqlite3`` findes. Klienten har synkroniseret kontoen før."""
    sync_all: bool
    folders: list[str]
    root_files: bool
    unknown: list[str]
    removed: list[RemovedPath] = field(default_factory=list)


@dataclass
class Result:
    resynced: bool
    trash_failures: list[Path] = field(default_factory=list)


def has_synced(confdir: Path) -> bool:
    return (Path(confdir) / "items.sqlite3").exists()


def upload_command(confdir: Path) -> list[str]:
    return [ONEDRIVE, f"--confdir={confdir}", "--sync", "--upload-only", "--no-remote-delete"]


def _foreign_processes(account: Account, home: Path | None, proc_root: Path, allowed_unit: str):
    return [p for p in find_processes(account.confdir, home=home, proc_root=proc_root)
            if not allowed_unit or p.unit != allowed_unit]


def _describe_processes(processes) -> str:
    lines = [f"PID {p.pid}: {' '.join(p.args)}" for p in processes]
    return "\n".join(lines)


def _rule_sets(account: Account, current, *, sync_all: bool, folders: list[str],
               root_files: bool) -> tuple[RuleSet, RuleSet]:
    """De gamle og de nye regler. En regel, der ikke kan tolkes, giver ``ApplyError``."""
    confdir = account.confdir
    config = dict(skip_dirs=read_skip_dirs(confdir), skip_dir_strict=read_skip_dir_strict(confdir),
                  skip_files=read_skip_files(confdir), skip_dotfiles=read_skip_dotfiles(confdir))
    try:
        old = RuleSet(current.folders if current.exists else None, read_sync_root_files(confdir),
                      current.unknown, **config)
        # "Synkroniser alle mapper" fjerner sync_list og dermed også de ukendte regler.
        new = RuleSet(None if sync_all else folders, root_files, current.unknown, **config)
    except UnknownRuleError as exc:
        raise ApplyError(f"{exc} Applikationen ændrer ikke noget. "
                         f"Ret eller fjern reglen i {Path(confdir) / 'sync_list'}.") from None
    return old, new


def prepare(account: Account, *, sync_all: bool, folders: list[str], root_files: bool,
            home: Path | None = None, proc_root: Path = PROC_ROOT) -> Change:
    """Kontrollér valget og find de lokale stier, der forsvinder. Ændrer intet."""
    folders = list(folders)
    if not sync_all and not folders:
        raise SelectionError("Vælg mindst 1 mappe, eller vælg \"Synkroniser alle mapper\".")
    current = read_sync_list(account.confdir)
    old, new = _rule_sets(account, current, sync_all=sync_all, folders=folders, root_files=root_files)
    synced = has_synced(account.confdir)
    if synced and not account.service:
        raise ApplyError("Kontoen har ingen service. Applikationen kan ikke ændre mappevalget sikkert.")
    others = _foreign_processes(account, home, proc_root, account.service)
    if others:
        raise ApplyError("En anden onedrive-proces bruger kontoen. Stop den først.\n"
                         + _describe_processes(others))
    change = Change(account=account, synced=synced, sync_all=sync_all, folders=folders,
                    root_files=root_files, unknown=current.unknown)
    if synced:
        change.removed = find_removed(account.sync_path, old, new)
    return change


def _write(change: Change) -> None:
    confdir = change.account.confdir
    write_sync_list(confdir, change.sync_all, change.folders, change.unknown)
    write_sync_root_files(confdir, change.root_files)


def _upload(change: Change, run: Run) -> None:
    cmd = upload_command(change.account.confdir)
    log.info("Kører %s", " ".join(cmd))
    try:
        # En upload kan tage lang tid. Der er derfor ingen tidsgrænse.
        result = run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except OSError as exc:
        raise ApplyError(f"Kan ikke starte {ONEDRIVE}: {exc}") from None
    if result.returncode != 0:
        lines = [line.strip() for line in (result.stderr or result.stdout or "").splitlines() if line.strip()]
        detail = "\n".join(lines[-5:])
        raise ApplyError(f"Uploaden af lokale ændringer fejlede med exit-kode {result.returncode}.\n{detail}".strip())


def default_trash(path: Path) -> bool:
    return sideeffects.trash(path)


def execute(change: Change, *, home: Path | None = None, run: Run | None = None,
            trash: Trash | None = None, proc_root: Path = PROC_ROOT) -> Result:
    run = run or sideeffects.run
    trash = trash or default_trash
    if not change.synced:
        _write(change)
        return Result(resynced=False)

    service = change.account.service
    try:
        service_control.stop(service, run=run)
    except SystemctlError as exc:
        raise ApplyError(f"Kan ikke stoppe {service}:\n{exc}") from None

    try:
        remaining = find_processes(change.account.confdir, home=home, proc_root=proc_root)
        if remaining:
            raise ApplyError("onedrive kører stadig for kontoen, efter at servicen er stoppet.\n"
                             + _describe_processes(remaining))
        _upload(change, run)
        _write(change)
    except (ApplyError, SelectionError, OSError) as exc:
        _start_again(service, run)
        if isinstance(exc, OSError):
            raise ApplyError(f"Kan ikke skrive kontoens filer: {exc}") from None
        raise

    failures = []
    for removed in change.removed:
        try:
            moved = trash(removed.path)
        except OSError as exc:
            log.warning("Kan ikke flytte %s til papirkurven: %s", removed.path, exc)
            moved = False
        if not moved:
            log.warning("Kan ikke flytte %s til papirkurven", removed.path)
            failures.append(removed.path)

    try:
        service_control.restart_with_resync(service, home=home, run=run)
    except (SystemctlError, OSError) as exc:
        raise ApplyError(f"Mappevalget er gemt, men {service} startede ikke med --resync:\n{exc}") from None
    return Result(resynced=True, trash_failures=failures)


def _start_again(service: str, run: Run) -> None:
    try:
        service_control.start(service, run=run)
    except SystemctlError as exc:
        log.warning("Kan ikke starte %s igen: %s", service, exc)
