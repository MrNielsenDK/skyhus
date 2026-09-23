"""Den seneste fejllinje fra servicens journal (feature 0004).

Linjerne er optaget fra ``journalctl --user -u onedrive-privat.service -o json``.
Stierne er erstattet med opdigtede stier.
"""

import json

from onedrive_gui import journal

from fakes import ScriptedRun


def entry(message, identifier="onedrive", pid="226838"):
    return json.dumps({"SYSLOG_IDENTIFIER": identifier, "_PID": pid, "PRIORITY": "6",
                       "MESSAGE": message}, ensure_ascii=False)


def journal_output(*entries):
    return "".join(e + "\n" for e in entries)


NO_SPACE_ERROR = [
    entry("Downloading file: Dokumenter/film.avi ... done"),
    entry("ERROR: The local file system returned an error with the following details:"),
    entry("  Calling Function:  syncEngine.downloadFileItem()"),
    entry("  Path:              Dokumenter/film.avi"),
    entry("  Error Message:     Wrote 0 instead of 16375 objects of type ubyte to file "
          "`Dokumenter/film.avi.partial' (No space left on device)"),
    entry("  Disk Space (CWD):  0 bytes available"),
]

TIMEOUT_TAIL = [
    entry("Received termination signal, attempting to cleanly shutdown application"),
    entry("Stopping onedrive-privat.service - OneDrive Client for Linux (privat konto)...", "systemd", "3263"),
    entry("onedrive-privat.service: State 'stop-sigterm' timed out. Killing.", "systemd", "3263"),
    entry("onedrive-privat.service: Main process exited, code=killed, status=9/KILL", "systemd", "3263"),
    entry("onedrive-privat.service: Failed with result 'timeout'.", "systemd", "3263"),
    entry("Stopped onedrive-privat.service - OneDrive Client for Linux (privat konto).", "systemd", "3263"),
]


def latest(*entries):
    return journal.latest_error(journal.parse_entries(journal_output(*entries)))


def test_error_message_line_follows_error():
    assert latest(
        entry("ERROR: The local file system returned an error with the following details:"),
        entry("  Error Message:     Wrote 0 instead of 16375 objects (No space left on device)"),
    ) == "Error Message: Wrote 0 instead of 16375 objects (No space left on device)"


def test_error_message_line_after_other_detail_lines():
    """Klienten skriver "Calling Function:" og "Path:" før "Error Message:"."""
    line = latest(*NO_SPACE_ERROR, *TIMEOUT_TAIL)

    assert line.startswith("Error Message: Wrote 0 instead of 16375")
    assert line.endswith("(No space left on device)")


def test_newest_of_two_errors():
    assert latest(
        entry("ERROR: Invalid sync_list rule '/gammel' detected."),
        entry("Syncing changes from Microsoft OneDrive ..."),
        entry("ERROR: Check your configuration as your refresh_token may be empty or invalid."),
    ) == "ERROR: Check your configuration as your refresh_token may be empty or invalid."


def test_failed_with_result_when_there_is_no_error_line():
    assert latest(*TIMEOUT_TAIL) == "onedrive-privat.service: Failed with result 'timeout'."


def test_empty_journal_gives_no_error_line():
    assert latest() == ""
    assert journal.latest_error(journal.parse_entries("")) == ""
    assert journal.latest_error(journal.parse_entries("-- No entries --\n")) == ""


def test_resync_required_counts_as_error_line():
    """Klienten skriver ikke "ERROR:" foran beskeden, når den stopper med exit-kode 126."""
    assert latest(
        entry("An application configuration change has been detected where a --resync is required"),
        entry("onedrive-privat.service: Main process exited, code=exited, status=126/n/a", "systemd", "1"),
        entry("onedrive-privat.service: Failed with result 'exit-code'.", "systemd", "1"),
    ) == "An application configuration change has been detected where a --resync is required"


def test_error_inside_trace_line_is_not_an_error_line():
    assert latest(
        entry("TRACE log.d: addLogEntry dropped message; lb=null msg=ERROR: File failed to download."),
        *TIMEOUT_TAIL,
    ) == "onedrive-privat.service: Failed with result 'timeout'."


def test_message_as_bytes_is_decoded():
    raw = json.dumps({"SYSLOG_IDENTIFIER": "onedrive", "_PID": "1",
                      "MESSAGE": list("ERROR: Fejl i æ".encode())})
    assert journal.latest_error(journal.parse_entries(raw + "\n")) == "ERROR: Fejl i æ"


def test_read_latest_error_runs_journalctl():
    run = ScriptedRun(outputs={"journalctl": journal_output(*TIMEOUT_TAIL)})

    line = journal.read_latest_error("onedrive-privat.service", run=run)

    assert line == "onedrive-privat.service: Failed with result 'timeout'."
    assert run.calls == [["journalctl", "--user", "-u", "onedrive-privat.service",
                          "-n", "500", "-o", "json", "--no-pager"]]


def test_read_latest_error_gives_empty_when_journalctl_fails():
    run = ScriptedRun(fail={"journalctl"})

    assert journal.read_latest_error("onedrive-privat.service", run=run) == ""
