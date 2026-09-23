# Servicestatus og genstart

Version: 0.4.0
Status: udviklet
Oprettet: 2026-09-23

## Problem

Hver konto synkroniserer via sin egen systemd-user-service.
Brugeren kan ikke se i applikationen, om en service kører, er stoppet eller har fejlet.
Fejler en service, skal brugeren finde årsagen med `journalctl` og genstarte med `systemctl` i en terminal.
Stopper klienten med exit-kode 126, hjælper en almindelig genstart ikke. Klienten kræver så `--resync`.

## Løsning

Kontosiden har kortet "Service". Kortet viser servicens tilstand, siden hvornår tilstanden gælder, og en knap.
Statusprikken i sidebjælken viser den samme tilstand.
Applikationen opdaterer tilstanden hvert 3. sekund, mens vinduet er åbent.

Applikationen viser disse tilstande:

| Tilstand | Betingelse | Prik | Knap |
|---|---|---|---|
| Kører | `ActiveState=active` | `success` | Genstart |
| Starter | `ActiveState=activating` | `warning` | Genstart |
| Stopper | `ActiveState=deactivating` | `warning` | Ingen |
| Kræver resync | `ExecMainStatus=126`, og servicen er ikke aktiv | `danger` | Genstart med resync |
| Fejlet | `ActiveState=failed` | `danger` | Start |
| Stoppet | `ActiveState=inactive` | `textSecondary` | Start |
| Kører uden for servicen | En anden `onedrive`-proces bruger kontoens config-mappe | `warning` | Ingen |
| Ikke logget ind | `refresh_token` findes ikke | `textSecondary` | Ingen |
| Ingen service | Kontoen har ingen service | `textSecondary` | Ingen |

Passer flere betingelser, vælger applikationen den første tilstand i denne rækkefølge:
1. Ingen service
2. Ikke logget ind
3. Kører uden for servicen
4. Kræver resync
5. Kører, Starter, Stopper, Fejlet eller Stoppet efter `ActiveState`

Ved "Fejlet" og "Kræver resync" viser kortet den seneste fejllinje fra servicens journal.

Knappen "Genstart" og "Start" nulstiller en fejlet tilstand og starter servicen.
Knappen "Genstart med resync" viser først en bekræftelse. Bekræftelsen forklarer, at klienten sammenligner hele kontoen igen, og at det kan tage lang tid.
Mens applikationen venter på servicen, viser knappen en spinner og kan ikke klikkes.

## Afgrænsning

- Applikationen har ikke en knap, der stopper en service.
- Applikationen viser ikke synkfremdrift, antal filer eller ledig plads.
- Applikationen viser kun 1 fejllinje. En fuld logvisning er en separat feature.
- Applikationen stopper ikke en `onedrive`-proces, der kører uden for servicen.
- Applikationen sender ikke notifikationer. `onedrive-failure@.service` klarer det allerede.
- Applikationen lytter ikke på D-Bus-signaler. Den spørger `systemctl` hvert 3. sekund.
- Applikationen opdaterer ikke tilstanden, når vinduet er minimeret eller lukket.
- Applikationen ændrer ikke unit-filerne, bortset fra den midlertidige drop-in til resync.

## Plan

1. `onedrive_gui/service_state.py` — hent tilstanden for alle konti med ét kald: `systemctl --user show <service1> <service2> … -p Id,LoadState,ActiveState,SubState,Result,ExecMainStatus,MainPID,ActiveEnterTimestamp,InactiveEnterTimestamp`. Del svaret op pr. unit.
2. `onedrive_gui/service_state.py` — omsæt egenskaberne og kontoens filer til én tilstand efter tabellen i Løsning. Brug `process.py` fra feature 0002 til "Kører uden for servicen". En proces er uden for servicen, hvis dens PID ikke er servicens `MainPID`.
3. `onedrive_gui/service_state.py` — lav teksten "siden" ud fra `ActiveEnterTimestamp` eller `InactiveEnterTimestamp`. Formen er "i dag kl. 08:37", "i går kl. 08:37" eller "22. sep. kl. 08:37".
4. `onedrive_gui/journal.py` — find den seneste fejllinje med `journalctl --user -u <service> -n 500 -o json --no-pager`. Tag den nyeste linje fra `onedrive`, der starter med `ERROR:`. Følger en linje med `Error Message:` lige efter, så vis den i stedet. Findes ingen `ERROR:`-linje, så tag den nyeste linje fra `systemd` med `Failed with result`.
5. `onedrive_gui/service_control.py` — "Start" og "Genstart" kører `systemctl --user reset-failed <service>` og derefter `systemctl --user restart <service>`.
6. `onedrive_gui/service_control.py` — flyt den midlertidige resync-drop-in fra plan-trin 10 i feature 0002 hertil, så begge features bruger den samme funktion.
7. `onedrive_gui/service_control.py` — efter et klik venter applikationen, til servicen er "Kører", "Fejlet" eller "Kræver resync", højst i 120 sekunder. Servicen har `TimeoutStopSec=90`, så en genstart kan tage over 1 minut.
8. `onedrive_gui/viewmodels.py` — en timer på 3 sekunder, der kører, mens vinduet er synligt. Timeren opdaterer tilstanden for alle konti.
9. `onedrive_gui/qml/components/ServiceCard.qml` — kortet med tilstand, "siden", fejllinje og knap. Fejllinjen kan markeres og kopieres.
10. `onedrive_gui/qml/sheets/ConfirmResyncSheet.qml` — bekræftelsen til "Genstart med resync".
11. `onedrive_gui/qml/AccountPage.qml` og `onedrive_gui/qml/Main.qml` — vis `ServiceCard` på kontosiden, og lad statusprikken i sidebjælken følge tilstanden.

## Tests

Testene kalder ikke den rigtige `systemctl` eller `journalctl`. Testene bruger optagne svar.

Tilstand:
- Ved `ActiveState=active` og `SubState=running` skal tilstanden være "Kører", og knappen skal være "Genstart".
- Ved `ActiveState=activating` skal tilstanden være "Starter".
- Ved `ActiveState=failed` og `Result=timeout` skal tilstanden være "Fejlet", og knappen skal være "Start".
- Ved `ActiveState=failed` og `ExecMainStatus=126` skal tilstanden være "Kræver resync", og knappen skal være "Genstart med resync".
- Ved `ActiveState=inactive` og `ExecMainStatus=0` skal tilstanden være "Stoppet".
- Ved en `onedrive`-proces med `--confdir` for kontoen, som ikke er servicens `MainPID`, skal tilstanden være "Kører uden for servicen", og der skal ikke være en knap.
- Ved en proces, der er servicens `MainPID`, skal tilstanden ikke være "Kører uden for servicen".
- Ved en konto uden `refresh_token` skal tilstanden være "Ikke logget ind", også når servicen er `failed`.
- Ved en konto uden service skal tilstanden være "Ingen service", og applikationen skal ikke kalde `systemctl` for kontoen.
- Ved `LoadState=not-found` skal tilstanden være "Ingen service".
- Ved et svar fra `systemctl show` med 3 units skal hver konto få sin egen tilstand.
- Når `systemctl show` fejler, skal applikationen beholde den sidste kendte tilstand og vise "Kan ikke læse status".

Tid:
- Ved `ActiveEnterTimestamp` i dag kl. 08:37 skal teksten være "i dag kl. 08:37".
- Ved et tidspunkt i går skal teksten være "i går kl. 08:37".
- Ved `2026-09-20 08:37` skal teksten være "20. sep. kl. 08:37".
- Ved et tomt tidspunkt skal applikationen ikke vise en "siden"-tekst.

Fejllinje:
- Ved en journal med `ERROR: The local file system returned an error` efterfulgt af `Error Message: … (No space left on device)` skal fejllinjen være linjen med `Error Message:`.
- Ved en journal med 2 `ERROR:`-linjer skal fejllinjen være den nyeste.
- Ved en journal uden `ERROR:`-linjer og med `Failed with result 'timeout'` skal fejllinjen være den linje.
- Ved en tom journal skal applikationen ikke vise en fejllinje.
- Ved tilstanden "Kører" skal applikationen ikke kalde `journalctl`.

Handlinger:
- "Genstart" skal kalde `reset-failed` og derefter `restart` for kontoens service, i den rækkefølge.
- "Genstart med resync" skal ikke gøre noget, før brugeren har bekræftet.
- Efter bekræftelse skal "Genstart med resync" starte servicen med `--resync --resync-auth`, og drop-in-filen skal være væk bagefter.
- Når servicen ikke når "Kører", "Fejlet" eller "Kræver resync" inden 120 sekunder, skal applikationen stoppe spinneren og vise "Servicen svarer ikke".
- Når `systemctl restart` fejler, skal applikationen vise fejlbeskeden fra `systemctl`.
- Mens applikationen venter på en service, skal et nyt klik på knappen ikke gøre noget.

Opdatering:
- Timeren skal køre, når vinduet er synligt, og stoppe, når vinduet er minimeret.
- Skifter en service fra "Kører" til "Fejlet", skal statusprikken i sidebjælken skifte til `danger` ved næste opdatering.

**Eksisterende tests, der ændrer sig:** Feature 0003 er ikke bygget endnu. I 0003 viser statusprikken kun "Logget ind" eller "Ikke logget ind". Efter denne feature følger prikken tabellen i Løsning. Manuel afprøvning 3 i 0003 skal derfor sige "en statusprik, der svarer til servicens tilstand".

## Verifikation

```bash
python3 -m pytest
```

Manuel afprøvning:

1. Åbn applikationen. Firmakontoen skal vise "Kører" og en grøn prik.
2. Kør `systemctl --user stop onedrive.service` i en terminal. Inden 3 sekunder skal kontoen vise "Stoppet".
3. Klik "Start". Spinneren skal køre, og kontoen skal ende i "Kører".
4. Kør `systemctl --user kill -s KILL onedrive.service`. Kontoen skal vise "Fejlet" eller "Starter" og en fejllinje, hvis journalen har en.
5. Klik "Genstart". Kontoen skal ende i "Kører".
6. Stop `onedrive-privat.service`, og start `onedrive --confdir="$HOME/.config/onedrive-privat" --monitor` i en terminal. Privatkontoen skal vise "Kører uden for servicen" uden en knap.

## Åbne spørgsmål

- Klienten skriver måske ikke `ERROR:` i starten af alle fejllinjer. Implementeringen skal tjekke flere fejltyper i journalen og tilpasse reglen i plan-trin 4, hvis det er nødvendigt.
