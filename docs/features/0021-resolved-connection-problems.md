# Hide connection problems after a sync

Version: 0.14.1
Status: developed
Created: 2026-10-26

## Problem

The card "Activity" (feature 0019) shows the row "No connection to Microsoft OneDrive" for 24 hours after the client lost the connection. The row stays also when the client connected again and synced.

On the user's machine, on 2026-10-26, the network was down 2 times: at 09:20 (after sleep) and at 13:52. Both services synced again a short time after each time, and then every 5 minutes. The card still showed "No connection to Microsoft OneDrive", and the user thought that the sync did not work.

A connection problem is not a problem when a sync completed after it. The client tries again by itself.

## Solution

`Activity.problems()` ignores a "No connection to Microsoft OneDrive" event when a "Sync with Microsoft OneDrive is complete" event of the same service has a later time.

- The row shows only the connection problems after the last sync. The count and the newest time come from these events only.
- When all connection problems are before the last sync, the card does not show the row.
- When the client cannot connect after the last sync, the card shows the row, as today.
- When there is no sync in the 24 hours, the card shows all connection problems, as today.
- An event with the same time as the sync is not before the sync. The card shows it. Too many rows are better than a hidden problem.

The rule applies to all events with the message `NO_CONNECTION`. These come from the lines `Cannot connect to the Microsoft OneDrive Service - Network Connection Issue ...` and `Internet connectivity to Microsoft OneDrive service has been interrupted ...`, and from `ERROR:` lines with a network error (`Could not resolve hostname`, `Couldn't resolve host`, `Couldn't connect to server`, `Timeout was reached`).

"Copy problems" uses `problems()`, so it also does not copy the hidden rows.

## Scope

- The feature does not change other problems. Failed files, `ERROR:` lines without a network error, HTTP 429, HTTP 408 and HTTP 503 stay for 24 hours, as today.
- The feature does not change the summary line, the recent files or the state of the service.
- The feature does not remove events from `Activity`. It only filters them in `problems()`.
- The feature does not change the tray icon. The tray does not use the card "Activity".

## Plan

1. `skyhus/activity.py` — in `Activity.problems()`, find the time of the newest `SYNCED` event. Before the grouping, ignore each `PROBLEM` event with the message `NO_CONNECTION` and a time before that time. Update the docstring of the module.
2. `docs/features/0019-activity-and-problems.md` — no change. This document records the new rule.
3. `README.md` — in the section "Activity", add 1 sentence: the connection problems before the last sync are not shown.
4. `CHANGELOG.md` — an entry under `[0.14.1]` with `### Fixed`. Bump `version` to 0.14.1.

## Tests

`Activity.problems()`:
- 3 connection problems, then a sync: no row "No connection to Microsoft OneDrive".
- 2 connection problems, a sync, then 1 connection problem: 1 row with the count 1 and the time of the last problem.
- Connection problems without a sync: 1 row with all of them, as today.
- A connection problem with the same time as the sync: the row is shown.
- A connection problem from an `ERROR:` line with `Could not resolve hostname`, then a sync: no row.
- A failed download, an `ERROR:` line without a network error and an HTTP 429 problem, then a sync: all 3 rows are shown.
- `problems_text()` after a sync has no line for the hidden connection problems.

## Verification

```bash
python3 -m pytest tests/test_activity.py
python3 -m pytest
python3 -m skyhus.app --safe
```

Manual in safe mode, on the user's machine: open the accounts "OneDrive" and "privat". The journal of 2026-10-26 has connection problems at 09:20 and at 13:52, and syncs after them. The card "Activity" does not show "No connection to Microsoft OneDrive". Compare with:

```bash
journalctl --user -u onedrive-privat.service --since -24h -o short-iso | grep -E "Cannot connect|connectivity|Sync with Microsoft OneDrive is complete"
```

## Open questions

1. Must the same rule apply to HTTP 429, HTTP 408 and HTTP 503? These problems are also temporary, and the client tries again by itself. This document changes only the connection problems.
