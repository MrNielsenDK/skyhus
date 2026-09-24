"""The latest error line from the journal of a service (feature 0004).

The rule:

1. Take the newest line from ``onedrive`` that starts with ``ERROR:``, or that
   says that the client needs ``--resync``. The client does not write ``ERROR:``
   in front of that message when it stops with exit code 126.
2. The client writes details in indented lines just after the ``ERROR:`` line,
   for example ``Calling Function:``, ``Path:`` and ``Error Message:``. If there
   is an ``Error Message:`` line among them, the application uses it.
3. If there is no error line from ``onedrive``, take the newest line from
   ``systemd`` with ``Failed with result``.

``invocation_lines()`` gives the lines from the current run of the service
(feature 0009). With a cursor it gives only the lines after the cursor.
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
    """``__REALTIME_TIMESTAMP`` as seconds since 1970. 0 if the field is missing."""


def journal_command(service: str) -> list[str]:
    return ["journalctl", "--user", "-u", service, "-n", str(JOURNAL_LINES), "-o", "json", "--no-pager"]


def invocation_command(service: str, invocation_id: str, after_cursor: str = "") -> list[str]:
    cmd = ["journalctl", "--user", "-u", service, f"_SYSTEMD_INVOCATION_ID={invocation_id}",
           "-o", "json", "--no-pager"]
    if after_cursor:
        cmd.append(f"--after-cursor={after_cursor}")
    return cmd


def _message(value) -> str:
    # journalctl writes a message as a list of bytes if it is not valid UTF-8.
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
    """The lines from ``journalctl -o json``, the oldest first."""
    return [_entry(data) for data in _records(output)]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _is_client_error(entry: Entry) -> bool:
    if entry.identifier != CLIENT_IDENTIFIER:
        return False
    text = entry.message.strip()
    return text.startswith(ERROR_PREFIX) or RESYNC_REQUIRED in text


def _error_message_after(entries: list[Entry], index: int) -> str:
    """``Error Message:`` among the indented lines just after ``entries[index]``."""
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
    """The error line that the card shows, or empty."""
    for index in range(len(entries) - 1, -1, -1):
        if _is_client_error(entries[index]):
            return _error_message_after(entries, index) or _one_line(entries[index].message)
    for entry in reversed(entries):
        if entry.identifier == SYSTEMD_IDENTIFIER and FAILED_WITH_RESULT in entry.message:
            return _one_line(entry.message)
    return ""


def read_latest_error(service: str, run: Run | None = None) -> str:
    """Run ``journalctl`` for the service. An error gives an empty error line."""
    run = run or sideeffects.run
    cmd = journal_command(service)
    try:
        result = run(cmd, capture_output=True, text=True, timeout=JOURNALCTL_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Cannot read the journal for %s: %s", service, exc)
        return ""
    if result.returncode != 0:
        log.warning("journalctl failed for %s: %s", service, (result.stderr or "").strip())
        return ""
    return latest_error(parse_entries(result.stdout or ""))


ACTIVITY_LIMIT = 50_000
ACTIVITY_SINCE = "-24h"


def activity_command(service: str, after_cursor: str = "", limit: int = ACTIVITY_LIMIT,
                     since: str = ACTIVITY_SINCE) -> list[str]:
    cmd = ["journalctl", "--user", "-u", service, "-o", "json", "--no-pager", "-n", str(limit)]
    if after_cursor:
        cmd.append(f"--after-cursor={after_cursor}")
    else:
        cmd += ["--since", since]
    return cmd


def activity_lines(service: str, after_cursor: str = "", limit: int = ACTIVITY_LIMIT,
                   since: str = ACTIVITY_SINCE, run: Run | None = None) -> tuple[list[Entry], str, bool]:
    """The lines for the card "Activity" (feature 0019), the last cursor, and whether the limit was reached.

    Without a cursor, the function reads the lines ``since``. With a cursor, only the lines after it.
    """
    run = run or sideeffects.run
    cmd = activity_command(service, after_cursor, limit, since)
    try:
        result = run(cmd, capture_output=True, text=True, timeout=JOURNALCTL_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Cannot read the journal for %s: %s", service, exc)
        return [], after_cursor, False
    if result.returncode != 0:
        log.warning("journalctl failed for %s: %s", service, (result.stderr or "").strip())
        return [], after_cursor, False
    entries, cursor = [], after_cursor
    for data in _records(result.stdout or ""):
        entries.append(_entry(data))
        cursor = str(data.get("__CURSOR") or cursor)
    return entries, cursor, len(entries) >= limit


def invocation_lines(service: str, invocation_id: str, after_cursor: str = "",
                     run: Run | None = None) -> tuple[list[Entry], str]:
    """The lines from the run ``invocation_id`` of the service, and the last cursor.

    With ``after_cursor`` the function gives only the lines after it. If there
    are no new lines, or ``journalctl`` fails, the cursor does not change.
    """
    run = run or sideeffects.run
    cmd = invocation_command(service, invocation_id, after_cursor)
    try:
        result = run(cmd, capture_output=True, text=True, timeout=JOURNALCTL_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Cannot read the journal for %s: %s", service, exc)
        return [], after_cursor
    if result.returncode != 0:
        log.warning("journalctl failed for %s: %s", service, (result.stderr or "").strip())
        return [], after_cursor
    entries, cursor = [], after_cursor
    for data in _records(result.stdout or ""):
        entries.append(_entry(data))
        cursor = str(data.get("__CURSOR") or cursor)
    return entries, cursor
