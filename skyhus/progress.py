"""Fremdrift fra klientens linjer (feature 0009).

``SyncProgress.feed(line)`` opdaterer fremdriften ud fra 1 linje, som
``onedrive`` skriver på stdout eller i journalen. Klienten skriver linjerne
uden ``--verbose``. Reglerne:

- En linje, der begynder med en tekst i ``PHASES``, skifter fasen. Nogle af
  linjerne giver også det samlede antal filer. Antallet af færdige filer
  starter forfra ved hver ny fase.
- Når fasen er "Afslutter", skifter den ikke igen. Klienten henter listen fra
  OneDrive en sidste gang i den fase.
- ``Downloading file: … done``, ``Uploading new file: … done`` og
  ``Uploading modified file: … done`` tæller 1 fil.
- ``Downloading: <sti> ... 45%`` sætter den seneste fil og procenten.
- ``Sync with Microsoft OneDrive is complete`` og ``Sync with Microsoft
  OneDrive has completed, however …`` giver resultatet. Derefter ændrer
  ingen linje fremdriften.
- Alle andre linjer ændrer intet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

CHECKING_DATABASE = "Kontrollerer den lokale database"
FETCHING = "Henter listen fra OneDrive"
PROCESSING = "Behandler elementer fra OneDrive"
DOWNLOADING = "Downloader filer"
SCANNING = "Scanner lokale filer"
UPLOADING = "Uploader filer"
FINISHING = "Afslutter"

# (mønster, fase). En gruppe i mønsteret er det samlede antal filer i fasen.
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
    """Klienten skriver ``./`` foran nye filer ved upload. Brugerfladen viser stien uden."""
    return value[2:] if value.startswith("./") else value


@dataclass
class SyncProgress:
    phase: str = ""
    done: int = 0
    """Antallet af færdige filer i fasen."""
    total: int | None = None
    """Det samlede antal filer i fasen. ``None``, når klienten ikke har skrevet det."""
    latest: str = ""
    percent: int | None = None
    """Procenten for den seneste fil, hvis klienten har skrevet den."""
    started: float | None = None
    """Tidspunktet for den første linje, som sekunder siden 1970."""
    finished: float | None = None
    """Tidspunktet for linjen med resultatet."""
    result: str = ""
    """Tom, ``COMPLETE`` eller ``COMPLETE_WITH_FAILURES``."""
    failed: int = 0
    """Antallet fra ``Failed items to download to/from Microsoft OneDrive: <N>``."""

    @property
    def determinate(self) -> bool:
        return self.total is not None

    @property
    def fraction(self) -> float:
        """Andelen af færdige filer fra 0 til 1. 0, når det samlede antal ikke er kendt."""
        if not self.total:
            return 0.0
        return min(1.0, self.done / self.total)

    def snapshot(self) -> "SyncProgress":
        """En kopi, som en anden tråd kan læse, mens denne ændrer sig."""
        return replace(self)

    def feed(self, line: str, when: float | None = None) -> bool:
        """Opdatér fremdriften ud fra 1 linje. Svar sandt, hvis noget ændrede sig."""
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


def count_text(done: int, total: int | None, singular: str = "fil", plural: str = "filer") -> str:
    """"30 af 120 filer", "1 af 1 fil" eller "15 filer"."""
    if total is None:
        return f"{done} {singular if done == 1 else plural}"
    return f"{done} af {total} {singular if total == 1 else plural}"


def format_duration(seconds: float) -> str:
    """"under 1 min", "12 min" eller "3 t 2 min"."""
    minutes = int(max(0, seconds)) // 60
    if minutes < 1:
        return "under 1 min"
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} t {minutes} min"
    return f"{minutes} min"
