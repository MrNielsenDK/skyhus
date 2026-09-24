"""Remove an account (feature 0018).

``prepare()`` finds what belongs to the account and changes nothing.
``execute()`` removes the account in this order:

1. check that no other ``onedrive`` process uses the account,
2. disable the trigger units (for example a ``.path`` unit), so they cannot start the service,
3. disable and stop the service, and wait until it is inactive,
4. upload the local changes (only when the sync folder goes to Trash),
5. remove the unit files that Skyhus wrote, then ``daemon-reload``,
6. delete ``refresh_token`` permanently,
7. move the config folder to Trash,
8. move the sync folder to Trash (only when the user chose it),
9. remove the account from the registry and from ``state.json``.

If step 2, 3 or 4 fails, or the user stops the upload, ``execute()`` enables
and starts the units again as they were before. Nothing else changes.
Skyhus never deletes a unit file, a ``.path`` unit or a drop-in that it did not write.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import sideeffects
from .accounts import DEFAULT_CONFDIR_NAME, CONFDIR_PREFIX, Account, config_home, home_dir, unit_dir
from .apply import CancelFlag, ApplyError, Upload, current_rule_set, run_upload
from .process import PROC_ROOT, find_processes
from .progress import SyncProgress
from .registry import Registry
from .removal import RemovedPath, count_files, find_local_only, total_size
from .rules import UnknownRuleError
from .service import SystemctlError, daemon_reload, disable_now, systemctl
from .service_control import RESYNC_DROP_IN, SETTLE_POLL_SECONDS, SETTLE_TIMEOUT_SECONDS
from .service_state import clear_resync_cancelled

log = logging.getLogger(__name__)

Run = Callable[..., subprocess.CompletedProcess]
Popen = Callable[..., object]
Trash = Callable[[Path], bool]
SendSignal = Callable[[object, int], None]
OnStep = Callable[[int, str, "SyncProgress | None"], None]

TRIGGERS, SERVICE, UPLOAD, UNITS, TOKEN, CONFIG, SYNC, CLEANUP = range(1, 9)
STEPS = {
    TRIGGERS: "Disabling the units that start the service",
    SERVICE: "Stopping and disabling the service",
    UPLOAD: "Uploading local changes",
    UNITS: "Removing the unit files",
    TOKEN: "Deleting the sign-in token",
    CONFIG: "Moving the config folder to Trash",
    SYNC: "Moving the sync folder to Trash",
    CLEANUP: "Removing the account from Skyhus",
}

WAITING = "waiting"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

HEADER = "Created by Skyhus."
LEGACY_HEADERS = ("Oprettet af Skyhus.", "Oprettet af " + "onedrive" + "-gui.")  # allow-danish: headers before 0.10.0
"""The unit header from before version 0.10.0 and from before the name Skyhus."""
SHOW_PROPERTIES = "Id,LoadState,ActiveState,UnitFileState,FragmentPath,TriggeredBy"
STOPPED_STATES = ("inactive", "failed")


class RemovalError(RuntimeError):
    """The removal cannot continue. The message can be shown to the user."""


@dataclass(frozen=True)
class UnitInfo:
    name: str
    load_state: str = ""
    active_state: str = ""
    unit_file_state: str = ""
    fragment: str = ""
    triggered_by: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.unit_file_state == "enabled"

    @property
    def active(self) -> bool:
        return self.active_state in ("active", "activating", "reloading", "refreshing")


@dataclass
class LocalOnly:
    paths: list[RemovedPath]
    """The topmost paths that the rules keep out of the sync."""
    files: int
    size: int


@dataclass
class RemovalPlan:
    account: Account
    service: str
    """The service of the account, or empty if it has none."""
    triggers: list[str]
    unit_files: list[Path]
    """The unit files and drop-ins that Skyhus wrote. Only these are deleted."""
    kept_units: list[str]
    """The units that are disabled, but whose files stay."""
    sync_path: Path
    sync_trashable: bool
    sync_reason: str
    """Why the sync folder cannot go to Trash. Empty when it can."""
    local_only: LocalOnly | None = None

    def steps(self, remove_sync_folder: bool) -> list[int]:
        """The steps that ``execute()`` does, in order."""
        with_sync = remove_sync_folder and self.sync_trashable
        steps = []
        if self.triggers:
            steps.append(TRIGGERS)
        if self.service:
            steps.append(SERVICE)
        if with_sync:
            steps.append(UPLOAD)
        if self.unit_files:
            steps.append(UNITS)
        steps += [TOKEN, CONFIG]
        if with_sync:
            steps.append(SYNC)
        steps.append(CLEANUP)
        return steps


@dataclass
class RemovalResult:
    outcome: str = DONE
    """``DONE`` or ``CANCELLED``."""
    sync_folder_left: Path | None = None
    """The sync folder, if it had to go to Trash but could not."""


def is_written_by_skyhus(path: Path) -> bool:
    """Has Skyhus written the unit file? The first comment lines tell it."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            head = [next(f, "") for _ in range(5)]
    except OSError:
        return False
    headers = (HEADER, *LEGACY_HEADERS)
    return any(line.startswith("#") and any(h in line for h in headers) for line in head)


def parse_show(output: str) -> dict[str, UnitInfo]:
    """The output of ``systemctl show`` with ``SHOW_PROPERTIES``, 1 block per unit."""
    units = {}
    for block in output.strip().split("\n\n"):
        props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        name = props.get("Id", "")
        if not name:
            continue
        units[name] = UnitInfo(
            name=name,
            load_state=props.get("LoadState", ""),
            active_state=props.get("ActiveState", ""),
            unit_file_state=props.get("UnitFileState", ""),
            fragment=props.get("FragmentPath", ""),
            triggered_by=tuple(props.get("TriggeredBy", "").split()),
        )
    return units


def read_units(names: list[str], run: Run | None = None) -> dict[str, UnitInfo]:
    names = [n for n in dict.fromkeys(names) if n]
    if not names:
        return {}
    return parse_show(systemctl("show", *names, "-p", SHOW_PROPERTIES, run=run))


def _is_below(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _real(path: Path | str) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def check_confdir(account: Account, home: Path | None) -> None:
    """The config folder must be ``~/.config/onedrive`` or ``~/.config/onedrive-*``."""
    confdir = Path(account.confdir)
    name = confdir.name
    right_name = name == DEFAULT_CONFDIR_NAME or (name.startswith(CONFDIR_PREFIX) and len(name) > len(CONFDIR_PREFIX))
    if _real(confdir.parent) != _real(config_home(home)) or not right_name or not confdir.is_dir():
        raise RemovalError(f"Skyhus does not remove the folder {confdir}. "
                           "An account folder must be ~/.config/onedrive or ~/.config/onedrive-<name>.")


def _sync_folder_check(account: Account, accounts: list[Account], home: Path | None) -> str:
    """Why the sync folder cannot go to Trash, or empty when it can."""
    sync = _real(account.sync_path)
    home_path = _real(home_dir(home))
    if not sync.is_dir():
        return f"The sync folder {sync} does not exist."
    if sync == home_path:
        return "The sync folder is your home folder."
    if not _is_below(sync, home_path):
        return "The sync folder is not inside your home folder."
    if _is_below(sync, _real(config_home(home))):
        return "The sync folder is inside ~/.config."
    for other in accounts:
        if _real(other.confdir) == _real(account.confdir):
            continue
        for path in (_real(other.sync_path), _real(other.confdir)):
            if _is_below(sync, path) or _is_below(path, sync):
                return f"The sync folder overlaps with the folders of the account {other.name}."
    return ""


def _local_only(account: Account, sync: Path) -> LocalOnly:
    rules = current_rule_set(account.confdir)
    paths = find_local_only(sync, rules)
    return LocalOnly(paths=paths, files=count_files(paths), size=total_size(paths))


def prepare(account: Account, accounts: list[Account], *, home: Path | None = None,
            run: Run | None = None) -> RemovalPlan:
    """Find what belongs to the account. Only ``systemctl show`` runs. Nothing changes."""
    check_confdir(account, home)
    service = account.service
    triggers: list[str] = []
    unit_files: list[Path] = []
    kept: list[str] = []
    if service:
        try:
            info = read_units([service], run=run).get(service)
        except SystemctlError as exc:
            raise RemovalError(f"Cannot read the service {service}:\n{exc}") from None
        if info is None or info.load_state == "not-found":
            service = ""
        else:
            triggers = list(info.triggered_by)
            fragment = Path(info.fragment) if info.fragment else None
            user_units = _real(unit_dir(home))
            if fragment is not None and _real(fragment.parent) == user_units and is_written_by_skyhus(fragment):
                unit_files.append(fragment)
            else:
                kept.append(service)
            drop_in = unit_dir(home) / f"{service}.d" / RESYNC_DROP_IN
            if drop_in.is_file():
                unit_files.append(drop_in)
            kept += triggers

    reason = _sync_folder_check(account, accounts, home)
    local_only = None
    if not reason:
        try:
            local_only = _local_only(account, _real(account.sync_path))
        except UnknownRuleError:
            reason = ("Skyhus cannot interpret the rules of the account. "
                      "So it cannot find the files that are only on this computer.")
    return RemovalPlan(account=account, service=service, triggers=triggers, unit_files=unit_files,
                       kept_units=kept, sync_path=_real(account.sync_path), sync_trashable=not reason,
                       sync_reason=reason, local_only=local_only)


def _report(on_step: OnStep | None, step: int, state: str, progress: SyncProgress | None = None) -> None:
    if on_step is not None:
        on_step(step, state, progress.snapshot() if progress is not None else None)


def _describe(processes) -> str:
    return "\n".join(f"PID {p.pid}: {' '.join(p.args)}" for p in processes)


class _Undo:
    """Enable and start the units again, as they were before the removal."""

    def __init__(self, before: dict[str, UnitInfo], run: Run):
        self._before = before
        self._run = run
        self.disabled: list[str] = []

    def __call__(self) -> list[str]:
        """Undo in the opposite order. Returns the units that could not be restored."""
        failed = []
        for name in reversed(self.disabled):
            info = self._before.get(name)
            if info is None:
                continue
            try:
                if info.enabled:
                    systemctl("enable", name, run=self._run)
                if info.active:
                    systemctl("start", name, run=self._run)
            except SystemctlError as exc:
                log.warning("Cannot restore %s: %s", name, exc)
                failed.append(name)
        self.disabled = []
        return failed


def _undo_text(failed: list[str]) -> str:
    if not failed:
        return "Skyhus enabled the service again. Nothing else changed."
    return ("Skyhus could not enable these units again. Enable them with "
            f"\"systemctl --user enable --now <unit>\": {', '.join(failed)}")


def _wait_until_stopped(service: str, run: Run, clock, sleep) -> None:
    deadline = clock() + SETTLE_TIMEOUT_SECONDS
    while True:
        try:
            info = read_units([service], run=run).get(service)
            state = info.active_state if info is not None else "inactive"
        except SystemctlError as exc:
            log.warning("Cannot read the status while waiting: %s", exc)
            state = ""
        if state in STOPPED_STATES:
            return
        if clock() >= deadline:
            raise RemovalError(f"The service {service} does not respond. It did not stop.")
        sleep(SETTLE_POLL_SECONDS)


def execute(plan: RemovalPlan, *, remove_sync_folder: bool, home: Path | None = None,
            run: Run | None = None, popen: Popen | None = None, trash: Trash | None = None,
            send_signal: SendSignal | None = None, proc_root: Path = PROC_ROOT,
            clock: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None,
            on_step: OnStep | None = None, cancel: CancelFlag | None = None) -> RemovalResult:
    """Remove the account. See the module docstring for the order."""
    live = not sideeffects.safe_mode() or (run is not None and run is not sideeffects.run)
    run = run or sideeffects.run
    trash = trash or sideeffects.trash
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    account = plan.account
    confdir = Path(account.confdir)
    steps = plan.steps(remove_sync_folder)
    for step in steps:
        _report(on_step, step, WAITING)

    # Step 1: check. Nothing is changed before this passes.
    check_confdir(account, home)
    others = [p for p in find_processes(confdir, home=home, proc_root=proc_root)
              if not plan.service or p.unit != plan.service]
    if others:
        raise RemovalError("Another onedrive process uses the account. Stop it first.\n" + _describe(others))
    try:
        before = read_units([plan.service, *plan.triggers], run=run)
    except SystemctlError as exc:
        raise RemovalError(f"Cannot read the service {plan.service}:\n{exc}") from None
    undo = _Undo(before, run)

    step = TRIGGERS
    try:
        if TRIGGERS in steps:
            _report(on_step, TRIGGERS, RUNNING)
            for unit in plan.triggers:
                try:
                    disable_now(unit, run=run)
                except SystemctlError as exc:
                    raise RemovalError(f"Cannot disable {unit}:\n{exc}") from None
                undo.disabled.append(unit)
            _report(on_step, TRIGGERS, DONE)

        if SERVICE in steps:
            step = SERVICE
            _report(on_step, SERVICE, RUNNING)
            try:
                disable_now(plan.service, run=run)
            except SystemctlError as exc:
                raise RemovalError(f"Cannot stop and disable {plan.service}:\n{exc}") from None
            undo.disabled.append(plan.service)
            if live:
                _wait_until_stopped(plan.service, run, clock, sleep)
                remaining = find_processes(confdir, home=home, proc_root=proc_root)
                if remaining:
                    raise RemovalError("onedrive is still running for the account after the service stopped.\n"
                                       + _describe(remaining))
            else:
                log.warning("SAFE MODE: not waiting for %s to stop", plan.service)
            _report(on_step, SERVICE, DONE)

        if UPLOAD in steps:
            step = UPLOAD
            if not live and popen is None:
                log.warning("SAFE MODE: not uploading the local changes of %s", account.name)
                _report(on_step, UPLOAD, DONE)
            else:
                upload = Upload(confdir, popen or sideeffects.popen,
                                lambda progress: _report(on_step, UPLOAD, RUNNING, progress),
                                cancel=cancel, send_signal=send_signal, clock=clock, sleep=sleep)
                _report(on_step, UPLOAD, RUNNING, upload.progress)
                try:
                    stopped = run_upload(upload, cancel)
                except ApplyError as exc:
                    raise RemovalError(str(exc)) from None
                if stopped:
                    log.info("The user stopped the upload. The account %s is not removed.", account.name)
                    _report(on_step, UPLOAD, CANCELLED, upload.progress)
                    failed = undo()
                    if failed:
                        raise RemovalError("The removal is stopped. " + _undo_text(failed))
                    return RemovalResult(outcome=CANCELLED)
                _report(on_step, UPLOAD, DONE, upload.progress)
    except RemovalError as exc:
        _report(on_step, step, FAILED)
        failed = undo()
        raise RemovalError(f"{exc}\n{_undo_text(failed)}") from None

    # From here, the service is disabled. An error does not undo, but tells what to do.
    if UNITS in steps:
        step = UNITS
        _report(on_step, UNITS, RUNNING)
        try:
            _remove_unit_files(plan, run)
        except (OSError, SystemctlError) as exc:
            _report(on_step, UNITS, FAILED)
            names = ", ".join(str(p) for p in plan.unit_files)
            raise RemovalError(f"The service is disabled, but Skyhus could not remove the unit files: {exc}\n"
                               f"Remove these files yourself: {names}") from None
        _report(on_step, UNITS, DONE)

    _report(on_step, TOKEN, RUNNING)
    try:
        _delete_token(confdir)
    except OSError as exc:
        _report(on_step, TOKEN, FAILED)
        raise RemovalError(f"The service is disabled, but Skyhus could not delete the sign-in token: {exc}\n"
                           f"Remove the folder {confdir} yourself.") from None
    _report(on_step, TOKEN, DONE)

    _report(on_step, CONFIG, RUNNING)
    if not _to_trash(trash, confdir):
        _report(on_step, CONFIG, FAILED)
        raise RemovalError(f"The service is disabled, but Skyhus could not move the config folder to Trash.\n"
                           f"Remove the folder {confdir} yourself.")
    _report(on_step, CONFIG, DONE)

    result = RemovalResult()
    if SYNC in steps:
        _report(on_step, SYNC, RUNNING)
        if _to_trash(trash, plan.sync_path):
            _report(on_step, SYNC, DONE)
        else:
            _report(on_step, SYNC, FAILED)
            result.sync_folder_left = plan.sync_path

    _report(on_step, CLEANUP, RUNNING)
    if live:
        Registry.for_home(home).remove(confdir)
        if plan.service:
            clear_resync_cancelled(plan.service, home=home)
    else:
        log.warning("SAFE MODE: not removing %s from the registry", account.name)
    _report(on_step, CLEANUP, DONE)
    log.info("The account %s is removed", account.name)
    return result


def _remove_unit_files(plan: RemovalPlan, run: Run) -> None:
    removed = False
    for path in plan.unit_files:
        if not sideeffects.guard_write(path):
            continue
        path.unlink(missing_ok=True)
        log.info("Removed %s", path)
        removed = True
        if path.name == RESYNC_DROP_IN:
            try:
                path.parent.rmdir()
            except OSError:
                pass
    if removed:
        daemon_reload(run=run)


def _delete_token(confdir: Path) -> None:
    """Delete ``refresh_token`` permanently. It is a secret and must not go to Trash."""
    token = confdir / "refresh_token"
    if sideeffects.guard_write(token):
        token.unlink(missing_ok=True)
        log.info("Deleted %s", token)


def _to_trash(trash: Trash, path: Path) -> bool:
    try:
        moved = trash(path)
    except OSError as exc:
        log.warning("Cannot move %s to Trash: %s", path, exc)
        return False
    if not moved:
        log.warning("Cannot move %s to Trash", path)
    return bool(moved)
