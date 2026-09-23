# Oprydning: luk, annullér, testrækkefølge og README

Version: 0.5.3
Status: udviklet
Oprettet: 2026-09-23

## Problem

Feature 0001–0007 efterlod 4 fejl og mangler.

1. **Luk under arbejde.** Nogle handlinger kører i en tråd og stopper en service først. Det gælder login med `--reauth`, ændring af mappevalget og knapperne i kortet "Service". Lukker brugeren vinduet under en sådan handling, stopper applikationen midt i handlingen. Servicen kan så blive stående stoppet. Ved en ændring af mappevalget kan `sync_list` være skrevet, uden at servicen er startet med `--resync`.
2. **Annullér under stop.** Mens applikationen stopper servicen før et login med `--reauth`, gør knappen "Annullér" ingenting. `cancelLogin` i `onedrive_gui/viewmodels.py` returnerer, når `_service_thread` findes. Stoppet kan tage op til 90 sekunder.
3. **Testrækkefølge.** `tests/test_viewmodels.py` opretter en `QCoreApplication`, og `tests/test_qml.py` kræver en `QGuiApplication`. Kører `test_viewmodels.py` først i samme proces, crasher Qt med "Fatal Python error: Aborted".
4. **README.** `README.md` nævner ikke mappevælgeren, papirkurven, kortet "Service" eller login med `--reauth`.

Reproduktion af fejl 3:

```bash
python3 -m pytest tests/test_viewmodels.py tests/test_qml.py
```

## Løsning

1. **Luk under arbejde.** Applikationen holder styr på alle handlinger, der kan stoppe eller starte en service. Lukker brugeren vinduet under en sådan handling, lukker vinduet ikke. Applikationen viser arket "Applikationen lukker, når arbejdet er færdigt" med navnet på handlingen og en spinner. Når handlingen er færdig, lukker vinduet af sig selv. Arket har knappen "Luk alligevel". Den knap viser en advarsel om, at servicen kan blive stående stoppet, og lukker derefter.
2. **Annullér under stop.** "Annullér" virker med det samme. Knappen viser "Annullerer …". Når stoppet er færdigt, starter applikationen ikke klienten. Applikationen starter servicen igen, hvis den kørte før.
3. **Testrækkefølge.** Alle tests bruger én fælles `QGuiApplication` fra `tests/conftest.py`. Suiten består i alle rækkefølger.
4. **README.** `README.md` beskriver alle funktioner fra feature 0001–0007.

## Afgrænsning

- Applikationen afbryder ikke en handling, der er i gang. Den venter kun på den.
- Brugeren kan ikke afbryde upload eller `--resync`. Det er en separat feature.
- Applikationen viser ikke fremdrift på arket. Den viser kun navnet på handlingen og en spinner.
- Featuren ændrer ikke læsningen af status hvert 3. sekund. Status-tråden kan afbrydes, når vinduet lukker.
- Featuren tilføjer ikke en linter.
- README beskriver ikke koden. Den beskriver kun, hvad brugeren kan gøre.

## Plan

1. `onedrive_gui/viewmodels.py` — samlingen `_critical_jobs`. Alle tråde og `_Job`s, der kan stoppe eller starte en service, registrerer sig her med en tekst som "Genstarter onedrive.service". Det gælder login med `--reauth`, `activate_service`, `restore_service`, `apply.execute` og `service_control.perform`.
2. `onedrive_gui/viewmodels.py` — egenskaben `busyText` og slottet `requestClose()`. `requestClose()` svarer sandt, når ingen kritiske handlinger kører. Ellers åbner den arket og lukker vinduet, når samlingen er tom.
3. `onedrive_gui/viewmodels.py` — slottet `forceClose()`. Det logger en advarsel med de handlinger, der stadig kører, og lukker vinduet.
4. `onedrive_gui/qml/Main.qml` — `onClosing` sætter `close.accepted` til resultatet af `controller.requestClose()`. Controlleren sender et signal, når vinduet må lukke.
5. `onedrive_gui/qml/sheets/ClosingSheet.qml` (ny) — arket med tekst, spinner og knappen "Luk alligevel". Advarslen bruger `Sheet` og komponenterne fra feature 0003.
6. `onedrive_gui/login_flow.py` — feltet `cancel_requested`. `cancel()` sætter feltet, også mens servicen stopper. Når stoppet er færdigt, afslutter flowet med `CANCELLED` uden at starte klienten.
7. `onedrive_gui/viewmodels.py` — `cancelLogin` kalder altid `flow.cancel()` og sætter login-tilstanden `cancelling`. Login-arket viser "Annullerer …".
8. `tests/conftest.py` — en fixture med `scope="session"`, der giver én `QGuiApplication`. `tests/test_viewmodels.py`, `tests/test_qml.py` og `tests/test_theme.py` bruger den i stedet for deres egne.
9. `README.md` — tilføj afsnit om mappevælgeren og papirkurven, kortet "Service" med dets tilstande og knapper, og login igen med `--reauth`.

## Tests

Luk under arbejde:
- Når ingen kritisk handling kører, skal `requestClose()` svare sandt.
- Når en genstart fra kortet "Service" kører, skal `requestClose()` svare falsk, og `busyText` skal nævne servicen.
- Når handlingen bliver færdig, skal controlleren sende signalet om, at vinduet må lukke.
- Når `apply.execute` kører, skal `requestClose()` svare falsk, indtil `execute` er færdig med genstarten.
- Når login med `--reauth` stopper servicen, skal `requestClose()` svare falsk.
- Når kun læsningen af status kører, skal `requestClose()` svare sandt.
- `forceClose()` skal lukke, selvom en handling kører, og give en advarsel i loggen med handlingens tekst.
- Når 2 handlinger kører, og den ene bliver færdig, må vinduet ikke lukke før den anden.

Annullér under stop:
- Når brugeren klikker "Annullér", mens servicen stopper, skal login-tilstanden straks være `cancelling`.
- Når stoppet er færdigt efter "Annullér", må klienten ikke starte, og `refresh_token` skal være uændret.
- Når stoppet er færdigt efter "Annullér", skal applikationen starte servicen igen, hvis den var aktiv før.
- Når stoppet fejler efter "Annullér", skal applikationen vise fejlen og ikke starte klienten.

Testrækkefølge:
- `tests/conftest.py` skal give den samme `QGuiApplication` til alle tests.
- Ingen testfil må selv oprette en `QCoreApplication`, `QGuiApplication` eller `QApplication`. En test søger i kildekoden i `tests/` efter det.

README:
- `README.md` skal nævne "Vælg mapper", "papirkurv", "Genstart med resync" og `--reauth`.

**Eksisterende tests, der ændrer sig:** Tests i `tests/test_viewmodels.py`, der kalder `cancelLogin` under et stop og forventer, at intet sker, skal nu forvente tilstanden `cancelling`. Testen af `shutdown()` fra feature 0005 skal forvente, at applikationen venter på tråden, i stedet for at springe genstarten over. Fixturerne `app` i `tests/test_viewmodels.py`, `tests/test_qml.py` og `tests/test_theme.py` forsvinder.

## Verifikation

Suiten skal bestå i begge rækkefølger:

```bash
python3 -m pytest
python3 -m pytest tests/test_viewmodels.py tests/test_qml.py
python3 -m pytest tests/test_qml.py tests/test_viewmodels.py
```

Manuel afprøvning med `--safe`:

1. Start `python3 -m onedrive_gui.app --safe`.
2. Klik "Genstart" på en konto, og luk vinduet med det samme. Arket "Applikationen lukker, når arbejdet er færdigt" skal vises.
3. Vent. Vinduet skal lukke af sig selv.
4. Gentag trin 2, og klik "Luk alligevel". Advarslen skal vises, og vinduet skal lukke.

## Åbne spørgsmål
