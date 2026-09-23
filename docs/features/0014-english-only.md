# English only

Version: 0.10.0
Status: developed
Created: 2026-09-23

## Problem

All text in Skyhus is in Danish. This includes the user interface, error messages, log lines, the install command, the `.desktop` file, code comments, docstrings, `README.md`, `CLAUDE.md` and `CHANGELOG.md`.
The project must be in English. Users who do not read Danish cannot use Skyhus. Contributors who do not read Danish cannot read the code.

## Solution

All text in the project is in English. Skyhus has 1 language. There is no language setting and no translation files.

This applies to:

- all text in the user interface (QML files, and the texts that `viewmodels.py`, `service_state.py`, `apply.py` and the other modules send to QML),
- error messages and other messages that the user sees,
- log lines, including the `SAFE MODE:` lines,
- the output of `python3 -m skyhus.install` and the text in the `.desktop` file (`GenericName=OneDrive accounts`, `Comment=Multiple OneDrive accounts on Linux`),
- the comments in the files that Skyhus writes (unit files, the resync drop-in, the start script, the icon marker),
- code comments and docstrings in `skyhus/` and `tests/`,
- test names and test data where the data is not about Danish input,
- `README.md`, `CLAUDE.md`, `pyproject.toml` and all of `CHANGELOG.md`, also the old entries,
- new feature documents from 0014 and later, and new commit messages.

The name "Skyhus" does not change.

The file markers change:
- the script and the icon get `Installed by Skyhus`,
- `X-Skyhus-Installer=true` does not change.

The install command must also know the Danish markers. Then it can overwrite and remove the files from version 0.9.0.

### Word list

The same Danish word always gets the same English word.

| Danish | English |
|---|---|
| Konto, konti | Account, accounts |
| Visningsnavn | Display name |
| Synkmappe | Sync folder |
| Config-mappe | Config folder |
| Tilføj konto | Add account |
| Log ind, logget ind, ikke logget ind | Sign in, signed in, not signed in |
| Omdøb | Rename |
| Vælg mapper, mappevælger, mappevalg | Choose folders, folder picker, folder selection |
| Synkroniser alle mapper | Sync all folders |
| Synkroniser filer i roden | Sync files in the root |
| Papirkurv, flyt til papirkurven | Trash, move to Trash |
| Kører | Running |
| Starter, stopper | Starting, stopping |
| Stoppet | Stopped |
| Fejlet | Failed |
| Kræver resync | Needs resync |
| Resynkroniserer | Resyncing |
| Resync afbrudt | Resync stopped |
| Resync er færdig, færdig med fejl | Resync complete, complete with errors |
| Kører uden for servicen | Running outside the service |
| Ingen service | No service |
| Henter status … | Getting status … |
| Genstart, genstart med resync | Restart, restart with resync |
| Afbryd, afbryd resync | Stop, stop resync |
| Annullér | Cancel |
| Gem, luk, luk alligevel | Save, close, close anyway |
| Venter, i gang, færdigt, afbrudt | Waiting, running, done, stopped |
| Sikker tilstand | Safe mode |
| Applikationen | Skyhus (in the user interface), the application (in code and documents) |

"Stop" is the word for a user action that ends running work (upload, resync). "Cancel" is the word for a user action that closes a dialog or ends a sign-in without a change.

### Number format

Sizes use a decimal point: "1.5 kB", not "1,5 kB".

### Danish input stays

Skyhus must still accept Danish input. `naming.slugify` changes "æ", "ø" and "å" to "ae", "oe" and "aa". The tests for this use Danish test data. This is the only Danish text in the code.

## Scope

- The feature does not add a language setting, `qsTr()` or translation files.
- The feature does not translate the feature documents 0001–0013. They are history.
- The feature does not change old commit messages.
- The feature does not change file names, paths, service names, the environment variables or `ONEDRIVE_GUI_SAFE_MODE`.
- The feature does not change the behavior of Skyhus. Only text changes.
- The feature does not change text that comes from the `onedrive` client or from `systemctl`. Skyhus shows that text as it is.

## Plan

1. `tests/test_language.py` — a test that finds Danish text. See "Tests".
2. `skyhus/*.py` — translate all strings, comments and docstrings. Use the word list.
3. `skyhus/qml/**/*.qml` — translate all visible text and comments.
4. `skyhus/install.py` — the markers `Installed by Skyhus`. `_is_ours()` also accepts the old marker `Installeret af Skyhus`. The `.desktop` text and all output in English.
5. `skyhus/service.py`, `skyhus/service_control.py` — the comments in new unit files and in the resync drop-in in English.
6. `tests/` — translate test names, comments, docstrings and the expected texts.
7. `README.md`, `CLAUDE.md`, `pyproject.toml` (`description`, comments) — in English. `CLAUDE.md` says that the project language is English, that feature documents and `CHANGELOG.md` use ASD-STE100 in English, that the status values are `planned` and `developed`, and that documents 0001–0013 stay in Danish.
8. `CHANGELOG.md` — translate all entries. Add the entry for 0.10.0 under `### Changed`. Bump `version` to 0.10.0.
9. After the build: run `python3 -m skyhus.install` again. It overwrites the 3 installed files with the English text.

## Tests

Language:
- No file in `skyhus/`, `tests/`, `README.md`, `CLAUDE.md`, `CHANGELOG.md` or `pyproject.toml` contains "æ", "ø" or "å", or one of these Danish words as a whole word: `og`, `ikke`, `til`, `med`, `af`, `det`, `der`, `på`, `kan`, `skal`, `når`, `eller`, `hvis`, `efter`, `før`, `konto`, `konti`, `mappe`, `mapper`, `fejl`, `applikationen`, `servicen`, `klienten`, `brugeren`, `findes`, `ingen`, `alle`, `ændrer`.
- A line can have the comment `allow-danish` with a reason. The test then skips that line. Only these lines can use it:
  - the Danish input for `slugify` (`naming.py`, `test_naming.py`),
  - the old marker `Installeret af Skyhus` in `install.py`,
  - Danish folder names as test data for `sync_list` (`test_synclist.py`),
  - real systemd journal lines with a Danish unit description (`test_journal.py`).

User interface:
- The service card shows "Running", "Needs resync", "Resyncing" and "Resync stopped" for the related states.
- The safe mode banner shows "Safe mode – Skyhus does not change anything on the system".
- The steps in the "Changing folder selection" sheet have the English titles.

Install:
- The script and the icon have the marker `Installed by Skyhus`. The `.desktop` file has `GenericName=OneDrive accounts`.
- A script with the old marker `Installeret af Skyhus` is overwritten on install and removed on uninstall.

**Existing tests that change:** All tests that expect a Danish text now expect the English text from the word list. The behavior that the tests check does not change.

## Verification

```bash
python3 -m pytest
python3 -m skyhus.app --safe      # all text is in English
python3 -m skyhus.install         # the installed files get the English text
```

Manual:
1. Open all sheets in safe mode: add account, rename, folder picker, confirm resync, stop resync, remove folders, changing folder selection, closing. Make sure that no Danish text shows.
2. Open the program menu in KDE. The tooltip for Skyhus is in English.

## Open questions

None.
