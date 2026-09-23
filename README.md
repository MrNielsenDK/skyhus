# Skyhus

Skyhus is a Qt window for multiple OneDrive accounts on the same machine.
Skyhus uses the client [abraunegg/onedrive](https://github.com/abraunegg/onedrive).
Each account has its own config folder and its own systemd user service.

Skyhus can:

- show all accounts in `~/.config/onedrive` and `~/.config/onedrive-*`,
- show if each account is signed in,
- give each account a display name,
- add a new account with sign-in in a built-in browser window,
- sign in an existing account again with `--reauth`,
- choose which folders on OneDrive each account syncs,
- show the state of the service for each account and start or restart it,
- show the progress during upload, move to Trash and `--resync`.

## Add an account

Click "Add account". Type a display name and a sync folder.
Skyhus makes the config folder and opens the Microsoft sign-in page.
When you are signed in, Skyhus shows the folder picker.
Skyhus makes and starts the service when you click "OK" in the folder picker.
If you close the folder picker and do not choose, the account is signed in, but Skyhus does not make the service.

## Sign in again

Click "Sign in" on an account that is already signed in. Skyhus then signs in with `--reauth`.

- If the service of the account is running, Skyhus stops it before the sign-in. The sign-in sheet shows "The service is stopped while you sign in".
- When the sign-in is complete, Skyhus starts the service again. It starts the service only if the service was running before the sign-in.
- If the sign-in fails, or if you click "Cancel", Skyhus puts back the old `refresh_token` and starts the service again.
- You can click "Cancel" while the service stops. The button then shows "Cancelling …". Skyhus does not start `onedrive` when the service has stopped.
- If a different `onedrive` process uses the account, Skyhus does not start the sign-in.

## Choose folders

Click "Choose folders …" on an account. The folder picker gets the folders from OneDrive with the sign-in of the account.

- Select "Sync all folders", or select the folders that the account must sync.
- "Sync files in the root" sets if the client also syncs the files at the top level of OneDrive.
- You cannot select a folder that is in `skip_dir`.
- Skyhus writes the selection to `sync_list`. Skyhus keeps all other lines in the file as they are.

If you remove a folder from the selection, Skyhus moves the local copy to the Trash. OneDrive keeps the folder.
Before this, Skyhus shows a list of the local folders and files and their total size.
Click "Move to Trash" to confirm, or click "Cancel" to stop.

When you save a new folder selection for an account that synced before, Skyhus does these steps in this order:

1. It stops the service of the account.
2. It uploads local changes with `--upload-only --no-remote-delete`.
3. It writes `sync_list`.
4. It moves the removed folders to the Trash.
5. It restarts the service 1 time with `--resync`. This can take a long time for a large account.

The sheet "Changing folder selection" shows the 5 steps. Each step shows "Waiting", "Running", "Done" or "Failed".
During the upload, the sheet shows the number of uploaded files and the last file. During the move to Trash, it shows the number of moved paths.
The sheet closes when the service has started with `--resync`. If a step fails, the sheet stays open until you click "Close".

During step 2, the sheet has the button "Stop". A click stops the upload. Then Skyhus does not change anything.
It does not write `sync_list` and does not move anything to the Trash. If the service was running before, it starts again without `--resync`.
The sheet shows "The change is stopped. The folder selection did not change." Files that the client uploaded before the stop stay on OneDrive.
After step 2, you cannot stop the change.

## The "Service" card

The "Service" card on each account shows the state of the service and the time when the state started. Skyhus reads the state every 3 seconds while the window is visible.
The dot next to the account in the sidebar has the same color as the state.

| State | Button |
| --- | --- |
| Running | "Restart" stops the client and starts it again. |
| Starting | "Restart" |
| Stopping | No button |
| Stopped | "Start" starts the client. |
| Failed | "Start" resets the failure and starts the client. The card shows the last error from the log. |
| Needs resync | "Restart with resync" restarts the service 1 time with `--resync --resync-auth`. You must confirm it first. |
| Resyncing | "Stop resync" stops the service. You must confirm it first. The card shows the phase, a progress bar, the last file and the time since the start. |
| Resync stopped | "Restart with resync". Skyhus does not start the service without `--resync`, because the database of the client can be incomplete. |
| Running outside the service | No button. A different `onedrive` process uses the account. |
| Not signed in | No button |
| No service | No button |

During "Resyncing", Skyhus reads the journal of the service every 2 seconds while the window is visible.
The state applies when the main process of the service has `--resync` and the client has not yet written that the sync is complete.
The progress bar shows the number of files when the client has written the total number. If not, the progress bar moves from side to side.
When the client is done, the card shows "Resync complete" or "Resync complete with errors" and the number of failed items.
If you close Skyhus and open it again, Skyhus reads the full journal for the current run of the service and shows the same progress.

After a click, Skyhus waits for up to 120 seconds until the service runs or fails.
If the service does not become stable, the card shows "The service does not respond.".
If `systemctl` cannot do the action, the card shows the message from `systemctl`.

## Install the dependencies

Skyhus uses the system packages from Ubuntu/Debian:

```bash
sudo apt install onedrive python3-pyside6.qtquick python3-pyside6.qtquickcontrols2 \
    python3-pyside6.qtwebenginequick python3-pyside6.qtsvg python3-pytest
```

The sign-in window needs `python3-pyside6.qtwebenginequick`.
Without this package, Skyhus starts, but the sign-in window shows an error.

## Start Skyhus

Run this command from the root of the project:

```bash
python3 -m skyhus.app
```

## Install

Run this command from the root of the project:

```bash
python3 -m skyhus.install
```

The command adds Skyhus to the program menu and installs the command `skyhus`. It writes 3 files:

- `~/.local/bin/skyhus` starts Skyhus from the project folder,
- `~/.local/share/applications/skyhus.desktop` shows Skyhus in the program menu,
- `~/.local/share/icons/hicolor/scalable/apps/skyhus.svg` is the icon.

The installation uses the PySide6 of the system. It does not use pip.
If one of the files already exists, and Skyhus did not write it, the installation stops and does not change anything.

If you move the project folder, run `python3 -m skyhus.install` again.

To remove Skyhus from the program menu, run this command:

```bash
python3 -m skyhus.install --uninstall
```

The command removes only the 3 files. Your accounts, services, sync folders and `~/.config/skyhus/` stay.

## Safe mode

In safe mode, Skyhus does not change anything on the system.
The user interface and all flows still work. You can try them and take screenshots.
At the top of the window, a banner shows "Safe mode – Skyhus does not change anything on the system".

To start Skyhus in safe mode, run this command:

```bash
python3 -m skyhus.app --safe
```

Safe mode is also on in these 2 cases:

- The environment variable `SKYHUS_SAFE_MODE` is `1`.
- `HOME` is a different folder than your real home folder. In this case, you cannot turn off safe mode.

In safe mode, these rules apply:

- `systemctl --user show`, `cat`, `status` and `is-active` run as usual. `journalctl` also runs as usual.
- All other `systemctl` commands do not run. Skyhus reports that they were successful.
- Skyhus does not start `onedrive`. A sign-in ends with the error "Safe mode: onedrive was not started".
- Skyhus does not move files to the Trash.
- Skyhus does not write files under your real home folder. The exception is `~/.config/skyhus/`.
- Calls to Microsoft Graph run as usual. The calls only read.

Each blocked action writes a line to the log. The line starts with `SAFE MODE:`.

## Run the tests

```bash
python3 -m pytest
```

The tests use a temporary `HOME` and safe mode. They do not call the real `onedrive` or `systemctl`.
The test of `LoginSheet.qml` is skipped if QtWebEngine is not installed.

## Files

- `~/.config/skyhus/accounts.json` keeps the display names.
- `~/.config/skyhus/state.json` keeps the services where you stopped a resync.
- `~/.config/onedrive-<slug>/config` is the config file for a new account.
- `~/.config/systemd/user/onedrive-<slug>.service` is the service for a new account.
