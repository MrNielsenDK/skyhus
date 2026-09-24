"""The activity of an account from the journal of its service (feature 0019).

``parse()`` turns the client's journal lines into events: files that the
client downloaded, uploaded or deleted, files that failed, problems such as
no connection, and the end of each sync. ``Activity`` keeps the events of the
last 24 hours for 1 service and gives the summary, the grouped problems and the
recent files for the card "Activity".

The line texts are checked against the strings in ``/usr/bin/onedrive`` 2.5.11.
Other lines are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .journal import CLIENT_IDENTIFIER, ERROR_MESSAGE_PREFIX, ERROR_PREFIX, Entry
from .service_state import format_when

WINDOW_SECONDS = 24 * 3600
LIMIT_TEXT = "(only the newest 50,000 lines)"

DOWNLOADED = "downloaded"
UPLOADED = "uploaded"
DELETED_ONLINE = "deleted_online"
DELETED_LOCAL = "deleted_local"
FAILED = "failed"
PROBLEM = "problem"
SYNCED = "synced"
FILE_KINDS = frozenset({DOWNLOADED, UPLOADED, DELETED_ONLINE, DELETED_LOCAL, FAILED})

REASON_DISK_SPACE = "not enough disk space"
NO_CONNECTION = "No connection to Microsoft OneDrive"
HTTP_429 = "Microsoft asked the client to wait (HTTP 429)"
HTTP_408 = "Microsoft did not answer in time (HTTP 408)"
HTTP_503 = "Microsoft OneDrive was not available (HTTP 503)"

_DONE = re.compile(r"^(Downloading file|Uploading new file|Uploading modified file): (.+) \.\.\. done$")
_FAILED = re.compile(r"^(Downloading|Uploading)[^:]*: (.+) \.\.\. failed!$")
_DELETED_ONLINE = re.compile(r"^Deleting (?:item|online file|online folder) from Microsoft OneDrive: (.+)$")
_DELETED_LOCAL = re.compile(r"^Deleting local (?:file|directory): (.+)$")
_DISK_SPACE = "Insufficient local disk space to download file"
_CONNECTION = ("Cannot connect to the Microsoft OneDrive Service - Network Connection Issue",
               "Internet connectivity to Microsoft OneDrive service has been interrupted")
_HTTP = ((re.compile(r"HTTP 429 Response Code"), HTTP_429),
         (re.compile(r"HTTP 408 Response Code"), HTTP_408),
         (re.compile(r"status code 503"), HTTP_503))
_SYNC_COMPLETE = "Sync with Microsoft OneDrive is complete"
_NETWORK_ERRORS = ("Could not resolve hostname", "Couldn't resolve host", "Couldn't connect to server",
                   "Timeout was reached")
"""Error details that mean that the network was down, for example after sleep."""
_VARIABLE = re.compile(r"\b(?:on handle [0-9A-Fa-f]+|0x[0-9A-Fa-f]+|[0-9A-Fa-f]{10,})\b")
"""Parts of an error text that change each time, such as handles. They are removed before grouping."""


@dataclass(frozen=True)
class Event:
    kind: str
    when: float
    """Seconds since 1970."""
    path: str = ""
    reason: str = ""
    message: str = ""
    direction: str = ""
    """``Download`` or ``Upload`` for a failed file."""
    is_error: bool = False
    """The problem comes from an ``ERROR:`` line."""


@dataclass(frozen=True)
class Problem:
    title: str
    count: int
    newest: float
    example: str
    tone: str
    """``danger`` for failed files and errors, ``warning`` for the other problems."""


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _error_detail(entries: list[Entry], index: int) -> str:
    """The text after ``Error Message:`` in the indented lines just after ``entries[index]``."""
    error = entries[index]
    for entry in entries[index + 1:]:
        if entry.identifier != error.identifier or entry.pid != error.pid or not entry.message.strip():
            continue
        if not entry.message[:1].isspace():
            return ""
        text = entry.message.strip()
        if text.startswith(ERROR_MESSAGE_PREFIX):
            return _one_line(text[len(ERROR_MESSAGE_PREFIX):])
    return ""


def parse(entries: list[Entry]) -> list[Event]:
    """The events in the journal lines, the oldest first."""
    events: list[Event] = []
    reasons: dict[str, str] = {}
    for index, entry in enumerate(entries):
        if entry.identifier != CLIENT_IDENTIFIER:
            continue
        text = entry.message.strip()
        when = entry.timestamp
        if text == _DISK_SPACE:
            reasons[entry.pid] = REASON_DISK_SPACE
            continue
        match = _DONE.match(text)
        if match:
            reasons.pop(entry.pid, None)
            kind = DOWNLOADED if match.group(1).startswith("Downloading") else UPLOADED
            events.append(Event(kind, when, match.group(2)))
            continue
        match = _FAILED.match(text)
        if match:
            events.append(Event(FAILED, when, match.group(2), reason=reasons.pop(entry.pid, ""),
                                direction="Download" if match.group(1) == "Downloading" else "Upload"))
            continue
        match = _DELETED_ONLINE.match(text)
        if match:
            events.append(Event(DELETED_ONLINE, when, match.group(1)))
            continue
        match = _DELETED_LOCAL.match(text)
        if match:
            events.append(Event(DELETED_LOCAL, when, match.group(1)))
            continue
        if text.startswith(ERROR_PREFIX):
            detail = _error_detail(entries, index) or _one_line(text[len(ERROR_PREFIX):])
            if any(marker in detail for marker in _NETWORK_ERRORS):
                events.append(Event(PROBLEM, when, message=NO_CONNECTION))
            else:
                detail = _one_line(_VARIABLE.sub("", detail))
                events.append(Event(PROBLEM, when, message=f"Error: {detail}", is_error=True))
            continue
        if text.startswith(_CONNECTION):
            events.append(Event(PROBLEM, when, message=NO_CONNECTION))
            continue
        for pattern, message in _HTTP:
            if pattern.search(text):
                events.append(Event(PROBLEM, when, message=message))
                break
        else:
            if text == _SYNC_COMPLETE:
                events.append(Event(SYNCED, when))
    return events


def _title(event: Event) -> str:
    if event.kind == FAILED:
        base = f"{event.direction} failed"
        return f"{base}: {event.reason}" if event.reason else base
    return event.message


class Activity:
    """The events of the last 24 hours for 1 service. Only in memory."""

    def __init__(self):
        self._events: list[Event] = []
        self.truncated = False

    def replace(self, events: Iterable[Event], now: float, truncated: bool = False) -> None:
        self._events = []
        self.truncated = truncated
        self.add(events, now)

    def add(self, events: Iterable[Event], now: float) -> None:
        self._events.extend(events)
        cutoff = now - WINDOW_SECONDS
        self._events = [e for e in self._events if e.when >= cutoff]

    def summary(self, now: datetime) -> str:
        counts = {DOWNLOADED: 0, UPLOADED: 0, FAILED: 0}
        deleted = 0
        last_sync = None
        for event in self._events:
            if event.kind in counts:
                counts[event.kind] += 1
            elif event.kind in (DELETED_ONLINE, DELETED_LOCAL):
                deleted += 1
            elif event.kind == SYNCED and (last_sync is None or event.when > last_sync):
                last_sync = event.when
        parts = [f"{n} {label}" for n, label in ((counts[DOWNLOADED], "downloaded"), (counts[UPLOADED], "uploaded"),
                                                  (deleted, "deleted"), (counts[FAILED], "failed")) if n]
        pieces = []
        if last_sync is not None:
            pieces.append(f"Last sync: {format_when(datetime.fromtimestamp(last_sync), now)}")
        if parts:
            pieces.append("24 h: " + ", ".join(parts))
        text = " · ".join(pieces) if pieces else "No activity in the last 24 hours"
        return f"{text} {LIMIT_TEXT}" if self.truncated else text

    def problems(self) -> list[Problem]:
        """1 row for each kind of problem, the newest problem first."""
        groups: dict[str, list[Event]] = {}
        for event in self._events:
            if event.kind in (FAILED, PROBLEM):
                groups.setdefault(_title(event), []).append(event)
        problems = []
        for title, events in groups.items():
            newest = max(events, key=lambda e: e.when)
            with_path = [e for e in events if e.path]
            example = max(with_path, key=lambda e: e.when).path if with_path else ""
            tone = "danger" if newest.kind == FAILED or newest.is_error else "warning"
            problems.append(Problem(title, len(events), newest.when, example, tone))
        return sorted(problems, key=lambda p: p.newest, reverse=True)

    def recent(self, limit: int) -> list[Event]:
        """The newest file events, the newest first."""
        files = [e for e in self._events if e.kind in FILE_KINDS]
        return sorted(files, key=lambda e: e.when, reverse=True)[:limit]


def problem_line(problem: Problem, now: datetime) -> str:
    times = "1 time" if problem.count == 1 else f"{problem.count} times"
    parts = [problem.title, times, format_when(datetime.fromtimestamp(problem.newest), now)]
    if problem.example:
        parts.append(problem.example)
    return " · ".join(parts)


def problems_text(problems: list[Problem], now: datetime) -> str:
    """The text for "Copy problems": 1 line per problem."""
    return "\n".join(problem_line(p, now) for p in problems)
