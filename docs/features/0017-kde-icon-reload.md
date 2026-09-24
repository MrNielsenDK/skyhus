# Tell KDE to reload icons after install

Version: 0.11.2
Status: developed
Created: 2026-09-24

## Problem

After `python3 -m skyhus.install`, the KDE program menu can show Skyhus without an icon, also when the icon file and the icon cache are correct (feature 0016).
Plasma (`plasmashell`) keeps the icon lookup in memory. If Plasma looked for `skyhus` before the install, it remembers that the icon does not exist. It does not look again until it restarts.

On the user's machine, `plasmashell` started before the install. The icon file and the cache were correct, but the menu had no icon. After this D-Bus signal, the menu showed the icon without a logout and without a restart of Plasma:

```bash
dbus-send --session --type=signal /KIconLoader org.kde.KIconLoader.iconChanged int32:0
```

KDE sends the same signal when the user changes the icon theme in System Settings.

## Solution

On KDE, the install command sends the signal `org.kde.KIconLoader.iconChanged` after it updates the icon cache and the program menu. The uninstall command also sends it after it removes the icon.

Rules:
- The command sends the signal only when `XDG_CURRENT_DESKTOP` contains `KDE` (not case-sensitive, the value can be a list separated by `:`). On other desktops, nothing listens to the signal.
- The command is `dbus-send --session --type=signal /KIconLoader org.kde.KIconLoader.iconChanged int32:0`. It runs through `sideeffects.run`. In safe mode, it does not run.
- If `dbus-send` is missing, the command writes a log line and continues. There is no warning.
- If `dbus-send` fails, for example when there is no session bus, the result gets this warning: `KDE did not get the message to reload icons. If the menu shows no icon for Skyhus, log out and log in again.`
- The signal does not restart a program and does not change a file.

## Scope

- The feature does not restart `plasmashell` or another program.
- The feature does not send signals on GNOME or other desktops.
- The feature does not change the icon, the icon cache or the `.desktop` file.

## Plan

1. `skyhus/desktop.py` — `is_kde(environ) -> bool`, in the same form as `is_gnome_wayland()`.
2. `skyhus/install.py` — the function `_reload_kde_icons(environ, run)`. It returns a list of warnings. `install()` and `uninstall()` get an optional `environ` parameter (default `os.environ`). `install()` calls the function after `_refresh_menu()`. `uninstall()` calls it after `_refresh_menu()` when the icon was removed.
3. `tests/test_desktop.py` and `tests/test_install.py` — the tests below.
4. `CHANGELOG.md` — an entry under `[0.11.2]` with `### Fixed`. Bump `version` to 0.11.2.

## Tests

`desktop.is_kde`:
- `KDE` → true. `ubuntu:KDE` → true. `GNOME` → false. No value → false.

Install:
- On KDE, the install calls `dbus-send --session --type=signal /KIconLoader org.kde.KIconLoader.iconChanged int32:0` after `update-desktop-database` and `kbuildsycoca6`.
- On GNOME, the install does not call `dbus-send`.
- `dbus-send` is missing (`FileNotFoundError`): no warning.
- `dbus-send` fails with exit code 1: the result has the warning about logout.
- On KDE, the uninstall calls `dbus-send` when the icon was removed.
- In safe mode without an injected `run`, `dbus-send` does not run.

## Verification

```bash
python3 -m pytest
python3 -m skyhus.install
```

Manual on KDE:
1. Run `python3 -m skyhus.install --uninstall`. The program menu no longer shows Skyhus.
2. Run `python3 -m skyhus.install`. The program menu shows Skyhus with its icon, without a logout.

## Open questions

None.
