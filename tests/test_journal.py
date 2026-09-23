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


# Feature 0009: linjerne fra servicens nuværende kørsel.

INVOCATION = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


def invocation_entry(message, cursor, identifier="onedrive", when="1790143816219521"):
    """En linje, som ``journalctl -o json`` skriver den for en user-service."""
    return json.dumps({"SYSLOG_IDENTIFIER": identifier, "_PID": "315472", "PRIORITY": "6",
                       "_TRANSPORT": "stdout", "_SYSTEMD_USER_UNIT": "onedrive-privat.service",
                       "_SYSTEMD_INVOCATION_ID": INVOCATION, "__REALTIME_TIMESTAMP": when,
                       "__CURSOR": cursor, "MESSAGE": message}, ensure_ascii=False)


def test_invocation_lines_filters_on_the_current_invocation():
    run = ScriptedRun(outputs={"journalctl": journal_output(
        invocation_entry("Configuration file successfully loaded", "s=1;i=a"),
        invocation_entry("Number of items to download from Microsoft OneDrive: 120", "s=1;i=b"))})

    entries, cursor = journal.invocation_lines("onedrive-privat.service", INVOCATION, run=run)

    assert run.calls == [["journalctl", "--user", "-u", "onedrive-privat.service",
                          f"_SYSTEMD_INVOCATION_ID={INVOCATION}", "-o", "json", "--no-pager"]]
    assert [e.message for e in entries] == ["Configuration file successfully loaded",
                                            "Number of items to download from Microsoft OneDrive: 120"]
    assert entries[0].identifier == "onedrive"
    assert entries[0].timestamp == 1790143816.219521
    assert cursor == "s=1;i=b"


def test_invocation_lines_after_cursor_gives_only_new_lines():
    run = ScriptedRun(outputs={"journalctl": journal_output(
        invocation_entry("Downloading file: A/b.txt ... done", "s=1;i=c"))})

    entries, cursor = journal.invocation_lines("onedrive-privat.service", INVOCATION,
                                               after_cursor="s=1;i=b", run=run)

    assert run.calls == [["journalctl", "--user", "-u", "onedrive-privat.service",
                          f"_SYSTEMD_INVOCATION_ID={INVOCATION}", "-o", "json", "--no-pager",
                          "--after-cursor=s=1;i=b"]]
    assert [e.message for e in entries] == ["Downloading file: A/b.txt ... done"]
    assert cursor == "s=1;i=c"


def test_invocation_lines_without_new_lines_keeps_the_cursor():
    run = ScriptedRun(outputs={"journalctl": ""})

    entries, cursor = journal.invocation_lines("onedrive-privat.service", INVOCATION,
                                               after_cursor="s=1;i=b", run=run)

    assert entries == []
    assert cursor == "s=1;i=b"


def test_invocation_lines_gives_nothing_when_journalctl_fails():
    run = ScriptedRun(fail={"journalctl"})

    assert journal.invocation_lines("onedrive-privat.service", INVOCATION,
                                    after_cursor="s=1;i=b", run=run) == ([], "s=1;i=b")
