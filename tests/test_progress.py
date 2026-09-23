"""Fremdrift fra klientens linjer (feature 0009).

Linjerne er optaget fra en rigtig ``onedrive --resync`` (v2.5) på en privat
konto. Alle filnavne og stier er erstattet med opdigtede navne.
"""

from skyhus import progress
from skyhus.progress import SyncProgress

# Et forkortet forløb fra en rigtig resync. Rækkefølgen og linjernes form er klientens.
RESYNC_LINES = [
    "Reading configuration file: /home/bruger/.config/onedrive-test/config",
    "Configuration file successfully loaded",
    "Deleting the saved application sync status ...",
    "Attempting to contact the Microsoft OneDrive Service",
    "Successfully reached the Microsoft OneDrive Service",
    "Removing interrupted download file due to --resync for: Ferie/Klip/klip_0001.avi",
    "Fetching items from the OneDrive API for Drive ID: 0a1b2c3d4e5f6789 ..............",
    "Processing 5821 applicable JSON items received from Microsoft OneDrive ........ ",
    "Number of items to download from Microsoft OneDrive: 4",
    "Downloading: Ferie/Strand/IMG_0001.JPG ... 0%   |  ETA    --:--:--",
    "Downloading: Ferie/Strand/IMG_0001.JPG ... 50%  |  ETA    00:00:02",
    "Downloading: Ferie/Strand/IMG_0001.JPG ... 100% | DONE in 00:00:02",
    "Downloading file: Ferie/Strand/IMG_0001.JPG ... done",
    "Downloading file: Ferie/Strand/IMG_0002.JPG ... done",
    "Downloading file: Tegninger/hus.psd ... failed!",
    "ERROR: File failed to download. Re-run with --verbose to see more details.",
    "Downloading file: Backup/arkiv-2026-01-01.zip ... done",
    "Performing a database consistency and integrity check on locally stored data .......... ",
    "Changed local items to upload to Microsoft OneDrive: 1",
    "Uploading modified file: Noter/indkoeb.txt ... done",
    "Scanning the local file system '~/OneDrive-Test' for new data to upload ............. ",
    "New items to upload to Microsoft OneDrive: 2",
    "Uploading new file: ./Rapporter/Q1/rapport.md ... done",
    "Uploading new file: ./Rapporter/Q1/bilag.md ... done",
    "Performing a last examination of the most recent online data within Microsoft OneDrive "
    "to complete the reconciliation process",
    "Fetching items from the OneDrive API for Drive ID: 0a1b2c3d4e5f6789 .. ",
    "Processing 24 applicable JSON items received from Microsoft OneDrive . ",
    "",
    "Failed items to download to/from Microsoft OneDrive: 1",
    "Failed to download: Tegninger/hus.psd",
    "",
    "Sync with Microsoft OneDrive has completed, however there are items that failed to sync.",
    "To fix any download failures you may need to perform a --resync to ensure this system is "
    "correctly synced with your Microsoft OneDrive Account",
]


def fed(*lines):
    p = SyncProgress()
    for line in lines:
        p.feed(line)
    return p


def test_number_of_items_to_download_sets_phase_and_total():
    p = fed("Number of items to download from Microsoft OneDrive: 120")

    assert p.phase == "Downloader filer"
    assert p.total == 120
    assert p.determinate is True


def test_three_done_lines_count_three_files():
    p = fed(*["Downloading file: A/b.txt ... done"] * 3)

    assert p.done == 3
    assert p.latest == "A/b.txt"


def test_failed_download_does_not_count():
    p = fed("Downloading file: A/b.txt ... done", "Downloading file: A/c.txt ... failed!")

    assert p.done == 1


def test_processing_line_sets_phase():
    p = fed("Processing 5821 applicable JSON items received from Microsoft OneDrive ....")

    assert p.phase == "Behandler elementer fra OneDrive"


def test_without_a_total_the_bar_is_indeterminate():
    p = fed("Fetching items from the OneDrive API for Drive ID: 0a1b2c3d4e5f6789 ....",
            "Downloading file: A/b.txt ... done")

    assert p.total is None
    assert p.determinate is False


def test_sync_complete_gives_result_complete():
    p = fed("Sync with Microsoft OneDrive is complete")

    assert p.result == progress.COMPLETE


def test_completed_with_failures_gives_count():
    p = fed("Failed items to download to/from Microsoft OneDrive: 2",
            "Sync with Microsoft OneDrive has completed, however there are items that failed to sync.")

    assert p.result == progress.COMPLETE_WITH_FAILURES
    assert p.failed == 2


def test_unknown_line_changes_nothing():
    p = fed("Number of items to download from Microsoft OneDrive: 120",
            "Downloading file: A/b.txt ... done")
    before = p.snapshot()

    changed = p.feed("Handling a Microsoft Graph API HTTP 429 Response Code (Too Many Requests)")

    assert changed is False
    assert p == before


def test_trace_line_does_not_count():
    p = fed("TRACE log.d: addLogEntry dropped message; lb=null msg=Downloading file: A/b.txt ... done")

    assert p.done == 0
    assert p.latest == ""


def test_percent_line_sets_latest_file_without_counting():
    p = fed("Downloading: A/film.avi ... 45%   |  ETA    00:01:10")

    assert p.latest == "A/film.avi"
    assert p.percent == 45
    assert p.done == 0


def test_done_line_clears_the_percent():
    p = fed("Downloading: A/film.avi ... 45%   |  ETA    00:01:10",
            "Downloading file: A/film.avi ... done")

    assert p.percent is None
    assert p.done == 1


def test_recorded_resync_gives_phases_counts_and_result():
    p = SyncProgress()
    phases = []
    for line in RESYNC_LINES:
        p.feed(line)
        if not phases or phases[-1] != p.phase:
            phases.append(p.phase)

    assert phases == ["", "Henter listen fra OneDrive", "Behandler elementer fra OneDrive",
                      "Downloader filer", "Kontrollerer den lokale database", "Scanner lokale filer",
                      "Uploader filer", "Afslutter"]
    assert p.result == progress.COMPLETE_WITH_FAILURES
    assert p.failed == 1


def test_download_phase_counts_against_the_total():
    p = fed(*RESYNC_LINES[:17])

    assert p.phase == "Downloader filer"
    assert (p.done, p.total) == (3, 4)
    assert p.latest == "Backup/arkiv-2026-01-01.zip"


def test_upload_lines_count_and_drop_the_dot_prefix():
    p = fed(*RESYNC_LINES[:24])

    assert p.phase == "Uploader filer"
    assert (p.done, p.total) == (2, 2)
    assert p.latest == "Rapporter/Q1/bilag.md"


def test_nothing_changes_after_the_result():
    p = fed("Sync with Microsoft OneDrive is complete")
    before = p.snapshot()

    assert p.feed("Number of items to download from Microsoft OneDrive: 7") is False
    assert p.feed("Downloading file: A/b.txt ... done") is False
    assert p == before


def test_start_and_finish_time_come_from_the_lines():
    p = SyncProgress()
    p.feed("Configuration file successfully loaded", when=100.0)
    p.feed("Downloading file: A/b.txt ... done", when=160.0)
    p.feed("Sync with Microsoft OneDrive is complete", when=400.0)

    assert p.started == 100.0
    assert p.finished == 400.0


def test_count_text():
    assert progress.count_text(30, 120) == "30 af 120 filer"
    assert progress.count_text(1, 1) == "1 af 1 fil"
    assert progress.count_text(15, None) == "15 filer"
    assert progress.count_text(1, None) == "1 fil"
    assert progress.count_text(2, 4, "sti", "stier") == "2 af 4 stier"


def test_format_duration():
    assert progress.format_duration(30) == "under 1 min"
    assert progress.format_duration(12 * 60 + 5) == "12 min"
    assert progress.format_duration(3 * 3600 + 2 * 60) == "3 t 2 min"
