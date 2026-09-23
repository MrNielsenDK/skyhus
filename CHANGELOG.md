# Changelog

Projektet følger [Keep a Changelog](https://keepachangelog.com/) og [SemVer](https://semver.org/).

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
