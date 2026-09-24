# Remove an account

Version: 0.12.0
Status: developed
Created: 2026-09-24

## Problem

Skyhus can add an account, but it cannot remove one.
To remove an account, the user must do these steps in a terminal:
- stop and disable the service,
- stop and disable the `.path` unit that starts the service,
- remove the unit file and run `systemctl --user daemon-reload`,
- remove the config folder,
- decide what to do with the local sync folder.

It is easy to do a step in the wrong order. On the user's machine, `onedrive-privat.path` has `PathExists=%h/.config/onedrive-privat/refresh_token`. If the user stops only the service, the `.path` unit starts it again at once.

If the user removes the link to OneDrive but keeps the local sync folder, there are 2 sets of data that are not in sync any more. But the local folder can contain data that is not on OneDrive:
- local changes that are not uploaded yet,
- files that the rules keep out of the sync (`skip_file`, `skip_dir`, `skip_dotfiles`, folders outside `sync_list`),
- files that failed to upload.

## Solution

The account page gets the button "Remove account …" at the bottom, below the "Service" card. A click opens the sheet "Remove account?". The sheet shows what Skyhus does and what it does not do. The user clicks "Remove account" to continue, or "Cancel".

### The local sync folder

The sheet has the check box "Also move the local folder to the Trash", with the path of the sync folder. The check box is on by default. The user can turn it off to keep a local copy.

When the check box is on, Skyhus first uploads the local changes to OneDrive, and then moves the sync folder to the Trash. The user can restore the folder from the Trash. The space on the disk is free only after the user empties the Trash.

Before the user confirms, the sheet shows the files that are only on this computer. These are the files in the sync folder that the rules of the account keep out of the sync (`rules.RuleSet`). The sheet shows the number, the total size and the first 10 paths, for example "12 files are only on this computer (48 MB)". When the number is more than 0, the text uses the color for danger. When the check box is on, these files go to the Trash with the folder.

Skyhus does not show the check box, and keeps the folder, when one of these conditions is true:
- the sync folder does not exist,
- the sync folder is the home folder, is not below the home folder, or is below `~/.config`,
- the sync folder is the same as, is inside, or contains the sync folder or the config folder of a different account.
The sheet then tells why the folder stays.

### What Skyhus removes

For the account, Skyhus finds:
- **The service:** the service from the registry. If the account has no service, Skyhus skips the service steps.
- **The trigger units:** the units in the property `TriggeredBy` of the service, from `systemctl --user show`. On the user's machine, this is the `.path` unit.
- **The unit files that Skyhus wrote:** the unit file of the service, if it has the header `Created by Skyhus.` or one of the old headers `Oprettet af Skyhus.` and `Oprettet af onedrive-gui.` Also the resync drop-in `zz-skyhus-resync.conf`, if it exists.
- **The config folder:** `~/.config/onedrive` or `~/.config/onedrive-<slug>`.
- **The sync folder,** when the check box is on.

Then Skyhus does these steps in this order:

1. **Check.** Skyhus refuses when one of these conditions is true, and changes nothing:
   - an `onedrive` process for the account runs outside the service (`process.py`),
   - a sign-in, a folder change or a service action for the account runs,
   - the config folder is not below `~/.config` or its name is not `onedrive` or `onedrive-*`.
2. **Disable the trigger units.** `systemctl --user disable --now <unit>` for each trigger unit. Then the trigger units cannot start the service again.
3. **Disable the service.** `systemctl --user disable --now <service>`. Skyhus waits until the service is `inactive` or `failed`. The limit is 120 seconds, because the service has `TimeoutStopSec=90`.
4. **Upload the local changes** (only when the check box is on). Skyhus runs `onedrive --confdir=<config folder> --upload-only --no-remote-delete`, with the same function and progress as a folder change (`apply.py`, feature 0009). The sheet shows the progress and the button "Stop" (feature 0010).
5. **Remove the unit files that Skyhus wrote.** Then `systemctl --user daemon-reload`.
6. **Remove the token.** Skyhus deletes `refresh_token` in the config folder permanently. The token is a secret, so it must not go to the Trash.
7. **Move the config folder to the Trash.**
8. **Move the sync folder to the Trash** (only when the check box is on).
9. **Clean up Skyhus's own data.** Skyhus removes the account from `~/.config/skyhus/accounts.json` and removes a "Resync stopped" mark from `state.json`.

After step 9, the account is not in the list. The page shows the next account, or the empty state if there is no account.

### What Skyhus does not remove

- **The files on OneDrive.** The upload uses `--no-remote-delete`, so it does not delete files on OneDrive.
- **The sync folder,** when the user turns the check box off.
- **Unit files that Skyhus did not write.** For example the package unit `/usr/lib/systemd/user/onedrive.service`, `onedrive-privat.service` and the `.path` units on the user's machine. Skyhus disables them, but the files stay.
- **Drop-in files that Skyhus did not write.** For example `onedrive.service.d/failure-notify.conf`. The service is disabled, so they have no effect.
- **The sign-in at Microsoft.** Microsoft still lists the OneDrive client as an app with access to the account. The sheet tells the user that they can remove this access in the settings of their Microsoft account.

### Errors and undo

Skyhus stops at the first step that fails, and does not do the next steps. The message tells which steps are done and which are not.
- **Step 2 or 3 fails:** Skyhus enables and starts again the trigger units that it disabled. Nothing else changed. The user can try again.
- **Step 4 fails, or the user clicks "Stop":** Skyhus enables and starts the service and the trigger units again, with `enable --now` and without `--resync`. Nothing else changed. The account is as before.
- **Step 5 to 7 fails:** the service is disabled. The account shows "No service" in the list. The message tells the user which files or folders to remove.
- **Step 8 fails,** for example because the Trash is on a different file system: the account is removed, but the sync folder stays. The message names the folder.

### The sheet "Remove account?"

The sheet shows:
- the display name and the config folder,
- the check box for the sync folder, and the files that are only on this computer,
- the list "Skyhus removes": the service (if any), the trigger units, the unit files that Skyhus wrote, the config folder (to the Trash, the token deleted), the sync folder (to the Trash, when the check box is on),
- the list "Skyhus does not remove": the files on OneDrive, and the sync folder when the check box is off,
- the note about the access at Microsoft.

The button "Remove account" uses the color for danger. When the user clicks it, the sheet shows the steps with their state, as the sheet "Changing folder selection" does. The removal is a critical job (feature 0008): while it runs, the window does not close without a warning.

### Safe mode

In safe mode, the flow and the sheet work, but `systemctl`, `onedrive`, the delete and the Trash do nothing, as in the rest of Skyhus. The account stays in the list, because its config folder stays.

## Scope

- The feature does not sign out at Microsoft and does not revoke the token at Microsoft.
- The feature does not delete files on OneDrive.
- The feature does not delete the sync folder permanently. It only moves it to the Trash.
- The feature does not remove more than 1 account at a time.
- The feature does not change the `onedrive-failure@.service` template.
- The feature does not delete unit files, `.path` units or drop-ins that Skyhus did not write.
- The feature cannot know which files will fail to upload. It shows only the files that the rules keep out of the sync.

## Plan

1. `skyhus/account_removal.py` — a new module without Qt:
   - `prepare(account, accounts, home, run) -> RemovalPlan`. It finds the service, the trigger units (`systemctl --user show <service> -p TriggeredBy`), the unit files that Skyhus wrote, the config folder, the sync folder, whether the sync folder can go to the Trash (the conditions above), and the files that are only local. It changes nothing.
   - `execute(plan, remove_sync_folder, home, run, popen, trash, send_signal, proc_root, clock, sleep, on_step, cancel) -> RemovalResult`. It does steps 1 to 9 in the fixed order, with the undo rules above. All side effects go through `sideeffects` (`run`, `popen`, `trash`, `signal_process`, `guard_write`).
   - `is_written_by_skyhus(path)` — checks the header of a unit file.
2. `skyhus/apply.py` — make the upload a function that `account_removal.py` can call. Its behavior does not change.
3. `skyhus/removal.py` — a function that lists the files in a folder that a `RuleSet` keeps out of the sync.
4. `skyhus/service.py` — `disable_now(unit, run)` and `daemon_reload(run)`, in the same form as `enable_now()`.
5. `skyhus/registry.py` — `Registry.remove(confdir)`. `skyhus/service_state.py` — remove the mark for a service.
6. `skyhus/viewmodels.py` — the slots `requestRemoveAccount(confdir)`, `setRemoveSyncFolder(bool)`, `confirmRemoveAccount()`, `stopRemoveAccount()` and `cancelRemoveAccount()`, the property `removeAccountPlan` for the sheet, the steps and their state, and a critical `_Job` for `execute()`.
7. `skyhus/qml/sheets/RemoveAccountSheet.qml` and the button on `AccountPage.qml`.
8. `README.md` — the section "Remove an account".
9. `CHANGELOG.md` — an entry under `[0.12.0]` with `### Added`. Bump `version` to 0.12.0.

## Tests

`prepare`:
- A service with `TriggeredBy=onedrive-privat.path` gives the trigger unit `onedrive-privat.path`.
- A unit file with `Created by Skyhus.` is in "files to remove". A unit file with the old header `Oprettet af Skyhus.` is also in the list. A unit file without the header is not.
- The package unit in `/usr/lib/systemd/user/` is never in "files to remove".
- An account without a service has no service steps.
- A file that `skip_file` matches is in "only local". A file in a folder outside `sync_list` is in "only local". A synced file is not.
- The sync folder can go to the Trash when it is below the home folder and has no overlap. It cannot go to the Trash when it is the home folder, is outside the home folder, is below `~/.config`, or is the same as, inside or around the sync folder of a different account.
- `prepare` makes only the read-only call `systemctl --user show`.

`execute`, order and content:
- With the check box on, the calls come in this order: `disable --now` for each trigger unit, `disable --now` for the service, the upload with `--upload-only --no-remote-delete`, `daemon-reload` (only if a unit file was removed).
- With the check box off, there is no upload, and the sync folder is not changed.
- `refresh_token` is deleted and is not in the Trash. The config folder is in the Trash. With the check box on, the sync folder is in the Trash after the config folder.
- The registry has no entry for the account. `state.json` has no mark for the service.

`execute`, refusals, errors and undo:
- An `onedrive` process for the account outside the service: `execute` refuses, and makes no `systemctl` call.
- A config folder outside `~/.config` or with a different name: `execute` refuses.
- `disable --now` for a trigger unit fails: the service is not stopped, the trigger units that were disabled get `enable --now` again, and nothing else changes.
- `disable --now` for the service fails: the trigger units get `enable --now` again, and the config folder is not changed.
- The upload fails with exit code 1: the service and the trigger units get `enable --now` again, and no file or folder is changed.
- The user clicks "Stop" during the upload: the client gets `SIGTERM` through `send_signal`, then the same undo as for a failed upload.
- The Trash fails for the config folder: the message says that the service is disabled and names the folder to remove.
- The Trash fails for the sync folder: the account is removed, and the message names the sync folder.
- The service is not `inactive` after 120 seconds: the trigger units get `enable --now` again, and the config folder is not changed.

Safe mode:
- Without injected functions, `execute` makes no changing `systemctl` call, starts no `onedrive`, deletes nothing, and moves nothing to the Trash under the real home folder.

User interface:
- The button "Remove account …" opens the sheet with the name, the config folder, the check box (on), the files that are only local, the two lists and the note about Microsoft.
- Without files that are only local, the sheet does not show the danger text.
- When the sync folder cannot go to the Trash, the sheet has no check box and tells why.
- "Cancel" closes the sheet and changes nothing.
- During the upload, the sheet shows the progress and the button "Stop".
- During the removal, `requestClose()` shows the closing sheet.
- After the removal, the account is not in the list, and the page shows the next account or the empty state.

## Verification

```bash
python3 -m pytest
python3 -m skyhus.app --safe
```

Manual in safe mode: open "Remove account …" for both accounts, and check that the lists and the files that are only local are correct. For the default account, the package unit `onedrive.service` must show as "disabled, not removed".

Manual test with a real removal: only with a new test account that has little data, never with the user's accounts. Add the account with "Add account", add a local file, then remove the account with the check box on. Check that:
- the new file is on OneDrive,
- `systemctl --user list-unit-files 'onedrive*'` does not show the service of the test account,
- the config folder is in the Trash without `refresh_token`,
- the sync folder is in the Trash.

## Open questions

1. Must the user type the account name to confirm, or is the button in the sheet enough? Both folders go to the Trash, so this document uses only the button.
