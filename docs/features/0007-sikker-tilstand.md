# Sikker tilstand

Version: 0.5.0
Status: udviklet
Oprettet: 2026-09-23

## Problem

Applikationen kalder `systemctl --user`, starter `onedrive`, flytter filer til papirkurven og skriver unit-filer.
`systemctl --user` rammer brugerens rigtige units, også når `HOME` peger på en midlertidig mappe.
Den 2026-09-23 kl. 07:32 kørte et script med en falsk `HOME`. Scriptet stoppede og genstartede brugerens rigtige `onedrive.service`.
Testene i `tests/conftest.py` blokerer kaldene, men et script uden for testene har ingen beskyttelse.

## Løsning

Applikationen har en sikker tilstand. I sikker tilstand ændrer applikationen intet på systemet.
Applikationen kører stadig hele brugerfladen og alle forløb, så brugeren og scripts kan afprøve og tage skærmbilleder.

Sikker tilstand er slået til, når mindst 1 af disse betingelser gælder:
- Miljøvariablen `ONEDRIVE_GUI_SAFE_MODE` er `1`.
- Applikationen er startet med `--safe`.
- `HOME` er en anden mappe end brugerens rigtige hjemmemappe fra `pwd.getpwuid(os.getuid()).pw_dir`.

I sikker tilstand gælder disse regler:

| Handling | I sikker tilstand |
|---|---|
| `systemctl --user show`, `cat`, `status`, `is-active` | Kører som normalt |
| `journalctl` | Kører som normalt |
| Alle andre `systemctl`-kommandoer | Kører ikke. Applikationen logger kommandoen og svarer, at den lykkedes |
| Start af `onedrive` | Kører ikke. Applikationen logger kommandoen og svarer med exit-kode 1 og teksten "Sikker tilstand: onedrive blev ikke startet" |
| Flyt til papirkurven | Kører ikke. Applikationen logger stien og svarer, at flytningen lykkedes |
| Skriv en fil under den rigtige hjemmemappe | Kører ikke. Applikationen logger stien. Undtagelsen er `~/.config/onedrive-gui/` |
| Skriv en fil uden for den rigtige hjemmemappe | Kører som normalt |
| Kald til Microsoft Graph | Kører som normalt. Kaldene læser kun |

Øverst i vinduet står et banner i `warning`-tonen med teksten "Sikker tilstand – applikationen ændrer ikke noget på systemet".

## Afgrænsning

- Brugeren kan ikke slå sikker tilstand til eller fra inde i vinduet.
- Applikationen viser ikke listen over blokerede handlinger i vinduet. Listen står kun i loggen.
- Sikker tilstand beskytter ikke mod kode, der kalder `subprocess` direkte uden om modulet `sideeffects.py`.
- Sikker tilstand erstatter ikke blokeringen i `tests/conftest.py`. Testene beholder den.
- Applikationen kan ikke slå den automatiske sikre tilstand fra, når `HOME` er falsk.

## Plan

1. `onedrive_gui/sideeffects.py` (ny) — funktionen `safe_mode()`, der vurderer de 3 betingelser. Resultatet ligger fast, fra applikationen starter.
2. `onedrive_gui/sideeffects.py` — `run`, `popen`, `trash` og `guard_write(path)`. De følger tabellen i Løsning. En blokeret handling giver en linje i loggen, der starter med `SAFE MODE:`.
3. `onedrive_gui/service.py`, `onedrive_gui/service_control.py`, `onedrive_gui/auth.py`, `onedrive_gui/apply.py` og `onedrive_gui/viewmodels.py` — brug `sideeffects.run`, `sideeffects.popen` og `sideeffects.trash` som standard i stedet for `subprocess.run`, `subprocess.Popen` og `QFile.moveToTrash`.
4. `onedrive_gui/provision.py`, `onedrive_gui/synclist.py`, `onedrive_gui/config.py`, `onedrive_gui/service.py` og `onedrive_gui/service_control.py` — kald `guard_write(path)` før hver skrivning og sletning af en fil.
5. `onedrive_gui/app.py` — læs `--safe` fra kommandolinjen, og giv `safeMode` til QML.
6. `onedrive_gui/qml/Main.qml` og `onedrive_gui/qml/components/SafeModeBanner.qml` (ny) — banneret, når `safeMode` er sand.
7. `tests/conftest.py` — sæt `ONEDRIVE_GUI_SAFE_MODE=1` i alle tests. Behold blokeringen af `subprocess` og `urlopen`.
8. `README.md` — beskriv sikker tilstand og kommandoen `python3 -m onedrive_gui.app --safe`.

## Tests

Aktivering:
- Ved `ONEDRIVE_GUI_SAFE_MODE=1` skal `safe_mode()` være sand.
- Ved `--safe` skal `safe_mode()` være sand.
- Ved en `HOME`, der er forskellig fra hjemmemappen i `pwd`, skal `safe_mode()` være sand, også uden miljøvariablen.
- Ved den rigtige `HOME`, uden miljøvariablen og uden `--safe`, skal `safe_mode()` være falsk.
- Ved `ONEDRIVE_GUI_SAFE_MODE=0` og en falsk `HOME` skal `safe_mode()` stadig være sand.

Blokering:
- `systemctl --user restart onedrive.service` må ikke nå den underliggende `run`. Kaldet skal svare med exit-kode 0 og give en linje med `SAFE MODE:` i loggen.
- `systemctl --user stop`, `start`, `enable`, `reset-failed` og `daemon-reload` må ikke nå den underliggende `run`.
- `systemctl --user show onedrive.service` og `journalctl --user -u onedrive.service` skal nå den underliggende `run`.
- Start af `onedrive` må ikke nå den underliggende `popen`. Processen skal svare med exit-kode 1.
- `trash(path)` må ikke flytte filen. Filen skal stadig findes bagefter.
- `guard_write` på `~/.config/systemd/user/x.service` under den rigtige hjemmemappe skal blokere skrivningen.
- `guard_write` på `~/.config/onedrive-gui/accounts.json` under den rigtige hjemmemappe skal tillade skrivningen.
- `guard_write` på en sti i en midlertidig mappe uden for den rigtige hjemmemappe skal tillade skrivningen.
- Uden sikker tilstand skal alle kald nå den underliggende funktion.

Forløb:
- I sikker tilstand skal "Genstart" fra feature 0004 ende uden fejl, og ingen `systemctl`-kommando, der ændrer noget, må nå den underliggende `run`.
- I sikker tilstand skal login fra feature 0001 ende i tilstanden `FAILED` med teksten "Sikker tilstand: onedrive blev ikke startet".
- Hvert modul fra plan-trin 3 må ikke have `subprocess.run`, `subprocess.Popen` eller `QFile.moveToTrash` som standard. En test søger i kildekoden efter det.

Brugerflade:
- I sikker tilstand skal `Main.qml` vise teksten "Sikker tilstand – applikationen ændrer ikke noget på systemet".
- Uden sikker tilstand må banneret ikke vises.

**Eksisterende tests, der ændrer sig:** Ingen tests skal ændre forventning. Tests, der giver deres egen falske `run` eller `popen`, skal stadig få deres egen funktion kaldt. Den falske funktion går foran sikker tilstand.

## Verifikation

```bash
python3 -m pytest
```

Manuel afprøvning:

1. Kør `python3 -m onedrive_gui.app --safe`. Banneret skal stå øverst.
2. Klik "Genstart" på firmakontoen. Loggen skal vise `SAFE MODE: systemctl --user restart onedrive.service`.
3. `systemctl --user show onedrive.service -p ActiveEnterTimestamp` skal vise det samme tidspunkt som før klikket.
4. Kør `HOME=$(mktemp -d) python3 -m onedrive_gui.app` uden `--safe`. Banneret skal stå øverst.

## Åbne spørgsmål
