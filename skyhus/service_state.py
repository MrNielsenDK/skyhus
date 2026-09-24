"""The state of the service for each account (feature 0004).

The application asks ``systemctl show`` about all accounts with one call. The
state comes from the properties, the files of the account and the running
``onedrive`` processes. If more than one state applies, the first one in this
order wins:

1. No service
2. Not signed in
3. Running outside the service
4. Needs resync
5. Resyncing
6. Resync stopped
7. Running, Starting, Stopping, Failed or Stopped from ``ActiveState``

"Resyncing" applies when the main process of the service has ``--resync`` on
the command line, and the journal for the current run of the service does not
yet have a line that ends the sync (feature 0009). ``ResyncTracker`` reads the
journal for the run and remembers the progress and the cursor.

"Resync stopped" applies when the application itself stopped the service during
a resync, and the service is still stopped (feature 0010). The mark is in
``~/.config/skyhus/state.json`` per service together with the ``InvocationID``
of the run. The mark goes away when the service starts a new run.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from . import journal
from . import sideeffects
from .accounts import Account, gui_dir
from .process import PROC_ROOT, OnedriveProcess, cmdline, find_processes
from .progress import COMPLETE, COMPLETE_WITH_FAILURES, SyncProgress
from .service import SystemctlError, systemctl

log = logging.getLogger(__name__)

SHOW_PROPERTIES = ("Id", "LoadState", "ActiveState", "SubState", "Result", "ExecMainStatus",
                   "MainPID", "ActiveEnterTimestamp", "InactiveEnterTimestamp", "InvocationID")
RESYNC_EXIT_STATUS = 126

NO_SERVICE = "no_service"
LOGGED_OUT = "logged_out"
FOREIGN = "foreign"
NEEDS_RESYNC = "needs_resync"
RESYNCING = "resyncing"
RESYNC_CANCELLED = "resync_cancelled"
RUNNING = "running"
STARTING = "starting"
STOPPING = "stopping"
FAILED = "failed"
STOPPED = "stopped"
UNKNOWN = "unknown"

SETTLED = frozenset({RUNNING, FAILED, NEEDS_RESYNC, RESYNCING})
"""The states that the application waits for after a click."""

# Key: (text, dot, action). The action is "restart", "start", "resync" or empty.
STATES = {
    RUNNING: ("Running", "success", "restart"),
    STARTING: ("Starting", "warning", "restart"),
    STOPPING: ("Stopping", "warning", ""),
    NEEDS_RESYNC: ("Needs resync", "danger", "resync"),
    RESYNCING: ("Resyncing", "warning", ""),
    RESYNC_CANCELLED: ("Resync stopped", "warning", "resync"),
    FAILED: ("Failed", "danger", "start"),
    STOPPED: ("Stopped", "textSecondary", "start"),
    FOREIGN: ("Running outside the service", "warning", ""),
    LOGGED_OUT: ("Not signed in", "textSecondary", ""),
    NO_SERVICE: ("No service", "textSecondary", ""),
    UNKNOWN: ("Getting status …", "textSecondary", ""),
}

ACTION_LABELS = {"restart": "Restart", "start": "Start", "resync": "Restart with resync"}

RESYNC_FLAG = "--resync"
RESULT_TEXTS = {COMPLETE: "Resync complete", COMPLETE_WITH_FAILURES: "Resync complete with errors"}

_BY_ACTIVE_STATE = {
    "active": RUNNING,
    "reloading": RUNNING,
    "refreshing": RUNNING,
    "activating": STARTING,
    "deactivating": STOPPING,
    "failed": FAILED,
    "inactive": STOPPED,
}

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_TIMESTAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})")

Run = Callable[..., subprocess.CompletedProcess]
READ_ERROR = "Cannot read the status"

STATE_FILE = "state.json"
CANCELLED_KEY = "resync_cancelled"
_STOPPED_STATES = ("inactive", "failed")
_STARTED_STATES = ("active", "reloading", "refreshing", "activating")
# The status thread and the thread for "Stop resync" can write the file at the same time.
_state_lock = threading.Lock()


@dataclass(frozen=True)
class UnitStatus:
    """The properties of 1 unit from ``systemctl show``."""

    id: str
    load_state: str = ""
    active_state: str = ""
    sub_state: str = ""
    result: str = ""
    exec_main_status: int = 0
    main_pid: int = 0
    active_enter: str = ""
    inactive_enter: str = ""
    invocation_id: str = ""

    @classmethod
    def from_properties(cls, props: dict[str, str]) -> "UnitStatus":
        def number(key: str) -> int:
            try:
                return int(props.get(key, "0") or "0")
            except ValueError:
                return 0

        return cls(
            id=props.get("Id", ""),
            load_state=props.get("LoadState", ""),
            active_state=props.get("ActiveState", ""),
            sub_state=props.get("SubState", ""),
            result=props.get("Result", ""),
            exec_main_status=number("ExecMainStatus"),
            main_pid=number("MainPID"),
            active_enter=props.get("ActiveEnterTimestamp", ""),
            inactive_enter=props.get("InactiveEnterTimestamp", ""),
            invocation_id=props.get("InvocationID", ""),
        )


@dataclass(frozen=True)
class ServiceState:
    key: str
    since: str = ""
    """For example "today at 08:37". Empty if the state has no time."""

    @property
    def label(self) -> str:
        return STATES[self.key][0]

    @property
    def tone(self) -> str:
        return STATES[self.key][1]

    @property
    def action(self) -> str:
        return STATES[self.key][2]

    @property
    def action_label(self) -> str:
        return ACTION_LABELS.get(self.action, "")


@dataclass(frozen=True)
class AccountStatus:
    state: ServiceState
    error_line: str = ""
    """The latest error line from the journal for "Failed" and "Needs resync"."""
    stale: bool = False
    """``systemctl show`` failed. ``state`` is the last known state."""
    read_error: str = ""
    progress: SyncProgress | None = None
    """The progress when the main process of the service has ``--resync``. Otherwise ``None``."""

    @property
    def progress_text(self) -> str:
        """"Resync complete", "Resync complete with errors" or empty."""
        return RESULT_TEXTS.get(self.progress.result, "") if self.progress is not None else ""

    @property
    def message(self) -> str:
        if not self.stale:
            return ""
        return f"{READ_ERROR}: {self.read_error}" if self.read_error else f"{READ_ERROR}."


def parse_show(output: str, services: list[str]) -> dict[str, UnitStatus]:
    """Split the output of ``systemctl show`` per unit.

    ``systemctl`` writes one block per unit in the same order as the names. It
    does not write the fields in the order that ``-p`` gives.
    """
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        key, sep, value = line.partition("=")
        if sep:
            current[key] = value
    if current:
        blocks.append(current)
    units = [UnitStatus.from_properties(b) for b in blocks]
    if len(units) == len(services):
        return dict(zip(services, units))
    return {u.id: u for u in units}


def read_units(services: list[str], run: Run | None = None) -> dict[str, UnitStatus]:
    services = list(dict.fromkeys(s for s in services if s))
    if not services:
        return {}
    output = systemctl("show", *services, "-p", ",".join(SHOW_PROPERTIES), run=run)
    return parse_show(output, services)


def parse_timestamp(value: str) -> datetime | None:
    """Convert for example ``Wed 2026-09-23 08:37:12 CEST`` to local time."""
    match = _TIMESTAMP.search(value or "")
    if not match:
        return None
    year, month, day, hour, minute = (int(g) for g in match.groups())
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def format_since(value: str, now: datetime) -> str:
    """"today at 08:37", "yesterday at 08:37" or "22 Sep at 08:37"."""
    when = parse_timestamp(value)
    if when is None:
        return ""
    return format_when(when, now)


def format_when(when: datetime, now: datetime) -> str:
    """The same text as ``format_since()`` for a ``datetime`` (feature 0019)."""
    clock = f"at {when:%H:%M}"
    today: date = now.date()
    if when.date() == today:
        return f"today {clock}"
    if when.date() == today - timedelta(days=1):
        return f"yesterday {clock}"
    if when.year != today.year:
        return f"{when.day} {MONTHS[when.month - 1]} {when.year} {clock}"
    return f"{when.day} {MONTHS[when.month - 1]} {clock}"


def _logged_in(account: Account) -> bool:
    return (Path(account.confdir) / "refresh_token").is_file()


def state_path(home: Path | None = None) -> Path:
    return gui_dir(home) / STATE_FILE


def _read_state_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Cannot read %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _write_state_file(path: Path, data: dict) -> None:
    if not sideeffects.guard_write(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def cancelled_resyncs(home: Path | None = None) -> dict[str, str]:
    """The services where the application has stopped a resync. The value is the ``InvocationID`` of the run."""
    with _state_lock:
        marks = _read_state_file(state_path(home)).get(CANCELLED_KEY)
    if not isinstance(marks, dict):
        return {}
    return {service: str(entry.get("invocation", "")) for service, entry in marks.items()
            if isinstance(entry, dict)}


def mark_resync_cancelled(service: str, invocation: str, home: Path | None = None) -> None:
    """Remember that the application has stopped ``service`` during a resync."""
    path = state_path(home)
    with _state_lock:
        data = _read_state_file(path)
        marks = data.get(CANCELLED_KEY)
        if not isinstance(marks, dict):
            marks = {}
        marks[service] = {"invocation": invocation}
        data[CANCELLED_KEY] = marks
        _write_state_file(path, data)
    log.info("%s: resync stopped (run %s)", service, invocation or "unknown")


def clear_resync_cancelled(service: str, home: Path | None = None) -> None:
    """Remove the mark for ``service``. Does nothing if there is none."""
    path = state_path(home)
    with _state_lock:
        data = _read_state_file(path)
        marks = data.get(CANCELLED_KEY)
        if not isinstance(marks, dict) or service not in marks:
            return
        del marks[service]
        _write_state_file(path, data)
    log.info("%s: the mark for the stopped resync is removed", service)


def determine(account: Account, unit: UnitStatus | None, processes: list[OnedriveProcess],
              now: datetime, progress: SyncProgress | None = None,
              resync_cancelled: bool = False) -> ServiceState:
    """The state from the table in feature 0004, "Resyncing" from feature 0009
    and "Resync stopped" from feature 0010.

    ``progress`` is the progress of the run when the main process has ``--resync``.
    ``resync_cancelled`` is true when the application has stopped a resync for the service.
    """
    if not account.service or unit is None or unit.load_state == "not-found":
        return ServiceState(NO_SERVICE)
    if not _logged_in(account):
        return ServiceState(LOGGED_OUT)
    # A process belongs to the service if it is MainPID or is in the cgroup of the service.
    if any(p.pid != unit.main_pid and p.unit != account.service for p in processes):
        return ServiceState(FOREIGN)
    if unit.exec_main_status == RESYNC_EXIT_STATUS and unit.active_state in ("failed", "inactive"):
        return ServiceState(NEEDS_RESYNC, format_since(unit.inactive_enter, now))
    # If the service is stopping, the card shows "Stopping", also if the main process still resyncs.
    if progress is not None and not progress.result and unit.active_state != "deactivating":
        return ServiceState(RESYNCING, format_since(unit.active_enter, now))
    if resync_cancelled and unit.active_state in _STOPPED_STATES:
        return ServiceState(RESYNC_CANCELLED, format_since(unit.inactive_enter, now))
    key = _BY_ACTIVE_STATE.get(unit.active_state, STOPPED)
    if key == RUNNING:
        since = format_since(unit.active_enter, now)
    elif key in (FAILED, STOPPED):
        since = format_since(unit.inactive_enter, now)
    else:
        since = ""
    return ServiceState(key, since)


def has_resync(unit: UnitStatus, proc_root: Path = PROC_ROOT) -> bool:
    """Does the main process of the service have ``--resync`` on the command line?"""
    return RESYNC_FLAG in cmdline(unit.main_pid, proc_root)


@dataclass
class _Invocation:
    invocation_id: str
    cursor: str = ""
    progress: SyncProgress = field(default_factory=SyncProgress)


class ResyncTracker:
    """The progress of the current ``--resync`` run of each service.

    The first time, the tracker reads the whole journal of the run. After that it
    reads only the lines after the last cursor. When the run has a result, it
    does not read the journal again. Two threads can call the tracker at the same time.
    """

    def __init__(self, run: Run | None = None):
        self._run = run
        self._lock = threading.Lock()
        self._invocations: dict[str, _Invocation] = {}

    def update(self, service: str, invocation_id: str) -> SyncProgress:
        """Read the new lines for the run, and return a copy of the progress."""
        with self._lock:
            current = self._invocations.get(service)
            if current is None or current.invocation_id != invocation_id:
                current = _Invocation(invocation_id)
                self._invocations[service] = current
            if not current.progress.result:
                entries, current.cursor = journal.invocation_lines(
                    service, invocation_id, current.cursor, run=self._run)
                for entry in entries:
                    if entry.identifier == journal.CLIENT_IDENTIFIER:
                        current.progress.feed(entry.message, entry.timestamp or None)
            return current.progress.snapshot()

    def invocation(self, service: str) -> str:
        with self._lock:
            current = self._invocations.get(service)
            return current.invocation_id if current is not None else ""

    def forget(self, service: str) -> None:
        with self._lock:
            self._invocations.pop(service, None)


def initial_status(account: Account) -> AccountStatus:
    """The state before the application has asked ``systemctl``."""
    if not account.service:
        return AccountStatus(ServiceState(NO_SERVICE))
    if not _logged_in(account):
        return AccountStatus(ServiceState(LOGGED_OUT))
    return AccountStatus(ServiceState(UNKNOWN))


class StatusReader:
    """Read the state for all accounts. Remembers the last known state and the error line."""

    def __init__(self, *, home: Path | None = None, run: Run | None = None,
                 proc_root: Path = PROC_ROOT, now: Callable[[], datetime] | None = None):
        self._home = home
        self._run = run
        self._proc_root = Path(proc_root)
        self._now = now or datetime.now
        self._last: dict[str, AccountStatus] = {}
        self._errors: dict[str, tuple[tuple, str]] = {}
        self._tracker = ResyncTracker(run)

    def _processes(self, account: Account) -> list[OnedriveProcess]:
        return find_processes(account.confdir, home=self._home, proc_root=self._proc_root)

    def _progress(self, account: Account, unit: UnitStatus) -> SyncProgress | None:
        if unit.main_pid <= 0 or not unit.invocation_id or not has_resync(unit, self._proc_root):
            self._tracker.forget(account.service)
            return None
        return self._tracker.update(account.service, unit.invocation_id)

    def _state_and_progress(self, account: Account,
                            units: dict[str, UnitStatus]) -> tuple[ServiceState, SyncProgress | None]:
        unit = units.get(account.service) if account.service else None
        processes = self._processes(account) if unit is not None and _logged_in(account) else []
        progress = None
        cancelled = False
        if unit is not None and unit.load_state != "not-found" and _logged_in(account):
            progress = self._progress(account, unit)
            cancelled = self._resync_cancelled(account.service, unit)
        return determine(account, unit, processes, self._now(), progress, cancelled), progress

    def _resync_cancelled(self, service: str, unit: UnitStatus) -> bool:
        """Is there a mark for the service? It goes away when the service starts a new run."""
        marks = cancelled_resyncs(self._home)
        if service not in marks:
            return False
        # Same InvocationID: the output from systemctl can be from before the stop was done.
        if unit.active_state in _STARTED_STATES and unit.invocation_id != marks[service]:
            clear_resync_cancelled(service, self._home)
            return False
        return True

    def _state(self, account: Account, units: dict[str, UnitStatus]) -> ServiceState:
        return self._state_and_progress(account, units)[0]

    def _error_line(self, account: Account, state: ServiceState, unit: UnitStatus) -> str:
        if state.key not in (FAILED, NEEDS_RESYNC):
            return ""
        # The journal does not change while the service stays in the same state.
        key = (state.key, unit.inactive_enter)
        cached = self._errors.get(account.service)
        if cached is not None and cached[0] == key:
            return cached[1]
        line = journal.read_latest_error(account.service, run=self._run)
        self._errors[account.service] = (key, line)
        return line

    def read(self, accounts: list[Account]) -> dict[str, AccountStatus]:
        """The state for each account. The key is the config folder as text."""
        result: dict[str, AccountStatus] = {}
        try:
            units = read_units([a.service for a in accounts], run=self._run)
            error = ""
        except SystemctlError as exc:
            log.warning("Cannot read the status of the services: %s", exc)
            units, error = {}, str(exc)
        for account in accounts:
            key = str(account.confdir)
            if account.service and (error or account.service not in units):
                last = self._last.get(key, initial_status(account))
                result[key] = replace(last, stale=True, read_error=error)
                continue
            state, progress = self._state_and_progress(account, units)
            line = self._error_line(account, state, units[account.service]) if account.service else ""
            result[key] = AccountStatus(state, line, progress=progress)
        self._last.update({k: v for k, v in result.items() if not v.stale})
        return result

    def read_progress(self, accounts: list[Account]) -> dict[str, SyncProgress]:
        """Read the new lines for accounts that show "Resyncing". Does not call ``systemctl``."""
        result: dict[str, SyncProgress] = {}
        for account in accounts:
            key = str(account.confdir)
            last = self._last.get(key)
            if last is None or last.state.key != RESYNCING or not account.service:
                continue
            invocation = self._tracker.invocation(account.service)
            if invocation:
                result[key] = self._tracker.update(account.service, invocation)
        return result

    def read_state(self, account: Account) -> ServiceState:
        """The state for 1 account without the error line. Used while the application waits."""
        units = read_units([account.service], run=self._run)
        return self._state(account, units)
