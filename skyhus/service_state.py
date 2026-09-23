"""Servicens tilstand for hver konto (feature 0004).

Applikationen spørger ``systemctl show`` om alle konti med ét kald. Tilstanden
kommer fra egenskaberne, kontoens filer og de kørende ``onedrive``-processer.
Passer flere tilstande, vinder den første i denne rækkefølge:

1. Ingen service
2. Ikke logget ind
3. Kører uden for servicen
4. Kræver resync
5. Resynkroniserer
6. Resync afbrudt
7. Kører, Starter, Stopper, Fejlet eller Stoppet efter ``ActiveState``

"Resynkroniserer" gælder, når servicens hovedproces har ``--resync`` på
kommandolinjen, og journalen for servicens nuværende kørsel endnu ikke har en
linje, der afslutter synkroniseringen (feature 0009). ``ResyncTracker`` læser
journalen for kørslen og husker fremdriften og cursoren.

"Resync afbrudt" gælder, når applikationen selv har stoppet servicen under en
resync, og servicen stadig er stoppet (feature 0010). Markeringen står i
``~/.config/skyhus/state.json`` pr. service sammen med kørslens
``InvocationID``. Markeringen forsvinder, når servicen starter en ny kørsel.
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
"""Tilstandene, som applikationen venter på efter et klik."""

# Nøgle: (tekst, prik, handling). Handlingen er "restart", "start", "resync" eller tom.
STATES = {
    RUNNING: ("Kører", "success", "restart"),
    STARTING: ("Starter", "warning", "restart"),
    STOPPING: ("Stopper", "warning", ""),
    NEEDS_RESYNC: ("Kræver resync", "danger", "resync"),
    RESYNCING: ("Resynkroniserer", "warning", ""),
    RESYNC_CANCELLED: ("Resync afbrudt", "warning", "resync"),
    FAILED: ("Fejlet", "danger", "start"),
    STOPPED: ("Stoppet", "textSecondary", "start"),
    FOREIGN: ("Kører uden for servicen", "warning", ""),
    LOGGED_OUT: ("Ikke logget ind", "textSecondary", ""),
    NO_SERVICE: ("Ingen service", "textSecondary", ""),
    UNKNOWN: ("Henter status …", "textSecondary", ""),
}

ACTION_LABELS = {"restart": "Genstart", "start": "Start", "resync": "Genstart med resync"}

RESYNC_FLAG = "--resync"
RESULT_TEXTS = {COMPLETE: "Resync er færdig", COMPLETE_WITH_FAILURES: "Resync er færdig med fejl"}

_BY_ACTIVE_STATE = {
    "active": RUNNING,
    "reloading": RUNNING,
    "refreshing": RUNNING,
    "activating": STARTING,
    "deactivating": STOPPING,
    "failed": FAILED,
    "inactive": STOPPED,
}

MONTHS = ("jan.", "feb.", "mar.", "apr.", "maj", "jun.", "jul.", "aug.", "sep.", "okt.", "nov.", "dec.")
_TIMESTAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})")

Run = Callable[..., subprocess.CompletedProcess]
READ_ERROR = "Kan ikke læse status"

STATE_FILE = "state.json"
CANCELLED_KEY = "resync_cancelled"
_STOPPED_STATES = ("inactive", "failed")
_STARTED_STATES = ("active", "reloading", "refreshing", "activating")
# Statustråden og tråden for "Afbryd resync" kan skrive filen på samme tid.
_state_lock = threading.Lock()


@dataclass(frozen=True)
class UnitStatus:
    """Egenskaberne for 1 unit fra ``systemctl show``."""

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
    """Fx "i dag kl. 08:37". Tom, hvis tilstanden ikke har et tidspunkt."""

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
    """Den seneste fejllinje fra journalen ved "Fejlet" og "Kræver resync"."""
    stale: bool = False
    """``systemctl show`` fejlede. ``state`` er den sidste kendte tilstand."""
    read_error: str = ""
    progress: SyncProgress | None = None
    """Fremdriften, når servicens hovedproces har ``--resync``. Ellers ``None``."""

    @property
    def progress_text(self) -> str:
        """"Resync er færdig", "Resync er færdig med fejl" eller tom."""
        return RESULT_TEXTS.get(self.progress.result, "") if self.progress is not None else ""

    @property
    def message(self) -> str:
        if not self.stale:
            return ""
        return f"{READ_ERROR}: {self.read_error}" if self.read_error else f"{READ_ERROR}."


def parse_show(output: str, services: list[str]) -> dict[str, UnitStatus]:
    """Del svaret fra ``systemctl show`` op pr. unit.

    ``systemctl`` skriver en blok pr. unit i samme rækkefølge som navnene. Den
    skriver ikke felterne i den rækkefølge, som ``-p`` angiver.
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
    """Omsæt fx ``Wed 2026-09-23 08:37:12 CEST`` til lokal tid."""
    match = _TIMESTAMP.search(value or "")
    if not match:
        return None
    year, month, day, hour, minute = (int(g) for g in match.groups())
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def format_since(value: str, now: datetime) -> str:
    """"i dag kl. 08:37", "i går kl. 08:37" eller "22. sep. kl. 08:37"."""
    when = parse_timestamp(value)
    if when is None:
        return ""
    clock = f"kl. {when:%H:%M}"
    today: date = now.date()
    if when.date() == today:
        return f"i dag {clock}"
    if when.date() == today - timedelta(days=1):
        return f"i går {clock}"
    if when.year != today.year:
        return f"{when.day}. {MONTHS[when.month - 1]} {when.year} {clock}"
    return f"{when.day}. {MONTHS[when.month - 1]} {clock}"


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
        log.warning("Kan ikke læse %s: %s", path, exc)
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
    """De services, hvor applikationen har afbrudt en resync. Værdien er kørslens ``InvocationID``."""
    with _state_lock:
        marks = _read_state_file(state_path(home)).get(CANCELLED_KEY)
    if not isinstance(marks, dict):
        return {}
    return {service: str(entry.get("invocation", "")) for service, entry in marks.items()
            if isinstance(entry, dict)}


def mark_resync_cancelled(service: str, invocation: str, home: Path | None = None) -> None:
    """Husk, at applikationen har stoppet ``service`` under en resync."""
    path = state_path(home)
    with _state_lock:
        data = _read_state_file(path)
        marks = data.get(CANCELLED_KEY)
        if not isinstance(marks, dict):
            marks = {}
        marks[service] = {"invocation": invocation}
        data[CANCELLED_KEY] = marks
        _write_state_file(path, data)
    log.info("%s: resync afbrudt (kørsel %s)", service, invocation or "ukendt")


def clear_resync_cancelled(service: str, home: Path | None = None) -> None:
    """Fjern markeringen for ``service``. Gør intet, hvis der ikke er en."""
    path = state_path(home)
    with _state_lock:
        data = _read_state_file(path)
        marks = data.get(CANCELLED_KEY)
        if not isinstance(marks, dict) or service not in marks:
            return
        del marks[service]
        _write_state_file(path, data)
    log.info("%s: markeringen for afbrudt resync er fjernet", service)


def determine(account: Account, unit: UnitStatus | None, processes: list[OnedriveProcess],
              now: datetime, progress: SyncProgress | None = None,
              resync_cancelled: bool = False) -> ServiceState:
    """Tilstanden efter tabellen i feature 0004, "Resynkroniserer" fra feature 0009
    og "Resync afbrudt" fra feature 0010.

    ``progress`` er fremdriften for kørslen, når hovedprocessen har ``--resync``.
    ``resync_cancelled`` er sand, når applikationen har afbrudt en resync for servicen.
    """
    if not account.service or unit is None or unit.load_state == "not-found":
        return ServiceState(NO_SERVICE)
    if not _logged_in(account):
        return ServiceState(LOGGED_OUT)
    # En proces hører til servicen, hvis den er MainPID eller står i servicens cgroup.
    if any(p.pid != unit.main_pid and p.unit != account.service for p in processes):
        return ServiceState(FOREIGN)
    if unit.exec_main_status == RESYNC_EXIT_STATUS and unit.active_state in ("failed", "inactive"):
        return ServiceState(NEEDS_RESYNC, format_since(unit.inactive_enter, now))
    # Stopper servicen, viser kortet "Stopper", også hvis hovedprocessen stadig resynkroniserer.
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
    """Har servicens hovedproces ``--resync`` på kommandolinjen?"""
    return RESYNC_FLAG in cmdline(unit.main_pid, proc_root)


@dataclass
class _Invocation:
    invocation_id: str
    cursor: str = ""
    progress: SyncProgress = field(default_factory=SyncProgress)


class ResyncTracker:
    """Fremdriften for hver services nuværende kørsel med ``--resync``.

    Første gang læser trackeren hele kørslens journal. Derefter læser den kun
    linjerne efter den sidste cursor. Når kørslen har et resultat, læser den
    ikke journalen igen. To tråde kan kalde trackeren på samme tid.
    """

    def __init__(self, run: Run | None = None):
        self._run = run
        self._lock = threading.Lock()
        self._invocations: dict[str, _Invocation] = {}

    def update(self, service: str, invocation_id: str) -> SyncProgress:
        """Læs de nye linjer for kørslen, og giv en kopi af fremdriften."""
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
    """Tilstanden, før applikationen har spurgt ``systemctl``."""
    if not account.service:
        return AccountStatus(ServiceState(NO_SERVICE))
    if not _logged_in(account):
        return AccountStatus(ServiceState(LOGGED_OUT))
    return AccountStatus(ServiceState(UNKNOWN))


class StatusReader:
    """Læs tilstanden for alle konti. Husker den sidste kendte tilstand og fejllinjen."""

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
        """Er der en markering for servicen? Den forsvinder, når servicen starter en ny kørsel."""
        marks = cancelled_resyncs(self._home)
        if service not in marks:
            return False
        # Samme InvocationID: svaret fra systemctl kan være læst, før stoppet var færdigt.
        if unit.active_state in _STARTED_STATES and unit.invocation_id != marks[service]:
            clear_resync_cancelled(service, self._home)
            return False
        return True

    def _state(self, account: Account, units: dict[str, UnitStatus]) -> ServiceState:
        return self._state_and_progress(account, units)[0]

    def _error_line(self, account: Account, state: ServiceState, unit: UnitStatus) -> str:
        if state.key not in (FAILED, NEEDS_RESYNC):
            return ""
        # Journalen ændrer sig ikke, så længe servicen står stille i samme tilstand.
        key = (state.key, unit.inactive_enter)
        cached = self._errors.get(account.service)
        if cached is not None and cached[0] == key:
            return cached[1]
        line = journal.read_latest_error(account.service, run=self._run)
        self._errors[account.service] = (key, line)
        return line

    def read(self, accounts: list[Account]) -> dict[str, AccountStatus]:
        """Tilstanden for hver konto. Nøglen er config-mappen som tekst."""
        result: dict[str, AccountStatus] = {}
        try:
            units = read_units([a.service for a in accounts], run=self._run)
            error = ""
        except SystemctlError as exc:
            log.warning("Kan ikke læse servicernes status: %s", exc)
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
        """Læs de nye linjer for konti, der står som "Resynkroniserer". Kalder ikke ``systemctl``."""
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
        """Tilstanden for 1 konto uden fejllinje. Bruges, mens applikationen venter."""
        units = read_units([account.service], run=self._run)
        return self._state(account, units)
