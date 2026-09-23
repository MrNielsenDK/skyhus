"""Safe mode (feature 0007) and the functions that change the system.

The rest of the application calls ``run``, ``popen`` and ``trash`` here instead
of ``subprocess.run``, ``subprocess.Popen`` and ``QFile.moveToTrash``. Before a
file is written or deleted, the code calls ``guard_write(path)``. A
signal to a process goes through ``signal_process`` (feature 0010).

In safe mode the application changes nothing on the system. A blocked
action gives a line in the log that starts with ``SAFE MODE:``.

Safe mode is on when at least 1 of these conditions applies:

- the environment variable ``SKYHUS_SAFE_MODE`` or the old ``ONEDRIVE_GUI_SAFE_MODE`` is ``1``,
- the application was started with ``--safe``,
- ``HOME`` is a different folder than the real home folder of the user.

The result is fixed from when the application starts. ``init()`` checks
the conditions. If ``safe_mode()`` is called before ``init()``, it uses ``sys.argv``.
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
"""The old name from before feature 0012. An old script must not run in normal mode."""
FLAG = "--safe"
NOT_STARTED = "Safe mode: {name} was not started"

READ_ONLY_SYSTEMCTL = frozenset({"show", "cat", "status", "is-active"})
READ_ONLY_PROGRAMS = frozenset({"journalctl"})

_state: bool | None = None


def real_home() -> Path:
    """The real home folder of the user. It does not depend on ``HOME``."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def _same_dir(a: str, b: Path) -> bool:
    return os.path.realpath(os.path.expanduser(a)) == os.path.realpath(b)


def reasons(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> list[str]:
    """The conditions that turn on safe mode. An empty list means normal mode."""
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
        found.append(f"HOME={home} is not the real home folder {real_home()}")
    return found


def init(argv: Sequence[str] | None = None) -> bool:
    """Check the conditions one time and lock the result."""
    global _state
    found = reasons(argv)
    _state = bool(found)
    if _state:
        log.warning("SAFE MODE: safe mode is on (%s)", "; ".join(found))
    return _state


def reset() -> None:
    """Forget the result. Only the tests use this function."""
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
    return NOT_STARTED.format(name=_program(cmd) or "the command")


def run(args, **kwargs) -> subprocess.CompletedProcess:
    """``subprocess.run`` that follows the rules for safe mode."""
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
    """The same as a ``Popen`` process that stopped with exit code 1 immediately."""

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
    """``subprocess.Popen`` that follows the rules for safe mode."""
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
    """Send ``sig`` to ``process``. In safe mode the function sends nothing.

    In safe mode ``popen`` does not start ``onedrive``. So there is no
    real process to stop. A process that is already stopped gives no error.
    """
    name = _signal_name(sig)
    pid = getattr(process, "pid", "?")
    if safe_mode():
        log.warning("SAFE MODE: not sending %s to PID %s", name, pid)
        return
    log.info("Sending %s to PID %s", name, pid)
    try:
        process.send_signal(sig)
    except ProcessLookupError:
        log.info("PID %s is already stopped", pid)


def trash(path: Path) -> bool:
    """Move ``path`` to Trash. In safe mode the function moves nothing."""
    if safe_mode():
        log.warning("SAFE MODE: not moving %s to Trash", path)
        return True
    from PySide6.QtCore import QFile
    return bool(QFile.moveToTrash(str(path)))


def _is_under(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def guard_write(path: Path | str) -> bool:
    """Can the application write or delete ``path``? A no goes in the log.

    In safe mode the answer is no for everything under the real home folder,
    except ``~/.config/skyhus/``.
    """
    if not safe_mode():
        return True
    target = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
    home = os.path.realpath(real_home())
    allowed = os.path.join(home, ".config", GUI_DIR_NAME)
    if _is_under(target, home) and not _is_under(target, allowed):
        log.warning("SAFE MODE: not writing %s", path)
        return False
    return True
