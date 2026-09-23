# onedrive-gui

onedrive-gui er et Qt-vindue til flere OneDrive-konti på den samme maskine.
Applikationen bruger klienten [abraunegg/onedrive](https://github.com/abraunegg/onedrive).
Hver konto har sin egen config-mappe og sin egen systemd-user-service.

Applikationen kan:

- vise alle konti i `~/.config/onedrive` og `~/.config/onedrive-*`,
- vise, om hver konto er logget ind,
- give hver konto et visningsnavn,
- tilføje en ny konto med login i et indbygget browservindue,
- logge en eksisterende konto ind igen.

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
