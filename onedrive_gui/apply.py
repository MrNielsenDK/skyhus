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

``execute()`` kalder ``on_step(step, state, progress)`` ved hvert skift
(feature 0009). ``step`` er nøglen i ``STEPS``, og ``state`` er ``WAITING``,
``RUNNING``, ``DONE`` eller ``FAILED``. Under uploaden og papirkurven er
``progress`` en kopi af en ``SyncProgress``. Ellers er den ``None``.
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
from .progress import SyncProgress
from .removal import RemovedPath, find_removed
from .rules import RuleSet, UnknownRuleError
from .service import SystemctlError
from .synclist import SelectionError, read_sync_list, write_sync_list

log = logging.getLogger(__name__)

Run = Callable[..., subprocess.CompletedProcess]
Popen = Callable[..., object]
Trash = Callable[[Path], bool]

STOP, UPLOAD, WRITE, TRASH, RESYNC = 1, 2, 3, 4, 5
STEPS = {
    STOP: "Stopper servicen",
    UPLOAD: "Uploader lokale ændringer",
    WRITE: "Skriver de nye regler",
    TRASH: "Flytter til papirkurven",
    RESYNC: "Starter servicen med resync",
}
"""De 5 trin i en ændring af mappevalget for en konto, der har synkroniseret før."""

WAITING = "waiting"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

OnStep = Callable[[int, str, "SyncProgress | None"], None]
UPLOAD_DETAIL_LINES = 5


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


class Upload:
    """Uploaden i trin 2. Klientens stdout går linje for linje til ``progress``.

    ``process`` er den kørende proces, mens ``run()`` venter på den.
    """

    def __init__(self, change: Change, popen: Popen, on_progress: Callable[[SyncProgress], None]):
        self.command = upload_command(change.account.confdir)
        self.progress = SyncProgress()
        self.process = None
        self._popen = popen
        self._on_progress = on_progress
        self._tail: list[str] = []

    def run(self) -> None:
        """Kør uploaden til ende. En fejl giver ``ApplyError`` med de sidste linjer fra klienten."""
        log.info("Kører %s", " ".join(self.command))
        try:
            # En upload kan tage lang tid. Der er derfor ingen tidsgrænse.
            self.process = self._popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, text=True, errors="replace")
        except OSError as exc:
            raise ApplyError(f"Kan ikke starte {ONEDRIVE}: {exc}") from None
        if self.process.stdout is not None:
            for line in self.process.stdout:
                self._line(line)
        returncode = self.process.wait()
        if returncode != 0:
            detail = "\n".join(self._tail)
            raise ApplyError(f"Uploaden af lokale ændringer fejlede med exit-kode {returncode}.\n{detail}".strip())

    def _line(self, line: str) -> None:
        text = line.strip()
        if text:
            self._tail = (self._tail + [text])[-UPLOAD_DETAIL_LINES:]
        if self.progress.feed(line):
            self._on_progress(self.progress.snapshot())


def default_trash(path: Path) -> bool:
    return sideeffects.trash(path)


def _report(on_step: OnStep | None, step: int, state: str, progress: SyncProgress | None = None) -> None:
    if on_step is not None:
        on_step(step, state, progress.snapshot() if progress is not None else None)


def execute(change: Change, *, home: Path | None = None, run: Run | None = None,
            popen: Popen | None = None, trash: Trash | None = None, proc_root: Path = PROC_ROOT,
            on_step: OnStep | None = None) -> Result:
    run = run or sideeffects.run
    popen = popen or sideeffects.popen
    trash = trash or default_trash
    if not change.synced:
        _report(on_step, WRITE, RUNNING)
        try:
            _write(change)
        except BaseException:
            _report(on_step, WRITE, FAILED)
            raise
        _report(on_step, WRITE, DONE)
        return Result(resynced=False)

    service = change.account.service
    step = STOP
    _report(on_step, STOP, RUNNING)
    try:
        service_control.stop(service, run=run)
    except SystemctlError as exc:
        _report(on_step, STOP, FAILED)
        raise ApplyError(f"Kan ikke stoppe {service}:\n{exc}") from None

    try:
        remaining = find_processes(change.account.confdir, home=home, proc_root=proc_root)
        if remaining:
            raise ApplyError("onedrive kører stadig for kontoen, efter at servicen er stoppet.\n"
                             + _describe_processes(remaining))
        _report(on_step, STOP, DONE)
        step = UPLOAD
        upload = Upload(change, popen, lambda progress: _report(on_step, UPLOAD, RUNNING, progress))
        _report(on_step, UPLOAD, RUNNING, upload.progress)
        upload.run()
        _report(on_step, UPLOAD, DONE, upload.progress)
        step = WRITE
        _report(on_step, WRITE, RUNNING)
        _write(change)
        _report(on_step, WRITE, DONE)
    except (ApplyError, SelectionError, OSError) as exc:
        _report(on_step, step, FAILED)
        _start_again(service, run)
        if isinstance(exc, OSError):
            raise ApplyError(f"Kan ikke skrive kontoens filer: {exc}") from None
        raise

    failures = []
    moved_count = SyncProgress(total=len(change.removed))
    _report(on_step, TRASH, RUNNING, moved_count)
    for removed in change.removed:
        try:
            moved = trash(removed.path)
        except OSError as exc:
            log.warning("Kan ikke flytte %s til papirkurven: %s", removed.path, exc)
            moved = False
        if not moved:
            log.warning("Kan ikke flytte %s til papirkurven", removed.path)
            failures.append(removed.path)
        moved_count.done += 1
        moved_count.latest = str(removed.path)
        _report(on_step, TRASH, RUNNING, moved_count)
    _report(on_step, TRASH, DONE, moved_count)

    _report(on_step, RESYNC, RUNNING)
    try:
        service_control.restart_with_resync(service, home=home, run=run)
    except (SystemctlError, OSError) as exc:
        _report(on_step, RESYNC, FAILED)
        raise ApplyError(f"Mappevalget er gemt, men {service} startede ikke med --resync:\n{exc}") from None
    _report(on_step, RESYNC, DONE)
    return Result(resynced=True, trash_failures=failures)


def _start_again(service: str, run: Run) -> None:
    try:
        service_control.start(service, run=run)
    except SystemctlError as exc:
        log.warning("Kan ikke starte %s igen: %s", service, exc)
