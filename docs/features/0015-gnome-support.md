# GNOME support

Version: 0.11.0
Status: developed
Created: 2026-09-23

## Problem

Skyhus is tested only on KDE Plasma on Wayland. Nobody has run Skyhus on GNOME.
The code does not need KDE, but 3 areas can be different on GNOME:

1. **Title bar.** GNOME on Wayland does not draw title bars for applications. Qt draws the title bar itself. The default Qt title bar ("bradient") does not look like the title bars of GNOME applications.
2. **Dark theme.** On GNOME, Qt gets the light or dark setting through xdg-desktop-portal. If the portal does not give a value, `Theme._detect()` uses the palette, and the palette can be light when GNOME is dark.
3. **Packages.** The `apt install` line in `README.md` is for Debian and Ubuntu only. The README does not give the minimum versions.

## Solution

Skyhus supports GNOME 46 and later, on Wayland and on X11, in addition to KDE Plasma 6.

### Title bar

On GNOME on Wayland, Qt must use the title bar plugin `adwaita`. This plugin is part of QtWayland 6.8 and later. It draws a title bar that looks like the title bars of GNOME applications.

`app.py` sets `QT_WAYLAND_DECORATION=adwaita` before it makes the `QGuiApplication`, when all these conditions are true:
- `XDG_CURRENT_DESKTOP` contains `GNOME` (not case-sensitive, the value can be a list separated by `:`),
- `WAYLAND_DISPLAY` is set,
- `QT_WAYLAND_DECORATION` is not set (the user's value always wins),
- the plugin file `wayland-decoration-client/libadwaita.so` is in the Qt plugin folder.

If the plugin is missing, Skyhus starts with the default Qt title bar and writes this log line: `GNOME: the adwaita title bar plugin is missing. Qt draws its default title bar.`

The logic is in the new function `desktop.wayland_decoration(environ, plugin_dir)`. The function does not change anything. `app.py` applies the result.

### Dark theme

No code change is necessary if the portal gives the value. The GNOME test (see "Verification") checks this. If the test shows that the theme is wrong on GNOME, a new feature document describes the fix. This feature does not guess a fix now.

### Install

`python3 -m skyhus.install` already works without KDE: it skips `kbuildsycoca6` when the command is missing, and GNOME reads `~/.local/share/applications` without help. A test makes sure that a missing `kbuildsycoca6` gives no warning.

### README

`README.md` gets the section "Supported desktops":
- KDE Plasma 6 and GNOME 46 or later, on Wayland or X11.
- Python 3.12 or later, PySide6 6.8 or later with QtQuick, QtQuickControls2, QtSvg and QtWebEngineQuick.
- `onedrive` (abraunegg) 2.5 or later.

The install section gets 2 package lines: one for Debian and Ubuntu (the current line) and one for Fedora. The Fedora package names come from the Fedora test (see "Verification"). Until the test is done, the Fedora line is not in the README.

## Scope

- The feature does not add GNOME Shell extensions, a tray icon or a background service.
- The feature does not change the look of the window content. The controls still use the Qt style "Basic" and the Skyhus design.
- The feature does not support GNOME before version 46, other desktops (Xfce, Cinnamon and so on) or distributions other than Debian, Ubuntu and Fedora. Skyhus can work there, but nobody tests it.
- The feature does not add packages for Flatpak, Snap, apt or dnf.

## Plan

1. `skyhus/desktop.py` — `wayland_decoration(environ, plugin_dir) -> str | None`. It returns `"adwaita"` when the conditions in "Title bar" are true. Else it returns `None`. The module does not use Qt, so the tests can give their own `environ` and `plugin_dir`.
2. `skyhus/app.py` — the new function `use_gnome_title_bar(environ)`. `main()` calls it before `QGuiApplication(sys.argv)`. The function gets the plugin folder with `QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)`, call `wayland_decoration()` and set `os.environ["QT_WAYLAND_DECORATION"]` when the result is not `None`. Write the log line when GNOME on Wayland is found but the plugin is missing.
3. `tests/test_install.py` — a test: `kbuildsycoca6` is missing (`FileNotFoundError`) and `update-desktop-database` works. The result has no warnings.
4. `README.md` — the section "Supported desktops" and the minimum versions.
5. `CHANGELOG.md` — an entry under `[0.11.0]` with `### Added`. Bump `version` to 0.11.0.
6. After the GNOME test: add the Fedora package line to `README.md`, and write new feature documents for the problems that the test finds.

## Tests

`desktop.wayland_decoration`:
- GNOME on Wayland, the plugin is there, the variable is not set → `"adwaita"`.
- `XDG_CURRENT_DESKTOP=ubuntu:GNOME` → `"adwaita"`.
- `XDG_CURRENT_DESKTOP=KDE` → `None`.
- No `WAYLAND_DISPLAY` (X11) → `None`.
- `QT_WAYLAND_DECORATION=bradient` is set → `None`.
- The plugin file is missing → `None`.

`app.py`:
- `main()` calls `use_gnome_title_bar()` before it makes the `QGuiApplication`. The test checks the order in the source code with AST, the same way as the other source tests.
- `use_gnome_title_bar()` sets `QT_WAYLAND_DECORATION` when `wayland_decoration()` gives a value, writes the log line when GNOME on Wayland has no plugin, and does nothing on KDE.

Install:
- A missing `kbuildsycoca6` gives no warning.

README:
- `README.md` contains "Supported desktops", "GNOME 46" and "PySide6 6.8".

## Verification

```bash
python3 -m pytest
```

Automatic tests cannot show how Skyhus looks on GNOME. A manual test is necessary on:
- Ubuntu 24.04 LTS or later with GNOME, on Wayland and on X11,
- Fedora Workstation 42 or later (GNOME), on Wayland.

Use a virtual machine. The machine must not have the user's OneDrive accounts. Run Skyhus with `skyhus --safe` or `python3 -m skyhus.app --safe`.

On each machine, check:
1. `python3 -m skyhus.install` works, and Skyhus shows in the GNOME activities overview with its icon.
2. The dock shows the Skyhus icon next to the open window, not a default icon.
3. On Wayland, the title bar looks like the title bars of GNOME applications (the `adwaita` plugin). On X11, GNOME draws the title bar.
4. Switch between light and dark style in GNOME Settings. Skyhus changes its theme without a restart.
5. The sign-in window opens and shows the Microsoft page.
6. All sheets open and close: add account, rename, folder picker, confirm resync, stop resync, remove folders, changing folder selection, closing.
7. On Fedora, write down the package names that are necessary for step 1 to 6.

Record the results in this document under "Results of the GNOME test".

## Results of the GNOME test

Not done yet.

## Open questions

1. Does QtWayland 6.8 and later already select `adwaita` on GNOME without `QT_WAYLAND_DECORATION`? If yes, the setting in `app.py` does no harm, but it is only necessary for older Qt versions. The GNOME test answers this.
2. Which Ubuntu and Debian versions have PySide6 6.8 or later with QtWebEngine as system packages? The README must give the correct minimum versions.
