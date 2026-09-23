# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projektet

`skyhus` er en Qt Quick-brugerflade (PySide6 + QML) til flere konti med klienten [abraunegg/onedrive](https://github.com/abraunegg/onedrive) (v2.5.x, `/usr/bin/onedrive`). Hver konto er én config-mappe (`~/.config/onedrive` eller `~/.config/onedrive-<slug>`) og én systemd-user-service. Brugerfladen og al dokumentation er på dansk.

## Kommandoer

Afhængighederne er systempakker (ingen venv/pip): se `README.md` for `apt install`-linjen.

```bash
python3 -m pytest                                   # hele suiten
python3 -m pytest tests/test_rules.py -k dotfiles   # én fil / ét udvalg
python3 -m skyhus.app --safe                  # start uden at ændre noget på systemet
python3 -m skyhus.app                         # skarp tilstand – rammer de rigtige services
```

Der er ingen linter eller build-trin ud over setuptools. `python3 -m compileall -q skyhus` fanger syntaksfejl.

Alle tests deler én `QGuiApplication` fra fixturen `app` (`scope="session"`) i `tests/conftest.py`. Ingen testfil må oprette sin egen (`tests/test_suite.py` håndhæver det). Den autouse-fixture `collect_qt_garbage` kører `gc.collect()` efter hver test. Uden den kan en QTimer fra en tidligere `AppController` ramme et objekt, der ikke findes længere, og så segfaulter suiten.

## Sikkerhed – vigtigst

Maskinen har brugerens rigtige OneDrive-konti (firma i `~/.config/onedrive` med `onedrive.service`, privat i `~/.config/onedrive-privat` med `onedrive-privat.service`).

- `systemctl --user` rammer de rigtige units, **også når `HOME` er falsk**. En falsk HOME isolerer kun filer.
- Kør aldrig `start/stop/restart/reset-failed/daemon-reload/enable` og skriv aldrig under `~/.config/systemd`, `~/.config/onedrive*` eller synkmapperne. Læsende `systemctl --user show` og `journalctl --user … -o json` er i orden.
- Scripts uden for pytest (fx skærmbilleder) skal blokere `subprocess.run`/`Popen`/`urlopen` som `tests/conftest.py` gør, og køre med `SKYHUS_SAFE_MODE=1` eller `--safe`.
- Mod rigtige konti må `onedrive` kun afprøves med en ny, midlertidig `--confdir` uden kopierede filer.

## Arkitektur

**Lag.** Rene Python-moduler i `skyhus/` indeholder al logik og kender ikke Qt (undtagen `theme.py` og `viewmodels.py`). `viewmodels.py` er det eneste bindingslag til QML: `AccountListModel`, `FolderTreeModel` og `AppController`, som `app.py` giver QML som initial property `controller`. QML kalder slots på `controller` og læser properties og roller. Der er ingen logik i QML.

**Side-effekter går gennem `sideeffects.py`.** `run`, `popen`, `trash` og `guard_write(path)` er standarden overalt. I sikker tilstand blokerer modulet kommandoer, der ændrer noget, og skrivninger under den rigtige hjemmemappe. Sikker tilstand slår til med `--safe`, `SKYHUS_SAFE_MODE=1`, eller automatisk når `HOME` ikke er brugerens rigtige hjemmemappe. `tests/test_sideeffects.py` gennemgår kildekoden med AST og fejler, hvis et modul bruger `subprocess.*` eller `QFile.moveToTrash` direkte, eller skriver en fil uden `guard_write`. Nye moduler skal følge det. Hver funktion med side-effekter tager en valgfri `run=`/`popen=`/`opener=`, som testene injicerer. En injiceret funktion går foran sikker tilstand.

**Tråde.** Blokerende arbejde (`systemctl` kan vente 90 s pga. `TimeoutStopSec`, `ExecStartPre` sover 15 s, Graph-kald, upload) kører i `_Job`-tråde i `viewmodels.py`. `QTimer`s poller `job.done` i hovedtråden og opdaterer modellerne. Tråde sender ikke Qt-signaler. Handlinger, der kan stoppe eller starte en service, registrerer sig i `_critical_jobs`. Så længe en af dem kører, holder `requestClose()` vinduet åbent og viser `ClosingSheet`.

**Konti.** Mapperne på disken afgør, hvilke konti der findes (`discovery.py`). `registry.py` (`~/.config/skyhus/accounts.json`) giver dem kun visningsnavn og service. En konto er logget ind, når `refresh_token` findes.

**Login.** `auth.AuthSession` kører `onedrive --auth-files auth.url:response.url` (plus `--reauth` for en eksisterende konto, med backup/tilbagelægning af `refresh_token`). `LoginSheet.qml` fanger videresendelsen til `…/oauth2/nativeclient?code=…`. `login_flow.LoginFlow` har 2 trin: `poll()` til `LOGGED_IN`, derefter `activate_service()`. Imellem viser brugerfladen mappevælgeren for nye konti.

**Mappevalg.** `graph.py` henter mappetræet fra Microsoft Graph med kontoens `refresh_token` (og gemmer aldrig det nye token). `synclist.py` skriver kun regler af formen `/sti/` og bevarer alle andre linjer i `sync_list` uændret øverst. `apply.prepare()` ændrer intet. `apply.execute()` har en fast rækkefølge: stop service → upload (`--upload-only --no-remote-delete`) → skriv `sync_list` → papirkurv → genstart med `--resync`. Servicen skal stoppes først, ellers kan klienten sende den lokale sletning videre til OneDrive. `rules.RuleSet` tolker alle klientens regler (`sync_list`, `skip_dir`, `skip_file`, `skip_dotfiles`, `sync_root_files`). `removal.find_removed` lægger kun en sti i papirkurven, hvis de gamle regler inkluderede den, og de nye ikke gør. Er tolkningen i tvivl, skal koden vælge det sikre: hellere for lidt i papirkurven end for meget.

**Services.** `service.py` skriver nye units efter formen på `onedrive-privat.service` (inkl. `OnFailure=onedrive-failure@%N.service`, `RestartPreventExitStatus=126`) og overskriver aldrig en eksisterende. `service_control.py`: start/genstart er altid `reset-failed` + `restart`. Resync sker via en midlertidig drop-in `<service>.d/zz-skyhus-resync.conf`, som kopierer `ExecStart` og tilføjer `--resync --resync-auth`. Drop-in'en fjernes igen efter genstarten. `service_state.py` henter alle units med ét `systemctl show`-kald og vælger tilstand i en fast prioritet. Exit-kode 126 betyder "Kræver resync". `process.py` finder `onedrive`-processer uden for servicen via `/proc` og cgroup. Handlinger afvises, når sådan en proces kører.

**Design.** Alle farver, størrelser og tider ligger som tokens i QML-singletonen `Theme` (`import Skyhus 1.0`, `theme.py`). Temaet følger systemets lyse/mørke tema live. QML må ikke indeholde `#RRGGBB` eller navngivne farver; tests håndhæver det og tjekker WCAG-kontrast for tokens. Genbrug komponenterne i `qml/components/` og præsentér dialoger som `Sheet`. Ikoner er Lucide-SVG i `assets/icons/` via `image://icon/<navn>/<rrggbb>`. Skriften Inter ligger i `assets/fonts/`.

## Arbejdsgang

Ingen kode uden et feature-dokument. Hver ændring, også bugfixes, bliver beskrevet i `docs/features/NNNN-kort-navn.md` med skillen `vaas-agenter:feature-workflow`, før der skrives kode. Brugeren dikterer features og siger selv til, når der skal bygges. Feature-dokumenter og `CHANGELOG.md` skrives på dansk efter ASD-STE100-reglerne i skillen. Implementering sker typisk med agenten `vaas-agenter:implementer` med stien til dokumentet. Den skriver tests først, bumper `version` i `pyproject.toml` (eneste versionskilde, SemVer) og tilføjer en linje i `CHANGELOG.md` (Keep a Changelog). Status i dokumentet går fra `planlagt` til `udviklet`.
