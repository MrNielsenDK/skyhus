"""Progress from the lines of the client (feature 0009).

``SyncProgress.feed(line)`` updates the progress from 1 line that ``onedrive``
writes on stdout or in the journal. The client writes the lines without
``--verbose``. The rules:

- A line that starts with a text in ``PHASES`` changes the phase. Some of the
  lines also give the total number of files. The number of done files starts
  again at each new phase.
- When the phase is "Finishing", it does not change again. The client gets the
  list from OneDrive one last time in that phase.
- ``Downloading file: … done``, ``Uploading new file: … done`` and
  ``Uploading modified file: … done`` count 1 file.
- ``Downloading: <path> ... 45%`` sets the latest file and the percent.
- ``Sync with Microsoft OneDrive is complete`` and ``Sync with Microsoft
  OneDrive has completed, however …`` give the result. After that, no line
  changes the progress.
- All other lines change nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

CHECKING_DATABASE = "Checking the local database"
FETCHING = "Getting the list from OneDrive"
PROCESSING = "Processing items from OneDrive"
DOWNLOADING = "Downloading files"
SCANNING = "Scanning local files"
UPLOADING = "Uploading files"
FINISHING = "Finishing"

# (pattern, phase). A group in the pattern is the total number of files in the phase.
PHASES = (
    (re.compile(r"Performing a database consistency and integrity check"), CHECKING_DATABASE),
    (re.compile(r"Fetching items from the OneDrive API"), FETCHING),
    (re.compile(r"Processing \d+ applicable"), PROCESSING),
    (re.compile(r"Number of items to download from Microsoft OneDrive: (\d+)"), DOWNLOADING),
    (re.compile(r"Scanning the local file system"), SCANNING),
    (re.compile(r"New items to upload to Microsoft OneDrive: (\d+)"), UPLOADING),
    (re.compile(r"Performing a last examination of the most recent online data"), FINISHING),
)

_FILE_DONE = re.compile(r"(?:Downloading file|Uploading new file|Uploading modified file): (.+) \.\.\. done$")
_PERCENT = re.compile(r"Downloading: (.+) \.\.\. (\d+)%")
_FAILED_ITEMS = re.compile(r"Failed items to download to/from Microsoft OneDrive: (\d+)")

COMPLETE_LINE = "Sync with Microsoft OneDrive is complete"
COMPLETE_WITH_FAILURES_LINE = "Sync with Microsoft OneDrive has completed, however there are items that failed to sync"

COMPLETE = "complete"
COMPLETE_WITH_FAILURES = "complete_with_failures"


def _path(value: str) -> str:
    """The client writes ``./`` in front of new files on upload. The user interface shows the path without it."""
    return value[2:] if value.startswith("./") else value


@dataclass
class SyncProgress:
    phase: str = ""
    done: int = 0
    """The number of done files in the phase."""
    total: int | None = None
    """The total number of files in the phase. ``None`` when the client has not written it."""
    latest: str = ""
    percent: int | None = None
    """The percent for the latest file, if the client has written it."""
    started: float | None = None
    """The time of the first line, as seconds since 1970."""
    finished: float | None = None
    """The time of the line with the result."""
    result: str = ""
    """Empty, ``COMPLETE`` or ``COMPLETE_WITH_FAILURES``."""
    failed: int = 0
    """The number from ``Failed items to download to/from Microsoft OneDrive: <N>``."""

    @property
    def determinate(self) -> bool:
        return self.total is not None

    @property
    def fraction(self) -> float:
        """The fraction of done files from 0 to 1. 0 when the total is not known."""
        if not self.total:
            return 0.0
        return min(1.0, self.done / self.total)

    def snapshot(self) -> "SyncProgress":
        """A copy that another thread can read while this one changes."""
        return replace(self)

    def feed(self, line: str, when: float | None = None) -> bool:
        """Update the progress from 1 line. Return true if something changed."""
        if self.result:
            return False
        if when is not None and self.started is None:
            self.started = when
        text = line.strip()
        if not text:
            return False
        if text.startswith(COMPLETE_LINE):
            self.result = COMPLETE
            self.finished = when
            return True
        if text.startswith(COMPLETE_WITH_FAILURES_LINE):
            self.result = COMPLETE_WITH_FAILURES
            self.finished = when
            return True
        match = _FILE_DONE.match(text)
        if match:
            self.done += 1
            self.latest = _path(match.group(1))
            self.percent = None
            return True
        match = _PERCENT.match(text)
        if match:
            self.latest = _path(match.group(1))
            self.percent = int(match.group(2))
            return True
        match = _FAILED_ITEMS.match(text)
        if match:
            self.failed = int(match.group(1))
            return True
        for pattern, phase in PHASES:
            match = pattern.match(text)
            if match:
                return self._set_phase(phase, match)
        return False

    def _set_phase(self, phase: str, match: re.Match) -> bool:
        if self.phase == FINISHING:
            return False
        self.phase = phase
        self.total = int(match.group(1)) if match.groups() else None
        self.done = 0
        self.latest = ""
        self.percent = None
        return True


def count_text(done: int, total: int | None, singular: str = "file", plural: str = "files") -> str:
    """"30 of 120 files", "1 of 1 file" or "15 files"."""
    if total is None:
        return f"{done} {singular if done == 1 else plural}"
    return f"{done} of {total} {singular if total == 1 else plural}"


def format_duration(seconds: float) -> str:
    """"less than 1 min", "12 min" or "3 h 2 min"."""
    minutes = int(max(0, seconds)) // 60
    if minutes < 1:
        return "less than 1 min"
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"
