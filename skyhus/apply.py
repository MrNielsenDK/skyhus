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

Brugeren kan afbryde uploaden i trin 2 med ``CancelFlag`` (feature 0010).
Så sender ``execute()`` ``SIGTERM`` til klienten og ``SIGKILL`` efter 30
sekunder. Derefter ændrer den intet og starter servicen igen uden ``--resync``,
hvis den kørte før. Trin 2 står som ``CANCELLED``, og resultatet er ``CANCELLED``.
"""

from __future__ import annotations

import logging
import signal
import subprocess
import threading
import time
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
SendSignal = Callable[[object, int], None]

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
CANCELLED = "cancelled"
"""Trin 2 og resultatet, når brugeren har afbrudt uploaden (feature 0010)."""

OnStep = Callable[[int, str, "SyncProgress | None"], None]
UPLOAD_DETAIL_LINES = 5
CANCEL_POLL_SECONDS = 1
"""Så ofte ser tråden efter "Afbryd", når klienten ikke skriver nye linjer."""
KILL_AFTER_SECONDS = 30
"""Så længe får klienten til at lukke pænt ned efter ``SIGTERM``."""


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
    outcome: str = DONE
    """``DONE`` eller ``CANCELLED``."""


class CancelFlag:
    """Knappen "Afbryd" i trin 2 (feature 0010).

    Hovedtråden kalder ``request()``, og tråden i ``execute()`` læser flaget.
    Flaget virker kun, mens uploaden kører. Før og efter trin 2 svarer
    ``request()`` falsk og ændrer intet.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._open = False
        self._requested = False

    def request(self) -> bool:
        """Afbryd uploaden. Falsk, hvis trin 2 ikke kører."""
        with self._lock:
            if not self._open:
                return False
            self._requested = True
            return True

    def is_set(self) -> bool:
        with self._lock:
            return self._requested

    def begin(self) -> None:
        """Trin 2 begynder. Fra nu kan brugeren afbryde."""
        with self._lock:
            self._open = True

    def end(self) -> bool:
        """Trin 2 er slut. Sandt, hvis brugeren nåede at afbryde."""
        with self._lock:
            self._open = False
            return self._requested


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

    ``process`` er den kørende proces, mens ``run()`` venter på den. Med et
    ``cancel``-flag ser ``run()`` efter "Afbryd" for hver linje og hvert sekund.
    """

    def __init__(self, change: Change, popen: Popen, on_progress: Callable[[SyncProgress], None], *,
                 cancel: CancelFlag | None = None, send_signal: SendSignal | None = None,
                 clock: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None):
        self.command = upload_command(change.account.confdir)
        self.progress = SyncProgress()
        self.process = None
        self._popen = popen
        self._on_progress = on_progress
        self._tail: list[str] = []
        self._cancel = cancel
        self._send_signal = send_signal or sideeffects.signal_process
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._finished = threading.Event()
        self._signal_lock = threading.Lock()
        self._terminated_at: float | None = None

    def run(self) -> None:
        """Kør uploaden til ende. En fejl giver ``ApplyError`` med de sidste linjer fra klienten."""
        log.info("Kører %s", " ".join(self.command))
        try:
            # En upload kan tage lang tid. Der er derfor ingen tidsgrænse.
            self.process = self._popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, text=True, errors="replace")
        except OSError as exc:
            raise ApplyError(f"Kan ikke starte {ONEDRIVE}: {exc}") from None
        watcher = None
        if self._cancel is not None:
            watcher = threading.Thread(target=self._watch, daemon=True)
            watcher.start()
        try:
            if self.process.stdout is not None:
                for line in self.process.stdout:
                    self._line(line)
                    if self._cancel is not None and self._cancel.is_set():
                        self._terminate()
            returncode = self.process.wait()
        finally:
            self._finished.set()
        if watcher is not None:
            watcher.join()
        if returncode != 0:
            detail = "\n".join(self._tail)
            raise ApplyError(f"Uploaden af lokale ændringer fejlede med exit-kode {returncode}.\n{detail}".strip())

    def _watch(self) -> None:
        """Se efter "Afbryd" hvert sekund. Stop processen, hvis brugeren har klikket."""
        while not self._finished.wait(CANCEL_POLL_SECONDS):
            if self._cancel.is_set():
                self._terminate()
                self._kill_after_grace()
                return

    def _terminate(self) -> None:
        with self._signal_lock:
            if self._terminated_at is not None:
                return
            self._terminated_at = self._clock()
        log.info("Afbryder uploaden: sender SIGTERM til %s", " ".join(self.command))
        self._send_signal(self.process, signal.SIGTERM)

    def _stopped(self) -> bool:
        return self._finished.is_set() or self.process.poll() is not None

    def _kill_after_grace(self) -> None:
        """Send ``SIGKILL``, hvis processen ikke er stoppet 30 sekunder efter ``SIGTERM``."""
        while not self._stopped():
            if self._clock() - self._terminated_at >= KILL_AFTER_SECONDS:
                log.warning("Uploaden stoppede ikke inden %s sekunder. Sender SIGKILL.", KILL_AFTER_SECONDS)
                self._send_signal(self.process, signal.SIGKILL)
                return
            self._sleep(CANCEL_POLL_SECONDS)

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


def _upload(upload: Upload, cancel: CancelFlag | None) -> bool:
    """Kør uploaden. Sandt, hvis brugeren afbrød den. En afbrudt upload er ikke en fejl."""
    if cancel is None:
        upload.run()
        return False
    cancel.begin()
    try:
        upload.run()
    except ApplyError:
        if cancel.end():
            return True
        raise
    # Slutter uploaden med exit-kode 0, idet brugeren klikker, er ændringen stadig afbrudt.
    return cancel.end()


def execute(change: Change, *, home: Path | None = None, run: Run | None = None,
            popen: Popen | None = None, trash: Trash | None = None, proc_root: Path = PROC_ROOT,
            on_step: OnStep | None = None, cancel: CancelFlag | None = None,
            service_active: bool = True, send_signal: SendSignal | None = None,
            clock: Callable[[], float] | None = None,
            sleep: Callable[[float], None] | None = None) -> Result:
    """Udfør ændringen. ``service_active`` er falsk, hvis servicen var stoppet før.

    Så starter ``execute()`` ikke servicen igen efter en fejl eller en afbrydelse.
    """
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
        upload = Upload(change, popen, lambda progress: _report(on_step, UPLOAD, RUNNING, progress),
                        cancel=cancel, send_signal=send_signal, clock=clock, sleep=sleep)
        _report(on_step, UPLOAD, RUNNING, upload.progress)
        if _upload(upload, cancel):
            log.info("Brugeren afbrød uploaden. Mappevalget er uændret.")
            _report(on_step, UPLOAD, CANCELLED, upload.progress)
            if service_active:
                _start_again(service, run)
            return Result(resynced=False, outcome=CANCELLED)
        _report(on_step, UPLOAD, DONE, upload.progress)
        step = WRITE
        _report(on_step, WRITE, RUNNING)
        _write(change)
        _report(on_step, WRITE, DONE)
    except (ApplyError, SelectionError, OSError) as exc:
        _report(on_step, step, FAILED)
        if service_active:
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
