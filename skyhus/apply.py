"""Carry out a change of the folder selection for an account.

``prepare()`` checks the selection and finds the local paths that disappear.
It changes nothing. ``execute()`` carries out the change in this order:

1. stop the account's service,
2. upload local changes with ``--upload-only --no-remote-delete``,
3. write ``sync_list`` and ``sync_root_files``,
4. move the local paths that disappear to Trash,
5. start the service one time with ``--resync --resync-auth``.

The service stops before the application writes anything. Then the client cannot
see a local deletion and send it on to OneDrive.

Before the first sync, ``items.sqlite3`` does not exist. Then
``execute()`` only writes ``sync_list`` and ``sync_root_files``.

``execute()`` calls ``on_step(step, state, progress)`` at each change
(feature 0009). ``step`` is the key in ``STEPS``, and ``state`` is ``WAITING``,
``RUNNING``, ``DONE`` or ``FAILED``. During the upload and the Trash step,
``progress`` is a copy of a ``SyncProgress``. Otherwise it is ``None``.

The user can stop the upload in step 2 with ``CancelFlag`` (feature 0010).
Then ``execute()`` sends ``SIGTERM`` to the client and ``SIGKILL`` after 30
seconds. After that it changes nothing and starts the service again without
``--resync`` if it was running before. Step 2 shows ``CANCELLED``, and the result
is ``CANCELLED``.
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
    STOP: "Stopping the service",
    UPLOAD: "Uploading local changes",
    WRITE: "Writing the new rules",
    TRASH: "Moving to Trash",
    RESYNC: "Starting the service with resync",
}
"""The 5 steps in a change of the folder selection for an account that has synced before."""

WAITING = "waiting"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
"""Step 2 and the result when the user has stopped the upload (feature 0010)."""

OnStep = Callable[[int, str, "SyncProgress | None"], None]
UPLOAD_DETAIL_LINES = 5
CANCEL_POLL_SECONDS = 1
"""How often the thread checks for "Stop" when the client writes no new lines."""
KILL_AFTER_SECONDS = 30
"""The time the client gets to shut down cleanly after ``SIGTERM``."""


class ApplyError(RuntimeError):
    """The change cannot be carried out. The message can be shown to the user."""


@dataclass
class Change:
    account: Account
    synced: bool
    """``items.sqlite3`` exists. The client has synced the account before."""
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
    """``DONE`` or ``CANCELLED``."""


class CancelFlag:
    """The "Stop" button in step 2 (feature 0010).

    The main thread calls ``request()``, and the thread in ``execute()`` reads the flag.
    The flag only works while the upload runs. Before and after step 2,
    ``request()`` returns false and changes nothing.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._open = False
        self._requested = False

    def request(self) -> bool:
        """Stop the upload. False if step 2 is not running."""
        with self._lock:
            if not self._open:
                return False
            self._requested = True
            return True

    def is_set(self) -> bool:
        with self._lock:
            return self._requested

    def begin(self) -> None:
        """Step 2 begins. From now on the user can stop."""
        with self._lock:
            self._open = True

    def end(self) -> bool:
        """Step 2 is over. True if the user stopped in time."""
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
    """The old and the new rules. A rule that cannot be interpreted gives ``ApplyError``."""
    confdir = account.confdir
    config = dict(skip_dirs=read_skip_dirs(confdir), skip_dir_strict=read_skip_dir_strict(confdir),
                  skip_files=read_skip_files(confdir), skip_dotfiles=read_skip_dotfiles(confdir))
    try:
        old = RuleSet(current.folders if current.exists else None, read_sync_root_files(confdir),
                      current.unknown, **config)
        # "Sync all folders" removes sync_list and with it also the unknown rules.
        new = RuleSet(None if sync_all else folders, root_files, current.unknown, **config)
    except UnknownRuleError as exc:
        raise ApplyError(f"{exc} Skyhus does not change anything. "
                         f"Fix or remove the rule in {Path(confdir) / 'sync_list'}.") from None
    return old, new


def prepare(account: Account, *, sync_all: bool, folders: list[str], root_files: bool,
            home: Path | None = None, proc_root: Path = PROC_ROOT) -> Change:
    """Check the selection and find the local paths that disappear. Changes nothing."""
    folders = list(folders)
    if not sync_all and not folders:
        raise SelectionError("Choose at least 1 folder, or choose \"Sync all folders\".")
    current = read_sync_list(account.confdir)
    old, new = _rule_sets(account, current, sync_all=sync_all, folders=folders, root_files=root_files)
    synced = has_synced(account.confdir)
    if synced and not account.service:
        raise ApplyError("The account has no service. Skyhus cannot change the folder selection safely.")
    others = _foreign_processes(account, home, proc_root, account.service)
    if others:
        raise ApplyError("Another onedrive process uses the account. Stop it first.\n"
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
    """The upload in step 2. The client's stdout goes line by line to ``progress``.

    ``process`` is the running process while ``run()`` waits for it. With a
    ``cancel`` flag, ``run()`` checks for "Stop" at each line and each second.
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
        """Run the upload to the end. An error gives ``ApplyError`` with the last lines from the client."""
        log.info("Running %s", " ".join(self.command))
        try:
            # An upload can take a long time. So there is no time limit.
            self.process = self._popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, text=True, errors="replace")
        except OSError as exc:
            raise ApplyError(f"Cannot start {ONEDRIVE}: {exc}") from None
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
            raise ApplyError(f"The upload of local changes failed with exit code {returncode}.\n{detail}".strip())

    def _watch(self) -> None:
        """Check for "Stop" each second. Stop the process if the user has clicked."""
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
        log.info("Stopping the upload: sending SIGTERM to %s", " ".join(self.command))
        self._send_signal(self.process, signal.SIGTERM)

    def _stopped(self) -> bool:
        return self._finished.is_set() or self.process.poll() is not None

    def _kill_after_grace(self) -> None:
        """Send ``SIGKILL`` if the process has not stopped 30 seconds after ``SIGTERM``."""
        while not self._stopped():
            if self._clock() - self._terminated_at >= KILL_AFTER_SECONDS:
                log.warning("The upload did not stop within %s seconds. Sending SIGKILL.", KILL_AFTER_SECONDS)
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
    """Run the upload. True if the user stopped it. A stopped upload is not an error."""
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
    # If the upload ends with exit code 0 as the user clicks, the change is still stopped.
    return cancel.end()


def execute(change: Change, *, home: Path | None = None, run: Run | None = None,
            popen: Popen | None = None, trash: Trash | None = None, proc_root: Path = PROC_ROOT,
            on_step: OnStep | None = None, cancel: CancelFlag | None = None,
            service_active: bool = True, send_signal: SendSignal | None = None,
            clock: Callable[[], float] | None = None,
            sleep: Callable[[float], None] | None = None) -> Result:
    """Carry out the change. ``service_active`` is false if the service was stopped before.

    Then ``execute()`` does not start the service again after an error or a stop.
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
        raise ApplyError(f"Cannot stop {service}:\n{exc}") from None

    try:
        remaining = find_processes(change.account.confdir, home=home, proc_root=proc_root)
        if remaining:
            raise ApplyError("onedrive is still running for the account after the service stopped.\n"
                             + _describe_processes(remaining))
        _report(on_step, STOP, DONE)
        step = UPLOAD
        upload = Upload(change, popen, lambda progress: _report(on_step, UPLOAD, RUNNING, progress),
                        cancel=cancel, send_signal=send_signal, clock=clock, sleep=sleep)
        _report(on_step, UPLOAD, RUNNING, upload.progress)
        if _upload(upload, cancel):
            log.info("The user stopped the upload. The folder selection did not change.")
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
            raise ApplyError(f"Cannot write the account's files: {exc}") from None
        raise

    failures = []
    moved_count = SyncProgress(total=len(change.removed))
    _report(on_step, TRASH, RUNNING, moved_count)
    for removed in change.removed:
        try:
            moved = trash(removed.path)
        except OSError as exc:
            log.warning("Cannot move %s to Trash: %s", removed.path, exc)
            moved = False
        if not moved:
            log.warning("Cannot move %s to Trash", removed.path)
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
        raise ApplyError(f"The folder selection is saved, but {service} did not start with --resync:\n{exc}") from None
    _report(on_step, RESYNC, DONE)
    return Result(resynced=True, trash_failures=failures)


def _start_again(service: str, run: Run) -> None:
    try:
        service_control.start(service, run=run)
    except SystemctlError as exc:
        log.warning("Cannot start %s again: %s", service, exc)
