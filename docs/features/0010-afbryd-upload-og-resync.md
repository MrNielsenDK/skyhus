# Afbryd upload og resync

Version: 0.7.0
Status: udviklet
Oprettet: 2026-09-23

## Problem

Upload og `--resync` kan tage fra minutter til timer.
Brugeren kan ikke afbryde dem i applikationen. Brugeren skal i stedet bruge `kill` eller `systemctl` i en terminal.
Afbryder brugeren på den måde, ved applikationen ikke, i hvilken tilstand kontoen er bagefter.

## Løsning

### Afbryd upload

Arket "Ændrer mappevalg" (feature 0009) har knappen "Afbryd", mens trin 2 kører.
Et klik stopper uploaden. Applikationen ændrer derefter intet:
- Applikationen skriver ikke den nye `sync_list`.
- Applikationen flytter ikke noget til papirkurven.
- Applikationen starter servicen igen uden `--resync`, hvis den kørte før.

Arket viser "Ændringen er afbrudt. Mappevalget er uændret." Filer, som klienten nåede at uploade, bliver på OneDrive.

Efter trin 2 kan brugeren ikke afbryde. Knappen forsvinder, fordi trin 3 og 4 ændrer filer.

### Afbryd resync

Kortet "Service" har knappen "Afbryd resync" under tilstanden "Resynkroniserer" (feature 0009).
Knappen viser først en bekræftelse: "Afbryd resync? Kontoen synkroniserer ikke, før du starter en ny resync. En ny resync begynder forfra."
Efter bekræftelse stopper applikationen servicen.
Kortet viser derefter tilstanden "Resync afbrudt" med knappen "Genstart med resync".

Applikationen starter ikke servicen uden `--resync` efter en afbrudt resync. Klientens database kan være ufuldstændig.

## Afgrænsning

- Brugeren kan ikke afbryde trin 1, 3, 4 eller 5 i en ændring af mappevalget.
- Brugeren kan ikke pause og fortsætte en resync. En ny resync begynder forfra.
- Applikationen sletter ikke de filer, som klienten nåede at uploade eller downloade før afbrydelsen.
- Applikationen afbryder ikke en `onedrive`-proces uden for servicen.
- Applikationen afbryder ikke login. Login har allerede "Annullér" fra feature 0001 og 0008.

## Plan

1. `onedrive_gui/apply.py` — `execute()` får et `cancel`-flag, som tråden kan læse. Under trin 2 tjekker `execute()` flaget for hver linje fra uploaden og hvert sekund.
2. `onedrive_gui/apply.py` — ved afbrydelse sender applikationen `SIGTERM` til upload-processen. Klienten lukker så pænt ned. Stopper processen ikke inden 30 sekunder, sender applikationen `SIGKILL`. Signalerne går gennem `sideeffects`.
3. `onedrive_gui/apply.py` — efter afbrydelsen følger `execute()` samme vej som ved en fejl i uploaden (feature 0002): ingen `sync_list`, ingen papirkurv og `systemctl --user start`. Resultatet er `CANCELLED` i stedet for en fejl.
4. `onedrive_gui/service_state.py` — tilstanden "Resync afbrudt" gælder, når applikationen selv har stoppet servicen under en resync. Applikationen gemmer det i `~/.config/onedrive-gui/state.json` pr. service. Markeringen forsvinder, når servicen starter igen.
5. `onedrive_gui/service_control.py` — `cancel_resync(service)` kører `systemctl --user stop <service>` og skriver markeringen.
6. `onedrive_gui/viewmodels.py` — slottene `cancelApply()`, `requestCancelResync(confdir)`, `confirmCancelResync()` og `dismissCancelResync()`. Afbrydelse af resync er en kritisk handling efter feature 0008.
7. `onedrive_gui/qml/sheets/ApplyProgressSheet.qml` — knappen "Afbryd" under trin 2 og beskeden efter afbrydelsen.
8. `onedrive_gui/qml/sheets/ConfirmCancelResyncSheet.qml` (ny) — bekræftelsen.
9. `onedrive_gui/qml/components/ServiceCard.qml` — knappen "Afbryd resync" og tilstanden "Resync afbrudt".

## Tests

Afbryd upload:
- Når brugeren afbryder under trin 2, skal upload-processen få `SIGTERM`.
- Når processen ikke stopper inden 30 sekunder, skal den få `SIGKILL`. Testen bruger et falsk ur.
- Efter afbrydelsen må `sync_list` ikke være ændret, og ingen sti må være flyttet til papirkurven.
- Efter afbrydelsen skal applikationen kalde `systemctl --user start` for en service, der kørte før, og ikke `--resync`.
- Efter afbrydelsen må applikationen ikke starte en service, der var stoppet før.
- Resultatet af `execute()` skal være `CANCELLED`, og arket skal vise "Ændringen er afbrudt. Mappevalget er uændret."
- Efter trin 2 må knappen "Afbryd" ikke vises, og `cancelApply()` må ikke gøre noget.
- Når brugeren afbryder, idet uploaden alligevel slutter med exit-kode 0, skal `execute()` stadig ende som `CANCELLED` uden at skrive `sync_list`.

Afbryd resync:
- "Afbryd resync" må ikke stoppe servicen, før brugeren har bekræftet.
- Efter bekræftelse skal applikationen kalde `systemctl --user stop` for servicen og skrive markeringen i `state.json`.
- Efter stoppet skal kortet vise "Resync afbrudt" med knappen "Genstart med resync".
- Under "Resync afbrudt" må kortet ikke vise knappen "Start".
- Når servicen starter igen, skal markeringen forsvinde fra `state.json`.
- Når `systemctl --user stop` fejler, skal kortet vise fejlen, og markeringen må ikke skrives.
- I sikker tilstand må stoppet ikke nå den underliggende `run`.
- Mens afbrydelsen kører, skal `requestClose()` fra feature 0008 svare falsk.

**Eksisterende tests, der ændrer sig:** Testene for tilstandene i `tests/test_service_state.py` skal også dække prioriteten for "Resync afbrudt". Den står lige efter "Resynkroniserer".

## Verifikation

```bash
python3 -m pytest
```

Manuel afprøvning med en testkonto:

1. Fravælg en mappe, mens der er lokale ændringer at uploade. Klik "Afbryd" under trin 2.
2. `sync_list` skal være uændret, og servicen skal køre uden `--resync`.
3. Start "Genstart med resync". Klik "Afbryd resync", og bekræft.
4. Kortet skal vise "Resync afbrudt". `systemctl --user status <service>` skal vise `inactive`.
5. Klik "Genstart med resync". Kortet skal vise "Resynkroniserer" og begynde forfra.

## Åbne spørgsmål

- Implementeringen skal afprøve med en testkonto, at klienten ved `SIGTERM` under `--upload-only` lukker pænt ned uden halve filer på OneDrive.
