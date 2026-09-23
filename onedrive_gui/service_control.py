"""Styr en kontos service: stop, start, genstart og genstart med ``--resync``.

En genstart med ``--resync`` bruger en midlertidig drop-in. Drop-in'en
kopierer den gældende ``ExecStart`` og tilføjer ``--resync --resync-auth``.
Applikationen fjerner drop-in'en igen, når servicen er genstartet. Unit-filen
selv ændrer sig ikke.

Knapperne i kortet "Service" (feature 0004) bruger ``perform()``. Den udfører
handlingen og venter, til servicen er "Kører", "Fejlet" eller "Kræver resync".

``cancel_resync()`` stopper en service under en resync og skriver markeringen
for "Resync afbrudt" (feature 0010). ``perform()`` fjerner markeringen, når
servicen er startet igen.
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

RESYNC_DROP_IN = "zz-onedrive-gui-resync.conf"
RESYNC_FLAGS = "--resync --resync-auth"
# Servicen har TimeoutStopSec=90. En genstart kan derfor tage over 1 minut.
SETTLE_TIMEOUT_SECONDS = 120
SETTLE_POLL_SECONDS = 1

Run = Callable[..., subprocess.CompletedProcess]


class ServiceTimeoutError(SystemctlError):
    """Servicen nåede ikke en fast tilstand inden for tidsgrænsen."""


def stop(service: str, run: Run | None = None) -> None:
    systemctl("stop", service, run=run)


def start(service: str, run: Run | None = None) -> None:
    systemctl("start", service, run=run)


def cancel_resync(service: str, *, home: Path | None = None, run: Run | None = None) -> None:
    """Knappen "Afbryd resync": stop servicen, og husk, at resync er afbrudt.

    Fejler ``systemctl stop``, giver funktionen ``SystemctlError`` og skriver ingen markering.
    I sikker tilstand når stoppet kun ``systemctl``, når kalderen giver sin egen ``run``.
    Ellers skriver funktionen heller ingen markering (feature 0011).
    """
    unit = read_units([service], run=run).get(service)
    invocation = unit.invocation_id if unit is not None else ""
    stop(service, run=run)
    injected = run is not None and run is not sideeffects.run
    if sideeffects.safe_mode() and not injected:
        log.warning("SAFE MODE: skriver ikke markeringen for %s", service)
        return
    mark_resync_cancelled(service, invocation, home=home)


def reset_and_restart(service: str, run: Run | None = None) -> None:
    """Knapperne "Start" og "Genstart": nulstil en fejlet tilstand og genstart."""
    systemctl("reset-failed", service, run=run)
    systemctl("restart", service, run=run)


def resync_drop_in_path(service: str, home: Path | None = None) -> Path:
    return unit_dir(home) / f"{service}.d" / RESYNC_DROP_IN


def effective_exec_start(cat_output: str) -> str:
    """Den ``ExecStart``, som gælder efter unit-filen og alle drop-ins.

    En tom ``ExecStart=`` nulstiller listen, som i systemd.
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
        raise SystemctlError(f"Servicen skal have præcis 1 ExecStart. Den har {len(commands)}.")
    return commands[0]


def restart_with_resync(service: str, *, home: Path | None = None, run: Run | None = None) -> None:
    """Genstart servicen én gang med ``--resync --resync-auth``."""
    exec_start = effective_exec_start(systemctl("cat", service, run=run))
    path = resync_drop_in_path(service, home)
    if sideeffects.guard_write(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Midlertidig. onedrive-gui fjerner filen efter genstart.\n"
            "[Service]\nExecStart=\n"
            f"ExecStart={exec_start} {RESYNC_FLAGS}\n", encoding="utf-8")
        log.info("Skrev %s", path)
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
        log.info("Fjernede %s", path)
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
    """Spørg ``read_state``, til tilstanden er i ``SETTLED``, eller tiden er gået."""
    while True:
        try:
            state = read_state()
        except SystemctlError as exc:
            log.warning("Kan ikke læse status under ventetiden: %s", exc)
            state = ""
        if state in SETTLED:
            return state
        if clock() >= deadline:
            raise ServiceTimeoutError("Servicen svarer ikke.")
        sleep(SETTLE_POLL_SECONDS)


def perform(action: str, service: str, read_state: Callable[[], str], *,
            home: Path | None = None, run: Run | None = None,
            clock: Callable[[], float] | None = None,
            sleep: Callable[[float], None] | None = None,
            timeout: float = SETTLE_TIMEOUT_SECONDS) -> str:
    """Udfør "start", "restart" eller "resync" og returnér den tilstand, servicen endte i.

    En fejl fra ``systemctl`` giver ``SystemctlError`` med ``systemctl``'s egen
    besked. Når servicen ikke falder til ro, giver den ``ServiceTimeoutError``.
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
        raise ValueError(f"Ukendt handling: {action}")
    clear_resync_cancelled(service, home=home)
    return wait_until_settled(read_state, deadline=deadline, clock=clock, sleep=sleep)
