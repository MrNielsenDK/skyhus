# Installér Skyhus på skrivebordet

Version: 0.9.0
Status: udviklet
Oprettet: 2026-09-23

## Problem

Brugeren kan kun starte Skyhus fra en terminal i projektmappen med `python3 -m skyhus.app`.
Skyhus er ikke i programmenuen og har intet ikon.
README siger `pip install --user -e .`. Kommandoen fejler på maskinen, fordi systemets Python er markeret `EXTERNALLY-MANAGED`.
`pyproject.toml` kræver `PySide6>=6.8`. Et værktøj som pip eller pipx henter derfor en ekstra kopi af PySide6 fra PyPI i stedet for at bruge systempakkerne.

## Løsning

Kommandoen `python3 -m skyhus.install` installerer Skyhus for den aktuelle bruger. Kommandoen `python3 -m skyhus.install --uninstall` fjerner installationen igen.
Installationen bruger koden i projektmappen og systemets PySide6. Den bruger ikke pip.

Installationen skriver 3 filer:

| Fil | Indhold |
|---|---|
| `~/.local/bin/skyhus` | Et shell-script: `PYTHONPATH=<projektmappe> exec <python> -m skyhus.app "$@"`. `<python>` er den Python, der kører installationen. Rettigheder 0755. |
| `~/.local/share/applications/skyhus.desktop` | `Name=Skyhus`, `GenericName=OneDrive-konti`, `Comment=Flere OneDrive-konti på Linux`, `Exec=<fuld sti til ~/.local/bin/skyhus>`, `Icon=skyhus`, `Categories=Network;FileTransfer;Qt;`, `StartupWMClass=skyhus`. |
| `~/.local/share/icons/hicolor/scalable/apps/skyhus.svg` | Ikonet: en sky over et hus. |

Hver fil har en markering, der viser, at Skyhus har skrevet den: `# Installeret af Skyhus` i scriptet, `X-Skyhus-Installer=true` i `.desktop`-filen og `<!-- Installeret af Skyhus -->` i ikonet.

Installationen følger disse regler:
- Findes en af filerne allerede uden markeringen, stopper installationen, før den skriver noget. Beskeden nævner filen. Applikationen overskriver aldrig en fil, som den ikke selv har skrevet.
- Findes filen med markeringen, overskriver installationen den. Brugeren kan derfor installere igen, fx efter at projektmappen har skiftet navn.
- Efter skrivningen kører installationen `update-desktop-database ~/.local/share/applications` og `kbuildsycoca6`, hvis kommandoerne findes. En fejl i dem stopper ikke installationen. Den giver en advarsel.
- Til sidst viser installationen de 3 stier og kommandoen til at starte Skyhus.

Afinstallationen fjerner kun de 3 filer, og kun når de har markeringen. En fil uden markeringen bliver liggende, og beskeden nævner den. Afinstallationen fjerner ikke `~/.config/skyhus/`, konti, services eller synkmapper.

I sikker tilstand skriver og fjerner kommandoen intet under den rigtige hjemmemappe. Loggen viser `SAFE MODE: skriver ikke <sti>` for hver fil, som i resten af applikationen. Med en falsk `HOME` skriver kommandoen kun i den falske `HOME`.

Applikationen kalder `setDesktopFileName("skyhus")`. På Wayland viser panelet i KDE så ikonet fra `skyhus.desktop` ved vinduet. Vinduet får også ikonet via `setWindowIcon`.

`pyproject.toml` har ingen `dependencies`. En kommentar i filen siger, at afhængighederne er systempakker, og at README har `apt install`-linjen.

## Afgrænsning

- Featuren starter ikke Skyhus automatisk ved login.
- Featuren laver ingen pakke til apt, Flatpak eller PyPI.
- Featuren ændrer ikke, hvad Skyhus gør, når brugeren starter den.
- Featuren flytter ikke koden ud af projektmappen. Flytter brugeren projektmappen, skal brugeren køre installationen igen.
- Featuren installerer ingen systempakker. Mangler PySide6, stopper installationen med `apt install`-linjen fra README.

## Plan

1. `skyhus/assets/skyhus.svg` — ikonet. Et eget SVG med en sky over et hus i 2 farver og uden tekst. Ikonet skal være tydeligt ved 16, 24, 48 og 256 px.
2. `skyhus/install.py` — `plan(home, repo)` returnerer de 3 filer med sti, indhold og rettigheder og ændrer intet. `install(home, repo, run=None)` og `uninstall(home, run=None)` følger reglerne ovenfor. Alle skrivninger bruger `sideeffects.guard_write`, og kommandoerne bruger `sideeffects.run`. `main()` tolker `--uninstall` og viser resultatet på dansk.
3. `skyhus/install.py` — før `install()` skriver, tjekker den med `importlib.util.find_spec`, at `PySide6.QtQuick` og `PySide6.QtWebEngineQuick` findes i den Python, der kører installationen. Scriptet starter Skyhus med den samme Python. Tjekket starter ingen proces, så det virker også i sikker tilstand. Mangler `QtWebEngineQuick`, fortsætter installationen med en advarsel om login-vinduet. Mangler `QtQuick`, stopper den.
4. `skyhus/app.py` — `setDesktopFileName("skyhus")` og `setWindowIcon` med `assets/skyhus.svg`.
5. `pyproject.toml` — fjern `dependencies`, og tilføj kommentaren. Tilføj `assets/skyhus.svg` til `package-data`. Bump `version` til 0.9.0.
6. `README.md` — afsnittet "Installér" med `python3 -m skyhus.install`, `--uninstall` og besked om at installere igen efter en flytning. Fjern linjen med `pip install --user -e .`.
7. `CHANGELOG.md` — en linje under `[0.9.0]` med `### Added`.

## Tests

Installation:
- `install()` i en tom falsk `HOME` skriver de 3 filer. Scriptet har rettighederne 0755 og indeholder den absolutte sti til projektmappen.
- `.desktop`-filen har `Exec=` med den fulde sti til `~/.local/bin/skyhus`, `Icon=skyhus` og `X-Skyhus-Installer=true`.
- Et symlink på en af de 3 stier stopper installationen, også når målet har markeringen.
- En fil uden markeringen på en af de 3 stier stopper installationen. Ingen af de 3 filer bliver skrevet eller ændret.
- En fil med markeringen bliver overskrevet med det nye indhold.
- Installationen kalder `update-desktop-database` og `kbuildsycoca6` via den injicerede `run`. En fejl fra dem giver en advarsel og ingen undtagelse.
- Mangler `PySide6.QtQuick`, skriver installationen intet og viser `apt install`-linjen.

Afinstallation:
- `uninstall()` fjerner de 3 filer med markeringen.
- En fil uden markeringen bliver liggende, og beskeden nævner den.
- `uninstall()` fjerner ikke `~/.config/skyhus/`.

Sikker tilstand:
- Uden en injiceret `run` og med sikker tilstand slået til skriver og fjerner `install()` og `uninstall()` intet under den rigtige hjemmemappe.

Applikationen:
- `app.py` kalder `setDesktopFileName("skyhus")`.
- `skyhus/assets/skyhus.svg` er gyldig SVG og indeholder hverken `<text>` eller eksterne referencer.
- `pyproject.toml` har ingen `dependencies` og har `assets/skyhus.svg` i `package-data`.
- README nævner `python3 -m skyhus.install` og ikke `pip install`.

## Verifikation

```bash
python3 -m pytest
HOME=$(mktemp -d) python3 -m skyhus.install    # sikker tilstand: skriver kun i den falske HOME
desktop-file-validate <falsk HOME>/.local/share/applications/skyhus.desktop
python3 -m skyhus.install                      # den rigtige installation
```

Manuelt efter den rigtige installation:
1. Skyhus står i programmenuen i KDE med ikonet.
2. Start Skyhus fra menuen. Panelet viser ikonet ved vinduet.
3. Første skarpe kørsel: se kun. Sammenlign tilstanden for de 2 konti med `systemctl --user status onedrive onedrive-privat`. Klik ikke på handlinger.
4. `python3 -m skyhus.install --uninstall` fjerner Skyhus fra menuen.

## Åbne spørgsmål

Ingen.
