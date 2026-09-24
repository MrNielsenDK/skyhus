# Activity and problems per account

Version: 0.13.0
Status: developed
Created: 2026-09-24

## Problem

The "Service" card shows the state of the service and the latest error line. It does not show what the client did, and it does not show problems that do not stop the service.
To see which files the client synced, or why files failed, the user must read the journal with `journalctl` in a terminal.

On the user's machine, the journal of `onedrive-privat.service` had 6437 lines "Insufficient local disk space to download file" in 3 days, and a large number of downloads that ended with "... failed!". The service stayed "Running", so Skyhus showed no problem.

## Solution

The account page gets the card "Activity", between the "Service" card and the "Details" card. The card shows the last 24 hours of the account, from the journal of its service.

### What the card shows

1. **Summary.** One line, for example: "Last sync: today at 08:37 · 24 h: 120 downloaded, 3 uploaded, 12 failed". "Last sync" is the time of the newest line "Sync with Microsoft OneDrive is complete". A number that is 0 is not shown.
2. **Problems.** One row for each kind of problem, with the number of times, the time of the newest one and 1 example path when there is one. The newest problem is first. The rows use the color for danger for errors and for warning for the other problems. Examples:
   - "Download failed: not enough disk space · 6437 times · yesterday at 03:13"
   - "Download failed · 1250 times · yesterday at 03:13 · Backup/…/IMG_0001.jpg"
   - "No connection to Microsoft OneDrive · 56 times · …"
   - "Microsoft asked the client to wait (HTTP 429) · 8 times · …"
   - "Error: <the Error Message line>" for each different `ERROR:` message.
   When there is no problem, the card shows "No problems in the last 24 hours".
3. **Recent files.** The newest 20 files that the client downloaded, uploaded or deleted, with an icon for the direction, the path and the time. A button "Show all" opens a sheet with the newest 200.

The card has the button "Copy problems". It copies the problem rows as plain text to the clipboard, so the user can search for them or send them to someone. Skyhus sends nothing by itself.

### Which lines count

Skyhus reads the lines with the identifier `onedrive` from the service's journal. The first version knows these lines. The texts are checked against the strings in `/usr/bin/onedrive` 2.5.11:

| Line from the client | Event |
|---|---|
| `Downloading file: <path> ... done` | Downloaded |
| `Uploading new file: <path> ... done`, `Uploading modified file: <path> ... done` | Uploaded |
| `Deleting item from Microsoft OneDrive: <path>`, `Deleting online file from Microsoft OneDrive: <path>`, `Deleting online folder from Microsoft OneDrive: <path>` | Deleted online |
| `Deleting local file: <path>`, `Deleting local directory: <path>` | Deleted locally |
| `Downloading file: <path> ... failed!`, `Uploading ...: <path> ... failed!` | Failed. The reason is the nearest reason line before it from the same process. |
| `Insufficient local disk space to download file` | Reason: not enough disk space |
| `Cannot connect to the Microsoft OneDrive Service - Network Connection Issue ...`, `Internet connectivity to Microsoft OneDrive service has been interrupted ...` | Problem: no connection |
| `Handling a Microsoft Graph API HTTP 429 Response Code (Too Many Requests) ...` | Problem: HTTP 429 |
| `Handling a Microsoft Graph API HTTP 408 Response Code (Request Time Out) ...` | Problem: HTTP 408 |
| `HTTP request returned status code 503 (Service Unavailable) ...` | Problem: HTTP 503 |
| `ERROR: ...` with the indented lines after it | Problem: error. The text is the `Error Message:` line, as in `journal.py` (feature 0004). Parts that change each time, such as `on handle 7FADA011A1B0`, are removed, so the same error is 1 row. |
| `ERROR: ...` with `Could not resolve hostname`, `Couldn't resolve host`, `Couldn't connect to server` or `Timeout was reached` | Problem: no connection (warning, not error). On the user's machine, these errors come after sleep. |
| `Sync with Microsoft OneDrive is complete` | Last sync |

Progress lines such as `Downloading: <path> ... 45% | ETA` do not count. Other lines are ignored. A new kind of line needs a change in the table and a test.

### When Skyhus reads the journal

- When the user opens the account page, Skyhus reads the lines of the last 24 hours: `journalctl --user -u <service> --since -24h -o json --no-pager`.
- While the page is visible and the window is visible, Skyhus reads only the new lines every 30 seconds with `--after-cursor`.
- The card has the button "Refresh", which reads the last 24 hours again.
- Skyhus keeps the events of the last 24 hours in memory, per account, and removes older events. It does not write them to a file.
- Skyhus reads at most 50,000 lines in one call (`-n 50000`). When the limit is reached, the summary says "(only the newest 50,000 lines)".
- The reading runs in a `_Job` thread. `journalctl` only reads, so it also runs in safe mode.

An account without a service shows "No service. There is no activity to show."

## Scope

- The feature does not send notifications.
- The feature does not show more than 24 hours.
- The feature does not write the events to a file or send them anywhere.
- The feature does not repeat failed downloads or uploads, and does not free disk space.
- The feature does not read the log file of the client (`~/.local/share/onedrive` or `log_dir`). It reads only the journal.

## Plan

1. `skyhus/activity.py` — a new module without Qt:
   - `Event(kind, when, path, reason, message)` with the kinds `DOWNLOADED`, `UPLOADED`, `DELETED`, `FAILED`, `PROBLEM`, `SYNCED`.
   - `parse(entries) -> list[Event]` with the table above. The reason for "failed!" comes from the nearest reason line before it from the same PID.
   - `Activity` keeps the events of 24 hours for 1 service, adds new events, removes old ones, and gives `summary(now)`, `problems()` (grouped by kind and reason, with count, newest time and example path) and `recent(limit)`.
   - `problems_text(problems)` for "Copy problems".
2. `skyhus/journal.py` — `activity_lines(service, since, after_cursor, limit, run)`, in the same form as `invocation_lines()`.
3. `skyhus/viewmodels.py` — per account: an `Activity` object and the cursor. The slots `openActivity(confdir)` (called when the page shows an account), `refreshActivity(confdir)`, `copyProblems(confdir)` and `showAllFiles(confdir)`. The properties for the card and the sheet. A timer of 30 seconds while the window is visible.
4. `skyhus/qml/components/ActivityCard.qml`, `skyhus/qml/sheets/AllFilesSheet.qml`, and the card on `AccountPage.qml`.
5. Icons for the directions from Lucide: `arrow-down`, `arrow-up`, `trash-2` (exists) and `circle-alert` (exists).
6. `README.md` — the section "Activity". `CHANGELOG.md` — an entry under `[0.13.0]` with `### Added`. Bump `version` to 0.13.0.

## Tests

`activity.parse` (test data with made-up paths):
- Each line in the table gives the right event, with the path.
- `Downloading: <path> ... 45% | ETA ...` gives no event.
- `Downloading file: <path> ... failed!` after `Insufficient local disk space to download file` from the same PID gives `FAILED` with the reason "not enough disk space". A reason line from a different PID does not count.
- `ERROR:` with an indented `Error Message:` line gives a problem with the text of that line.
- A line from `systemd` gives no event.

`Activity`:
- Events older than 24 hours disappear after `add()` with a later time.
- `summary()` counts downloaded, uploaded and failed, and gives the time of the last sync. A number that is 0 is not in the text.
- `problems()` groups 6437 disk-space failures into 1 row with the count 6437 and the newest time, and sorts the newest problem first.
- `recent(20)` gives the 20 newest file events, newest first.
- `problems_text()` gives 1 line per problem, with the count and the time.

`journal.activity_lines`:
- The first call has `--since -24h` and `-n 50000`. A call with a cursor has `--after-cursor=<cursor>` and no `--since`.
- The result has the new cursor and tells when the limit was reached.

Controller and QML:
- `openActivity()` starts 1 read. A second call while it runs does not start a new one.
- The timer reads only the new lines, with the cursor.
- An account without a service shows the text for "No service" and starts no read.
- "Copy problems" puts the text on the clipboard.
- The card shows "No problems in the last 24 hours" when there are none.
- In safe mode, the card works: `journalctl` runs, and nothing else runs.

## Verification

```bash
python3 -m pytest
python3 -m skyhus.app --safe
```

Manual in safe mode, on the user's machine: open the account "Privat". The card shows the summary, the problems and the recent files from the last 24 hours. Compare the numbers with:

```bash
journalctl --user -u onedrive-privat.service --since -24h -o cat | grep -c "\.\.\. done$"
```

## Open questions

1. Is 24 hours the right window, or must the user be able to choose (for example 24 hours, 7 days)? This document uses 24 hours to keep the number of lines small.
