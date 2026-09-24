"""Activity and problems per account (feature 0019)."""

from datetime import datetime

from skyhus import activity
from skyhus.activity import Activity, Event, parse
from skyhus.journal import Entry

T0 = datetime(2026, 9, 24, 8, 0).timestamp()


def entry(message, pid="100", when=T0, identifier="onedrive"):
    return Entry(identifier, pid, message, when)


def kinds(events):
    return [(e.kind, e.path) for e in events]


# parse

def test_done_lines_give_file_events():
    events = parse([
        entry("Downloading file: Docs/a.txt ... done"),
        entry("Uploading new file: Docs/b.txt ... done"),
        entry("Uploading modified file: Docs/c.txt ... done"),
    ])

    assert kinds(events) == [(activity.DOWNLOADED, "Docs/a.txt"), (activity.UPLOADED, "Docs/b.txt"),
                             (activity.UPLOADED, "Docs/c.txt")]


def test_delete_lines_give_delete_events():
    events = parse([
        entry("Deleting item from Microsoft OneDrive: Old/x.txt"),
        entry("Deleting online file from Microsoft OneDrive: Old/y.txt"),
        entry("Deleting online folder from Microsoft OneDrive: Old/Z"),
        entry("Deleting local file: Old/w.txt"),
        entry("Deleting local directory: Old/V"),
    ])

    assert kinds(events) == [(activity.DELETED_ONLINE, "Old/x.txt"), (activity.DELETED_ONLINE, "Old/y.txt"),
                             (activity.DELETED_ONLINE, "Old/Z"), (activity.DELETED_LOCAL, "Old/w.txt"),
                             (activity.DELETED_LOCAL, "Old/V")]


def test_progress_lines_give_no_event():
    assert parse([entry("Downloading: Docs/a.txt ... 45% | ETA 00:00:10"),
                  entry("Downloading: Docs/a.txt ... 100% | DONE in 00:00:03")]) == []


def test_failed_download_gets_the_disk_space_reason_from_the_same_pid():
    events = parse([
        entry("Insufficient local disk space to download file", pid="100"),
        entry("Downloading file: Photos/1.jpg ... failed!", pid="100"),
    ])

    assert len(events) == 1
    assert events[0].kind == activity.FAILED
    assert events[0].path == "Photos/1.jpg"
    assert events[0].reason == activity.REASON_DISK_SPACE
    assert events[0].direction == "Download"


def test_reason_from_a_different_pid_does_not_count():
    events = parse([
        entry("Insufficient local disk space to download file", pid="200"),
        entry("Downloading file: Photos/1.jpg ... failed!", pid="100"),
    ])

    assert events[0].reason == ""


def test_reason_is_used_only_once():
    events = parse([
        entry("Insufficient local disk space to download file"),
        entry("Downloading file: Photos/1.jpg ... failed!"),
        entry("Downloading file: Photos/2.jpg ... failed!"),
    ])

    assert [e.reason for e in events] == [activity.REASON_DISK_SPACE, ""]


def test_failed_upload_is_an_upload_failure():
    events = parse([entry("Uploading new file: Docs/b.txt ... failed!")])

    assert events[0].kind == activity.FAILED
    assert events[0].direction == "Upload"


def test_connection_and_http_lines_are_problems():
    events = parse([
        entry("Cannot connect to the Microsoft OneDrive Service - Network Connection Issue: Could not resolve hostname"),
        entry("Internet connectivity to Microsoft OneDrive service has been interrupted .. re-trying in the background"),
        entry("Handling a Microsoft Graph API HTTP 429 Response Code (Too Many Requests) - Internal Thread ID: abc"),
        entry("Handling a Microsoft Graph API HTTP 408 Response Code (Request Time Out) - Internal Thread ID: abc"),
        entry("HTTP request returned status code 503 (Service Unavailable) when attempting to query"),
    ])

    assert [e.message for e in events] == [activity.NO_CONNECTION, activity.NO_CONNECTION, activity.HTTP_429,
                                           activity.HTTP_408, activity.HTTP_503]
    assert all(e.kind == activity.PROBLEM for e in events)


def test_error_line_uses_the_error_message_line():
    events = parse([
        entry("ERROR: Microsoft OneDrive API returned an error with the following message:"),
        entry("  Error Message:    The resource could not be found."),
    ])

    assert len(events) == 1
    assert events[0].kind == activity.PROBLEM
    assert events[0].message == "Error: The resource could not be found."
    assert events[0].is_error


def test_error_line_without_details_uses_its_own_text():
    events = parse([entry("ERROR: Something went wrong")])

    assert events[0].message == "Error: Something went wrong"


def test_network_error_is_no_connection():
    events = parse([
        entry("ERROR: Microsoft OneDrive API returned an error with the following message:"),
        entry("  Error Message:    Could not resolve hostname on handle 7FADA011A1B0"),
    ])

    assert events[0].message == activity.NO_CONNECTION
    assert not events[0].is_error


def test_changing_handles_are_removed_before_grouping():
    events = parse([
        entry("ERROR: x", pid="1"), entry("  Error Message:    Upload failed on handle 7FADA011A1B0", pid="1"),
        entry("ERROR: x", pid="2"), entry("  Error Message:    Upload failed on handle 5BF2BAFD3680", pid="2"),
    ])
    log = Activity()
    log.add(events, now=T0)

    assert [(p.title, p.count) for p in log.problems()] == [("Error: Upload failed", 2)]


def test_sync_complete_is_a_sync_event():
    assert kinds(parse([entry("Sync with Microsoft OneDrive is complete")])) == [(activity.SYNCED, "")]


def test_lines_from_systemd_give_no_event():
    assert parse([entry("Downloading file: a ... done", identifier="systemd")]) == []


# Activity

def test_old_events_disappear():
    log = Activity()
    log.add([Event(activity.DOWNLOADED, T0, "a")], now=T0)

    log.add([Event(activity.DOWNLOADED, T0 + 25 * 3600, "b")], now=T0 + 25 * 3600)

    assert [e.path for e in log.recent(10)] == ["b"]


def test_summary_counts_and_last_sync():
    log = Activity()
    log.add([Event(activity.DOWNLOADED, T0, "a"), Event(activity.DOWNLOADED, T0, "b"),
             Event(activity.UPLOADED, T0, "c"), Event(activity.FAILED, T0, "d", direction="Download"),
             Event(activity.SYNCED, T0 + 60)], now=T0 + 60)

    text = log.summary(datetime.fromtimestamp(T0 + 120))

    assert text == "Last sync: today at 08:01 · 24 h: 2 downloaded, 1 uploaded, 1 failed"


def test_summary_leaves_out_zero_and_says_when_empty():
    log = Activity()
    assert log.summary(datetime.fromtimestamp(T0)) == "No activity in the last 24 hours"

    log.add([Event(activity.UPLOADED, T0, "c")], now=T0)
    assert log.summary(datetime.fromtimestamp(T0)) == "24 h: 1 uploaded"


def test_summary_says_when_the_limit_was_reached():
    log = Activity()
    log.replace([Event(activity.UPLOADED, T0, "c")], now=T0, truncated=True)

    assert log.summary(datetime.fromtimestamp(T0)).endswith("(only the newest 50,000 lines)")


def test_problems_are_grouped_and_newest_first():
    log = Activity()
    disk = [Event(activity.FAILED, T0 + i, f"Photos/{i}.jpg", reason=activity.REASON_DISK_SPACE,
                  direction="Download") for i in range(6437)]
    log.add(disk + [Event(activity.PROBLEM, T0 + 10, message=activity.NO_CONNECTION)], now=T0 + 7000)

    problems = log.problems()

    assert [p.title for p in problems] == ["Download failed: not enough disk space", activity.NO_CONNECTION]
    assert problems[0].count == 6437
    assert problems[0].newest == T0 + 6436
    assert problems[0].example == "Photos/6436.jpg"
    assert problems[0].tone == "danger"
    assert problems[1].tone == "warning"


def test_recent_gives_the_newest_file_events_first():
    log = Activity()
    log.add([Event(activity.DOWNLOADED, T0 + i, f"f{i}") for i in range(30)]
            + [Event(activity.SYNCED, T0 + 100)], now=T0 + 100)

    recent = log.recent(20)

    assert len(recent) == 20
    assert recent[0].path == "f29"
    assert all(e.kind != activity.SYNCED for e in recent)


def test_problems_text_has_one_line_per_problem():
    log = Activity()
    log.add([Event(activity.FAILED, T0, "Photos/1.jpg", reason=activity.REASON_DISK_SPACE, direction="Download"),
             Event(activity.FAILED, T0 + 5, "Photos/2.jpg", reason=activity.REASON_DISK_SPACE, direction="Download"),
             Event(activity.PROBLEM, T0, message=activity.HTTP_429)], now=T0 + 5)

    text = activity.problems_text(log.problems(), datetime.fromtimestamp(T0 + 60))

    assert text.splitlines() == [
        "Download failed: not enough disk space · 2 times · today at 08:00 · Photos/2.jpg",
        f"{activity.HTTP_429} · 1 time · today at 08:00",
    ]
