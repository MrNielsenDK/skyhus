# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## The project

`skyhus` is a Qt Quick user interface (PySide6 + QML) for multiple accounts with the client [abraunegg/onedrive](https://github.com/abraunegg/onedrive) (v2.5.x, `/usr/bin/onedrive`). Each account is 1 config folder (`~/.config/onedrive` or `~/.config/onedrive-<slug>`) and 1 systemd user service. The user interface and all documentation are in English.

## Commands

The dependencies are system packages (no venv/pip): see `README.md` for the `apt install` line.

```bash
python3 -m pytest                                   # the full suite
python3 -m pytest tests/test_rules.py -k dotfiles   # 1 file / 1 selection
python3 -m skyhus.app --safe                  # start without changes to the system
python3 -m skyhus.app                         # live mode – uses the real services
```

There is no linter and no build step other than setuptools. `python3 -m compileall -q skyhus` finds syntax errors.

All tests share 1 `QGuiApplication` from the fixture `app` (`scope="session"`) in `tests/conftest.py`. No test file can make its own (`tests/test_suite.py` enforces this). The autouse fixture `collect_qt_garbage` runs `gc.collect()` after each test. Without it, a QTimer from an earlier `AppController` can hit an object that no longer exists, and then the suite has a segfault.

## Safety – most important

The machine has the real OneDrive accounts of the user (work in `~/.config/onedrive` with `onedrive.service`, private in `~/.config/onedrive-privat` with `onedrive-privat.service`).

- `systemctl --user` uses the real units, **also when `HOME` is fake**. A fake HOME isolates only files.
- Never run `start/stop/restart/reset-failed/daemon-reload/enable`, and never write under `~/.config/systemd`, `~/.config/onedrive*` or the sync folders. Read-only `systemctl --user show` and `journalctl --user … -o json` are permitted.
- Scripts outside pytest (for example screenshots) must block `subprocess.run`/`Popen`/`urlopen` as `tests/conftest.py` does, and run with `SKYHUS_SAFE_MODE=1` or `--safe`.
- With real accounts, you can try `onedrive` only with a new, temporary `--confdir` without copied files.

## Architecture

**Layers.** Pure Python modules in `skyhus/` contain all logic and do not know Qt (except `theme.py` and `viewmodels.py`). `viewmodels.py` is the only binding layer to QML: `AccountListModel`, `FolderTreeModel` and `AppController`, which `app.py` gives to QML as the initial property `controller`. QML calls slots on `controller` and reads properties and roles. There is no logic in QML.

**Side effects go through `sideeffects.py`.** `run`, `popen`, `trash` and `guard_write(path)` are the standard everywhere. In safe mode, the module blocks commands that change something, and writes under the real home folder. Safe mode is on with `--safe`, `SKYHUS_SAFE_MODE=1`, or automatically when `HOME` is not the real home folder of the user. `tests/test_sideeffects.py` examines the source code with AST and fails if a module uses `subprocess.*` or `QFile.moveToTrash` directly, or writes a file without `guard_write`. New modules must obey this. Each function with side effects takes an optional `run=`/`popen=`/`opener=`, which the tests inject. An injected function has priority over safe mode.

**Threads.** Blocking work (`systemctl` can wait 90 s because of `TimeoutStopSec`, `ExecStartPre` sleeps 15 s, Graph calls, upload) runs in `_Job` threads in `viewmodels.py`. `QTimer`s poll `job.done` in the main thread and update the models. Threads do not send Qt signals. Actions that can stop or start a service register in `_critical_jobs`. While one of them runs, `requestClose()` keeps the window open and shows `ClosingSheet`.

**Accounts.** The folders on disk set which accounts exist (`discovery.py`). `registry.py` (`~/.config/skyhus/accounts.json`) only gives them a display name and a service. An account is signed in when `refresh_token` exists.

**Sign-in.** `auth.AuthSession` runs `onedrive --auth-files auth.url:response.url` (plus `--reauth` for an existing account, with backup and restore of `refresh_token`). `LoginSheet.qml` catches the redirect to `…/oauth2/nativeclient?code=…`. `login_flow.LoginFlow` has 2 steps: `poll()` until `LOGGED_IN`, then `activate_service()`. Between the steps, the user interface shows the folder picker for new accounts.

**Folder selection.** `graph.py` gets the folder tree from Microsoft Graph with the `refresh_token` of the account (and never saves the new token). `synclist.py` writes only rules of the form `/path/` and keeps all other lines in `sync_list` unchanged at the top. `apply.prepare()` changes nothing. `apply.execute()` has a fixed order: stop service → upload (`--upload-only --no-remote-delete`) → write `sync_list` → Trash → restart with `--resync`. The service must stop first. If not, the client can send the local delete to OneDrive. `rules.RuleSet` interprets all rules of the client (`sync_list`, `skip_dir`, `skip_file`, `skip_dotfiles`, `sync_root_files`). `removal.find_removed` moves a path to the Trash only if the old rules included it and the new rules do not. If the interpretation is not certain, the code must choose the safe result: too little in the Trash is better than too much.

**Services.** `service.py` writes new units in the form of `onedrive-privat.service` (incl. `OnFailure=onedrive-failure@%N.service`, `RestartPreventExitStatus=126`) and never overwrites an existing unit. `service_control.py`: start/restart is always `reset-failed` + `restart`. Resync uses a temporary drop-in `<service>.d/zz-skyhus-resync.conf`, which copies `ExecStart` and adds `--resync --resync-auth`. The drop-in is removed again after the restart. `service_state.py` gets all units with 1 `systemctl show` call and selects the state in a fixed priority. Exit code 126 means "Needs resync". `process.py` finds `onedrive` processes outside the service through `/proc` and cgroup. Actions are refused when such a process runs.

**Design.** All colors, sizes and times are tokens in the QML singleton `Theme` (`import Skyhus 1.0`, `theme.py`). The theme follows the light/dark theme of the system live. QML must not contain `#RRGGBB` or named colors; tests enforce this and check the WCAG contrast of the tokens. Use the components in `qml/components/` again, and show dialogs as `Sheet`. Icons are Lucide SVG in `assets/icons/` through `image://icon/<name>/<rrggbb>`. The font Inter is in `assets/fonts/`.

## Workflow

The project language is English. This applies to the user interface, code, comments, documentation and commit messages. The only Danish text in the code is the Danish input for `naming.slugify` (see `tests/test_language.py`).

No code without a feature document. Each change, also bug fixes, is described in `docs/features/NNNN-short-name.md` with the skill `vaas-agenter:feature-workflow` before you write code. The user dictates features and tells you when to build. Feature documents and `CHANGELOG.md` are written in English with the ASD-STE100 rules in the skill. The feature documents 0001–0013 stay in Danish as history. Implementation usually uses the agent `vaas-agenter:implementer` with the path to the document. The agent writes tests first, bumps `version` in `pyproject.toml` (the only version source, SemVer) and adds a line in `CHANGELOG.md` (Keep a Changelog). The status in the document goes from `planned` to `developed`.
