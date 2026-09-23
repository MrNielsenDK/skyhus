"""Systemd-user-service for en konto.

Unit-filen følger formen på ``onedrive-privat.service``.
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
# OneDrive-konto "{comment}". Oprettet af onedrive-gui.
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
# Genstart ikke hvis der kræves --resync (exit code 126)
RestartPreventExitStatus=126
TimeoutStopSec=90

[Install]
WantedBy=default.target
"""


class ServiceExistsError(FileExistsError):
    pass


class SystemctlError(RuntimeError):
    """``systemctl`` fejlede. Beskeden er ``systemctl``'s egen fejltekst."""


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
    """Skriv unit-filen for kontoen og returnér dens navn.

    En eksisterende fil med samme navn bliver ikke overskrevet.
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
        raise ServiceExistsError(f"Servicen {name} findes allerede. Applikationen overskriver den ikke.") from None
    log.info("Skrev %s", path)
    return name


def systemctl(*args: str, run: Callable[..., subprocess.CompletedProcess] | None = None) -> str:
    """Kør ``systemctl --user`` og returnér dens stdout."""
    run = run or sideeffects.run
    cmd = ["systemctl", "--user", *args]
    log.info("Kører %s", " ".join(cmd))
    try:
        result = run(cmd, capture_output=True, text=True, timeout=SYSTEMCTL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise SystemctlError(f"{' '.join(cmd)} svarede ikke inden {SYSTEMCTL_TIMEOUT_SECONDS} sekunder.") from None
    except OSError as exc:
        raise SystemctlError(f"Kan ikke køre systemctl: {exc}") from None
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise SystemctlError(message or f"{' '.join(cmd)} fejlede med exit-kode {result.returncode}.")
    return result.stdout or ""


def enable_now(service: str, run: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
    systemctl("daemon-reload", run=run)
    systemctl("enable", "--now", service, run=run)


def restart(service: str, run: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
    systemctl("restart", service, run=run)
