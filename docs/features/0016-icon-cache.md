# Update the icon cache on install

Version: 0.11.1
Status: developed
Created: 2026-09-23

## Problem

After `python3 -m skyhus.install`, the KDE program menu shows Skyhus without an icon.

The icon file is correct: `~/.local/share/icons/hicolor/scalable/apps/skyhus.svg` exists, and `kiconfinder6 skyhus` finds it.
But `~/.local/share/icons/hicolor/` also contains the GTK icon cache `icon-theme.cache`. A different program made this cache before Skyhus was installed. The cache does not contain `skyhus`.
Qt uses the cache when it exists, and does not look in the folder. The Plasma menu uses Qt to find icons. So Qt does not find `skyhus`.

Reproduction on the user's machine (Qt 6.10, KDE Plasma 6):
1. `~/.local/share/icons/hicolor/icon-theme.cache` exists and does not contain `skyhus`.
2. `QIcon.fromTheme("skyhus")` with the search paths `~/.local/share/icons` and `/usr/share/icons` gives a null icon. `onedrive` and `linkedin` from the same cache are found.
3. On a copy of the folder, `gtk-update-icon-cache -f -t` makes a new cache. After that, Qt finds `skyhus`.

## Solution

When the icon cache `icon-theme.cache` exists in `~/.local/share/icons/hicolor/`, the install command updates it after it writes the icon. The uninstall command also updates it after it removes the icon.
The command is `gtk-update-icon-cache -f -t <home>/.local/share/icons/hicolor`.

Rules:
- If `icon-theme.cache` does not exist, the command does not make one. Qt then looks in the folder, and it finds the icon.
- If `gtk-update-icon-cache` is missing, the result gets this warning: `The icon cache <path> does not contain the Skyhus icon, and gtk-update-icon-cache is missing. Install the package that contains gtk-update-icon-cache and run the install again.`
- If the command fails, the result gets a warning with the exit code and the message. The install does not stop.
- The command runs through `sideeffects.run`, before `update-desktop-database` and `kbuildsycoca6`. In safe mode, the command does not run.

The cache is data that `gtk-update-icon-cache` makes from the folder. The command writes a new cache with all icons in the folder, also the icons from other programs. It does not remove icons from other programs.

## Scope

- The feature does not change other icon caches, for example in `/usr/share/icons`.
- The feature does not remove an icon cache that Skyhus did not make.
- The feature does not change the icon or the `.desktop` file.

## Plan

1. `skyhus/install.py` — the function `_refresh_icon_cache(home, run)`. It returns a list of warnings. `install()` calls it after it writes the files. `uninstall()` calls it after it removes the icon.
2. `tests/test_install.py` — the tests below.
3. `CHANGELOG.md` — an entry under `[0.11.1]` with `### Fixed`. Bump `version` to 0.11.1.
4. After the build: run `python3 -m skyhus.install` again on the user's machine.

## Tests

- With `icon-theme.cache` in the fake `HOME`: the install calls `gtk-update-icon-cache -f -t <home>/.local/share/icons/hicolor`, before `update-desktop-database`.
- Without `icon-theme.cache`: the install does not call `gtk-update-icon-cache`.
- `gtk-update-icon-cache` is missing (`FileNotFoundError`) and the cache exists: the result has the warning about the missing command. The 3 files are written.
- `gtk-update-icon-cache` fails with exit code 1: the result has a warning with the exit code.
- The uninstall calls `gtk-update-icon-cache` when the cache exists and the icon was removed.
- In safe mode without an injected `run`, the command does not run.

## Verification

```bash
python3 -m pytest
python3 -m skyhus.install
```

Manual:
1. The KDE program menu shows Skyhus with its icon. If the menu does not change at once, log out and log in again.
2. The panel shows the icon next to the open Skyhus window.

## Open questions

None.
