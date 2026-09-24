# Status icon in the system tray

Version: 0.14.0
Status: developed
Created: 2026-09-24

## Problem

Skyhus shows the state of the accounts only while its window is open. When the window is closed, Skyhus does not run, and the user cannot see that a service failed or needs a resync.
`onedrive-failure@.service` sends a notification when a service fails, but there is no place that always shows the state of all accounts.

## Solution

Skyhus shows an icon in the system tray. The icon shows the total state of all accounts. When the user closes the window, Skyhus keeps running in the tray. Skyhus can start at login without a window.

### The icon

The icon is the Skyhus icon (a cloud with a house). A dot in the lower right corner shows the total state:

| Total state | Dot | Rule |
|---|---|---|
| Error | danger (red) | At least 1 account has the tone `danger` ("Failed", "Needs resync"). |
| Attention | warning (orange) | No `danger`, and at least 1 account has the tone `warning` ("Starting", "Stopping", "Resyncing", "Resync stopped", "Running outside the service"). |
| OK | no dot | All other cases. |

The tones are the same as the dots in the sidebar (`service_state.STATES`), so the tray and the window always agree.
Skyhus draws the icon with `QPainter` from `assets/skyhus.svg` at 16, 22, 32 and 64 px. The colors come from the theme tokens `danger` and `warning` in the dark theme, with a white ring. The tokens of the light theme are darker for text contrast, and at 16 px their orange looks almost the same as their red.

The tooltip has 1 line per account, for example:

```
Skyhus
OneDrive: Running
privat: Needs resync
```

### Click and menu

A left click on the icon shows the window, or hides it when it is visible and active.

The menu (right click) has:

1. **Open Skyhus.**
2. 1 line per account with the name and the state, for example "privat — Needs resync". The line cannot be clicked.
   - When the state has the action "Restart" or "Start", the next item is "Restart privat" or "Start privat". It does the same as the button in the "Service" card.
   - When the state has the action "Restart with resync", the next item is "Restart privat with resync …". It opens the window and shows the confirmation sheet (feature 0004). The tray never starts a resync without the confirmation.
3. **Start Skyhus at login** (a check box). See "Start at login".
4. **Quit Skyhus.**

### Close and quit

When the tray is available:
- Closing the window hides it. Skyhus keeps running in the tray. The first time, the tray shows the message "Skyhus keeps running in the tray. To quit, use Quit Skyhus in the tray menu." Skyhus remembers in `~/.config/skyhus/settings.json` that it has shown the message.
- "Quit Skyhus" in the menu uses the same rule as closing the window today (feature 0008): while an action that can stop or start a service runs, Skyhus shows the window with the sheet "Skyhus closes when the work is done".

When the tray is not available, closing the window quits Skyhus, as today.

### Status in the background

While the window is visible, Skyhus reads the state every 3 seconds, as today.
While the window is hidden, Skyhus reads the state every 30 seconds for the tray. It reads only `systemctl --user show` (1 call for all accounts) and `/proc`. It does not read the journal (the card "Activity" and the progress read the journal only while the window is visible).

### Start at login

The check box "Start Skyhus at login" writes or removes `~/.config/autostart/skyhus.desktop`:

```
[Desktop Entry]
Type=Application
Name=Skyhus
Exec=<full path to ~/.local/bin/skyhus> --background
Icon=skyhus
X-GNOME-Autostart-enabled=true
X-Skyhus-Installer=true
```

- The check box is on when the file exists and has the marker `X-Skyhus-Installer=true`.
- Skyhus never overwrites or removes an autostart file without the marker. Then the check box cannot be changed, and its tooltip tells why.
- The check box cannot be changed when `~/.local/bin/skyhus` does not exist (Skyhus is not installed with `python3 -m skyhus.install`). Its tooltip says "Install Skyhus first: python3 -m skyhus.install".
- `python3 -m skyhus.install --uninstall` also removes the autostart file, when it has the marker.
- In safe mode, the check box shows the state, but Skyhus does not write or remove the file (`guard_write`).

`--background` starts Skyhus without a window, only with the tray icon. When the tray is not available, Skyhus ignores `--background` and shows the window.

### Only 1 Skyhus

Skyhus runs only once for each user. When Skyhus starts, it connects to the local socket `skyhus-<uid>` (`QLocalSocket`):
- If a Skyhus runs, the new start sends "show" to it, and the running Skyhus shows its window. The new start then quits with exit code 0.
- If no Skyhus runs, the new start listens on the socket (`QLocalServer`). A socket file that is left after a crash is removed before Skyhus listens.

### Desktops

- **KDE Plasma:** the tray uses StatusNotifierItem through D-Bus. It works on Wayland and on X11.
- **GNOME:** GNOME shows tray icons only with the extension "AppIndicator and KStatusNotifierItem Support". Ubuntu has it on by default. Without it, `QSystemTrayIcon.isSystemTrayAvailable()` is false, and Skyhus works as today, without a tray.

## Scope

- The feature does not add notifications. `onedrive-failure@.service` already sends a notification when a service fails.
- The feature does not start a resync from the tray without the confirmation in the window.
- The feature does not read the journal while the window is hidden.
- The feature does not add a settings window. The only setting is the check box in the tray menu.
- The feature does not change the behavior when the tray is not available.

## Plan

1. `skyhus/tray_state.py` — a new module without Qt: `total_tone(statuses)`, `tooltip(accounts, statuses)` and `menu_items(accounts, statuses)` (a list of lines and actions for the menu).
2. `skyhus/autostart.py` — a new module without Qt: `autostart_path(home)`, `render()`, `state(home) -> ON | OFF | FOREIGN | NOT_INSTALLED`, `enable(home)`, `disable(home)`. All writes use `sideeffects.guard_write`.
3. `skyhus/settings.py` — read and write `~/.config/skyhus/settings.json` (only `tray_hint_shown` for now).
4. `skyhus/tray.py` — the Qt part: `QSystemTrayIcon`, the icon with the dot, the menu, and the connection to `AppController`. Like `viewmodels.py`, this module uses Qt. `CLAUDE.md` names it.
5. `skyhus/app.py` —
   - `QApplication` in place of `QGuiApplication`, because `QSystemTrayIcon` needs Qt Widgets.
   - the single instance with `QLocalServer`/`QLocalSocket` in a function `single_instance(name)`,
   - `--background`,
   - the tray when `QSystemTrayIcon.isSystemTrayAvailable()`.
6. `skyhus/viewmodels.py` —
   - the property `trayActive`,
   - `requestClose()` hides the window when `trayActive` and the user closes the window,
   - the slot `quit()` for "Quit Skyhus" with the rule from feature 0008,
   - the status timer of 30 seconds while the window is hidden,
   - the signal `statusesChanged` for the tray.
7. `skyhus/qml/Main.qml` — `onClosing` uses the new result of `requestClose()`, and the window can be shown and hidden by the controller.
8. `skyhus/install.py` — `--uninstall` removes the autostart file with the marker. The install checks that `PySide6.QtWidgets` and `PySide6.QtNetwork` exist.
9. `tests/conftest.py` — the shared application fixture makes a `QApplication`, so the tray tests can run. `tests/test_suite.py` still checks that no test file makes its own application.
10. `README.md` — the section "System tray" and `python3-pyside6.qtwidgets python3-pyside6.qtnetwork` in the `apt install` line. `CLAUDE.md` — `tray.py` and `app.py` as Qt modules. `CHANGELOG.md` — an entry under `[0.14.0]` with `### Added`. Bump `version` to 0.14.0.

## Tests

`tray_state`:
- 1 account "Failed" and 1 "Running" gives `danger`. 1 "Resyncing" and 1 "Running" gives `warning`. All "Running" gives `success`. No accounts gives `success`.
- "Stopped", "Not signed in" and "No service" do not change the total state (the tone `textSecondary`).
- The tooltip has "Skyhus" and 1 line per account with the name and the state label.
- The menu items for "Running" give "Restart <name>". "Stopped" and "Failed" give "Start <name>". "Needs resync" gives "Restart <name> with resync …" with the action "open and confirm". "Resyncing" gives no action item.

`autostart`:
- `enable()` writes the file with `Exec=<home>/.local/bin/skyhus --background` and the marker. `disable()` removes it.
- A file without the marker gives `FOREIGN`. `enable()` and `disable()` do not change it.
- Without `~/.local/bin/skyhus`, `state()` gives `NOT_INSTALLED`, and `enable()` writes nothing.
- In safe mode without a fake home, `enable()` and `disable()` write and remove nothing under the real home folder.
- `install.uninstall()` removes the autostart file with the marker and keeps a file without the marker.

Single instance:
- A second `single_instance()` with the same name returns false and sends "show". The first gets the "show" message.
- A left socket file from a crash does not stop the first start.

Controller and tray:
- With `trayActive`, `requestClose()` hides the window and returns false. Skyhus keeps running. The first time, the tray message is shown, and `settings.json` has `tray_hint_shown`.
- Without `trayActive`, `requestClose()` works as before.
- `quit()` during a critical action shows the window and the closing sheet. Without a critical action, the application quits.
- While the window is hidden, the status timer has 30 seconds, and the progress and activity timers do not run.
- The tray icon gets a new icon and tooltip when the statuses change. The menu item "Restart <name>" calls the same action as the card. "Restart <name> with resync …" shows the window and the confirmation sheet.

## Verification

```bash
python3 -m pytest
python3 -m skyhus.app --safe
```

Manual on KDE, in safe mode:
1. The tray shows the Skyhus icon. The tooltip lists both accounts.
2. Close the window. Skyhus stays in the tray and shows the message 1 time.
3. Start `skyhus --safe` again from a terminal. The running Skyhus shows its window, and the new start quits.
4. The menu shows both accounts. "Quit Skyhus" quits.
5. "Start Skyhus at login" is not changed in safe mode.

Manual on KDE, without safe mode:
1. Turn on "Start Skyhus at login". Log out and log in. Skyhus runs in the tray without a window.
2. Turn it off. `~/.config/autostart/skyhus.desktop` is gone.

## Open questions

1. Must the icon show a green dot when all is OK, or no dot? This document uses no dot, so the icon is quiet when all is well.
2. Must "Start Skyhus at login" be on by default after the install? This document uses off: the user turns it on.
