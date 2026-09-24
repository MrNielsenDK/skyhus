# Changelog

The project follows [Keep a Changelog](https://keepachangelog.com/) and [SemVer](https://semver.org/).

## [0.13.0] - 2026-09-24

### Added
- The account page has the card "Activity" with the last 24 hours from the journal of the service: a summary with the last sync and the numbers of downloaded, uploaded, deleted and failed files, the problems grouped by kind, and the newest files. "Copy problems" copies the problems to the clipboard. See `docs/features/0019-activity-and-problems.md`.
- The sheet "Files in the last 24 hours" shows the newest 200 files. See `docs/features/0019-activity-and-problems.md`.

## [0.12.0] - 2026-09-24

### Added
- The account page has the button "Remove account …". The sheet "Remove account?" shows what Skyhus removes and keeps. Skyhus disables the units that start the service, stops and disables the service, removes only the unit files that it wrote, deletes the sign-in token, and moves the config folder to the Trash. See `docs/features/0018-remove-account.md`.
- The check box "Also move the local folder to the Trash" is on by default. Skyhus then uploads the local changes first and shows the files that are only on this computer. If the upload fails or the user clicks "Stop", Skyhus enables the service again and changes nothing. See `docs/features/0018-remove-account.md`.

## [0.11.2] - 2026-09-24

### Fixed
- On KDE, the program menu shows the Skyhus icon right after the install, without a logout. The install and uninstall commands send the KDE signal `org.kde.KIconLoader.iconChanged`, so Plasma looks for the icon again. See `docs/features/0017-kde-icon-reload.md`.

## [0.11.1] - 2026-09-24

### Fixed
- The program menu shows the Skyhus icon also when `~/.local/share/icons/hicolor/` has a GTK icon cache from a different program. The install command updates the cache after it writes the icon, and the uninstall command updates it after it removes the icon. See `docs/features/0016-icon-cache.md`.

## [0.11.0] - 2026-09-23

### Added
- On GNOME on Wayland, Skyhus uses the Qt title bar plugin `adwaita`, if it is installed. The title bar then looks like the title bars of GNOME applications. A value that the user sets in `QT_WAYLAND_DECORATION` always wins. See `docs/features/0015-gnome-support.md`.
- `README.md` has the section "Supported desktops" with KDE Plasma 6, GNOME 46 or later, and the minimum versions of Python, PySide6 and `onedrive`. See `docs/features/0015-gnome-support.md`.

## [0.10.0] - 2026-09-23

### Changed
- All text in Skyhus is in English. This includes the user interface, the messages, the log lines, the output of `python3 -m skyhus.install` and the `.desktop` file. See `docs/features/0014-english-only.md`.
- All text in the project is in English. This includes the code comments, `README.md`, `CLAUDE.md` and `CHANGELOG.md`. See `docs/features/0014-english-only.md`.
- The install command knows the files that version 0.9.0 installed. It overwrites them on install and removes them on uninstall. See `docs/features/0014-english-only.md`.

## [0.9.0] - 2026-09-23

### Added
- The command `python3 -m skyhus.install` adds Skyhus to the program menu with an icon and installs the command `skyhus`. `--uninstall` removes them again. The installation overwrites and removes only files that Skyhus wrote. See `docs/features/0013-installer-paa-skrivebordet.md`.
- The window has the Skyhus icon. On Wayland, the panel shows the icon next to the window. See `docs/features/0013-installer-paa-skrivebordet.md`.

### Removed
- `pyproject.toml` does not require PySide6 from PyPI. The README does not describe `pip install`. See `docs/features/0013-installer-paa-skrivebordet.md`.

## [0.8.0] - 2026-09-23

### Changed
- The application has the name Skyhus. The package is `skyhus`, the command is `skyhus`, and the window has the title "Skyhus". See `docs/features/0012-omdoeb-til-skyhus.md`.
- The application saves `accounts.json` and `state.json` in `~/.config/skyhus/`. The name of the drop-in for resync is `zz-skyhus-resync.conf`. See `docs/features/0012-omdoeb-til-skyhus.md`.
- The environment variable for safe mode is `SKYHUS_SAFE_MODE`. The old `ONEDRIVE_GUI_SAFE_MODE` also turns on safe mode. See `docs/features/0012-omdoeb-til-skyhus.md`.

## [0.7.1] - 2026-09-23

### Fixed
- In safe mode, "Stop resync" does not write the marker in `~/.config/onedrive-gui/state.json`. The card continues to show "Resyncing", because the service continues to run. See `docs/features/0011-sikker-tilstand-markering-og-signaler.md`.
- The sign-in stops the `onedrive` process with `sideeffects.signal_process`. In safe mode, the application does not send a signal. An AST test prevents direct signals in all modules. See `docs/features/0011-sikker-tilstand-markering-og-signaler.md`.

## [0.7.0] - 2026-09-23

### Added
- The sheet "Changing folder selection" has the button "Stop" while the application uploads local changes. A click stops the upload. The application does not write `sync_list` and does not move anything to the Trash. If the service was running before, the application starts it again without `--resync`. See `docs/features/0010-afbryd-upload-og-resync.md`.
- The "Service" card has the button "Stop resync" during "Resyncing". After a confirmation, the application stops the service. The card then shows "Resync stopped" with the button "Restart with resync". See `docs/features/0010-afbryd-upload-og-resync.md`.
- The application keeps a marker for each service with a stopped resync in `~/.config/onedrive-gui/state.json`. The marker is removed when the service starts again. See `docs/features/0010-afbryd-upload-og-resync.md`.

## [0.6.0] - 2026-09-23

### Added
- The sheet "Changing folder selection" shows the 5 steps of a change to the folder selection and the state of each step. During the upload, the sheet shows the number of uploaded files and the last file. During the move to Trash, it shows the number of moved paths. See `docs/features/0009-vis-fremdrift.md`.
- The "Service" card has the state "Resyncing" when the service runs with `--resync`. The card shows the phase, a progress bar, the last file and the time since the start. The status dot in the sidebar has the warning color. See `docs/features/0009-vis-fremdrift.md`.
- When the client is done with `--resync`, the card shows "Resync complete" or "Resync complete with errors" with the number of failed items. The progress is the same when the user opens the application again. See `docs/features/0009-vis-fremdrift.md`.

## [0.5.3] - 2026-09-23

### Fixed
- If the user closes the window while the application stops or starts a service, the window waits for the action. The sheet "Skyhus closes when the work is done" shows the action. Then the window closes automatically. "Close anyway" first shows a warning. See `docs/features/0008-oprydning-luk-annuller-tests-readme.md`.
- "Cancel" now works while the application stops the service before a sign-in with `--reauth`. The button shows "Cancelling …". The application does not start `onedrive`, and it starts the service again if the service was running before. See `docs/features/0008-oprydning-luk-annuller-tests-readme.md`.
- The test suite passes in all orders. All tests use 1 shared `QGuiApplication` from `tests/conftest.py`. See `docs/features/0008-oprydning-luk-annuller-tests-readme.md`.

### Changed
- `README.md` describes the folder picker, the Trash, the "Service" card and sign-in again with `--reauth`. See `docs/features/0008-oprydning-luk-annuller-tests-readme.md`.

## [0.5.2] - 2026-09-23

### Fixed
- When the user removes a folder from the selection, the application moves to the Trash only the paths that the client synced before and does not sync now. The application uses all rules in `sync_list`, `skip_dir`, `skip_file`, `skip_dotfiles` and `sync_root_files`. Symlinks and folders with `.nosync` always stay. If the application cannot interpret a rule in `sync_list`, it shows the rule and does not change anything. See `docs/features/0006-papirkurv-respekterer-alle-regler.md`.

## [0.5.1] - 2026-09-23

### Fixed
- "Sign in" on an account with a `refresh_token` now works. The application stops the service of the account, signs in with `onedrive --reauth` and starts the service again. If the sign-in fails, or if the user stops it, the application puts back the old `refresh_token`. See `docs/features/0005-log-ind-igen-med-reauth.md`.

## [0.5.0] - 2026-09-23

### Added
- The application has a safe mode. In safe mode, the application does not change anything on the system, and a banner shows at the top of the window. See `docs/features/0007-sikker-tilstand.md`.
- The command `python3 -m onedrive_gui.app --safe` turns on safe mode. The environment variable `ONEDRIVE_GUI_SAFE_MODE=1` and a fake `HOME` also turn it on. See `docs/features/0007-sikker-tilstand.md`.

## [0.4.0] - 2026-09-23

### Added
- The account page has the "Service" card. The card shows the state of the service, the time when the state started, and the last error line from the journal. See `docs/features/0004-servicestatus-og-genstart.md`.
- The card has the button "Start", "Restart" or "Restart with resync". "Restart with resync" first shows a confirmation. See `docs/features/0004-servicestatus-og-genstart.md`.

### Changed
- The status dot in the sidebar shows the state of the service. The application updates it every 3 seconds while the window is visible. See `docs/features/0004-servicestatus-og-genstart.md`.

## [0.3.0] - 2026-09-23

### Added
- Each account has a round avatar with initials and a fixed color. The application includes the font Inter and icons from Lucide. See `docs/features/0003-design-apple-inspireret.md`.

### Changed
- The window has a new design, inspired by "System Settings" on macOS. It has a sidebar with accounts, cards with rows, and sheets that slide down from the top. See `docs/features/0003-design-apple-inspireret.md`.
- The application follows the light or dark theme of the system and changes without a restart. See `docs/features/0003-design-apple-inspireret.md`.

## [0.2.0] - 2026-09-23

### Added
- Each account has the button "Choose folders". The folder picker gets the folders from OneDrive and writes `sync_list` and `sync_root_files`. See `docs/features/0002-vaelg-mapper-til-synk.md`.
- After the sign-in for a new account, the application shows the folder picker. The service starts only when the user has chosen folders. See `docs/features/0002-vaelg-mapper-til-synk.md`.
- When the user removes folders from the selection, the application moves the local copies to the Trash after a confirmation. The application does not delete anything on OneDrive. See `docs/features/0002-vaelg-mapper-til-synk.md`.

## [0.1.0] - 2026-09-23

### Added
- The application shows all OneDrive accounts on the machine, and if each account is signed in. See `docs/features/0001-flere-konti-og-login.md`.
- The user can give an account a display name, add a new account and sign in in a built-in browser window. See `docs/features/0001-flere-konti-og-login.md`.
- After the sign-in, the application makes and starts a systemd user service for a new account. See `docs/features/0001-flere-konti-og-login.md`.

## [0.0.0] - 2026-09-23

### Added
- The project is created. There is no code yet.
