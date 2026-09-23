"""Den seneste fejllinje fra en services journal (feature 0004).

Reglen:

1. Tag den nyeste linje fra ``onedrive``, der starter med ``ERROR:``, eller som
   siger, at klienten kræver ``--resync``. Klienten skriver ikke ``ERROR:``
   foran den besked, når den stopper med exit-kode 126.
2. Klienten skriver detaljer i indrykkede linjer lige efter ``ERROR:``-linjen,
   fx ``Calling Function:``, ``Path:`` og ``Error Message:``. Findes der en
   ``Error Message:``-linje blandt dem, bruger applikationen den.
3. Findes ingen fejllinje fra ``onedrive``, så tag den nyeste linje fra
   ``systemd`` med ``Failed with result``.

``invocation_lines()`` giver linjerne fra servicens nuværende kørsel
(feature 0009). Med en cursor giver den kun linjerne efter cursoren.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Callable

from . import sideeffects

log = logging.getLogger(__name__)

JOURNAL_LINES = 500
JOURNALCTL_TIMEOUT_SECONDS = 30
CLIENT_IDENTIFIER = "onedrive"
SYSTEMD_IDENTIFIER = "systemd"
ERROR_PREFIX = "ERROR:"
ERROR_MESSAGE_PREFIX = "Error Message:"
RESYNC_REQUIRED = "--resync is required"
FAILED_WITH_RESULT = "Failed with result"

Run = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Entry:
    identifier: str
    pid: str
    message: str
    timestamp: float = 0.0
    """``__REALTIME_TIMESTAMP`` som sekunder siden 1970. 0, hvis feltet mangler."""


def journal_command(service: str) -> list[str]:
    return ["journalctl", "--user", "-u", service, "-n", str(JOURNAL_LINES), "-o", "json", "--no-pager"]


def invocation_command(service: str, invocation_id: str, after_cursor: str = "") -> list[str]:
    cmd = ["journalctl", "--user", "-u", service, f"_SYSTEMD_INVOCATION_ID={invocation_id}",
           "-o", "json", "--no-pager"]
    if after_cursor:
        cmd.append(f"--after-cursor={after_cursor}")
    return cmd


def _message(value) -> str:
    # journalctl skriver en besked som en liste af bytes, hvis den ikke er gyldig UTF-8.
    if isinstance(value, list):
        try:
            return bytes(value).decode("utf-8", "replace")
        except (TypeError, ValueError):
            return ""
    return value if isinstance(value, str) else ""


def _timestamp(value) -> float:
    try:
        return int(value) / 1_000_000
    except (TypeError, ValueError):
        return 0.0


def _records(output: str):
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            yield data


def _entry(data: dict) -> Entry:
    return Entry(str(data.get("SYSLOG_IDENTIFIER", "")), str(data.get("_PID", "")),
                 _message(data.get("MESSAGE")), _timestamp(data.get("__REALTIME_TIMESTAMP")))


def parse_entries(output: str) -> list[Entry]:
    """Linjerne fra ``journalctl -o json``, den ældste først."""
    return [_entry(data) for data in _records(output)]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _is_client_error(entry: Entry) -> bool:
    if entry.identifier != CLIENT_IDENTIFIER:
        return False
    text = entry.message.strip()
    return text.startswith(ERROR_PREFIX) or RESYNC_REQUIRED in text


def _error_message_after(entries: list[Entry], index: int) -> str:
    """``Error Message:`` blandt de indrykkede linjer lige efter ``entries[index]``."""
    error = entries[index]
    for entry in entries[index + 1:]:
        if entry.identifier != error.identifier or entry.pid != error.pid:
            continue
        if not entry.message.strip():
            continue
        if not entry.message[:1].isspace():
            return ""
        text = entry.message.strip()
        if text.startswith(ERROR_MESSAGE_PREFIX):
            return _one_line(text)
    return ""


def latest_error(entries: list[Entry]) -> str:
    """Den fejllinje, som kortet viser, eller tom."""
    for index in range(len(entries) - 1, -1, -1):
        if _is_client_error(entries[index]):
            return _error_message_after(entries, index) or _one_line(entries[index].message)
    for entry in reversed(entries):
        if entry.identifier == SYSTEMD_IDENTIFIER and FAILED_WITH_RESULT in entry.message:
            return _one_line(entry.message)
    return ""


def read_latest_error(service: str, run: Run | None = None) -> str:
    """Kør ``journalctl`` for servicen. En fejl giver en tom fejllinje."""
    run = run or sideeffects.run
    cmd = journal_command(service)
    try:
        result = run(cmd, capture_output=True, text=True, timeout=JOURNALCTL_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Kan ikke læse journalen for %s: %s", service, exc)
        return ""
    if result.returncode != 0:
        log.warning("journalctl fejlede for %s: %s", service, (result.stderr or "").strip())
        return ""
    return latest_error(parse_entries(result.stdout or ""))


def invocation_lines(service: str, invocation_id: str, after_cursor: str = "",
                     run: Run | None = None) -> tuple[list[Entry], str]:
    """Linjerne fra servicens kørsel ``invocation_id`` og den sidste cursor.

    Med ``after_cursor`` giver funktionen kun linjerne efter den. Er der ingen
    nye linjer, eller fejler ``journalctl``, er cursoren uændret.
    """
    run = run or sideeffects.run
    cmd = invocation_command(service, invocation_id, after_cursor)
    try:
        result = run(cmd, capture_output=True, text=True, timeout=JOURNALCTL_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Kan ikke læse journalen for %s: %s", service, exc)
        return [], after_cursor
    if result.returncode != 0:
        log.warning("journalctl fejlede for %s: %s", service, (result.stderr or "").strip())
        return [], after_cursor
    entries, cursor = [], after_cursor
    for data in _records(result.stdout or ""):
        entries.append(_entry(data))
        cursor = str(data.get("__CURSOR") or cursor)
    return entries, cursor
