"""Qt-objekter, som QML binder til. Logikken ligger i de rene moduler."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)

from . import apply as apply_mod
from . import service_control, sideeffects
from .accounts import Account, home_dir
from .config import read_skip_dir_strict, read_skip_dirs, read_sync_root_files
from .discovery import discover_accounts
from .graph import Folder, GraphClient, GraphError
from .login_flow import FlowState, LoginFlow
from .naming import NamingError, plan_new_account, suggest_sync_dir, validate_display_name
from .process import PROC_ROOT
from .progress import COMPLETE_WITH_FAILURES, SyncProgress, count_text, format_duration
from .provision import provision_account, validate_sync_dir
from .registry import Registry
from .removal import format_size, is_skipped, total_size
from .service import SystemctlError
from .service_state import RESYNCING, UNKNOWN, AccountStatus, ServiceState, StatusReader, initial_status
from .synclist import Selection, SelectionError, read_sync_list
from .theme import avatar_color, avatar_text_color, initials

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 200
SERVICE_STOPPED_NOTE = "Servicen er stoppet, mens du logger ind"
PICKER_POLL_INTERVAL_MS = 100
STATUS_INTERVAL_MS = 3000
STATUS_POLL_INTERVAL_MS = 100
CLOSE_POLL_INTERVAL_MS = 100
ACTION_TEXTS = {"start": "Starter {}", "restart": "Genstarter {}", "resync": "Genstarter {} med --resync"}
"""Teksten i arket "Applikationen lukker, når arbejdet er færdigt" for hver servicehandling."""
PROGRESS_INTERVAL_MS = 2000
"""Så ofte læser applikationen nye linjer fra journalen under "Resynkroniserer" (feature 0009)."""
STEP_STATE_TEXTS = {apply_mod.WAITING: "Venter", apply_mod.RUNNING: "I gang",
                    apply_mod.DONE: "Færdigt", apply_mod.FAILED: "Fejlet"}
NO_PROGRESS = {"visible": False}


def progress_data(status: AccountStatus, now: float) -> dict:
    """Fremdriften for kortet "Service" som et map til QML (feature 0009)."""
    progress = status.progress
    active = status.state.key == RESYNCING
    if progress is None or not (active or progress.result):
        return dict(NO_PROGRESS)
    elapsed = ""
    if progress.started is not None:
        end = progress.finished if progress.finished is not None else now
        elapsed = format_duration(end - progress.started)
    latest = progress.latest
    if latest and progress.percent is not None:
        latest = f"{latest} · {progress.percent} %"
    if progress.result == COMPLETE_WITH_FAILURES:
        detail = f"{progress.failed} {'element' if progress.failed == 1 else 'elementer'} fejlede"
    else:
        detail = ""
    if progress.result and elapsed:
        detail = f"{detail} · varede {elapsed}" if detail else f"Varede {elapsed}"
    return {
        "visible": True,
        "active": active,
        "phase": progress.phase or "Starter resync",
        "counter": count_text(progress.done, progress.total) if progress.done or progress.total is not None else "",
        "determinate": progress.determinate,
        "value": progress.fraction,
        "latest": latest,
        "elapsed": f"Tid siden start: {elapsed}" if elapsed and not progress.result else "",
        "result": progress.result,
        "resultText": status.progress_text,
        "resultDetail": detail,
    }


def step_data(step: int, state: str, progress: SyncProgress | None) -> dict:
    """1 trin i arket "Ændrer mappevalg" som et map til QML (feature 0009)."""
    detail = latest = ""
    determinate, value = False, 0.0
    if progress is not None and state != apply_mod.WAITING:
        if step == apply_mod.TRASH:
            detail = count_text(progress.done, progress.total, "sti", "stier") if progress.total else "Ingen stier"
        else:
            detail = count_text(progress.done, progress.total)
        latest = progress.latest
        determinate, value = progress.determinate, progress.fraction
    return {
        "step": step,
        "title": apply_mod.STEPS[step],
        "state": state,
        "stateText": STEP_STATE_TEXTS[state],
        "detail": detail,
        "latest": latest,
        "showBar": state == apply_mod.RUNNING and step in (apply_mod.UPLOAD, apply_mod.TRASH),
        "determinate": determinate,
        "value": value,
    }


class AccountListModel(QAbstractListModel):
    NameRole = Qt.UserRole + 1
    ConfdirRole = Qt.UserRole + 2
    SyncDirRole = Qt.UserRole + 3
    ServiceRole = Qt.UserRole + 4
    LoggedInRole = Qt.UserRole + 5
    InitialsRole = Qt.UserRole + 6
    AvatarColorRole = Qt.UserRole + 7
    AvatarTextColorRole = Qt.UserRole + 8
    ServiceStateRole = Qt.UserRole + 9
    ServiceLabelRole = Qt.UserRole + 10
    ServiceToneRole = Qt.UserRole + 11
    ServiceSinceRole = Qt.UserRole + 12
    ServiceActionLabelRole = Qt.UserRole + 13
    ServiceErrorRole = Qt.UserRole + 14
    ServiceBusyRole = Qt.UserRole + 15
    ServiceMessageRole = Qt.UserRole + 16
    ServiceActionRole = Qt.UserRole + 17
    ServiceProgressRole = Qt.UserRole + 18

    SERVICE_ROLES = [ServiceStateRole, ServiceLabelRole, ServiceToneRole, ServiceSinceRole,
                     ServiceActionLabelRole, ServiceErrorRole, ServiceBusyRole, ServiceMessageRole,
                     ServiceActionRole, ServiceProgressRole]

    countChanged = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._accounts: list[Account] = []
        self._status: dict[str, AccountStatus] = {}
        self._busy: set[str] = set()
        self._messages: dict[str, str] = {}
        self.now = time.time

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._accounts)

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.NameRole: QByteArray(b"name"),
            self.ConfdirRole: QByteArray(b"confdir"),
            self.SyncDirRole: QByteArray(b"syncDir"),
            self.ServiceRole: QByteArray(b"service"),
            self.LoggedInRole: QByteArray(b"loggedIn"),
            self.InitialsRole: QByteArray(b"initials"),
            self.AvatarColorRole: QByteArray(b"avatarColor"),
            self.AvatarTextColorRole: QByteArray(b"avatarTextColor"),
            self.ServiceStateRole: QByteArray(b"serviceState"),
            self.ServiceLabelRole: QByteArray(b"serviceLabel"),
            self.ServiceToneRole: QByteArray(b"serviceTone"),
            self.ServiceSinceRole: QByteArray(b"serviceSince"),
            self.ServiceActionLabelRole: QByteArray(b"serviceActionLabel"),
            self.ServiceErrorRole: QByteArray(b"serviceError"),
            self.ServiceBusyRole: QByteArray(b"serviceBusy"),
            self.ServiceMessageRole: QByteArray(b"serviceMessage"),
            self.ServiceActionRole: QByteArray(b"serviceAction"),
            self.ServiceProgressRole: QByteArray(b"serviceProgress"),
        }

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._accounts):
            return None
        account = self._accounts[index.row()]
        if role in (self.NameRole, Qt.DisplayRole):
            return account.name
        if role == self.ConfdirRole:
            return str(account.confdir)
        if role == self.SyncDirRole:
            return account.sync_dir
        if role == self.ServiceRole:
            return account.service
        if role == self.LoggedInRole:
            return account.logged_in
        if role == self.InitialsRole:
            return initials(account.name)
        if role == self.AvatarColorRole:
            return avatar_color(account)
        if role == self.AvatarTextColorRole:
            return avatar_text_color(account)
        if role in self.SERVICE_ROLES:
            return self._service_data(account, role)
        return None

    def _service_data(self, account: Account, role: int):
        key = str(account.confdir)
        status = self.status(key)
        state = status.state
        if role == self.ServiceStateRole:
            return state.key
        if role == self.ServiceLabelRole:
            return state.label
        if role == self.ServiceToneRole:
            return state.tone
        if role == self.ServiceSinceRole:
            return state.since
        if role == self.ServiceActionLabelRole:
            return state.action_label
        if role == self.ServiceActionRole:
            return state.action
        if role == self.ServiceErrorRole:
            return status.error_line
        if role == self.ServiceBusyRole:
            return key in self._busy
        if role == self.ServiceMessageRole:
            return self._messages.get(key) or status.message
        if role == self.ServiceProgressRole:
            return progress_data(status, self.now())
        return None

    def status(self, confdir: str) -> AccountStatus:
        """Den sidst læste tilstand for kontoen."""
        status = self._status.get(confdir)
        if status is not None:
            return status
        account = next((a for a in self._accounts if str(a.confdir) == confdir), None)
        return initial_status(account) if account else AccountStatus(ServiceState(UNKNOWN))

    def set_statuses(self, statuses: dict[str, AccountStatus]) -> None:
        self._status.update(statuses)
        self._service_changed(statuses.keys())

    def set_progress(self, progress: dict[str, SyncProgress]) -> None:
        """Ny fremdrift for konti under "Resynkroniserer". Tilstanden ændrer sig ikke."""
        for confdir, value in progress.items():
            status = self._status.get(confdir)
            if status is not None:
                self._status[confdir] = replace(status, progress=value)
        self._service_changed(progress.keys())

    def resyncing(self) -> list[Account]:
        return [a for a in self._accounts if self.status(str(a.confdir)).state.key == RESYNCING]

    def set_busy(self, confdir: str, busy: bool) -> None:
        if busy:
            self._busy.add(confdir)
        else:
            self._busy.discard(confdir)
        self._service_changed([confdir])

    def is_busy(self, confdir: str) -> bool:
        return confdir in self._busy

    def set_service_message(self, confdir: str, message: str) -> None:
        if message:
            self._messages[confdir] = message
        else:
            self._messages.pop(confdir, None)
        self._service_changed([confdir])

    def _service_changed(self, confdirs) -> None:
        wanted = set(confdirs)
        for row, account in enumerate(self._accounts):
            if str(account.confdir) in wanted:
                index = self.index(row)
                self.dataChanged.emit(index, index, self.SERVICE_ROLES)

    def accounts(self) -> list[Account]:
        return list(self._accounts)

    def set_accounts(self, accounts: list[Account]) -> None:
        self.beginResetModel()
        self._accounts = list(accounts)
        self.endResetModel()
        self.countChanged.emit()

    def _count(self) -> int:
        return len(self._accounts)

    count = Property(int, _count, notify=countChanged)


class _Job:
    """Kør en funktion i en tråd. ``poll`` i brugerfladen henter resultatet."""

    def __init__(self, kind: str, fn, *args, **kwargs):
        self.kind = kind
        self.key = kwargs.pop("_key", "")
        self.result = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(fn, args, kwargs), daemon=True)
        self._thread.start()

    def _run(self, fn, args, kwargs) -> None:
        try:
            self.result = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - fejlen vises for brugeren
            self.error = exc

    @property
    def done(self) -> bool:
        return not self._thread.is_alive()


class FolderTreeModel(QAbstractListModel):
    """Træet i mappevælgeren som en flad liste. ``depth`` giver indrykningen."""

    NameRole = Qt.UserRole + 1
    PathRole = Qt.UserRole + 2
    DepthRole = Qt.UserRole + 3
    CheckStateRole = Qt.UserRole + 4
    HasChildrenRole = Qt.UserRole + 5
    ExpandedRole = Qt.UserRole + 6
    LoadingRole = Qt.UserRole + 7
    AvailableRole = Qt.UserRole + 8

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._children: dict[str, list[Folder]] = {}
        self.selection = Selection()
        self.skip_dirs: list[str] = []
        self.skip_strict = False

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.NameRole: QByteArray(b"name"),
            self.PathRole: QByteArray(b"path"),
            self.DepthRole: QByteArray(b"depth"),
            self.CheckStateRole: QByteArray(b"checkState"),
            self.HasChildrenRole: QByteArray(b"hasChildren"),
            self.ExpandedRole: QByteArray(b"expanded"),
            self.LoadingRole: QByteArray(b"loading"),
            self.AvailableRole: QByteArray(b"available"),
        }

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        folder: Folder = row["folder"]
        if role in (self.NameRole, Qt.DisplayRole):
            return folder.name
        if role == self.PathRole:
            return folder.path
        if role == self.DepthRole:
            return row["depth"]
        if role == self.CheckStateRole:
            return int(self.selection.state(folder.path))
        if role == self.HasChildrenRole:
            return folder.has_children
        if role == self.ExpandedRole:
            return row["expanded"]
        if role == self.LoadingRole:
            return row["loading"]
        if role == self.AvailableRole:
            return self.is_available(folder.path)
        return None

    def reset(self, selection: Selection, skip_dirs: list[str], skip_strict: bool) -> None:
        self.beginResetModel()
        self._rows = []
        self._children = {}
        self.selection = selection
        self.skip_dirs = skip_dirs
        self.skip_strict = skip_strict
        self.endResetModel()

    def is_available(self, path: str) -> bool:
        parts = path.split("/")
        return not any(is_skipped("/".join(parts[:i]), self.skip_dirs, self.skip_strict)
                       for i in range(1, len(parts) + 1))

    def row(self, row: int) -> dict | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def children_paths(self, path: str) -> list[str] | None:
        folders = self._children.get(path)
        return None if folders is None else [f.path for f in folders]

    def has_loaded(self, path: str) -> bool:
        return path in self._children

    def set_children(self, parent_path: str, folders: list[Folder]) -> None:
        """Gem undermapperne og vis dem, hvis overmappen er foldet ud."""
        self._children[parent_path] = list(folders)
        if parent_path == "":
            self.beginResetModel()
            self._rows = [self._new_row(f, 0) for f in folders]
            self.endResetModel()
            return
        index = self._index_of(parent_path)
        if index is None:
            return
        parent = self._rows[index]
        parent["loading"] = False
        self._changed(index)
        if parent["expanded"]:
            self._insert_children(index)

    def set_loading(self, row: int, loading: bool) -> None:
        self._rows[row]["loading"] = loading
        self._changed(row)

    def expand(self, row: int) -> None:
        node = self._rows[row]
        node["expanded"] = True
        self._changed(row)
        if node["folder"].path in self._children:
            self._insert_children(row)

    def collapse(self, row: int) -> None:
        node = self._rows[row]
        node["expanded"] = False
        self._changed(row)
        end = row + 1
        while end < len(self._rows) and self._rows[end]["depth"] > node["depth"]:
            end += 1
        if end > row + 1:
            self.beginRemoveRows(QModelIndex(), row + 1, end - 1)
            del self._rows[row + 1:end]
            self.endRemoveRows()

    def checks_changed(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1), [self.CheckStateRole])

    def _new_row(self, folder: Folder, depth: int) -> dict:
        return {"folder": folder, "depth": depth, "expanded": False, "loading": False}

    def _index_of(self, path: str) -> int | None:
        for i, row in enumerate(self._rows):
            if row["folder"].path == path:
                return i
        return None

    def _insert_children(self, row: int) -> None:
        node = self._rows[row]
        folders = self._children.get(node["folder"].path, [])
        if not folders or (row + 1 < len(self._rows) and self._rows[row + 1]["depth"] > node["depth"]):
            return
        self.beginInsertRows(QModelIndex(), row + 1, row + len(folders))
        self._rows[row + 1:row + 1] = [self._new_row(f, node["depth"] + 1) for f in folders]
        self.endInsertRows()

    def _changed(self, row: int) -> None:
        index = self.index(row)
        self.dataChanged.emit(index, index)


class AppController(QObject):
    loginChanged = Signal()
    messageChanged = Signal()
    pickerChanged = Signal()
    resyncChanged = Signal()
    closeChanged = Signal()
    closeReady = Signal()
    """Vinduet må lukke nu (feature 0008). QML kalder ``close()`` igen."""
    applyChanged = Signal()

    def __init__(self, home: Path | None = None, parent: QObject | None = None, *,
                 popen=None, run=None, opener=None, trash=None, proc_root: Path = PROC_ROOT,
                 clock=None, sleep=None):
        super().__init__(parent)
        self._home = home
        self._popen = popen or sideeffects.popen
        self._run = run or sideeffects.run
        self._opener = opener
        self._trash = trash or sideeffects.trash
        self._proc_root = Path(proc_root)
        self._registry = Registry.for_home(home)
        self._model = AccountListModel(self)
        self._flow: LoginFlow | None = None
        self._login_state = "idle"
        self._login_snapshot = ("idle", "", "", "")
        self._service_thread: threading.Thread | None = None
        self._message = ""
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._folders = FolderTreeModel(self)
        self._picker_state = "closed"
        self._picker_error = ""
        self._picker_account: Account | None = None
        self._picker_for_login = False
        self._folders_chosen = False
        self._graph: GraphClient | None = None
        self._jobs: list[_Job] = []
        self._sync_all = False
        self._sync_root_files = False
        self._unknown_rules = False
        self._change: apply_mod.Change | None = None
        self._picker_timer = QTimer(self)
        self._picker_timer.setInterval(PICKER_POLL_INTERVAL_MS)
        self._picker_timer.timeout.connect(self._poll_picker)
        # Servicestatus (feature 0004). Timeren kører kun, mens vinduet er synligt.
        self._clock = clock
        self._sleep = sleep
        self._status_reader = StatusReader(home=home, run=self._run, proc_root=self._proc_root)
        self._status_job: _Job | None = None
        self._status_again = False
        self._action_jobs: dict[str, _Job] = {}
        self._resync_confdir = ""
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(STATUS_INTERVAL_MS)
        self._status_timer.timeout.connect(self.refreshStatus)
        self._status_poll_timer = QTimer(self)
        self._status_poll_timer.setInterval(STATUS_POLL_INTERVAL_MS)
        self._status_poll_timer.timeout.connect(self._poll_status)
        # Fremdrift under "Resynkroniserer" (feature 0009). Timeren kører kun, mens vinduet er synligt.
        self._progress_job: _Job | None = None
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(PROGRESS_INTERVAL_MS)
        self._progress_timer.timeout.connect(self.refreshProgress)
        # Arket "Ændrer mappevalg" (feature 0009). _Job-tråden skriver trinnene under låsen.
        self._apply_state = ""
        self._apply_lock = threading.Lock()
        self._apply_steps: dict[int, tuple[str, SyncProgress | None]] = {}
        self._apply_version = 0
        self._apply_seen = 0
        # Luk under arbejde (feature 0008). Nøglen er tråden eller _Job-objektet.
        self._critical_jobs: dict[object, str] = {}
        self._closing = False
        self._close_allowed = False
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(CLOSE_POLL_INTERVAL_MS)
        self._close_timer.timeout.connect(self._poll_close)
        self.refresh()

    # Egenskaber til QML

    def _get_accounts(self) -> AccountListModel:
        return self._model

    accounts = Property(QObject, _get_accounts, constant=True)

    def _get_login_state(self) -> str:
        return self._login_state

    loginState = Property(str, _get_login_state, notify=loginChanged)

    def _get_auth_url(self) -> str:
        return self._flow.auth_url if self._flow else ""

    authUrl = Property(str, _get_auth_url, notify=loginChanged)

    def _get_login_name(self) -> str:
        return self._flow.name if self._flow else ""

    loginAccountName = Property(str, _get_login_name, notify=loginChanged)

    def _get_login_note(self) -> str:
        return SERVICE_STOPPED_NOTE if self._flow is not None and self._flow.service_stopped else ""

    loginNote = Property(str, _get_login_note, notify=loginChanged)
    """Teksten i login-arket, når flowet har stoppet kontoens service (feature 0005)."""

    def _get_message(self) -> str:
        return self._message

    message = Property(str, _get_message, notify=messageChanged)

    # Mappevælgeren

    def _get_folders(self) -> FolderTreeModel:
        return self._folders

    folders = Property(QObject, _get_folders, constant=True)

    def _get_picker_state(self) -> str:
        return self._picker_state

    pickerState = Property(str, _get_picker_state, notify=pickerChanged)
    """``closed``, ``loading``, ``open``, ``checking``, ``confirm`` eller ``applying``."""

    def _get_picker_error(self) -> str:
        return self._picker_error

    pickerError = Property(str, _get_picker_error, notify=pickerChanged)

    def _get_picker_name(self) -> str:
        return self._picker_account.name if self._picker_account else ""

    pickerAccountName = Property(str, _get_picker_name, notify=pickerChanged)

    def _get_sync_all(self) -> bool:
        return self._sync_all

    syncAll = Property(bool, _get_sync_all, notify=pickerChanged)

    def _get_sync_root_files(self) -> bool:
        return self._sync_root_files

    syncRootFiles = Property(bool, _get_sync_root_files, notify=pickerChanged)

    def _get_unknown_rules(self) -> bool:
        return self._unknown_rules

    pickerUnknownRules = Property(bool, _get_unknown_rules, notify=pickerChanged)

    def _get_removal_items(self) -> list:
        return [str(r.path) for r in self._change.removed] if self._change else []

    removalItems = Property("QVariantList", _get_removal_items, notify=pickerChanged)

    def _get_removal_size(self) -> str:
        return format_size(total_size(self._change.removed)) if self._change else ""

    removalSize = Property(str, _get_removal_size, notify=pickerChanged)

    # Servicestatus

    def _get_resync_name(self) -> str:
        account = self._find_account(self._resync_confdir) if self._resync_confdir else None
        return account.name if account else ""

    resyncAccountName = Property(str, _get_resync_name, notify=resyncChanged)
    """Navnet på kontoen, som venter på bekræftelsen af "Genstart med resync", eller tom."""

    # Arket "Ændrer mappevalg"

    def _get_apply_state(self) -> str:
        return self._apply_state

    applyState = Property(str, _get_apply_state, notify=applyChanged)
    """Tom, ``running`` eller ``failed``. Arket er synligt, når værdien ikke er tom."""

    def _get_apply_steps(self) -> list:
        with self._apply_lock:
            steps = dict(self._apply_steps)
        return [step_data(step, *steps[step]) for step in apply_mod.STEPS if step in steps]

    applySteps = Property("QVariantList", _get_apply_steps, notify=applyChanged)
    """De 5 trin med titel, tilstand, antal og seneste fil."""

    # Luk under arbejde

    def _get_busy_text(self) -> str:
        return "\n".join(self._critical_jobs.values())

    busyText = Property(str, _get_busy_text, notify=closeChanged)
    """Handlingerne, der kan stoppe eller starte en service, og som kører nu. 1 per linje."""

    def _get_closing(self) -> bool:
        return self._closing

    closing = Property(bool, _get_closing, notify=closeChanged)
    """Brugeren har lukket vinduet, og applikationen venter på handlingerne i ``busyText``."""

    # Handlinger fra QML

    @Slot()
    def refresh(self) -> None:
        self._registry.load()
        self._model.set_accounts(discover_accounts(self._home, self._registry))

    @Slot(str, result=str)
    def suggestSyncDir(self, name: str) -> str:
        return suggest_sync_dir(name)

    @Slot(QUrl, result=str)
    def folderToSyncDir(self, url: QUrl) -> str:
        path = url.toLocalFile() if url.isLocalFile() else url.toString()
        home = str(home_dir(self._home))
        if path == home or path.startswith(home + os.sep):
            return "~" + path[len(home):]
        return path

    @Slot(str, str, result=str)
    def rename(self, confdir: str, name: str) -> str:
        try:
            clean = validate_display_name(name, self._model.accounts(), exclude=Path(confdir))
            self._registry.set_name(Path(confdir), clean)
        except NamingError as exc:
            return str(exc)
        except OSError as exc:
            return f"Kan ikke gemme navnet: {exc}"
        self.refresh()
        return ""

    @Slot(str, str, result=str)
    def addAccount(self, name: str, sync_dir: str) -> str:
        """Opret kontoen og start login. Returnerer en fejlbesked eller tom."""
        if self._flow is not None:
            return "Et andet login er i gang."
        try:
            new = plan_new_account(name, self._model.accounts(), self._home)
            validate_sync_dir(sync_dir)
            provision_account(new.confdir, sync_dir.strip())
            self._registry.add(new.confdir, new.name)
        except (NamingError, ValueError) as exc:
            return str(exc)
        except OSError as exc:
            return f"Kan ikke oprette kontoen: {exc}"
        self.refresh()
        self._start_login(new.confdir, new.name, "")
        return ""

    @Slot(str)
    def login(self, confdir: str) -> None:
        if self._flow is not None:
            return
        for account in self._model.accounts():
            if str(account.confdir) == confdir:
                self._start_login(account.confdir, account.name, account.service)
                return

    @Slot(str, result=bool)
    def submitRedirect(self, url: str) -> bool:
        if self._flow is None:
            return False
        handled = self._flow.submit_redirect(url)
        self._poll()
        return handled

    @Slot()
    def cancelLogin(self) -> None:
        if self._flow is None:
            return
        self._flow.cancel()
        if self._flow.cancel_requested and self._service_thread is not None:
            # Tråden stopper servicen. _poll afslutter flowet, når tråden er færdig.
            self._set_login_state("cancelling")
            return
        self._poll()

    @Slot()
    def clearMessage(self) -> None:
        self._set_message("")

    @Slot(str)
    def openFolderPicker(self, confdir: str) -> None:
        if self._picker_state != "closed" or self._flow is not None:
            return
        account = self._find_account(confdir)
        if account is None:
            return
        self._open_picker(account)

    @Slot(int)
    def toggleFolder(self, row: int) -> None:
        node = self._folders.row(row)
        if node is None or self._picker_state != "open":
            return
        path = node["folder"].path
        if not self._folders.is_available(path):
            return
        try:
            self._folders.selection.toggle(path, self._folders.children_paths)
        except SelectionError as exc:
            self._set_picker(error=str(exc))
            return
        self._folders.checks_changed()
        self._set_picker(error="")

    @Slot(int)
    def expandFolder(self, row: int) -> None:
        node = self._folders.row(row)
        if node is None or self._graph is None:
            return
        if node["expanded"]:
            self._folders.collapse(row)
            return
        folder = node["folder"]
        self._folders.expand(row)
        if not self._folders.has_loaded(folder.path) and not node["loading"]:
            self._folders.set_loading(row, True)
            self._start_job("children", self._graph.list_folders, folder.id, folder.path, _key=folder.path)

    @Slot(bool)
    def setSyncAll(self, value: bool) -> None:
        self._sync_all = bool(value)
        self._set_picker(error="")
        self.pickerChanged.emit()

    @Slot(bool)
    def setSyncRootFiles(self, value: bool) -> None:
        self._sync_root_files = bool(value)
        self.pickerChanged.emit()

    @Slot()
    def acceptPicker(self) -> None:
        account = self._picker_account
        if self._picker_state != "open" or account is None:
            return
        folders = self._folders.selection.paths
        if not self._sync_all and not folders:
            self._set_picker(error="Vælg mindst 1 mappe, eller vælg \"Synkroniser alle mapper\".")
            return
        self._set_picker(state="checking", error="")
        self._start_job("prepare", apply_mod.prepare, account, sync_all=self._sync_all,
                        folders=folders, root_files=self._sync_root_files,
                        home=self._home, proc_root=self._proc_root)

    @Slot()
    def confirmRemoval(self) -> None:
        if self._picker_state == "confirm" and self._change is not None:
            self._execute_change()

    @Slot()
    def cancelRemoval(self) -> None:
        if self._picker_state == "confirm":
            self._change = None
            self._set_picker(state="open")

    @Slot()
    def closePicker(self) -> None:
        if self._picker_state in ("closed", "checking", "applying"):
            return
        for_login = self._picker_for_login
        self._close_picker()
        if for_login and self._flow is not None:
            flow = self._flow
            self._set_message(f"{flow.name} er logget ind. Servicen er ikke startet, "
                              "fordi der ikke er valgt mapper.")
            self._end_login()

    @Slot(bool)
    def setWindowVisible(self, visible: bool) -> None:
        """Timeren kører, mens vinduet er synligt, og stopper, når det er minimeret."""
        if visible and not self._status_timer.isActive():
            self._status_timer.start()
            self._progress_timer.start()
            self.refreshStatus()
        elif not visible:
            self._status_timer.stop()
            self._progress_timer.stop()

    @Slot()
    def refreshStatus(self) -> None:
        """Læs tilstanden for alle konti i en tråd."""
        if self._status_job is not None:
            self._status_again = True
            return
        self._status_job = _Job("status", self._status_reader.read, self._model.accounts())
        self._status_poll_timer.start()

    @Slot()
    def refreshProgress(self) -> None:
        """Læs nye linjer fra journalen for konti under "Resynkroniserer" i en tråd."""
        if self._progress_job is not None:
            return
        accounts = self._model.resyncing()
        if not accounts:
            return
        self._progress_job = _Job("progress", self._status_reader.read_progress, accounts)
        self._status_poll_timer.start()

    @Slot()
    def closeApplyProgress(self) -> None:
        """Knappen "Luk" i arket "Ændrer mappevalg", når et trin er fejlet."""
        if self._apply_state == "failed":
            self._set_apply_state("")

    @Slot(str)
    def serviceAction(self, confdir: str) -> None:
        """Knappen i kortet "Service". "Genstart med resync" venter på en bekræftelse."""
        if self._model.is_busy(confdir) or self._resync_confdir:
            return
        account = self._find_account(confdir)
        if account is None or not account.service:
            return
        action = self._model.status(confdir).state.action
        if action == "resync":
            self._resync_confdir = confdir
            self.resyncChanged.emit()
        elif action:
            self._start_action(account, action)

    @Slot()
    def confirmResync(self) -> None:
        confdir = self._resync_confdir
        if not confdir:
            return
        self._resync_confdir = ""
        self.resyncChanged.emit()
        account = self._find_account(confdir)
        if account is not None and account.service and not self._model.is_busy(confdir):
            self._start_action(account, "resync")

    @Slot()
    def cancelResync(self) -> None:
        if self._resync_confdir:
            self._resync_confdir = ""
            self.resyncChanged.emit()

    @Slot(result=bool)
    def requestClose(self) -> bool:
        """Svar sandt, hvis vinduet må lukke. Ellers vent på handlingerne og send ``closeReady``."""
        if self._close_allowed or not self._critical_jobs:
            return True
        if not self._closing:
            log.info("Vinduet lukker, når dette er færdigt: %s", "; ".join(self._critical_jobs.values()))
            self._closing = True
            self.closeChanged.emit()
        self._close_timer.start()
        return False

    @Slot()
    def forceClose(self) -> None:
        """Knappen "Luk alligevel". Handlingerne kører videre, indtil processen slutter."""
        if self._critical_jobs:
            log.warning("Vinduet lukker, mens disse handlinger kører. Servicen kan blive stående "
                        "stoppet: %s", "; ".join(self._critical_jobs.values()))
        self._allow_close()

    # Intern styring

    def _begin_critical(self, key: object, text: str) -> None:
        """Registrér en handling, der kan stoppe eller starte en service."""
        self._critical_jobs[key] = text
        self.closeChanged.emit()

    def _end_critical(self, key: object) -> None:
        if self._critical_jobs.pop(key, None) is not None:
            self.closeChanged.emit()

    def _poll_close(self) -> None:
        if self._closing and not self._critical_jobs:
            self._allow_close()

    def _allow_close(self) -> None:
        self._close_timer.stop()
        self._close_allowed = True
        self.closeReady.emit()

    def _start_action(self, account: Account, action: str) -> None:
        confdir = str(account.confdir)
        self._model.set_service_message(confdir, "")
        self._model.set_busy(confdir, True)

        def read_state() -> str:
            return self._status_reader.read_state(account).key

        job = _Job("action", service_control.perform, action, account.service, read_state,
                   home=self._home, run=self._run, clock=self._clock, sleep=self._sleep)
        self._action_jobs[confdir] = job
        self._begin_critical(job, ACTION_TEXTS[action].format(account.service))
        self._status_poll_timer.start()

    def _poll_status(self) -> None:
        job = self._status_job
        if job is not None and job.done:
            self._status_job = None
            if job.error is not None:
                log.error("Uventet fejl, da applikationen læste status", exc_info=job.error)
            else:
                self._model.set_statuses(job.result)
            if self._status_again:
                self._status_again = False
                self.refreshStatus()
        progress_job = self._progress_job
        if progress_job is not None and progress_job.done:
            self._progress_job = None
            if progress_job.error is not None:
                log.error("Uventet fejl, da applikationen læste fremdriften", exc_info=progress_job.error)
            else:
                self._model.set_progress(progress_job.result)
                if any(p.result for p in progress_job.result.values()):
                    # Resync er færdig. Tilstanden skifter fra "Resynkroniserer" til "Kører".
                    self.refreshStatus()
        for confdir, action in list(self._action_jobs.items()):
            if not action.done:
                continue
            del self._action_jobs[confdir]
            self._end_critical(action)
            self._model.set_busy(confdir, False)
            if action.error is not None:
                self._model.set_service_message(confdir, self._action_error_text(action.error))
            self.refreshStatus()
        if self._status_job is None and self._progress_job is None and not self._action_jobs:
            self._status_poll_timer.stop()

    @staticmethod
    def _action_error_text(error: BaseException) -> str:
        if isinstance(error, (SystemctlError, OSError)):
            return str(error)
        log.error("Uventet fejl i en servicehandling", exc_info=error)
        return f"Uventet fejl: {error}"

    def _find_account(self, confdir: str) -> Account | None:
        for account in self._model.accounts():
            if str(account.confdir) == confdir:
                return account
        return None

    def _open_picker(self, account: Account, *, for_login: bool = False) -> None:
        if not (account.confdir / "refresh_token").is_file():
            self._set_message(f"{account.name}: Kontoen er ikke logget ind.")
            return
        current = read_sync_list(account.confdir)
        self._folders.reset(Selection(current.folders),
                            read_skip_dirs(account.confdir), read_skip_dir_strict(account.confdir))
        self._picker_account = account
        self._picker_for_login = for_login
        self._sync_all = not current.exists
        self._sync_root_files = read_sync_root_files(account.confdir)
        self._unknown_rules = any(line.strip() for line in current.unknown)
        self._change = None
        self._jobs = []
        self._graph = GraphClient(account.confdir, opener=self._opener)
        self._set_picker(state="loading", error="")
        self._start_job("children", self._graph.list_folders, _key="")

    def _close_picker(self) -> None:
        self._jobs = []
        self._picker_timer.stop()
        self._graph = None
        self._change = None
        self._picker_account = None
        self._picker_for_login = False
        self._set_apply_state("")
        self._set_picker(state="closed", error="")

    def _start_job(self, kind: str, fn, *args, **kwargs) -> None:
        self._jobs.append(_Job(kind, fn, *args, **kwargs))
        self._picker_timer.start()

    def _execute_change(self) -> None:
        change = self._change
        self._set_picker(state="applying", error="")
        if change.synced:
            with self._apply_lock:
                self._apply_steps = {step: (apply_mod.WAITING, None) for step in apply_mod.STEPS}
                self._apply_version += 1
            self._set_apply_state("running")
        self._start_job("execute", apply_mod.execute, change, home=self._home,
                        run=self._run, popen=self._popen, trash=self._trash, proc_root=self._proc_root,
                        on_step=self._on_apply_step if change.synced else None)
        if change.synced:
            text = f"Gemmer mappevalget for {change.account.name} og genstarter {change.account.service}"
        else:
            text = f"Gemmer mappevalget for {change.account.name}"
        self._begin_critical(self._jobs[-1], text)

    def _on_apply_step(self, step: int, state: str, progress: SyncProgress | None) -> None:
        """Kaldes fra _Job-tråden. Sender ikke Qt-signaler. ``_poll_picker`` gør det."""
        with self._apply_lock:
            self._apply_steps[step] = (state, progress)
            self._apply_version += 1

    def _set_apply_state(self, state: str) -> None:
        if state != self._apply_state:
            self._apply_state = state
            self.applyChanged.emit()

    def _poll_picker(self) -> None:
        # Find de færdige jobs først. Så er deres sidste trin med i versionen herunder.
        finished = [j for j in self._jobs if j.done]
        with self._apply_lock:
            version = self._apply_version
        if version != self._apply_seen:
            self._apply_seen = version
            self.applyChanged.emit()
        for job in finished:
            self._jobs.remove(job)
            self._end_critical(job)
            self._finish_job(job)
        if not self._jobs:
            self._picker_timer.stop()

    def _finish_job(self, job: _Job) -> None:
        error = job.error
        if job.kind == "children":
            if error is not None:
                if job.key:
                    index = self._folders._index_of(job.key)
                    if index is not None:
                        self._folders.set_loading(index, False)
                self._set_picker(state="open", error=self._error_text(error))
                return
            self._folders.set_children(job.key, job.result)
            if job.key == "":
                self._set_picker(state="open")
        elif job.kind == "prepare":
            if error is not None:
                self._set_picker(state="open", error=self._error_text(error))
                return
            self._change = job.result
            if self._change.removed:
                self._set_picker(state="confirm")
            else:
                self._execute_change()
        elif job.kind == "execute":
            if error is not None:
                self._change = None
                if self._apply_state == "running":
                    # Arket bliver stående med det fejlede trin, til brugeren klikker "Luk".
                    self._set_apply_state("failed")
                self._set_picker(state="open", error=self._error_text(error))
                return
            self._finish_change(job.result)

    def _finish_change(self, result: apply_mod.Result) -> None:
        account = self._picker_account
        for_login = self._picker_for_login
        self._close_picker()
        lines = []
        if result.trash_failures:
            lines.append("Disse stier kunne ikke flyttes til papirkurven:")
            lines.extend(str(p) for p in result.trash_failures)
        if for_login:
            self._folders_chosen = True
            if lines:
                self._set_message("\n".join(lines))
            self._timer.start()
            self._poll()
            return
        if result.resynced:
            lines.insert(0, f"Mappevalget for {account.name} er gemt. {account.service} "
                            "synkroniserer nu med --resync. Det kan tage lang tid.")
        else:
            lines.insert(0, f"Mappevalget for {account.name} er gemt.")
        self._set_message("\n".join(lines))

    @staticmethod
    def _error_text(error: BaseException) -> str:
        if isinstance(error, (GraphError, apply_mod.ApplyError, SelectionError)):
            return str(error)
        log.exception("Uventet fejl i mappevælgeren", exc_info=error)
        return f"Uventet fejl: {error}"

    def _set_picker(self, *, state: str | None = None, error: str | None = None) -> None:
        changed = False
        if state is not None and state != self._picker_state:
            self._picker_state = state
            changed = True
        if error is not None and error != self._picker_error:
            self._picker_error = error
            changed = True
        if changed:
            self.pickerChanged.emit()

    def _start_login(self, confdir: Path, name: str, service: str) -> None:
        self._folders_chosen = False
        self._flow = LoginFlow(confdir, name, service, registry=self._registry, home=self._home,
                               popen=self._popen, run=self._run, proc_root=self._proc_root)
        if self._flow.reauth:
            # Flowet stopper måske servicen først. Det kan tage op til 90 sekunder.
            text = f"Stopper {service} før login" if service else f"Starter login for {name}"
            self._start_service_thread(self._flow.start, text)
            self._set_login_state("starting")
        else:
            self._flow.start()
        self._timer.start()
        self._poll()

    def _poll(self) -> None:
        flow = self._flow
        if flow is None:
            return
        if self._service_thread is not None:
            if self._service_thread.is_alive():
                return
            self._end_critical(self._service_thread)
            self._service_thread = None
        state = flow.poll()
        if state is FlowState.LOGGED_IN and not flow.service and not flow.reauth and not self._folders_chosen:
            # En ny konto: brugeren vælger mapper, før servicen starter.
            if self._picker_state == "closed":
                self._timer.stop()
                self.refresh()
                account = self._find_account(str(flow.confdir))
                if account is not None:
                    self._open_picker(account, for_login=True)
                if self._picker_state == "closed":
                    self._set_message(f"{flow.name} er logget ind, men mappevælgeren kan ikke åbne.")
                    self._end_login()
                    return
                self._set_login_state("choosing_folders")
            return
        if state is FlowState.LOGGED_IN:
            # systemctl kan vente på ExecStartPre i 15 sekunder. Kør det i en tråd.
            self._start_service_thread(flow.activate_service,
                                       f"Starter {flow.service or 'servicen for ' + flow.name}")
            self._set_login_state("activating")
            return
        if flow.needs_restart:
            # Login fejlede eller blev afbrudt. Start servicen igen (feature 0005).
            self._start_service_thread(flow.restore_service, f"Starter {flow.service} igen")
            self._set_login_state("cancelling" if flow.cancel_requested else "activating")
            return
        restart_error = f"\nServicen {flow.service} kunne ikke startes igen:\n{flow.service_error}"
        if state is FlowState.DONE:
            if flow.service_error:
                self._set_message(f"{flow.name} er logget ind, men servicen fejlede:\n{flow.service_error}")
            elif flow.reauth and not flow.service_was_active:
                self._set_message(f"{flow.name} er logget ind.")
            else:
                self._set_message(f"{flow.name} er logget ind. Servicen {flow.service} kører.")
            self._end_login()
        elif state is FlowState.FAILED:
            self._set_message(f"Login fejlede for {flow.name}:\n{flow.error}"
                              + (restart_error if flow.service_error else ""))
            self._end_login()
        elif state is FlowState.CANCELLED:
            if flow.service_error:
                self._set_message(restart_error.strip())
            self._end_login()
        else:
            self._set_login_state(state.value)

    def _start_service_thread(self, target, text: str) -> None:
        self._service_thread = threading.Thread(target=target, daemon=True)
        self._begin_critical(self._service_thread, text)
        self._service_thread.start()

    def _end_login(self) -> None:
        self._timer.stop()
        self._flow = None
        self._set_login_state("idle")
        self.refresh()

    def _set_login_state(self, state: str) -> None:
        snapshot = (state, self._get_auth_url(), self._get_login_name(), self._get_login_note())
        if snapshot != self._login_snapshot:
            self._login_state = state
            self._login_snapshot = snapshot
            self.loginChanged.emit()

    def _set_message(self, message: str) -> None:
        if message != self._message:
            self._message = message
            self.messageChanged.emit()

    def shutdown(self) -> None:
        """Stop en igangværende login-proces, når vinduet lukker."""
        if self._flow is not None and self._service_thread is None:
            self._flow.cancel()
            if self._flow.needs_restart:
                self._flow.restore_service()
        self._timer.stop()
        self._picker_timer.stop()
        self._status_timer.stop()
        self._status_poll_timer.stop()
        self._progress_timer.stop()
        self._close_timer.stop()
