"""Control the service of an account: stop, start, restart and restart with ``--resync``.

A restart with ``--resync`` uses a temporary drop-in. The drop-in copies the
current ``ExecStart`` and adds ``--resync --resync-auth``. The application
removes the drop-in again when the service has restarted. The unit file itself
does not change.

The buttons in the "Service" card (feature 0004) use ``perform()``. It does
the action and waits until the service is "Running", "Failed" or "Needs resync".

``cancel_resync()`` stops a service during a resync and writes the mark for
"Resync stopped" (feature 0010). ``perform()`` removes the mark when the
service has started again.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import sideeffects
from .accounts import unit_dir
from .service import SystemctlError, systemctl
from .service_state import SETTLED, clear_resync_cancelled, mark_resync_cancelled, read_units

log = logging.getLogger(__name__)

RESYNC_DROP_IN = "zz-skyhus-resync.conf"
RESYNC_FLAGS = "--resync --resync-auth"
# The service has TimeoutStopSec=90. A restart can therefore take more than 1 minute.
SETTLE_TIMEOUT_SECONDS = 120
SETTLE_POLL_SECONDS = 1

Run = Callable[..., subprocess.CompletedProcess]


class ServiceTimeoutError(SystemctlError):
    """The service did not reach a settled state within the time limit."""


def stop(service: str, run: Run | None = None) -> None:
    systemctl("stop", service, run=run)


def start(service: str, run: Run | None = None) -> None:
    systemctl("start", service, run=run)


def cancel_resync(service: str, *, home: Path | None = None, run: Run | None = None) -> None:
    """The "Stop resync" button: stop the service, and remember that the resync is stopped.

    If ``systemctl stop`` fails, the function raises ``SystemctlError`` and writes no mark.
    In safe mode the stop only reaches ``systemctl`` when the caller gives its own ``run``.
    Otherwise the function also writes no mark (feature 0011).
    """
    unit = read_units([service], run=run).get(service)
    invocation = unit.invocation_id if unit is not None else ""
    stop(service, run=run)
    injected = run is not None and run is not sideeffects.run
    if sideeffects.safe_mode() and not injected:
        log.warning("SAFE MODE: not writing the mark for %s", service)
        return
    mark_resync_cancelled(service, invocation, home=home)


def reset_and_restart(service: str, run: Run | None = None) -> None:
    """The "Start" and "Restart" buttons: reset a failed state and restart."""
    systemctl("reset-failed", service, run=run)
    systemctl("restart", service, run=run)


def resync_drop_in_path(service: str, home: Path | None = None) -> Path:
    return unit_dir(home) / f"{service}.d" / RESYNC_DROP_IN


def effective_exec_start(cat_output: str) -> str:
    """The ``ExecStart`` that applies after the unit file and all drop-ins.

    An empty ``ExecStart=`` resets the list, as in systemd.
    """
    commands: list[str] = []
    section = ""
    for raw in cat_output.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section != "[Service]" or not line.startswith("ExecStart="):
            continue
        value = line.split("=", 1)[1].strip()
        if value:
            commands.append(value)
        else:
            commands = []
    if len(commands) != 1:
        raise SystemctlError(f"The service must have exactly 1 ExecStart. It has {len(commands)}.")
    return commands[0]


def restart_with_resync(service: str, *, home: Path | None = None, run: Run | None = None) -> None:
    """Restart the service one time with ``--resync --resync-auth``."""
    exec_start = effective_exec_start(systemctl("cat", service, run=run))
    path = resync_drop_in_path(service, home)
    if sideeffects.guard_write(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Temporary. Skyhus removes this file after the restart.\n"
            "[Service]\nExecStart=\n"
            f"ExecStart={exec_start} {RESYNC_FLAGS}\n", encoding="utf-8")
        log.info("Wrote %s", path)
    try:
        systemctl("daemon-reload", run=run)
        systemctl("restart", service, run=run)
    finally:
        remove_resync_drop_in(service, home=home, run=run)


def remove_resync_drop_in(service: str, *, home: Path | None = None, run: Run | None = None) -> None:
    path = resync_drop_in_path(service, home)
    if not sideeffects.guard_write(path):
        return
    try:
        path.unlink()
        log.info("Removed %s", path)
    except FileNotFoundError:
        return
    try:
        path.parent.rmdir()
    except OSError:
        pass
    systemctl("daemon-reload", run=run)


def wait_until_settled(read_state: Callable[[], str], *, deadline: float,
                       clock: Callable[[], float] = time.monotonic,
                       sleep: Callable[[float], None] = time.sleep) -> str:
    """Ask ``read_state`` until the state is in ``SETTLED`` or the time is up."""
    while True:
        try:
            state = read_state()
        except SystemctlError as exc:
            log.warning("Cannot read the status while waiting: %s", exc)
            state = ""
        if state in SETTLED:
            return state
        if clock() >= deadline:
            raise ServiceTimeoutError("The service does not respond.")
        sleep(SETTLE_POLL_SECONDS)


def perform(action: str, service: str, read_state: Callable[[], str], *,
            home: Path | None = None, run: Run | None = None,
            clock: Callable[[], float] | None = None,
            sleep: Callable[[float], None] | None = None,
            timeout: float = SETTLE_TIMEOUT_SECONDS) -> str:
    """Do "start", "restart" or "resync" and return the state that the service ended in.

    An error from ``systemctl`` raises ``SystemctlError`` with the message from
    ``systemctl``. When the service does not settle, it raises ``ServiceTimeoutError``.
    """
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    deadline = clock() + timeout
    if action == "resync":
        systemctl("reset-failed", service, run=run)
        restart_with_resync(service, home=home, run=run)
    elif action in ("start", "restart"):
        reset_and_restart(service, run=run)
    else:
        raise ValueError(f"Unknown action: {action}")
    clear_resync_cancelled(service, home=home)
    return wait_until_settled(read_state, deadline=deadline, clock=clock, sleep=sleep)
