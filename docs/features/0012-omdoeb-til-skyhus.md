# Omdøb til Skyhus

Version: 0.8.0
Status: udviklet
Oprettet: 2026-09-23

## Problem

Applikationen hedder `onedrive-gui`. Et andet projekt, bpozdena/OneDriveGUI, er også en brugerflade til abraunegg/onedrive. De 2 navne er næsten ens.
"OneDrive" er et varemærke, som Microsoft ejer. Navnet må ikke starte med "OneDrive".
Vinduet hedder "OneDrive-konti". Det navn er ikke et produktnavn.

## Løsning

Applikationen hedder **Skyhus**. Undertitlen er "Flere OneDrive-konti på Linux".
Alle navne i koden, filerne og dokumentationen skifter til det nye navn:

| Nu | Nyt |
|---|---|
| Pakken `onedrive_gui/` | `skyhus/` |
| Kommandoen `onedrive-gui` og `python3 -m onedrive_gui.app` | `skyhus` og `python3 -m skyhus.app` |
| `name = "onedrive-gui"` i `pyproject.toml` | `name = "skyhus"` |
| QML-modulet `OneDriveGui` (`import OneDriveGui`) | `Skyhus` (`import Skyhus`) |
| `setApplicationName("onedrive-gui")` | `setApplicationName("skyhus")` |
| `setApplicationDisplayName("OneDrive-konti")` og vinduestitlen "OneDrive-konti" | "Skyhus" |
| Mappen `~/.config/onedrive-gui/` (`accounts.json`, `state.json`) | `~/.config/skyhus/` |
| Drop-in'en `zz-onedrive-gui-resync.conf` | `zz-skyhus-resync.conf` |
| Miljøvariablen `ONEDRIVE_GUI_SAFE_MODE` | `SKYHUS_SAFE_MODE` |
| Arbejdsmappen `onedrive-gui-auth-*` og filen `refresh_token.onedrive-gui.tmp` | `skyhus-auth-*` og `refresh_token.skyhus.tmp` |
| Kommentaren "Oprettet af onedrive-gui." i nye units | "Oprettet af Skyhus." |
| Kommentaren "onedrive-gui fjerner filen efter genstart." i drop-in'en | "Skyhus fjerner filen efter genstart." |
| `README.md`, `CLAUDE.md` | Det nye navn, de nye stier og den nye miljøvariabel |

**Sikker tilstand beholder den gamle miljøvariabel.** Sikker tilstand slår også til med `ONEDRIVE_GUI_SAFE_MODE=1`.
Et gammelt script med den gamle variabel må ikke køre i skarp tilstand og ramme de rigtige services.
Loggen viser den gamle variabel som betingelse, som den viser de andre betingelser. README nævner kun `SKYHUS_SAFE_MODE`.

## Afgrænsning

- Featuren ændrer ikke klientens navne. `onedrive`, `/usr/bin/onedrive`, `~/.config/onedrive*`, `onedrive*.service` og `onedrive-failure@.service` bliver, som de er.
- Featuren flytter ikke filer fra `~/.config/onedrive-gui/` til `~/.config/skyhus/`. Mappen findes ikke på maskinen i dag, og applikationen er ikke udgivet.
- Featuren fjerner ikke gamle drop-ins med navnet `zz-onedrive-gui-resync.conf`. Der findes ingen på maskinen i dag.
- Featuren ændrer ikke kommentaren i units, der findes allerede.
- Featuren ændrer ikke `CHANGELOG.md` for tidligere versioner og ikke feature-dokumenterne 0001–0011. De beskriver historien.
- Featuren omdøber ikke projektmappen `~/Projects/OneDriveSync`. Brugeren gør det selv, hvis det er nødvendigt.
- Featuren tilføjer ikke en `.desktop`-fil eller et ikon for applikationen.

## Plan

1. `git mv onedrive_gui skyhus`. Ret alle imports i `skyhus/` og `tests/`.
2. `pyproject.toml` — `name`, `[project.scripts]` (`skyhus = "skyhus.app:main"`), `packages` og `package-data`. Bump `version` til 0.8.0.
3. `skyhus/theme.py` — `QML_IMPORT_NAME = "Skyhus"`. Alle QML-filer får `import Skyhus`.
4. `skyhus/app.py` — `setApplicationName("skyhus")`, `setApplicationDisplayName("Skyhus")`. `skyhus/qml/Main.qml` — titlen "Skyhus".
5. `skyhus/accounts.py` — `GUI_DIR_NAME = "skyhus"`. Docstrings i `registry.py`, `service_state.py` og `sideeffects.py` bruger `~/.config/skyhus/`.
6. `skyhus/sideeffects.py` — `ENV_VAR = "SKYHUS_SAFE_MODE"` og `LEGACY_ENV_VAR = "ONEDRIVE_GUI_SAFE_MODE"`. `reasons()` tjekker begge.
7. `skyhus/service_control.py` — `RESYNC_DROP_IN = "zz-skyhus-resync.conf"` og kommentaren i drop-in'en.
8. `skyhus/service.py` — kommentaren i nye units.
9. `skyhus/auth.py` — præfikset for arbejdsmappen og navnet på den midlertidige token-fil.
   `skyhus/naming.py` og `skyhus/discovery.py` — fjern reservationen af navnet "gui" og undtagelsen for mappen `onedrive-gui`. Mappen `~/.config/skyhus/` starter ikke med `onedrive-` og kan ikke blive en konto.
10. `README.md` og `CLAUDE.md` — navn, kommandoer, stier og miljøvariabel.
11. `CHANGELOG.md` — en linje under `[0.8.0]` med `### Changed`.

## Tests

Navn:
- Ingen fil i `skyhus/`, `tests/`, `README.md`, `CLAUDE.md` eller `pyproject.toml` må indeholde `onedrive-gui`, `onedrive_gui` eller `OneDriveGui`. Den eneste undtagelse er `ONEDRIVE_GUI_SAFE_MODE` i `skyhus/sideeffects.py` og i testene for sikker tilstand.
- `pyproject.toml` har `name = "skyhus"` og kommandoen `skyhus`.
- Vinduet i `Main.qml` har titlen "Skyhus". `app.py` har visningsnavnet "Skyhus". Ordet "OneDrive-konti" må stadig stå i beskrivende tekst.
- Kontoen "Skyhus" får mappen `~/.config/onedrive-skyhus`. Navnet "GUI" er ikke længere reserveret.
- QML-filerne kan indlæses med `import Skyhus`.

Stier:
- `registry.py` skriver `accounts.json` i `~/.config/skyhus/`.
- `service_state.py` skriver `state.json` i `~/.config/skyhus/`.
- Resync skriver drop-in'en `<service>.d/zz-skyhus-resync.conf` og fjerner den efter genstarten.
- I sikker tilstand må applikationen skrive under `~/.config/skyhus/`, men ikke under `~/.config/onedrive-gui/`.

Sikker tilstand:
- `SKYHUS_SAFE_MODE=1` slår sikker tilstand til.
- `ONEDRIVE_GUI_SAFE_MODE=1` slår stadig sikker tilstand til.

**Eksisterende tests, der ændrer sig:** Alle tests, der importerer `onedrive_gui` eller forventer en sti med `onedrive-gui`, bruger nu det nye navn. `tests/conftest.py` sætter `SKYHUS_SAFE_MODE=1`.

## Verifikation

```bash
python3 -m pytest
python3 -m compileall -q skyhus
python3 -m skyhus.app --safe
```

Vinduet skal have titlen "Skyhus", og loggen skal vise `SAFE MODE: sikker tilstand er slået til (--safe)`.

## Åbne spørgsmål

Ingen.
