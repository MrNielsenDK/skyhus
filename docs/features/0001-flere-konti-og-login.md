# Flere konti og login via GUI

Version: 0.1.0
Status: udviklet
Oprettet: 2026-09-23

## Problem

Brugeren har flere OneDrive-konti på maskinen, fx "Privat", "Firma 1" og "Firma 2".
I dag skal brugeren oprette hver konto manuelt i en terminal.
Brugeren skal selv skrive en config-fil og en systemd-service og kopiere en login-URL.
Der findes ikke et sted, der viser alle konti samlet.

## Løsning

Applikationen er et Qt-vindue, der viser en liste over alle OneDrive-konti på maskinen.
Hver konto har et visningsnavn, som brugeren selv vælger.

Applikationen finder automatisk de eksisterende konti i `~/.config/onedrive` og `~/.config/onedrive-*`.
For hver fundet konto viser applikationen, om kontoen er logget ind.
En konto er logget ind, når filen `refresh_token` findes i kontoens config-mappe.

Brugeren kan tilføje en ny konto med knappen "Tilføj konto".
Brugeren skriver et visningsnavn og vælger en synkmappe.
Applikationen foreslår synkmappen `~/OneDrive-<Navn>`.

Applikationen viser Microsofts login-side i et indbygget browservindue.
Når Microsoft sender brugeren videre til `https://login.microsoftonline.com/common/oauth2/nativeclient?code=...`, fanger applikationen URL'en.
Applikationen giver URL'en til klienten, og klienten gemmer `refresh_token`.

Efter login opretter applikationen en systemd-user-service for kontoen og starter den.
Servicen følger samme form som den eksisterende `onedrive-privat.service`.

Brugeren kan også logge en eksisterende konto ind igen.
Det gælder fx den firmakonto, som applikationen fandt automatisk, hvis dens `refresh_token` mangler.

## Afgrænsning

- Applikationen viser ikke synkstatus, fremdrift, filer eller log. Det bliver en separat feature.
- Applikationen kan ikke fjerne en konto, logge ud eller slette en config-mappe.
- Applikationen kan ikke ændre `skip_dir` eller andre config-indstillinger end `sync_dir`.
- Applikationen ændrer ikke de eksisterende filer `onedrive.service`, `onedrive-privat.service` eller deres `.path`-units.
- Applikationen opretter ikke `.path`-units eller `onedrive-nosleep.service` for nye konti.
- Applikationen har ikke en ikon i systembakken og starter ikke automatisk ved login.
- Applikationen understøtter ikke SharePoint-biblioteker, Intune-SSO eller device-login (`use_device_auth`).
- Applikationen kører ikke `--resync` eller en synkronisering selv. Kun systemd-servicen synkroniserer.

## Plan

Stakken er Python 3 og PySide6 (Qt 6). Brugerfladen er QML efter feature 0003. Login-arket bruger `QtWebEngine` til QML.
Koden skal holde logikken adskilt fra Qt, så testene kan køre uden et vindue.

1. `pyproject.toml` — opret projektet `onedrive-gui` med `version = "0.1.0"` og indgangen `onedrive-gui = "onedrive_gui.app:main"`. Tilføj `pytest` som test-afhængighed.
2. `onedrive_gui/accounts.py` — modellen `Account` med feltet `name` (visningsnavn), `confdir`, `sync_dir`, `service` og `logged_in`.
3. `onedrive_gui/registry.py` — læs og skriv `~/.config/onedrive-gui/accounts.json`. Filen gemmer visningsnavn, `confdir` og `service` for hver konto.
4. `onedrive_gui/discovery.py` — find config-mapper, der hedder `~/.config/onedrive` eller `~/.config/onedrive-*`. Mappen `~/.config/onedrive-gui` er ikke en konto. En mappe er en konto, hvis den indeholder `config`, `refresh_token` eller `items.sqlite3`.
5. `onedrive_gui/discovery.py` — find kontoens service. `~/.config/onedrive` hører til `onedrive.service`. For andre mapper finder funktionen den user-unit i `~/.config/systemd/user/`, hvis `ExecStart` nævner mappen. Findes ingen unit, er `service` tom.
6. `onedrive_gui/discovery.py` — læs `sync_dir` fra kontoens `config`. Mangler værdien, er synkmappen `~/OneDrive`.
7. `onedrive_gui/naming.py` — lav en slug ud fra visningsnavnet, fx "Firma 2" → `firma-2`. Slug'en giver `~/.config/onedrive-<slug>` og `onedrive-<slug>.service`. Æ, ø og å bliver til `ae`, `oe` og `aa`.
8. `onedrive_gui/provision.py` — opret config-mappen og skriv `config` med `sync_dir`. Opret synkmappen, hvis den ikke findes.
9. `onedrive_gui/auth.py` — start `onedrive --confdir=<confdir> --auth-files <auth.url>:<response.url>` som en baggrundsproces. Vent på, at klienten skriver `auth.url`. Skriv den fangede URL i `response.url`. Vent derefter på `refresh_token`. Afslutter processen ikke selv inden 30 sekunder efter `refresh_token`, skal applikationen stoppe den.
10. `onedrive_gui/service.py` — skriv `~/.config/systemd/user/onedrive-<slug>.service` efter skabelonen i `onedrive-privat.service`, inklusive `OnFailure=onedrive-failure@%N.service`. Kør `systemctl --user daemon-reload` og `systemctl --user enable --now onedrive-<slug>.service`.
11. `onedrive_gui/qml/Main.qml` og `onedrive_gui/qml/AccountPage.qml` — vinduet med kontolisten. Hver række viser visningsnavn, synkmappe og "Logget ind" eller "Ikke logget ind". Knapperne er "Tilføj konto", "Log ind" og "Omdøb".
12. `onedrive_gui/qml/sheets/AddAccountSheet.qml` — arket, hvor brugeren skriver visningsnavn og vælger synkmappe.
13. `onedrive_gui/qml/sheets/LoginSheet.qml` — et `WebEngineView`, der åbner `auth.url`. Vinduet fanger navigationen til `nativeclient` og sender URL'en til `auth.py`. Vinduet bruger en tom browserprofil, så en tidligere konto ikke logger ind automatisk.
14. `onedrive_gui/app.py` — `main()`, der starter Qt og indlæser `Main.qml`.
15. `README.md` — beskriv, hvordan brugeren installerer afhængighederne og starter applikationen.

## Tests

Testene kører med `pytest` og en midlertidig mappe som `HOME`. Testene kalder ikke den rigtige `onedrive` eller `systemctl`.

Kontoopdagelse:
- Ved en `HOME` med `~/.config/onedrive` og `~/.config/onedrive-privat` skal applikationen finde 2 konti.
- Ved en config-mappe med `refresh_token` skal kontoen stå som logget ind. Uden filen skal kontoen stå som ikke logget ind.
- Ved mappen `~/.config/onedrive-gui` skal applikationen ikke vise en konto.
- Ved en tom mappe `~/.config/onedrive-tom` uden `config`, `refresh_token` og `items.sqlite3` skal applikationen ikke vise en konto.
- Ved `~/.config/onedrive` skal kontoens service være `onedrive.service`.
- Ved en user-unit, hvis `ExecStart` indeholder `--confdir="%h/.config/onedrive-privat"`, skal kontoen `onedrive-privat` få den unit som service.
- Ved en config-mappe uden en tilhørende unit skal `service` være tom.
- Ved `sync_dir = "~/OneDrive-Privat"` i `config` skal synkmappen være `~/OneDrive-Privat`. Uden `sync_dir` skal synkmappen være `~/OneDrive`.
- Ved `config`-linjer, der starter med `#`, skal applikationen ignorere dem.

Register:
- Når brugeren omdøber en konto, skal det nye visningsnavn stå i `accounts.json`, og navnet skal overleve en genstart.
- Ved en fundet konto uden en post i `accounts.json` skal visningsnavnet være mappens navn uden `onedrive-`. `~/.config/onedrive` får navnet "OneDrive".
- Ved en ødelagt `accounts.json` skal applikationen stadig vise de fundne konti og ikke stoppe med en fejl.

Navne:
- "Firma 2" skal give slug'en `firma-2`.
- "Søstrenes Æbler" skal give slug'en `soestrenes-aebler`.
- Et visningsnavn, der allerede findes, skal give en fejl, før applikationen opretter filer.
- En slug, der giver en eksisterende config-mappe, skal give en fejl, før applikationen opretter filer.
- Et tomt visningsnavn eller et navn med kun mellemrum skal give en fejl.

Oprettelse:
- Ved en ny konto skal applikationen skrive `config` med præcis den valgte `sync_dir`.
- Ved en synkmappe, der ikke findes, skal applikationen oprette den.

Login:
- Når klienten har skrevet `auth.url`, skal login-vinduet få præcis den URL.
- Når login-vinduet fanger `https://login.microsoftonline.com/common/oauth2/nativeclient?code=abc`, skal `response.url` indeholde præcis den URL.
- Ved en navigation til en anden URL end `nativeclient` skal applikationen ikke skrive `response.url`.
- Ved en `nativeclient`-URL med `error=` i stedet for `code=` skal applikationen vise fejlbeskeden og ikke oprette en service.
- Når brugeren lukker login-vinduet før login, skal applikationen stoppe `onedrive`-processen og ikke oprette en service.
- Når `onedrive`-processen stopper med en exit-kode forskellig fra 0, før `refresh_token` findes, skal applikationen vise fejlen og ikke oprette en service.

Service:
- Ved en ny konto med slug'en `firma-2` skal filen `onedrive-firma-2.service` indeholde `ExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-firma-2"`.
- Unit-filen skal indeholde `OnFailure=onedrive-failure@%N.service` og `RestartPreventExitStatus=126`.
- Efter login skal applikationen kalde `systemctl --user daemon-reload` og derefter `systemctl --user enable --now onedrive-firma-2.service`.
- Når en service med samme navn allerede findes, skal applikationen ikke overskrive den.
- Når brugeren logger en eksisterende konto ind igen, skal applikationen ikke oprette en ny service. Applikationen skal genstarte den service, der findes.
- Når `systemctl` fejler, skal applikationen vise fejlbeskeden. Kontoen skal stadig stå som logget ind.

**Eksisterende tests, der ændrer sig:** Ingen. Projektet har ingen tests endnu.

## Verifikation

Afhængighederne skal være installeret:

```bash
sudo apt install python3-pytest python3-pyside6.qtwebenginequick
```

Testene skal bestå:

```bash
python3 -m pytest
```

Manuel afprøvning:

1. Kør `python3 -m onedrive_gui.app`. Vinduet skal vise firmakontoen og privatkontoen som logget ind.
2. Omdøb firmakontoen til "Firma 1". Luk og start applikationen igen. Navnet skal stadig være "Firma 1".
3. Klik "Tilføj konto" og skriv "Firma 2". Log ind i login-vinduet med en testkonto.
4. `~/.config/onedrive-firma-2/refresh_token` skal findes.
5. `systemctl --user status onedrive-firma-2` skal vise `active (running)`.
6. `onedrive.service` og `onedrive-privat.service` skal være uændrede.

## Åbne spørgsmål

- Klienten afslutter måske ikke selv efter login, når kommandoen hverken har `--sync` eller `--monitor`. Plan-trin 9 håndterer det med en tidsgrænse på 30 sekunder. Implementeringen skal bekræfte klientens faktiske adfærd.
- Implementeringen er ikke afprøvet mod en rigtig konto. `auth.py` stopper klienten 30 sekunder efter `refresh_token`, hvis klienten ikke afslutter selv. Brugeren skal bekræfte klientens faktiske adfærd manuelt ved manuel afprøvning 3.
