# Vælg mapper til synkronisering

Version: 0.2.0
Status: udviklet
Oprettet: 2026-09-23

## Problem

Klienten synkroniserer som standard hele OneDrive til computeren.
Brugeren vil ofte kun have nogle af mapperne lokalt.
I dag skal brugeren selv skrive filen `sync_list` og køre `--resync` i en terminal.
Når brugeren fjerner en mappe fra `sync_list`, bliver den lokale kopi liggende på disken.
Sletter brugeren selv den lokale kopi, mens klienten kører, kan klienten også slette mappen på OneDrive.

## Løsning

Hver konto har knappen "Vælg mapper". Knappen åbner en mappevælger.

Mappevælgeren viser mapperne på OneDrive som et træ med afkrydsningsfelter.
Applikationen henter mapperne direkte fra Microsoft Graph, så træet virker også før første synkronisering.
Applikationen henter undermapper først, når brugeren folder en mappe ud.

Mappevælgeren har 2 ekstra felter:
- "Synkroniser alle mapper". Når feltet er valgt, synkroniserer klienten alt, også mapper, der kommer til senere.
- "Synkroniser filer i roden". Feltet styrer `sync_root_files` i kontoens `config`.

Når brugeren tilføjer en ny konto (feature 0001), viser applikationen mappevælgeren efter login.
Applikationen starter først kontoens service, når brugeren har valgt mapper.

Når brugeren ændrer valget for en konto, der allerede har synkroniseret, gør applikationen dette:
1. Applikationen viser de lokale mapper og filer, der forsvinder fra computeren, og beder brugeren bekræfte.
2. Applikationen stopper kontoens service.
3. Applikationen uploader lokale ændringer, som klienten ikke har sendt til OneDrive endnu.
4. Applikationen skriver den nye `sync_list` og `sync_root_files`.
5. Applikationen flytter de lokale mapper og filer, der ikke længere er valgt, til papirkurven.
6. Applikationen starter servicen én gang med `--resync --resync-auth`.

Applikationen sletter aldrig noget på OneDrive.

## Afgrænsning

- Applikationen tømmer ikke papirkurven og sletter ikke lokale filer permanent.
- Brugeren kan ikke vælge enkelte filer. Mappevælgeren håndterer kun mapper og feltet for filer i roden.
- Mappevælgeren understøtter ikke wildcards, undtagelser med `!` eller regler uden en `/` foran.
- Applikationen ændrer ikke `skip_dir`. Mapper i `skip_dir` står som ikke tilgængelige i træet.
- Mappevælgeren viser ikke delte mapper ("Delt med mig") eller SharePoint-biblioteker.
- Applikationen viser ikke fremdrift under upload eller `--resync`. Den viser kun, at arbejdet er i gang.
- Brugeren kan ikke afbryde en ændring, når den er i gang.
- Applikationen skriver ikke en ny `refresh_token` til klientens config-mappe.

## Plan

Kontoens service stopper, før applikationen skriver noget. Så kan klienten ikke se en lokal sletning og sende den videre til OneDrive.

1. `onedrive_gui/graph.py` — læs kontoens `refresh_token` og hent et access-token fra `https://login.microsoftonline.com/common/oauth2/v2.0/token`. Brug klientens `client_id` `d50ca740-c83f-4d1b-b616-12c519384f0c` og samme scopes som klienten. Applikationen gemmer ikke det nye `refresh_token` fra svaret.
2. `onedrive_gui/graph.py` — hent undermapper med `GET /me/drive/root/children` og `GET /me/drive/items/{id}/children`. Returnér kun mapper. Følg `@odata.nextLink`, så lange lister kommer med.
3. `onedrive_gui/synclist.py` — læs `sync_list`. Del linjerne i 2 grupper: regler af formen `/sti/` (styret af applikationen) og alle andre linjer (ukendte regler). Tomme linjer og linjer med `#` hører til de ukendte regler.
4. `onedrive_gui/synclist.py` — lav om fra et valg i træet til regler. En mappe, der er helt valgt, giver én regel `/sti/`. En delvist valgt mappe giver regler for dens valgte undermapper. "Synkroniser alle mapper" betyder, at filen `sync_list` ikke findes.
5. `onedrive_gui/synclist.py` — skriv `sync_list`. Behold de ukendte regler uændret og i samme rækkefølge øverst i filen.
6. `onedrive_gui/config.py` — læs og skriv `sync_root_files` i kontoens `config`. Behold alle andre linjer og kommentarer uændret.
7. `onedrive_gui/removal.py` — find de lokale stier, der forsvinder. En sti forsvinder, hvis de gamle regler inkluderede den, og de nye regler ikke gør. En mappe, der indeholder en ny inkluderet sti, forsvinder ikke selv. Applikationen går videre ned i den. Stier i `skip_dir` forsvinder aldrig.
8. `onedrive_gui/process.py` — find kørende `onedrive`-processer for en config-mappe via `/proc/*/cmdline`. En proces uden `--confdir` bruger `~/.config/onedrive`.
9. `onedrive_gui/apply.py` — udfør ændringen i den rækkefølge, som afsnittet Løsning beskriver. Uploaden bruger `onedrive --confdir=<confdir> --sync --upload-only --no-remote-delete`. Papirkurven bruger `QFile.moveToTrash`.
10. `onedrive_gui/apply.py` — start servicen med `--resync --resync-auth` via en midlertidig drop-in `~/.config/systemd/user/<service>.d/zz-onedrive-gui-resync.conf`. Drop-in'en kopierer `ExecStart` fra `systemctl --user cat <service>` og tilføjer de 2 flag. Applikationen kører `daemon-reload` og `restart` og fjerner derefter drop-in'en og kører `daemon-reload` igen.
11. `onedrive_gui/apply.py` — før første synkronisering skriver applikationen kun `sync_list` og `sync_root_files`. Før første synkronisering betyder, at `items.sqlite3` ikke findes i config-mappen.
12. `onedrive_gui/qml/sheets/FolderPickerSheet.qml` — træet med afkrydsningsfelter i 3 tilstande og de 2 ekstra felter. Træet viser det nuværende valg fra `sync_list`. Findes der ukendte regler, viser vinduet en besked om, at applikationen beholder dem.
13. `onedrive_gui/qml/sheets/ConfirmRemovalSheet.qml` — listen over lokale stier, der ryger i papirkurven, og deres samlede størrelse.
14. `onedrive_gui/qml/AccountPage.qml` og `onedrive_gui/viewmodels.py` — tilføj knappen "Vælg mapper", og vis mappevælgeren efter login for en ny konto.

## Tests

Testene kalder ikke Microsoft Graph, `onedrive` eller `systemctl`. Testene bruger en midlertidig `HOME`.

Microsoft Graph:
- Ved et svar med 2 mapper og 1 fil skal applikationen returnere de 2 mapper.
- Ved et svar med `@odata.nextLink` skal applikationen også hente næste side og returnere mapperne fra begge sider.
- Efter et token-kald skal `refresh_token` i config-mappen være uændret, byte for byte.
- Når kontoen mangler `refresh_token`, skal applikationen vise "Kontoen er ikke logget ind" og ikke åbne træet.
- Ved svaret `invalid_grant` fra token-kaldet skal applikationen vise, at brugeren skal logge ind igen.

Regler:
- En helt valgt mappe `Dokumenter` skal give præcis reglen `/Dokumenter/`.
- En delvist valgt `Arbejde` med valgt undermappe `Kunder` skal give `/Arbejde/Kunder/` og ikke `/Arbejde/`.
- "Synkroniser alle mapper" skal fjerne filen `sync_list`.
- Når ingen mapper er valgt, og "Synkroniser alle mapper" ikke er valgt, skal applikationen vise en fejl og ikke skrive noget.
- Ved en mappe med mellemrum eller æøå i navnet skal reglen indeholde navnet præcis, som OneDrive viser det.
- Ved en `sync_list` med `!/Hemmelig/*` og en kommentar skal begge linjer stå uændret øverst efter en ny skrivning.
- Ved en `sync_list` med `/Dokumenter/` skal træet vise `Dokumenter` som valgt.
- Når brugeren slår "Synkroniser filer i roden" til, skal `config` indeholde `sync_root_files = "true"`, og de andre linjer skal være uændrede.

Lokale stier, der forsvinder:
- Ved gamle regler `/A/` og `/B/` og nye regler `/A/` skal `~/OneDrive-X/B` forsvinde, og `~/OneDrive-X/A` skal blive.
- Ved gamle regler `/A/` og nye regler `/A/B/` skal søskende til `B` og filer direkte i `A` forsvinde, og `A/B` skal blive.
- Ved en ændring fra "alle mapper" til `/A/` skal alle andre mapper i roden forsvinde.
- Når brugeren slår "Synkroniser filer i roden" fra, skal filerne i roden forsvinde, og mapperne skal blive.
- En mappe i `skip_dir` skal aldrig forsvinde.
- Ved en ændring, der kun tilføjer mapper, skal ingen lokale stier forsvinde, og applikationen skal ikke vise bekræftelsen.

Udførelse:
- Ved en konto, der har synkroniseret, skal kaldene komme i denne rækkefølge: `stop`, upload, skriv `sync_list`, papirkurv, `restart` med `--resync --resync-auth`.
- Uploaden skal indeholde `--upload-only` og `--no-remote-delete`.
- Efter `restart` skal drop-in-filen `zz-onedrive-gui-resync.conf` ikke findes.
- Ved en konto uden `items.sqlite3` skal applikationen ikke stoppe servicen, ikke uploade og ikke køre `--resync`.
- Når uploaden fejler, skal applikationen ikke skrive `sync_list`, ikke flytte noget til papirkurven og starte servicen igen uden `--resync`.
- Når en `onedrive`-proces uden for servicen bruger config-mappen, skal applikationen vise en fejl og ikke ændre noget.
- Når brugeren afviser bekræftelsen, skal applikationen ikke ændre noget.
- Når en sti ikke kan flyttes til papirkurven, skal applikationen vise stien, fortsætte med de andre og stadig starte servicen med `--resync`.
- Ved en konto uden service skal applikationen vise en fejl og ikke ændre noget.

**Eksisterende tests, der ændrer sig:** Feature 0001 er ikke bygget endnu, men dens tests ændrer sig. Testen for `systemctl --user enable --now` skal kræve, at brugeren har valgt mapper først. Lukker brugeren mappevælgeren uden at vælge, skal kontoen stå som logget ind uden en startet service.

## Verifikation

```bash
python3 -m pytest
```

Manuel afprøvning med en testkonto:

1. Tilføj en ny konto. Mappevælgeren skal åbne efter login, og servicen skal ikke køre endnu.
2. Vælg 2 mapper og klik OK. `sync_list` skal indeholde præcis de 2 regler, og servicen skal køre.
3. Vent, til de 2 mapper findes lokalt.
4. Fravælg den ene mappe. Bekræftelsen skal vise mappen.
5. Klik OK. Mappen skal ligge i papirkurven og ikke i synkmappen.
6. Åbn OneDrive i en browser. Den fravalgte mappe skal stadig findes der.
7. `systemctl --user cat <service>` må ikke vise drop-in'en `zz-onedrive-gui-resync.conf`.

## Åbne spørgsmål

- Genstarter servicen efter en fejl, før `--resync` er færdig, kører den uden `--resync`. Implementeringen skal afprøve, om klienten så stopper med exit-kode 126. Stopper klienten ikke, skal drop-in'en blive, til `--resync` er færdig.
- For en stor konto kan uploaden og `--resync` tage lang tid. Denne feature viser kun, at arbejdet er i gang.
