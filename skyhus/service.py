"""Systemd user service for an account.

The unit file follows the form of ``onedrive-privat.service``.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

from . import sideeffects
from .accounts import ONEDRIVE, unit_dir

log = logging.getLogger(__name__)

SYSTEMCTL_TIMEOUT_SECONDS = 120

UNIT_TEMPLATE = """\
# OneDrive account "{comment}". Created by Skyhus.
[Unit]
Description=OneDrive Client for Linux ({description})
Documentation=https://github.com/abraunegg/onedrive
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5
OnFailure=onedrive-failure@%N.service

[Service]
ProtectSystem=full
ProtectHostname=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictRealtime=true
ExecStartPre=/bin/sh -c 'sleep 15'
ExecStart={onedrive} --monitor --confdir="%h/.config/{confdir_name}"
Restart=on-failure
RestartSec=3
# Do not restart if --resync is required (exit code 126)
RestartPreventExitStatus=126
TimeoutStopSec=90

[Install]
WantedBy=default.target
"""


class ServiceExistsError(FileExistsError):
    pass


class SystemctlError(RuntimeError):
    """``systemctl`` failed. The message is the error text from ``systemctl``."""


def unit_name_for(confdir: Path) -> str:
    return f"{Path(confdir).name}.service"


def render_unit(confdir_name: str, display_name: str) -> str:
    one_line = " ".join(display_name.split())
    return UNIT_TEMPLATE.format(
        comment=one_line,
        description=one_line.replace("%", "%%"),
        onedrive=ONEDRIVE,
        confdir_name=confdir_name,
    )


def write_unit(confdir: Path, display_name: str, home: Path | None = None) -> str:
    """Write the unit file for the account and return its name.

    An existing file with the same name is not overwritten.
    """
    name = unit_name_for(confdir)
    path = unit_dir(home) / name
    if not sideeffects.guard_write(path):
        return name
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8") as f:
            f.write(render_unit(Path(confdir).name, display_name))
    except FileExistsError:
        raise ServiceExistsError(f"The service {name} already exists. Skyhus does not overwrite it.") from None
    log.info("Wrote %s", path)
    return name


def systemctl(*args: str, run: Callable[..., subprocess.CompletedProcess] | None = None) -> str:
    """Run ``systemctl --user`` and return its stdout."""
    run = run or sideeffects.run
    cmd = ["systemctl", "--user", *args]
    log.info("Running %s", " ".join(cmd))
    try:
        result = run(cmd, capture_output=True, text=True, timeout=SYSTEMCTL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise SystemctlError(f"{' '.join(cmd)} did not respond within {SYSTEMCTL_TIMEOUT_SECONDS} seconds.") from None
    except OSError as exc:
        raise SystemctlError(f"Cannot run systemctl: {exc}") from None
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise SystemctlError(message or f"{' '.join(cmd)} failed with exit code {result.returncode}.")
    return result.stdout or ""


def enable_now(service: str, run: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
    systemctl("daemon-reload", run=run)
    systemctl("enable", "--now", service, run=run)


def disable_now(unit: str, run: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
    """Stop the unit and disable it (feature 0018)."""
    systemctl("disable", "--now", unit, run=run)


def daemon_reload(run: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
    systemctl("daemon-reload", run=run)


def restart(service: str, run: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
    systemctl("restart", service, run=run)
