"""Sikker tilstand (feature 0007) og de funktioner, der ændrer systemet.

Resten af applikationen kalder ``run``, ``popen`` og ``trash`` her i stedet
for ``subprocess.run``, ``subprocess.Popen`` og ``QFile.moveToTrash``. Før en
fil bliver skrevet eller slettet, kalder koden ``guard_write(path)``. Et
signal til en proces går gennem ``signal_process`` (feature 0010).

I sikker tilstand ændrer applikationen intet på systemet. En blokeret
handling giver en linje i loggen, der starter med ``SAFE MODE:``.

Sikker tilstand er slået til, når mindst 1 af disse betingelser gælder:

- miljøvariablen ``SKYHUS_SAFE_MODE`` eller den gamle ``ONEDRIVE_GUI_SAFE_MODE`` er ``1``,
- applikationen er startet med ``--safe``,
- ``HOME`` er en anden mappe end brugerens rigtige hjemmemappe.

Resultatet ligger fast, fra applikationen starter. ``init()`` vurderer
betingelserne. Kaldes ``safe_mode()`` før ``init()``, bruger den ``sys.argv``.
"""

from __future__ import annotations

import logging
import os
import pwd
import signal
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence

from .accounts import GUI_DIR_NAME

log = logging.getLogger(__name__)

ENV_VAR = "SKYHUS_SAFE_MODE"
LEGACY_ENV_VAR = "ONEDRIVE_GUI_SAFE_MODE"
"""Det gamle navn fra før feature 0012. Et gammelt script må ikke køre i skarp tilstand."""
FLAG = "--safe"
NOT_STARTED = "Sikker tilstand: {name} blev ikke startet"

READ_ONLY_SYSTEMCTL = frozenset({"show", "cat", "status", "is-active"})
READ_ONLY_PROGRAMS = frozenset({"journalctl"})

_state: bool | None = None


def real_home() -> Path:
    """Brugerens rigtige hjemmemappe. Den afhænger ikke af ``HOME``."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _same_dir(a: str, b: Path) -> bool:
    return os.path.realpath(os.path.expanduser(a)) == os.path.realpath(b)


def reasons(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> list[str]:
    """De betingelser, der slår sikker tilstand til. En tom liste betyder normal tilstand."""
    argv = sys.argv if argv is None else argv
    environ = os.environ if environ is None else environ
    found = []
    for name in (ENV_VAR, LEGACY_ENV_VAR):
        if environ.get(name) == "1":
            found.append(f"{name}=1")
    if FLAG in argv[1:]:
        found.append(FLAG)
    home = environ.get("HOME")
    if home and not _same_dir(home, real_home()):
        found.append(f"HOME={home} er ikke den rigtige hjemmemappe {real_home()}")
    return found


def init(argv: Sequence[str] | None = None) -> bool:
    """Vurdér betingelserne én gang og lås resultatet fast."""
    global _state
    found = reasons(argv)
    _state = bool(found)
    if _state:
        log.warning("SAFE MODE: sikker tilstand er slået til (%s)", "; ".join(found))
    return _state


def reset() -> None:
    """Glem resultatet. Kun testene bruger funktionen."""
    global _state
    _state = None


def safe_mode() -> bool:
    if _state is None:
        return init()
    return _state


def _command(args) -> list[str]:
    if isinstance(args, (str, bytes)):
        return [os.fsdecode(args)]
    return [os.fsdecode(a) if isinstance(a, bytes) else str(a) for a in args]


def _program(cmd: list[str]) -> str:
    return os.path.basename(cmd[0]) if cmd else ""


def _allowed(cmd: list[str]) -> bool:
    program = _program(cmd)
    if program in READ_ONLY_PROGRAMS:
        return True
    if program == "systemctl":
        verb = next((a for a in cmd[1:] if not a.startswith("-")), "")
        return verb in READ_ONLY_SYSTEMCTL
    return False


def _not_started(cmd: list[str]) -> str:
    return NOT_STARTED.format(name=_program(cmd) or "kommandoen")


def run(args, **kwargs) -> subprocess.CompletedProcess:
    """``subprocess.run``, der følger reglerne for sikker tilstand."""
    if safe_mode():
        cmd = _command(args)
        if not _allowed(cmd):
            log.warning("SAFE MODE: %s", " ".join(cmd))
            text = kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding")
            if _program(cmd) == "systemctl":
                return subprocess.CompletedProcess(args, 0, stdout="" if text else b"",
                                                   stderr="" if text else b"")
            message = _not_started(cmd)
            return subprocess.CompletedProcess(args, 1, stdout="" if text else b"",
                                               stderr=message if text else message.encode())
    return subprocess.run(args, **kwargs)


class BlockedProcess:
    """Svarer til en ``Popen``-proces, der stoppede med exit-kode 1 med det samme."""

    def __init__(self, args, message: str, stdout=None):
        self.args = args
        self.returncode = 1
        self.pid = 0
        self.stdin = self.stdout = self.stderr = None
        if stdout is not None and hasattr(stdout, "write"):
            data = message + "\n"
            try:
                stdout.write(data.encode() if "b" in getattr(stdout, "mode", "") else data)
                stdout.flush()
            except (OSError, TypeError, ValueError):
                pass

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def communicate(self, input=None, timeout=None):
        return (None, None)

    def terminate(self):
        pass

    def kill(self):
        pass

    def send_signal(self, sig):
        pass


def popen(args, **kwargs):
    """``subprocess.Popen``, der følger reglerne for sikker tilstand."""
    if safe_mode():
        cmd = _command(args)
        if not _allowed(cmd):
            log.warning("SAFE MODE: %s", " ".join(cmd))
            return BlockedProcess(args, _not_started(cmd), kwargs.get("stdout"))
    return subprocess.Popen(args, **kwargs)


def _signal_name(sig) -> str:
    try:
        return signal.Signals(sig).name
    except ValueError:
        return str(sig)


def signal_process(process, sig) -> None:
    """Send ``sig`` til ``process``. I sikker tilstand sender funktionen intet.

    I sikker tilstand starter ``popen`` ikke ``onedrive``. Der er derfor ingen
    rigtig proces at stoppe. En proces, der allerede er stoppet, giver ingen fejl.
    """
    name = _signal_name(sig)
    pid = getattr(process, "pid", "?")
    if safe_mode():
        log.warning("SAFE MODE: sender ikke %s til PID %s", name, pid)
        return
    log.info("Sender %s til PID %s", name, pid)
    try:
        process.send_signal(sig)
    except ProcessLookupError:
        log.info("PID %s er allerede stoppet", pid)


def trash(path: Path) -> bool:
    """Flyt ``path`` til papirkurven. I sikker tilstand flytter funktionen intet."""
    if safe_mode():
        log.warning("SAFE MODE: flytter ikke %s til papirkurven", path)
        return True
    from PySide6.QtCore import QFile
    return bool(QFile.moveToTrash(str(path)))


def _is_under(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def guard_write(path: Path | str) -> bool:
    """Må applikationen skrive eller slette ``path``? Et nej står i loggen.

    I sikker tilstand er svaret nej for alt under den rigtige hjemmemappe,
    undtagen ``~/.config/skyhus/``.
    """
    if not safe_mode():
        return True
    target = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
    home = os.path.realpath(real_home())
    allowed = os.path.join(home, ".config", GUI_DIR_NAME)
    if _is_under(target, home) and not _is_under(target, allowed):
        log.warning("SAFE MODE: skriver ikke %s", path)
        return False
    return True
