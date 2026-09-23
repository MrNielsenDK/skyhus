# Changelog

Projektet følger [Keep a Changelog](https://keepachangelog.com/) og [SemVer](https://semver.org/).

## [0.9.0] - 2026-09-23

### Added
- Kommandoen `python3 -m skyhus.install` lægger Skyhus i programmenuen med et ikon og installerer kommandoen `skyhus`. `--uninstall` fjerner dem igen. Installationen overskriver og fjerner kun filer, som Skyhus selv har skrevet. Se `docs/features/0013-installer-paa-skrivebordet.md`.
- Vinduet har ikonet for Skyhus. På Wayland viser panelet ikonet ved vinduet. Se `docs/features/0013-installer-paa-skrivebordet.md`.

### Removed
- `pyproject.toml` kræver ikke længere PySide6 fra PyPI. README beskriver ikke længere `pip install`. Se `docs/features/0013-installer-paa-skrivebordet.md`.

## [0.8.0] - 2026-09-23

### Changed
- Applikationen hedder nu Skyhus. Pakken er `skyhus`, kommandoen er `skyhus`, og vinduet har titlen "Skyhus". Se `docs/features/0012-omdoeb-til-skyhus.md`.
- Applikationen gemmer `accounts.json` og `state.json` i `~/.config/skyhus/`. Drop-in'en for resync hedder `zz-skyhus-resync.conf`. Se `docs/features/0012-omdoeb-til-skyhus.md`.
- Miljøvariablen for sikker tilstand er `SKYHUS_SAFE_MODE`. Den gamle `ONEDRIVE_GUI_SAFE_MODE` slår stadig sikker tilstand til. Se `docs/features/0012-omdoeb-til-skyhus.md`.

## [0.7.1] - 2026-09-23

### Fixed
- I sikker tilstand skriver "Afbryd resync" ikke markeringen i `~/.config/onedrive-gui/state.json`. Kortet bliver ved med at vise "Resynkroniserer", fordi servicen kører videre. Se `docs/features/0011-sikker-tilstand-markering-og-signaler.md`.
- Login stopper `onedrive`-processen med `sideeffects.signal_process`. I sikker tilstand sender applikationen intet signal. En AST-test forbyder direkte signaler i alle moduler. Se `docs/features/0011-sikker-tilstand-markering-og-signaler.md`.

## [0.7.0] - 2026-09-23

### Added
- Arket "Ændrer mappevalg" har knappen "Afbryd", mens applikationen uploader lokale ændringer. Et klik stopper uploaden. Applikationen skriver ikke `sync_list` og flytter intet til papirkurven. Kørte servicen før, starter applikationen den igen uden `--resync`. Se `docs/features/0010-afbryd-upload-og-resync.md`.
- Kortet "Service" har knappen "Afbryd resync" under "Resynkroniserer". Efter en bekræftelse stopper applikationen servicen. Kortet viser derefter "Resync afbrudt" med knappen "Genstart med resync". Se `docs/features/0010-afbryd-upload-og-resync.md`.
- Applikationen husker en afbrudt resync pr. service i `~/.config/onedrive-gui/state.json`. Markeringen forsvinder, når servicen starter igen. Se `docs/features/0010-afbryd-upload-og-resync.md`.

## [0.6.0] - 2026-09-23

### Added
- Arket "Ændrer mappevalg" viser de 5 trin i en ændring af mappevalget og tilstanden for hvert trin. Under uploaden viser arket antallet af uploadede filer og den seneste fil. Under papirkurven viser det antallet af flyttede stier. Se `docs/features/0009-vis-fremdrift.md`.
- Kortet "Service" har tilstanden "Resynkroniserer", når servicen kører med `--resync`. Kortet viser fasen, en bjælke, den seneste fil og tiden siden start. Statusprikken i sidebjælken har farven for advarsel. Se `docs/features/0009-vis-fremdrift.md`.
- Når klienten er færdig med `--resync`, viser kortet "Resync er færdig" eller "Resync er færdig med fejl" med antallet af fejlede elementer. Fremdriften er den samme, når brugeren åbner applikationen igen. Se `docs/features/0009-vis-fremdrift.md`.

## [0.5.3] - 2026-09-23

### Fixed
- Lukker brugeren vinduet, mens applikationen stopper eller starter en service, venter vinduet på handlingen. Arket "Applikationen lukker, når arbejdet er færdigt" viser handlingen. Vinduet lukker af sig selv bagefter. "Luk alligevel" viser først en advarsel. Se `docs/features/0008-oprydning-luk-annuller-tests-readme.md`.
- "Annullér" virker nu, mens applikationen stopper servicen før et login med `--reauth`. Knappen viser "Annullerer …". Applikationen starter ikke `onedrive` og starter servicen igen, hvis den kørte før. Se `docs/features/0008-oprydning-luk-annuller-tests-readme.md`.
- Testsuiten består i alle rækkefølger. Alle tests bruger én fælles `QGuiApplication` fra `tests/conftest.py`. Se `docs/features/0008-oprydning-luk-annuller-tests-readme.md`.

### Changed
- `README.md` beskriver mappevælgeren, papirkurven, kortet "Service" og login igen med `--reauth`. Se `docs/features/0008-oprydning-luk-annuller-tests-readme.md`.

## [0.5.2] - 2026-09-23

### Fixed
- Når brugeren fravælger en mappe, lægger applikationen kun de stier i papirkurven, som klienten synkroniserede før og ikke synkroniserer nu. Applikationen bruger alle regler i `sync_list`, `skip_dir`, `skip_file`, `skip_dotfiles` og `sync_root_files`. Symlinks og mapper med `.nosync` bliver altid liggende. Kan applikationen ikke tolke en regel i `sync_list`, viser den reglen og ændrer ikke noget. Se `docs/features/0006-papirkurv-respekterer-alle-regler.md`.

## [0.5.1] - 2026-09-23

### Fixed
- "Log ind" på en konto med en `refresh_token` virker nu. Applikationen stopper kontoens service, logger ind med `onedrive --reauth` og starter servicen igen. Fejler login, eller afbryder brugeren det, lægger applikationen den gamle `refresh_token` tilbage. Se `docs/features/0005-log-ind-igen-med-reauth.md`.

## [0.5.0] - 2026-09-23

### Added
- Applikationen har en sikker tilstand. I sikker tilstand ændrer applikationen intet på systemet, og et banner står øverst i vinduet. Se `docs/features/0007-sikker-tilstand.md`.
- Kommandoen `python3 -m onedrive_gui.app --safe` slår sikker tilstand til. Miljøvariablen `ONEDRIVE_GUI_SAFE_MODE=1` og en falsk `HOME` slår den også til. Se `docs/features/0007-sikker-tilstand.md`.

## [0.4.0] - 2026-09-23

### Added
- Kontosiden har kortet "Service". Kortet viser servicens tilstand, siden hvornår tilstanden gælder, og den seneste fejllinje fra journalen. Se `docs/features/0004-servicestatus-og-genstart.md`.
- Kortet har knappen "Start", "Genstart" eller "Genstart med resync". "Genstart med resync" viser først en bekræftelse. Se `docs/features/0004-servicestatus-og-genstart.md`.

### Changed
- Statusprikken i sidebjælken viser servicens tilstand. Applikationen opdaterer den hvert 3. sekund, mens vinduet er synligt. Se `docs/features/0004-servicestatus-og-genstart.md`.

## [0.3.0] - 2026-09-23

### Added
- Hver konto har en rund avatar med initialer og en fast farve. Applikationen har skriften Inter og ikoner fra Lucide med. Se `docs/features/0003-design-apple-inspireret.md`.

### Changed
- Vinduet har et nyt design inspireret af "Systemindstillinger" på macOS. Det har en sidebjælke med konti, kort med rækker og ark, der glider ned fra toppen. Se `docs/features/0003-design-apple-inspireret.md`.
- Applikationen følger systemets lyse eller mørke tema og skifter uden en genstart. Se `docs/features/0003-design-apple-inspireret.md`.

## [0.2.0] - 2026-09-23

### Added
- Hver konto har knappen "Vælg mapper". Mappevælgeren henter mapperne fra OneDrive og skriver `sync_list` og `sync_root_files`. Se `docs/features/0002-vaelg-mapper-til-synk.md`.
- Efter login for en ny konto viser applikationen mappevælgeren. Servicen starter først, når brugeren har valgt mapper. Se `docs/features/0002-vaelg-mapper-til-synk.md`.
- Når brugeren fravælger mapper, flytter applikationen de lokale kopier til papirkurven efter en bekræftelse. Applikationen sletter intet på OneDrive. Se `docs/features/0002-vaelg-mapper-til-synk.md`.

## [0.1.0] - 2026-09-23

### Added
- Applikationen viser alle OneDrive-konti på maskinen, og om hver konto er logget ind. Se `docs/features/0001-flere-konti-og-login.md`.
- Brugeren kan give en konto et visningsnavn, tilføje en ny konto og logge ind i et indbygget browservindue. Se `docs/features/0001-flere-konti-og-login.md`.
- Efter login opretter og starter applikationen en systemd-user-service for en ny konto. Se `docs/features/0001-flere-konti-og-login.md`.

## [0.0.0] - 2026-09-23

### Added
- Projektet er oprettet. Der er endnu ingen kode.
