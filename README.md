# onedrive-gui

onedrive-gui er et Qt-vindue til flere OneDrive-konti på den samme maskine.
Applikationen bruger klienten [abraunegg/onedrive](https://github.com/abraunegg/onedrive).
Hver konto har sin egen config-mappe og sin egen systemd-user-service.

Applikationen kan:

- vise alle konti i `~/.config/onedrive` og `~/.config/onedrive-*`,
- vise, om hver konto er logget ind,
- give hver konto et visningsnavn,
- tilføje en ny konto med login i et indbygget browservindue,
- logge en eksisterende konto ind igen med `--reauth`,
- vælge, hvilke mapper på OneDrive hver konto synkroniserer,
- vise tilstanden for hver kontos service og starte eller genstarte den.

## Tilføj en konto

Klik "Tilføj konto", og skriv et visningsnavn og en synkmappe.
Applikationen opretter config-mappen og åbner Microsofts login-side.
Når du er logget ind, viser applikationen mappevælgeren.
Applikationen opretter og starter servicen, når du klikker "OK" i mappevælgeren.
Lukker du mappevælgeren uden at vælge, er kontoen logget ind, men servicen er ikke oprettet.

## Log ind igen

Klik "Log ind" på en konto, der allerede er logget ind. Applikationen logger så ind med `--reauth`.

- Kører kontoens service, stopper applikationen den før login. Login-arket viser "Servicen er stoppet, mens du logger ind".
- Når login er færdigt, starter applikationen servicen igen. Den starter kun servicen, hvis den kørte før login.
- Fejler login, eller klikker du "Annullér", lægger applikationen den gamle `refresh_token` tilbage og starter servicen igen.
- Du kan klikke "Annullér", mens servicen stopper. Knappen viser så "Annullerer …". Applikationen starter ikke `onedrive`, når stoppet er færdigt.
- Kører en anden `onedrive`-proces med kontoen, afviser applikationen login.

## Vælg mapper

Klik "Vælg mapper …" på en konto. Mappevælgeren henter mapperne fra OneDrive med kontoens login.

- Vælg "Synkroniser alle mapper", eller sæt flueben ved de mapper, kontoen skal synkronisere.
- "Synkroniser filer i roden" bestemmer, om klienten også synkroniserer filerne øverst på OneDrive.
- En mappe, der står i `skip_dir`, er ikke tilgængelig.
- Applikationen skriver valget i `sync_list`. Andre linjer i filen bevarer den uændret.

Fjerner du en mappe fra valget, flytter applikationen den lokale kopi til papirkurven. OneDrive beholder mappen.
Før det viser applikationen en liste over de lokale mapper og filer og deres samlede størrelse.
Du bekræfter med "Flyt til papirkurven" eller fortryder med "Annullér".

Når du gemmer et nyt mappevalg for en konto, der har synkroniseret før, gør applikationen dette i denne rækkefølge:

1. Den stopper kontoens service.
2. Den uploader lokale ændringer med `--upload-only --no-remote-delete`.
3. Den skriver `sync_list`.
4. Den flytter de fjernede mapper til papirkurven.
5. Den genstarter servicen 1 gang med `--resync`. Det kan tage lang tid for en stor konto.

## Kortet "Service"

Kortet "Service" på hver konto viser servicens tilstand og tidspunktet for den. Applikationen læser tilstanden hvert 3. sekund, mens vinduet er synligt.
Prikken ved kontoen i sidebjælken har den samme farve som tilstanden.

| Tilstand | Knap |
| --- | --- |
| Kører | "Genstart" stopper klienten og starter den igen. |
| Starter | "Genstart" |
| Stopper | Ingen knap |
| Stoppet | "Start" starter klienten. |
| Fejlet | "Start" nulstiller fejlen og starter klienten. Kortet viser den sidste fejl fra loggen. |
| Kræver resync | "Genstart med resync" genstarter servicen 1 gang med `--resync --resync-auth`. Du skal bekræfte det først. |
| Kører uden for servicen | Ingen knap. En anden `onedrive`-proces bruger kontoen. |
| Ikke logget ind | Ingen knap |
| Ingen service | Ingen knap |

Efter et klik venter applikationen i op til 120 sekunder på, at servicen kører eller fejler.
Falder servicen ikke til ro, viser kortet "Servicen svarer ikke.".
Kan `systemctl` ikke udføre handlingen, viser kortet beskeden fra `systemctl`.

## Installér afhængighederne

Applikationen bruger system-pakkerne fra Ubuntu/Debian:

```bash
sudo apt install onedrive python3-pyside6.qtquick python3-pyside6.qtquickcontrols2 \
    python3-pyside6.qtwebenginequick python3-pyside6.qtsvg python3-pytest
```

Login-vinduet kræver `python3-pyside6.qtwebenginequick`.
Uden pakken starter applikationen, men login-vinduet viser en fejl.

## Start applikationen

Kør denne kommando fra projektets rod:

```bash
python3 -m onedrive_gui.app
```

Du kan også installere kommandoen `onedrive-gui` med `pip install --user -e .`.

## Sikker tilstand

I sikker tilstand ændrer applikationen intet på systemet.
Brugerfladen og alle forløb virker stadig, så du kan afprøve dem og tage skærmbilleder.
Øverst i vinduet står et banner: "Sikker tilstand – applikationen ændrer ikke noget på systemet".

Start applikationen i sikker tilstand med denne kommando:

```bash
python3 -m onedrive_gui.app --safe
```

Sikker tilstand er også slået til i disse 2 tilfælde:

- Miljøvariablen `ONEDRIVE_GUI_SAFE_MODE` er `1`.
- `HOME` er en anden mappe end din rigtige hjemmemappe. Du kan ikke slå sikker tilstand fra i det tilfælde.

I sikker tilstand gælder disse regler:

- `systemctl --user show`, `cat`, `status` og `is-active` kører som normalt. Det gør `journalctl` også.
- Alle andre `systemctl`-kommandoer kører ikke. Applikationen svarer, at de lykkedes.
- Applikationen starter ikke `onedrive`. Et login ender med fejlen "Sikker tilstand: onedrive blev ikke startet".
- Applikationen flytter ingen filer til papirkurven.
- Applikationen skriver ingen filer under din rigtige hjemmemappe. Undtagelsen er `~/.config/onedrive-gui/`.
- Kald til Microsoft Graph kører som normalt. Kaldene læser kun.

Hver blokeret handling giver en linje i loggen, der starter med `SAFE MODE:`.

## Kør testene

```bash
python3 -m pytest
```

Testene bruger en midlertidig `HOME` og sikker tilstand. De kalder ikke den rigtige `onedrive` eller `systemctl`.
Testen af `LoginSheet.qml` springer over, hvis QtWebEngine mangler.

## Filer

- `~/.config/onedrive-gui/accounts.json` gemmer visningsnavnene.
- `~/.config/onedrive-<slug>/config` er config-filen for en ny konto.
- `~/.config/systemd/user/onedrive-<slug>.service` er servicen for en ny konto.
