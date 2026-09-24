"""Qt objects that QML binds to. The logic is in the pure modules."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QGuiApplication
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

from . import account_removal as removal_mod
from . import activity as activity_mod
from . import apply as apply_mod
from . import service_control, sideeffects
from .accounts import Account, home_dir
from .config import read_skip_dir_strict, read_skip_dirs, read_sync_root_files
from .discovery import discover_accounts
from .graph import Folder, GraphClient, GraphError
from .journal import activity_lines
from .login_flow import FlowState, LoginFlow
from .naming import NamingError, plan_new_account, suggest_sync_dir, validate_display_name
from .process import PROC_ROOT
from .progress import COMPLETE_WITH_FAILURES, SyncProgress, count_text, format_duration
from .provision import provision_account, validate_sync_dir
from .registry import Registry
from .removal import format_size, is_skipped, total_size
from .service import SystemctlError
from .service_state import (
    FAILED,
    NEEDS_RESYNC,
    RESYNC_CANCELLED,
    RESYNCING,
    STOPPED,
    STOPPING,
    UNKNOWN,
    AccountStatus,
    ServiceState,
    StatusReader,
    format_when,
    initial_status,
)
from .synclist import Selection, SelectionError, read_sync_list
from .theme import avatar_color, avatar_text_color, initials

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 200
SERVICE_STOPPED_NOTE = "The service is stopped while you sign in"
PICKER_POLL_INTERVAL_MS = 100
STATUS_INTERVAL_MS = 3000
STATUS_POLL_INTERVAL_MS = 100
CLOSE_POLL_INTERVAL_MS = 100
ACTION_TEXTS = {"start": "Starting {}", "restart": "Restarting {}", "resync": "Restarting {} with --resync",
                "cancel_resync": "Stopping resync for {}"}
"""The text in the sheet "Skyhus closes when the work is done" for each service action."""
PROGRESS_INTERVAL_MS = 2000
"""How often the application reads new lines from the journal during "Resyncing" (feature 0009)."""
STEP_STATE_TEXTS = {apply_mod.WAITING: "Waiting", apply_mod.RUNNING: "Running",
                    apply_mod.DONE: "Done", apply_mod.FAILED: "Failed", apply_mod.CANCELLED: "Stopped"}
NOT_RUNNING = frozenset({STOPPING, STOPPED, FAILED, NEEDS_RESYNC, RESYNC_CANCELLED})
"""The states where the service is not running. After a stopped upload, the application does not start it (feature 0010)."""
NO_PROGRESS = {"visible": False}


def progress_data(status: AccountStatus, now: float) -> dict:
    """The progress for the "Service" card as a map for QML (feature 0009)."""
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
        detail = f"{progress.failed} {'item' if progress.failed == 1 else 'items'} failed"
    else:
        detail = ""
    if progress.result and elapsed:
        detail = f"{detail} · took {elapsed}" if detail else f"Took {elapsed}"
    return {
        "visible": True,
        "active": active,
        "phase": progress.phase or "Starting resync",
        "counter": count_text(progress.done, progress.total) if progress.done or progress.total is not None else "",
        "determinate": progress.determinate,
        "value": progress.fraction,
        "latest": latest,
        "elapsed": f"Time since start: {elapsed}" if elapsed and not progress.result else "",
        "result": progress.result,
        "resultText": status.progress_text,
        "resultDetail": detail,
    }


REMOVE_POLL_INTERVAL_MS = 100
ACTIVITY_INTERVAL_MS = 30_000
"""How often the card "Activity" reads new journal lines while the window is visible (feature 0019)."""
ACTIVITY_POLL_INTERVAL_MS = 100
RECENT_FILES_SHOWN = 20
ALL_FILES_SHOWN = 200
ACTIVITY_ICONS = {activity_mod.DOWNLOADED: "arrow-down", activity_mod.UPLOADED: "arrow-up",
                  activity_mod.DELETED_ONLINE: "trash-2", activity_mod.DELETED_LOCAL: "trash-2",
                  activity_mod.FAILED: "circle-alert"}
ACTIVITY_VERBS = {activity_mod.DOWNLOADED: "Downloaded", activity_mod.UPLOADED: "Uploaded",
                  activity_mod.DELETED_ONLINE: "Deleted on OneDrive", activity_mod.DELETED_LOCAL: "Deleted locally",
                  activity_mod.FAILED: "Failed"}


def read_activity(service: str, cursor: str, run) -> tuple[list[activity_mod.Event], str, bool]:
    """Read and parse the journal lines for the card "Activity". Runs in a _Job thread (feature 0019)."""
    entries, cursor, truncated = activity_lines(service, after_cursor=cursor, run=run)
    return activity_mod.parse(entries), cursor, truncated
LOCAL_ONLY_SHOWN = 10
"""The number of paths that the sheet "Remove account?" shows of the files that are only local (feature 0018)."""


def removal_step_data(step: int, state: str, progress: SyncProgress | None) -> dict:
    """1 step in the sheet "Remove account?" as a map for QML (feature 0018)."""
    detail = latest = ""
    determinate, value = False, 0.0
    if progress is not None and state != removal_mod.WAITING:
        detail = count_text(progress.done, progress.total)
        latest = progress.latest
        determinate, value = progress.determinate, progress.fraction
    return {
        "step": step,
        "title": removal_mod.STEPS[step],
        "state": state,
        "stateText": STEP_STATE_TEXTS[state],
        "detail": detail,
        "latest": latest,
        "showBar": state == removal_mod.RUNNING and step == removal_mod.UPLOAD,
        "determinate": determinate,
        "value": value,
    }


def step_data(step: int, state: str, progress: SyncProgress | None) -> dict:
    """1 step in the "Changing folder selection" sheet as a map for QML (feature 0009)."""
    detail = latest = ""
    determinate, value = False, 0.0
    if progress is not None and state != apply_mod.WAITING:
        if step == apply_mod.TRASH:
            detail = count_text(progress.done, progress.total, "path", "paths") if progress.total else "No paths"
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
    ServiceCancellableRole = Qt.UserRole + 19

    SERVICE_ROLES = [ServiceStateRole, ServiceLabelRole, ServiceToneRole, ServiceSinceRole,
                     ServiceActionLabelRole, ServiceErrorRole, ServiceBusyRole, ServiceMessageRole,
                     ServiceActionRole, ServiceProgressRole, ServiceCancellableRole]

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
            self.ServiceCancellableRole: QByteArray(b"serviceCancellable"),
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
        if role == self.ServiceCancellableRole:
            # The "Stop resync" button (feature 0010).
            return state.key == RESYNCING
        return None

    def status(self, confdir: str) -> AccountStatus:
        """The last state that was read for the account."""
        status = self._status.get(confdir)
        if status is not None:
            return status
        account = next((a for a in self._accounts if str(a.confdir) == confdir), None)
        return initial_status(account) if account else AccountStatus(ServiceState(UNKNOWN))

    def set_statuses(self, statuses: dict[str, AccountStatus]) -> None:
        self._status.update(statuses)
        self._service_changed(statuses.keys())

    def set_progress(self, progress: dict[str, SyncProgress]) -> None:
        """New progress for accounts during "Resyncing". The state does not change."""
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
    """Run a function in a thread. ``poll`` in the user interface gets the result."""

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
        except BaseException as exc:  # noqa: BLE001 - the user sees the error
            self.error = exc

    @property
    def done(self) -> bool:
        return not self._thread.is_alive()


class FolderTreeModel(QAbstractListModel):
    """The tree in the folder picker as a flat list. ``depth`` gives the indentation."""

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
        """Save the subfolders and show them if the parent folder is expanded."""
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
    """The window can close now (feature 0008). QML calls ``close()`` again."""
    applyChanged = Signal()
    cancelResyncChanged = Signal()
    removeChanged = Signal()
    activityChanged = Signal()

    def __init__(self, home: Path | None = None, parent: QObject | None = None, *,
                 popen=None, run=None, opener=None, trash=None, proc_root: Path = PROC_ROOT,
                 clock=None, sleep=None, send_signal=None):
        super().__init__(parent)
        self._home = home
        self._popen = popen or sideeffects.popen
        self._run = run or sideeffects.run
        self._opener = opener
        self._trash = trash or sideeffects.trash
        self._send_signal = send_signal or sideeffects.signal_process
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
        # Service status (feature 0004). The timer runs only while the window is visible.
        self._clock = clock
        self._sleep = sleep
        self._status_reader = StatusReader(home=home, run=self._run, proc_root=self._proc_root)
        self._status_job: _Job | None = None
        self._status_again = False
        self._action_jobs: dict[str, _Job] = {}
        self._resync_confdir = ""
        self._cancel_resync_confdir = ""
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(STATUS_INTERVAL_MS)
        self._status_timer.timeout.connect(self.refreshStatus)
        self._status_poll_timer = QTimer(self)
        self._status_poll_timer.setInterval(STATUS_POLL_INTERVAL_MS)
        self._status_poll_timer.timeout.connect(self._poll_status)
        # Progress during "Resyncing" (feature 0009). The timer runs only while the window is visible.
        self._progress_job: _Job | None = None
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(PROGRESS_INTERVAL_MS)
        self._progress_timer.timeout.connect(self.refreshProgress)
        # The "Changing folder selection" sheet (feature 0009). The _Job thread writes the steps under the lock.
        self._apply_state = ""
        self._apply_lock = threading.Lock()
        self._apply_steps: dict[int, tuple[str, SyncProgress | None]] = {}
        self._apply_version = 0
        self._apply_seen = 0
        # "Stop" in step 2 (feature 0010).
        self._apply_cancel: apply_mod.CancelFlag | None = None
        self._apply_cancelling = False
        # Close during work (feature 0008). The key is the thread or the _Job object.
        self._critical_jobs: dict[object, str] = {}
        self._closing = False
        self._close_allowed = False
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(CLOSE_POLL_INTERVAL_MS)
        self._close_timer.timeout.connect(self._poll_close)
        # Remove an account (feature 0018). The _Job thread writes the steps under the lock.
        self._remove_state = ""
        self._remove_error = ""
        self._remove_plan: removal_mod.RemovalPlan | None = None
        self._remove_sync_folder = True
        self._remove_job: _Job | None = None
        self._remove_lock = threading.Lock()
        self._remove_steps: dict[int, tuple[str, SyncProgress | None]] = {}
        self._remove_version = 0
        self._remove_seen = 0
        self._remove_cancel: apply_mod.CancelFlag | None = None
        self._remove_cancelling = False
        self._remove_timer = QTimer(self)
        self._remove_timer.setInterval(REMOVE_POLL_INTERVAL_MS)
        self._remove_timer.timeout.connect(self._poll_remove)
        # The card "Activity" (feature 0019). Per account: the events of 24 hours and the journal cursor.
        self._activity: dict[str, activity_mod.Activity] = {}
        self._activity_cursor: dict[str, str] = {}
        self._activity_confdir = ""
        self._activity_job: _Job | None = None
        self._activity_job_confdir = ""
        self._activity_job_full = False
        self._activity_pending: tuple[str, bool] | None = None
        self._all_files_open = False
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(ACTIVITY_INTERVAL_MS)
        self._activity_timer.timeout.connect(self._read_current_activity)
        self._activity_poll_timer = QTimer(self)
        self._activity_poll_timer.setInterval(ACTIVITY_POLL_INTERVAL_MS)
        self._activity_poll_timer.timeout.connect(self._poll_activity)
        self.refresh()

    # Properties for QML

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
    """The text in the sign-in sheet when the flow has stopped the service of the account (feature 0005)."""

    def _get_message(self) -> str:
        return self._message

    message = Property(str, _get_message, notify=messageChanged)

    # The folder picker

    def _get_folders(self) -> FolderTreeModel:
        return self._folders

    folders = Property(QObject, _get_folders, constant=True)

    def _get_picker_state(self) -> str:
        return self._picker_state

    pickerState = Property(str, _get_picker_state, notify=pickerChanged)
    """``closed``, ``loading``, ``open``, ``checking``, ``confirm`` or ``applying``."""

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

    # Service status

    def _get_resync_name(self) -> str:
        account = self._find_account(self._resync_confdir) if self._resync_confdir else None
        return account.name if account else ""

    resyncAccountName = Property(str, _get_resync_name, notify=resyncChanged)
    """The name of the account that waits for the confirmation of "Restart with resync", or empty."""

    def _get_cancel_resync_name(self) -> str:
        account = self._find_account(self._cancel_resync_confdir) if self._cancel_resync_confdir else None
        return account.name if account else ""

    cancelResyncAccountName = Property(str, _get_cancel_resync_name, notify=cancelResyncChanged)
    """The name of the account that waits for the confirmation of "Stop resync", or empty (feature 0010)."""

    # The "Changing folder selection" sheet

    def _get_apply_state(self) -> str:
        return self._apply_state

    applyState = Property(str, _get_apply_state, notify=applyChanged)
    """Empty, ``running``, ``failed`` or ``cancelled``. The sheet is visible when the value is not empty."""

    def _get_apply_cancellable(self) -> bool:
        if self._apply_state != "running" or self._apply_cancel is None or self._apply_cancelling:
            return False
        with self._apply_lock:
            upload = self._apply_steps.get(apply_mod.UPLOAD)
        return upload is not None and upload[0] == apply_mod.RUNNING

    applyCancellable = Property(bool, _get_apply_cancellable, notify=applyChanged)
    """The "Stop" button is visible. This applies only while step 2 runs (feature 0010)."""

    def _get_apply_cancelling(self) -> bool:
        return self._apply_cancelling

    applyCancelling = Property(bool, _get_apply_cancelling, notify=applyChanged)
    """The user clicked "Stop", and the upload stops now."""

    def _get_apply_steps(self) -> list:
        with self._apply_lock:
            steps = dict(self._apply_steps)
        return [step_data(step, *steps[step]) for step in apply_mod.STEPS if step in steps]

    applySteps = Property("QVariantList", _get_apply_steps, notify=applyChanged)
    """The 5 steps with title, state, count and latest file."""

    # The sheet "Remove account?" (feature 0018)

    def _get_remove_state(self) -> str:
        return self._remove_state

    removeState = Property(str, _get_remove_state, notify=removeChanged)
    """Empty, ``loading``, ``confirm``, ``running``, ``failed`` or ``cancelled``. The sheet is visible when not empty."""

    def _get_remove_error(self) -> str:
        return self._remove_error

    removeError = Property(str, _get_remove_error, notify=removeChanged)

    def _get_remove_sync_folder(self) -> bool:
        return self._remove_sync_folder

    removeSyncFolder = Property(bool, _get_remove_sync_folder, notify=removeChanged)
    """The check box "Also move the local folder to the Trash". It is on by default."""

    def _get_remove_plan(self) -> dict:
        plan = self._remove_plan
        if plan is None:
            return {}
        with_sync = self._remove_sync_folder and plan.sync_trashable
        return {
            "name": plan.account.name,
            "confdir": str(plan.account.confdir),
            "syncPath": str(plan.sync_path),
            "syncTrashable": plan.sync_trashable,
            "syncReason": plan.sync_reason,
            "localOnlyText": self._local_only_text(plan),
            "localOnlyPaths": self._local_only_paths(plan),
            "removes": self._remove_lines(plan, with_sync),
            "keeps": self._keep_lines(plan, with_sync),
        }

    removePlan = Property("QVariantMap", _get_remove_plan, notify=removeChanged)

    def _get_remove_steps(self) -> list:
        with self._remove_lock:
            steps = dict(self._remove_steps)
        return [removal_step_data(step, *steps[step]) for step in removal_mod.STEPS if step in steps]

    removeSteps = Property("QVariantList", _get_remove_steps, notify=removeChanged)

    def _get_remove_cancellable(self) -> bool:
        if self._remove_state != "running" or self._remove_cancel is None or self._remove_cancelling:
            return False
        with self._remove_lock:
            upload = self._remove_steps.get(removal_mod.UPLOAD)
        return upload is not None and upload[0] == removal_mod.RUNNING

    removeCancellable = Property(bool, _get_remove_cancellable, notify=removeChanged)
    """The "Stop" button is visible. This applies only while the upload runs."""

    def _get_remove_cancelling(self) -> bool:
        return self._remove_cancelling

    removeCancelling = Property(bool, _get_remove_cancelling, notify=removeChanged)

    @staticmethod
    def _local_only_text(plan: removal_mod.RemovalPlan) -> str:
        local = plan.local_only
        if local is None or local.files == 0:
            return ""
        noun = "file is" if local.files == 1 else "files are"
        return f"{local.files} {noun} only on this computer ({format_size(local.size)})"

    @staticmethod
    def _local_only_paths(plan: removal_mod.RemovalPlan) -> list:
        local = plan.local_only
        if local is None:
            return []
        paths = []
        for item in local.paths[:LOCAL_ONLY_SHOWN]:
            try:
                rel = str(Path(item.path).relative_to(plan.sync_path))
            except ValueError:
                rel = str(item.path)
            paths.append(rel + ("/" if item.is_dir else ""))
        more = len(local.paths) - LOCAL_ONLY_SHOWN
        if more > 0:
            paths.append(f"and {more} more")
        return paths

    @staticmethod
    def _remove_lines(plan: removal_mod.RemovalPlan, with_sync: bool) -> list:
        lines = []
        if plan.service:
            if any(p.name == plan.service for p in plan.unit_files):
                lines.append(f"The service {plan.service}: stopped, disabled and its unit file removed")
            else:
                lines.append(f"The service {plan.service}: stopped and disabled. Its unit file stays.")
        for unit in plan.triggers:
            lines.append(f"{unit}: disabled. Its unit file stays.")
        for path in plan.unit_files:
            if path.name != plan.service:
                lines.append(f"The file {path}")
        lines.append(f"The config folder {plan.account.confdir}: to Trash. The sign-in token is deleted.")
        if with_sync:
            lines.append(f"The sync folder {plan.sync_path}: to Trash, after an upload of the local changes")
        return lines

    @staticmethod
    def _keep_lines(plan: removal_mod.RemovalPlan, with_sync: bool) -> list:
        lines = ["The files on OneDrive"]
        if not with_sync:
            lines.append(f"The sync folder {plan.sync_path}")
        return lines

    # The card "Activity" (feature 0019)

    def _current_activity(self) -> activity_mod.Activity | None:
        return self._activity.get(self._activity_confdir)

    def _get_activity_state(self) -> str:
        account = self._find_account(self._activity_confdir) if self._activity_confdir else None
        if account is None:
            return "none"
        if not account.service:
            return "no_service"
        if self._current_activity() is None:
            return "loading"
        return "ready"

    activityState = Property(str, _get_activity_state, notify=activityChanged)
    """``none``, ``no_service``, ``loading`` or ``ready`` for the account on the page."""

    def _get_activity_summary(self) -> str:
        log_ = self._current_activity()
        return log_.summary(datetime.now()) if log_ is not None else ""

    activitySummary = Property(str, _get_activity_summary, notify=activityChanged)

    def _get_activity_problems(self) -> list:
        log_ = self._current_activity()
        if log_ is None:
            return []
        now = datetime.now()
        rows = []
        for problem in log_.problems():
            detail = activity_mod.problem_line(problem, now)[len(problem.title) + len(" · "):]
            rows.append({"title": problem.title, "detail": detail, "tone": problem.tone})
        return rows

    activityProblems = Property("QVariantList", _get_activity_problems, notify=activityChanged)

    def _file_rows(self, limit: int) -> list:
        log_ = self._current_activity()
        if log_ is None:
            return []
        now = datetime.now()
        return [{"icon": ACTIVITY_ICONS[e.kind], "verb": ACTIVITY_VERBS[e.kind], "path": e.path,
                 "when": format_when(datetime.fromtimestamp(e.when), now),
                 "tone": "danger" if e.kind == activity_mod.FAILED else "textSecondary"}
                for e in log_.recent(limit)]

    def _get_activity_recent(self) -> list:
        return self._file_rows(RECENT_FILES_SHOWN)

    activityRecent = Property("QVariantList", _get_activity_recent, notify=activityChanged)

    def _get_all_files(self) -> list:
        return self._file_rows(ALL_FILES_SHOWN) if self._all_files_open else []

    activityAllFiles = Property("QVariantList", _get_all_files, notify=activityChanged)

    def _get_all_files_open(self) -> bool:
        return self._all_files_open

    allFilesOpen = Property(bool, _get_all_files_open, notify=activityChanged)

    def _get_activity_loading(self) -> bool:
        return self._activity_job is not None and self._activity_job_confdir == self._activity_confdir

    activityLoading = Property(bool, _get_activity_loading, notify=activityChanged)

    # Close during work

    def _get_busy_text(self) -> str:
        return "\n".join(self._critical_jobs.values())

    busyText = Property(str, _get_busy_text, notify=closeChanged)
    """The actions that can stop or start a service and that run now. 1 per line."""

    def _get_closing(self) -> bool:
        return self._closing

    closing = Property(bool, _get_closing, notify=closeChanged)
    """The user closed the window, and the application waits for the actions in ``busyText``."""

    # Actions from QML

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
            return f"Cannot save the name: {exc}"
        self.refresh()
        return ""

    @Slot(str, str, result=str)
    def addAccount(self, name: str, sync_dir: str) -> str:
        """Create the account and start the sign-in. Returns an error message or empty."""
        if self._flow is not None:
            return "Another sign-in is in progress."
        try:
            new = plan_new_account(name, self._model.accounts(), self._home)
            validate_sync_dir(sync_dir)
            provision_account(new.confdir, sync_dir.strip())
            self._registry.add(new.confdir, new.name)
        except (NamingError, ValueError) as exc:
            return str(exc)
        except OSError as exc:
            return f"Cannot create the account: {exc}"
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
            # The thread stops the service. _poll ends the flow when the thread is done.
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
            self._set_picker(error="Choose at least 1 folder, or choose \"Sync all folders\".")
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
            self._set_message(f"{flow.name} is signed in. The service is not started, "
                              "because no folders are chosen.")
            self._end_login()

    @Slot(bool)
    def setWindowVisible(self, visible: bool) -> None:
        """The timer runs while the window is visible and stops when it is minimized."""
        if visible and not self._status_timer.isActive():
            self._status_timer.start()
            self._progress_timer.start()
            self._activity_timer.start()
            self.refreshStatus()
        elif not visible:
            self._status_timer.stop()
            self._progress_timer.stop()
            self._activity_timer.stop()

    @Slot()
    def refreshStatus(self) -> None:
        """Read the state of all accounts in a thread."""
        if self._status_job is not None:
            self._status_again = True
            return
        self._status_job = _Job("status", self._status_reader.read, self._model.accounts())
        self._status_poll_timer.start()

    @Slot()
    def refreshProgress(self) -> None:
        """Read new lines from the journal for accounts during "Resyncing" in a thread."""
        if self._progress_job is not None:
            return
        accounts = self._model.resyncing()
        if not accounts:
            return
        self._progress_job = _Job("progress", self._status_reader.read_progress, accounts)
        self._status_poll_timer.start()

    @Slot()
    def closeApplyProgress(self) -> None:
        """The "Close" button in the "Changing folder selection" sheet when a step failed or the change was stopped."""
        if self._apply_state in ("failed", "cancelled"):
            self._set_apply_state("")

    @Slot()
    def cancelApply(self) -> None:
        """The "Stop" button in the "Changing folder selection" sheet. Does nothing outside step 2."""
        flag = self._apply_cancel
        if flag is None or self._apply_cancelling or not self._get_apply_cancellable():
            return
        if flag.request():
            log.info("The user stops the upload for %s",
                     self._picker_account.name if self._picker_account else "the account")
            self._apply_cancelling = True
            self.applyChanged.emit()

    @Slot(str)
    def serviceAction(self, confdir: str) -> None:
        """The button in the "Service" card. "Restart with resync" waits for a confirmation."""
        if self._model.is_busy(confdir) or self._resync_confdir or self._cancel_resync_confdir:
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

    @Slot(str)
    def requestCancelResync(self, confdir: str) -> None:
        """The "Stop resync" button in the "Service" card. It waits for a confirmation (feature 0010)."""
        if self._model.is_busy(confdir) or self._resync_confdir or self._cancel_resync_confdir:
            return
        account = self._find_account(confdir)
        if account is None or not account.service or self._model.status(confdir).state.key != RESYNCING:
            return
        self._cancel_resync_confdir = confdir
        self.cancelResyncChanged.emit()

    @Slot()
    def confirmCancelResync(self) -> None:
        confdir = self._cancel_resync_confdir
        if not confdir:
            return
        self._cancel_resync_confdir = ""
        self.cancelResyncChanged.emit()
        account = self._find_account(confdir)
        if account is not None and account.service and not self._model.is_busy(confdir):
            self._start_cancel_resync(account)

    @Slot()
    def dismissCancelResync(self) -> None:
        if self._cancel_resync_confdir:
            self._cancel_resync_confdir = ""
            self.cancelResyncChanged.emit()

    @Slot(str)
    def requestRemoveAccount(self, confdir: str) -> None:
        """The button "Remove account …". Finds what belongs to the account in a thread (feature 0018)."""
        if (self._remove_state or self._login_state != "idle" or self._picker_state != "closed"
                or self._model.is_busy(confdir) or self._resync_confdir or self._cancel_resync_confdir):
            return
        account = self._find_account(confdir)
        if account is None:
            return
        self._remove_plan = None
        self._remove_error = ""
        self._remove_sync_folder = True
        with self._remove_lock:
            self._remove_steps = {}
            self._remove_version += 1
        self._set_remove_state("loading")
        self._remove_job = _Job("prepare", removal_mod.prepare, account, self._model.accounts(),
                                home=self._home, run=self._run)
        self._remove_timer.start()

    @Slot(bool)
    def setRemoveSyncFolder(self, value: bool) -> None:
        if self._remove_state == "confirm" and value != self._remove_sync_folder:
            self._remove_sync_folder = value
            self.removeChanged.emit()

    @Slot()
    def confirmRemoveAccount(self) -> None:
        plan = self._remove_plan
        if self._remove_state != "confirm" or plan is None:
            return
        confdir = str(plan.account.confdir)
        if self._model.is_busy(confdir):
            return
        with_sync = self._remove_sync_folder and plan.sync_trashable
        with self._remove_lock:
            self._remove_steps = {step: (removal_mod.WAITING, None) for step in plan.steps(with_sync)}
            self._remove_version += 1
        self._remove_cancel = apply_mod.CancelFlag() if with_sync else None
        self._remove_cancelling = False
        self._model.set_busy(confdir, True)
        self._set_remove_state("running")
        self._remove_job = _Job("execute", removal_mod.execute, plan, remove_sync_folder=with_sync,
                                home=self._home, run=self._run, popen=self._popen, trash=self._trash,
                                send_signal=self._send_signal, proc_root=self._proc_root,
                                clock=self._clock, sleep=self._sleep, on_step=self._on_remove_step,
                                cancel=self._remove_cancel)
        self._begin_critical(self._remove_job, f"Removing the account {plan.account.name}")
        self._remove_timer.start()

    @Slot()
    def stopRemoveAccount(self) -> None:
        """The "Stop" button during the upload. The removal is undone."""
        flag = self._remove_cancel
        if flag is None or self._remove_cancelling or not self._get_remove_cancellable():
            return
        if flag.request():
            self._remove_cancelling = True
            self.removeChanged.emit()

    @Slot()
    def closeRemoveAccount(self) -> None:
        """"Cancel" in the confirmation, or "Close" after an error or a stop."""
        if self._remove_state in ("confirm", "failed", "cancelled"):
            self._remove_plan = None
            self._remove_error = ""
            self._set_remove_state("")

    @Slot(str)
    def openActivity(self, confdir: str) -> None:
        """The page shows ``confdir``. Read its activity: all 24 hours the first time, then the new lines."""
        if confdir != self._activity_confdir:
            self._activity_confdir = confdir
            self._all_files_open = False
            self.activityChanged.emit()
        if confdir:
            self._start_activity_read(confdir, full=confdir not in self._activity)

    @Slot()
    def refreshActivity(self) -> None:
        """The button "Refresh": read the last 24 hours again."""
        if self._activity_confdir:
            self._start_activity_read(self._activity_confdir, full=True)

    @Slot()
    def copyProblems(self) -> None:
        log_ = self._current_activity()
        if log_ is None:
            return
        text = activity_mod.problems_text(log_.problems(), datetime.now())
        if text:
            QGuiApplication.clipboard().setText(text)

    @Slot()
    def showAllFiles(self) -> None:
        if self._current_activity() is not None and not self._all_files_open:
            self._all_files_open = True
            self.activityChanged.emit()

    @Slot()
    def closeAllFiles(self) -> None:
        if self._all_files_open:
            self._all_files_open = False
            self.activityChanged.emit()

    @Slot(result=bool)
    def requestClose(self) -> bool:
        """Return true if the window can close. Otherwise wait for the actions and send ``closeReady``."""
        if self._close_allowed or not self._critical_jobs:
            return True
        if not self._closing:
            log.info("The window closes when this is done: %s", "; ".join(self._critical_jobs.values()))
            self._closing = True
            self.closeChanged.emit()
        self._close_timer.start()
        return False

    @Slot()
    def forceClose(self) -> None:
        """The "Close anyway" button. The actions continue until the process ends."""
        if self._critical_jobs:
            log.warning("The window closes while these actions run. The service can stay "
                        "stopped: %s", "; ".join(self._critical_jobs.values()))
        self._allow_close()

    # Internal control

    def _begin_critical(self, key: object, text: str) -> None:
        """Register an action that can stop or start a service."""
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

    def _read_current_activity(self) -> None:
        if self._activity_confdir:
            self._start_activity_read(self._activity_confdir, full=self._activity_confdir not in self._activity)

    def _start_activity_read(self, confdir: str, *, full: bool) -> None:
        account = self._find_account(confdir)
        if account is None or not account.service:
            return
        if self._activity_job is not None:
            # 1 read at a time. The newest request waits. A full read wins over a read of the new lines.
            pending = self._activity_pending
            same = pending is not None and pending[0] == confdir
            self._activity_pending = (confdir, full or (same and pending[1]))
            return
        cursor = "" if full else self._activity_cursor.get(confdir, "")
        self._activity_job = _Job("activity", read_activity, account.service, cursor, self._run)
        self._activity_job_confdir = confdir
        self._activity_job_full = full or not cursor
        self._activity_poll_timer.start()
        self.activityChanged.emit()

    def _poll_activity(self) -> None:
        job = self._activity_job
        if job is None or not job.done:
            return
        self._activity_job = None
        self._activity_poll_timer.stop()
        confdir = self._activity_job_confdir
        if job.error is not None:
            log.error("Unexpected error when the application read the activity", exc_info=job.error)
        else:
            events, cursor, truncated = job.result
            log_ = self._activity.get(confdir)
            if log_ is None or self._activity_job_full:
                log_ = activity_mod.Activity()
                log_.replace(events, time.time(), truncated)
                self._activity[confdir] = log_
            else:
                log_.add(events, time.time())
            self._activity_cursor[confdir] = cursor
        pending, self._activity_pending = self._activity_pending, None
        self.activityChanged.emit()
        if pending is not None:
            self._start_activity_read(pending[0], full=pending[1])

    def _set_remove_state(self, state: str) -> None:
        if state != self._remove_state:
            self._remove_state = state
            self.removeChanged.emit()

    def _on_remove_step(self, step: int, state: str, progress: SyncProgress | None) -> None:
        """Called from the _Job thread. Does not send Qt signals. ``_poll_remove`` does that."""
        with self._remove_lock:
            self._remove_steps[step] = (state, progress)
            self._remove_version += 1

    def _poll_remove(self) -> None:
        job = self._remove_job
        done = job is not None and job.done
        with self._remove_lock:
            version = self._remove_version
        if version != self._remove_seen:
            self._remove_seen = version
            self.removeChanged.emit()
        if job is None:
            self._remove_timer.stop()
            return
        if not done:
            return
        self._remove_job = None
        self._remove_timer.stop()
        if job.kind == "prepare":
            if job.error is not None:
                self._remove_error = self._remove_error_text(job.error)
                self._set_remove_state("failed")
                self.removeChanged.emit()
                return
            self._remove_plan = job.result
            self._set_remove_state("confirm")
            self.removeChanged.emit()
            return
        self._end_critical(job)
        plan = self._remove_plan
        self._model.set_busy(str(plan.account.confdir), False)
        self._remove_cancel = None
        self._remove_cancelling = False
        if job.error is not None:
            self._remove_error = self._remove_error_text(job.error)
            self._set_remove_state("failed")
            self.removeChanged.emit()
            self.refresh()
            self.refreshStatus()
            return
        if job.result.outcome == removal_mod.CANCELLED:
            self._set_remove_state("cancelled")
            self.removeChanged.emit()
            self.refreshStatus()
            return
        self._remove_plan = None
        self._set_remove_state("")
        self.refresh()
        if sideeffects.safe_mode() and self._run is sideeffects.run:
            self._set_message(f"Safe mode: Skyhus did not remove the account {plan.account.name}.")
            return
        lines = [f"The account {plan.account.name} is removed."]
        if job.result.sync_folder_left is not None:
            lines.append(f"Skyhus could not move the sync folder {job.result.sync_folder_left} to Trash. "
                         "Remove it yourself.")
        self._set_message("\n".join(lines))

    @staticmethod
    def _remove_error_text(error: BaseException) -> str:
        if isinstance(error, (removal_mod.RemovalError, SystemctlError, OSError)):
            return str(error)
        log.error("Unexpected error in the removal of an account", exc_info=error)
        return f"Unexpected error: {error}"

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

    def _start_cancel_resync(self, account: Account) -> None:
        """Stop the service in a thread. The action is critical as defined in feature 0008."""
        confdir = str(account.confdir)
        self._model.set_service_message(confdir, "")
        self._model.set_busy(confdir, True)
        job = _Job("action", service_control.cancel_resync, account.service, home=self._home, run=self._run)
        self._action_jobs[confdir] = job
        self._begin_critical(job, ACTION_TEXTS["cancel_resync"].format(account.service))
        self._status_poll_timer.start()

    def _poll_status(self) -> None:
        job = self._status_job
        if job is not None and job.done:
            self._status_job = None
            if job.error is not None:
                log.error("Unexpected error when the application read the status", exc_info=job.error)
            else:
                self._model.set_statuses(job.result)
            if self._status_again:
                self._status_again = False
                self.refreshStatus()
        progress_job = self._progress_job
        if progress_job is not None and progress_job.done:
            self._progress_job = None
            if progress_job.error is not None:
                log.error("Unexpected error when the application read the progress", exc_info=progress_job.error)
            else:
                self._model.set_progress(progress_job.result)
                if any(p.result for p in progress_job.result.values()):
                    # Resync is complete. The state changes from "Resyncing" to "Running".
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
        log.error("Unexpected error in a service action", exc_info=error)
        return f"Unexpected error: {error}"

    def _find_account(self, confdir: str) -> Account | None:
        for account in self._model.accounts():
            if str(account.confdir) == confdir:
                return account
        return None

    def _open_picker(self, account: Account, *, for_login: bool = False) -> None:
        if not (account.confdir / "refresh_token").is_file():
            self._set_message(f"{account.name}: The account is not signed in.")
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
        self._apply_cancel = None
        self._apply_cancelling = False
        self._set_apply_state("")
        self._set_picker(state="closed", error="")

    def _start_job(self, kind: str, fn, *args, **kwargs) -> None:
        self._jobs.append(_Job(kind, fn, *args, **kwargs))
        self._picker_timer.start()

    def _execute_change(self) -> None:
        change = self._change
        self._set_picker(state="applying", error="")
        self._apply_cancel = apply_mod.CancelFlag() if change.synced else None
        self._apply_cancelling = False
        if change.synced:
            with self._apply_lock:
                self._apply_steps = {step: (apply_mod.WAITING, None) for step in apply_mod.STEPS}
                self._apply_version += 1
            self._set_apply_state("running")
        state = self._model.status(str(change.account.confdir)).state.key
        self._start_job("execute", apply_mod.execute, change, home=self._home,
                        run=self._run, popen=self._popen, trash=self._trash, proc_root=self._proc_root,
                        on_step=self._on_apply_step if change.synced else None,
                        cancel=self._apply_cancel, service_active=state not in NOT_RUNNING,
                        send_signal=self._send_signal)
        if change.synced:
            text = f"Saving the folder selection for {change.account.name} and restarting {change.account.service}"
        else:
            text = f"Saving the folder selection for {change.account.name}"
        self._begin_critical(self._jobs[-1], text)

    def _on_apply_step(self, step: int, state: str, progress: SyncProgress | None) -> None:
        """Called from the _Job thread. Does not send Qt signals. ``_poll_picker`` does that."""
        with self._apply_lock:
            self._apply_steps[step] = (state, progress)
            self._apply_version += 1

    def _set_apply_state(self, state: str) -> None:
        if state != self._apply_state:
            self._apply_state = state
            self.applyChanged.emit()

    def _poll_picker(self) -> None:
        # Find the finished jobs first. Then their last step is included in the version below.
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
            self._apply_cancel = None
            self._apply_cancelling = False
            if error is None and job.result.outcome == apply_mod.CANCELLED:
                # The sheet shows "The change is stopped" until the user clicks "Close". The folder selection does not change.
                self._change = None
                self._set_apply_state("cancelled")
                self.applyChanged.emit()
                self._set_picker(state="open", error="")
                return
            if error is not None:
                self._change = None
                if self._apply_state == "running":
                    # The sheet stays open with the failed step until the user clicks "Close".
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
            lines.append("These paths could not be moved to Trash:")
            lines.extend(str(p) for p in result.trash_failures)
        if for_login:
            self._folders_chosen = True
            if lines:
                self._set_message("\n".join(lines))
            self._timer.start()
            self._poll()
            return
        if result.resynced:
            lines.insert(0, f"The folder selection for {account.name} is saved. {account.service} "
                            "now syncs with --resync. This can take a long time.")
        else:
            lines.insert(0, f"The folder selection for {account.name} is saved.")
        self._set_message("\n".join(lines))

    @staticmethod
    def _error_text(error: BaseException) -> str:
        if isinstance(error, (GraphError, apply_mod.ApplyError, SelectionError)):
            return str(error)
        log.exception("Unexpected error in the folder picker", exc_info=error)
        return f"Unexpected error: {error}"

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
                               popen=self._popen, run=self._run, proc_root=self._proc_root,
                               send_signal=self._send_signal)
        if self._flow.reauth:
            # The flow can stop the service first. This can take up to 90 seconds.
            text = f"Stopping {service} before sign-in" if service else f"Starting sign-in for {name}"
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
            # A new account: the user chooses folders before the service starts.
            if self._picker_state == "closed":
                self._timer.stop()
                self.refresh()
                account = self._find_account(str(flow.confdir))
                if account is not None:
                    self._open_picker(account, for_login=True)
                if self._picker_state == "closed":
                    self._set_message(f"{flow.name} is signed in, but the folder picker cannot open.")
                    self._end_login()
                    return
                self._set_login_state("choosing_folders")
            return
        if state is FlowState.LOGGED_IN:
            # systemctl can wait for ExecStartPre for 15 seconds. Run it in a thread.
            self._start_service_thread(flow.activate_service,
                                       f"Starting {flow.service or 'the service for ' + flow.name}")
            self._set_login_state("activating")
            return
        if flow.needs_restart:
            # The sign-in failed or was cancelled. Start the service again (feature 0005).
            self._start_service_thread(flow.restore_service, f"Starting {flow.service} again")
            self._set_login_state("cancelling" if flow.cancel_requested else "activating")
            return
        restart_error = f"\nThe service {flow.service} could not start again:\n{flow.service_error}"
        if state is FlowState.DONE:
            if flow.service_error:
                self._set_message(f"{flow.name} is signed in, but the service failed:\n{flow.service_error}")
            elif flow.reauth and not flow.service_was_active:
                self._set_message(f"{flow.name} is signed in.")
            else:
                self._set_message(f"{flow.name} is signed in. The service {flow.service} is running.")
            self._end_login()
        elif state is FlowState.FAILED:
            self._set_message(f"Sign-in failed for {flow.name}:\n{flow.error}"
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
        """Stop a running sign-in process when the window closes."""
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
        self._remove_timer.stop()
        self._activity_timer.stop()
        self._activity_poll_timer.stop()
