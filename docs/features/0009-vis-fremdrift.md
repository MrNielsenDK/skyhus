# Vis fremdrift under upload, papirkurv og resync

Version: 0.6.0
Status: planlagt
Oprettet: 2026-09-23

## Problem

En ændring af mappevalget (feature 0002) har 5 trin. Upload og `--resync` kan tage fra minutter til timer.
I dag viser applikationen kun en spinner. Brugeren kan ikke se, hvilket trin der kører, eller hvor langt det er nået.
Efter trin 5 kører `--resync` inde i servicen. Kortet "Service" viser så kun "Kører", også mens klienten henter tusindvis af filer.
Det samme gælder "Genstart med resync" fra feature 0004.

## Løsning

### Ændring af mappevalget

Når brugeren bekræfter en ændring, viser arket "Ændrer mappevalg" en liste med de 5 trin:

1. Stopper servicen
2. Uploader lokale ændringer
3. Skriver de nye regler
4. Flytter til papirkurven
5. Starter servicen med resync

Hvert trin har en tilstand: venter, i gang, færdigt eller fejlet.
Trin 2 viser antallet af uploadede filer ud af det samlede antal og navnet på den seneste fil.
Trin 4 viser antallet af flyttede stier ud af det samlede antal.
Når trin 5 er færdigt, lukker arket. Kortet "Service" viser derefter fremdriften for `--resync`.

### Resync i servicen

Kortet "Service" har tilstanden "Resynkroniserer". Tilstanden gælder, når 2 betingelser er opfyldt:
- Servicens hovedproces har `--resync` på kommandolinjen.
- Journalen for servicens nuværende kørsel har endnu ikke en linje, der afslutter synkroniseringen.

Statusprikken i sidebjælken har tonen `warning` under "Resynkroniserer".

Kortet viser fasen, en bjælke, den seneste fil og tiden siden start. Applikationen læser fasen fra journalen:

| Fase | Linjen i journalen begynder med |
|---|---|
| Kontrollerer den lokale database | `Performing a database consistency and integrity check` |
| Henter listen fra OneDrive | `Fetching items from the OneDrive API` |
| Behandler elementer fra OneDrive | `Processing <N> applicable` |
| Downloader filer | `Number of items to download from Microsoft OneDrive: <N>` |
| Scanner lokale filer | `Scanning the local file system` |
| Uploader filer | `New items to upload to Microsoft OneDrive: <N>` |
| Afslutter | `Performing a last examination of the most recent online data` |

Bjælken er bestemt, når applikationen kender det samlede antal `<N>`. Ellers er bjælken ubestemt.
Hver linje med `Downloading file: … done` eller `Uploading new file: … done` eller `Uploading modified file: … done` tæller 1 fil.
Klienten skriver `... done` på samme linje. Det viser loggen fra den manuelle resync på privatkontoen med 32161 linjer.
For store filer skriver klienten også `Downloading: <sti> ... 45%   |  ETA    00:01:10`. Kortet viser så procenten ved den seneste fil.

Resync er færdig ved en af disse linjer:
- `Sync with Microsoft OneDrive is complete`. Kortet viser "Resync er færdig".
- `Sync with Microsoft OneDrive has completed, however there are items that failed to sync.` Kortet viser "Resync er færdig med fejl" og antallet fra linjen `Failed items to download to/from Microsoft OneDrive: <N>`.

Fremdriften overlever, at brugeren lukker og åbner applikationen igen. Applikationen læser hele journalen for den nuværende kørsel ved start.

## Afgrænsning

- Brugeren kan ikke afbryde upload eller `--resync` i denne feature. Det er feature 0010.
- Applikationen viser ikke fremdrift for den almindelige synkronisering i `--monitor`. Kun `--resync` viser fremdrift.
- Applikationen viser ikke en liste over alle filer. Den viser kun den seneste fil.
- Applikationen beregner ikke en forventet sluttid.
- Applikationen viser ikke fremdrift for en `onedrive`-proces uden for servicen. Kortet viser stadig "Kører uden for servicen".
- Applikationen ændrer ikke klientens log-niveau og bruger ikke `--verbose`.

## Plan

1. `onedrive_gui/progress.py` (ny) — klassen `SyncProgress` med fase, antal færdige filer, samlet antal, seneste fil, starttid og slutresultat. Funktionen `feed(line)` opdaterer den ud fra én linje fra klienten. Reglerne står i tabellen i Løsning. Ukendte linjer ændrer intet.
2. `onedrive_gui/apply.py` — uploaden bruger `sideeffects.popen` med stdout som en pipe i stedet for `run`. Hver linje går til en `SyncProgress`. `execute()` får en callback `on_step(step, state, progress)`, som den kalder ved hvert skift.
3. `onedrive_gui/apply.py` — trin 4 kalder `on_step` efter hver flyttet sti med antallet flyttet og det samlede antal.
4. `onedrive_gui/service_state.py` — hent også `InvocationID` med `systemctl show`. Brug `process.py` til at læse `/proc/<MainPID>/cmdline` og afgøre, om kørslen har `--resync`.
5. `onedrive_gui/journal.py` — funktionen `invocation_lines(service, invocation_id, after_cursor)`. Den kører `journalctl --user -u <service> _SYSTEMD_INVOCATION_ID=<id> -o json --no-pager` og giver linjerne og den sidste cursor. Med `after_cursor` henter den kun nye linjer.
6. `onedrive_gui/service_state.py` — tilstanden "Resynkroniserer" efter betingelserne i Løsning. Den står i prioriteten lige efter "Kræver resync".
7. `onedrive_gui/viewmodels.py` — én `SyncProgress` pr. service med resync. Applikationen læser nye linjer hvert 2. sekund, mens vinduet er synligt. Arbejdet kører i en `_Job`.
8. `onedrive_gui/viewmodels.py` — properties til arket "Ændrer mappevalg": trinnene og deres tilstand, antal og seneste fil.
9. `onedrive_gui/qml/components/ProgressBar.qml` (ny) — en bestemt og en ubestemt bjælke efter tokens fra feature 0003.
10. `onedrive_gui/qml/sheets/ApplyProgressSheet.qml` (ny) — arket med de 5 trin. Det erstatter spinneren fra feature 0002.
11. `onedrive_gui/qml/components/ServiceCard.qml` — vis fase, bjælke, seneste fil og tid under "Resynkroniserer" og "Resync er færdig".

## Tests

Testene bruger linjer, der er optaget fra den rigtige klient, med opdigtede filnavne.

Fremdrift fra linjer:
- Ved `Number of items to download from Microsoft OneDrive: 120` skal fasen være "Downloader filer", og det samlede antal skal være 120.
- Ved 3 linjer med `Downloading file: A/b.txt ... done` skal antallet af færdige filer være 3, og den seneste fil skal være `A/b.txt`.
- Ved en linje med `Downloading file: A/c.txt ... failed!` må antallet ikke stige.
- Ved `Processing 5821 applicable JSON items received from Microsoft OneDrive ....` skal fasen være "Behandler elementer fra OneDrive".
- Uden en linje med et samlet antal skal bjælken være ubestemt.
- Ved `Sync with Microsoft OneDrive is complete` skal resultatet være "færdig".
- Ved `has completed, however there are items that failed to sync.` og `Failed items to download to/from Microsoft OneDrive: 2` skal resultatet være "færdig med fejl" med antallet 2.
- Ved en ukendt linje må tilstanden ikke ændre sig.
- Ved en `TRACE`-linje med `msg=Downloading file:` må antallet ikke stige.
- Ved `Downloading: A/film.avi ... 45%   |  ETA    00:01:10` skal den seneste fil være `A/film.avi` med 45 %, og antallet må ikke stige.

Ændring af mappevalget:
- `on_step` skal blive kaldt for alle 5 trin i rækkefølge med tilstanden "i gang" og derefter "færdigt".
- Under uploaden skal `on_step` give antallet af uploadede filer fra stdout.
- Når uploaden fejler, skal trin 2 stå som "fejlet", og trin 3–5 skal stå som "venter".
- Ved 4 stier til papirkurven skal trin 4 give 1/4, 2/4, 3/4 og 4/4.
- I sikker tilstand skal uploaden bruge `sideeffects.popen` og ende som "fejlet" uden at starte `onedrive`.

Resync i servicen:
- Ved en hovedproces med `--resync` og en journal uden en afsluttende linje skal tilstanden være "Resynkroniserer".
- Ved en hovedproces med `--resync` og linjen `Sync with Microsoft OneDrive is complete` skal tilstanden være "Kører", og kortet skal vise "Resync er færdig".
- Ved en hovedproces uden `--resync` må tilstanden aldrig være "Resynkroniserer".
- `journalctl` skal filtrere med `_SYSTEMD_INVOCATION_ID` for den nuværende kørsel.
- Med `after_cursor` skal `invocation_lines` kun give nye linjer.
- Når applikationen starter under en resync, skal den læse hele kørslens journal og vise det rigtige antal filer.
- Under "Resynkroniserer" skal statusprikken have tonen `warning`.

Brugerflade:
- `ApplyProgressSheet.qml` skal indlæses uden QML-advarsler og vise de 5 trin.
- `ServiceCard.qml` skal vise en bestemt bjælke ved 30 af 120 filer og en ubestemt bjælke uden et samlet antal.

**Eksisterende tests, der ændrer sig:** Tests i `tests/test_apply.py`, der forventer uploaden som et `run`-kald, skal nu forvente et `popen`-kald med de samme argumenter. Tests af spinneren under en ændring af mappevalget skal nu forvente `ApplyProgressSheet`.

## Verifikation

```bash
python3 -m pytest
```

Manuel afprøvning med en testkonto:

1. Fravælg en mappe med mange filer. Arket skal vise de 5 trin, og trin 4 skal tælle op.
2. Når arket lukker, skal kortet "Service" vise "Resynkroniserer" med fase og bjælke.
3. Luk applikationen, og åbn den igen. Kortet skal vise den samme fase og det samme antal filer.
4. Vent, til resync er færdig. Kortet skal vise "Resync er færdig" og derefter "Kører".

## Åbne spørgsmål

