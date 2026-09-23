"""Find running ``onedrive`` processes for a config folder via ``/proc``."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .accounts import DEFAULT_CONFDIR_NAME, config_home, home_dir

log = logging.getLogger(__name__)

PROC_ROOT = Path("/proc")


@dataclass(frozen=True)
class OnedriveProcess:
    pid: int
    args: list[str]
    unit: str
    """The systemd unit that the process runs in, for example ``onedrive-privat.service``.
    Empty if the process does not run in a service."""


def _expand(value: str, home: Path) -> str:
    if value == "~" or value.startswith("~/"):
        value = str(home) + value[1:]
    return os.path.normpath(value)


def confdir_of(args: list[str], home: Path | None = None) -> str:
    """The config folder that an ``onedrive`` command uses."""
    home = home_dir(home)
    for i, arg in enumerate(args[1:], start=1):
        if arg.startswith("--confdir="):
            return _expand(arg.split("=", 1)[1], home)
        if arg == "--confdir" and i + 1 < len(args):
            return _expand(args[i + 1], home)
    return os.path.normpath(str(config_home(home) / DEFAULT_CONFDIR_NAME))


def _unit_of(proc_dir: Path) -> str:
    try:
        text = (proc_dir / "cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        last = line.rsplit("/", 1)[-1]
        if last.endswith(".service") and not last.startswith("user@"):
            return last
    return ""


def find_processes(confdir: Path, *, home: Path | None = None,
                   proc_root: Path = PROC_ROOT) -> list[OnedriveProcess]:
    target = os.path.normpath(os.path.expanduser(str(confdir)))
    found = []
    try:
        entries = sorted((e for e in Path(proc_root).iterdir() if e.name.isdigit()), key=lambda e: int(e.name))
    except OSError as exc:
        log.warning("Cannot read %s: %s", proc_root, exc)
        return []
    for entry in entries:
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        args = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
        if not args or os.path.basename(args[0]) != "onedrive":
            continue
        if confdir_of(args, home) == target:
            found.append(OnedriveProcess(int(entry.name), args, _unit_of(entry)))
    return found


def cmdline(pid: int, proc_root: Path = PROC_ROOT) -> list[str]:
    """The command line of the process ``pid`` from ``/proc/<pid>/cmdline``. Empty if it cannot be read."""
    if pid <= 0:
        return []
    try:
        raw = (Path(proc_root) / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
