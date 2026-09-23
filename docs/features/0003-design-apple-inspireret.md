# Design inspireret af Apple

Version: 0.3.0
Status: udviklet
Oprettet: 2026-09-23

## Problem

Brugeren åbner applikationen sjældent.
Når brugeren åbner den, skal den være rar at se på og let at forstå.
Et standardvindue med Qt-widgets ser gammeldags ud og ligner ikke en moderne applikation.
Feature 0001 og 0002 beskriver funktionerne, men ikke udseendet.

## Løsning

Brugerfladen er bygget i Qt Quick (QML). Logikken bliver i Python.
Designet tager udgangspunkt i "Systemindstillinger" på macOS.

Vinduet har 2 dele:
- En sidebjælke til venstre med alle konti og knappen "Tilføj konto" nederst.
- Et indholdsfelt til højre med den valgte kontos detaljer.

Hver konto i sidebjælken har en rund avatar med initialer, visningsnavnet og en statusprik.
Hver konto får en fast farve til avataren. Farven følger kontoen, også efter en genstart.

Indholdsfeltet har en stor overskrift med visningsnavnet og synkmappen under.
Under overskriften står grupperede kort med afrundede hjørner.
Hvert kort har rækker med en tekst til venstre og en værdi eller knap til højre.
En tynd streg adskiller rækkerne.

Dialoger vises som et ark, der glider ned fra toppen af vinduet. Resten af vinduet bliver dæmpet.
Det gælder "Tilføj konto", login, mappevælgeren og bekræftelsen af, hvad der bliver fjernet.

Applikationen følger systemets tema. Er KDE sat til mørkt, er applikationen mørk.
Skifter brugeren tema i KDE, skifter applikationen med det samme uden en genstart.

Findes der ingen konti, viser indholdsfeltet et ikon, teksten "Ingen konti endnu" og knappen "Tilføj konto".

## Afgrænsning

- Applikationen har ikke et manuelt valg mellem lyst og mørkt tema.
- Applikationen bruger ikke KDE's accentfarve. Accentfarven er fast.
- Vinduet har ikke gennemsigtighed eller blur bag sidebjælken.
- Applikationen husker ikke vinduets størrelse og placering mellem 2 starter.
- Applikationen har ikke andre sprog end dansk.
- Applikationen viser ikke synkstatus ud over statusprikken for "Logget ind" og "Ikke logget ind". Rigtig synkstatus er en separat feature.
- Featuren tilføjer ikke nye funktioner. Den ændrer kun, hvordan funktionerne fra 0001 og 0002 ser ud.

## Designværdier

Alle farver, størrelser og tider står i ét modul. QML-filerne må ikke indeholde farvekoder eller faste størrelser.

### Farver

| Token | Lyst | Mørkt | Brug |
|---|---|---|---|
| `windowBg` | `#F5F5F7` | `#1E1E1E` | Baggrund i indholdsfeltet |
| `sidebarBg` | `#E8E8ED` | `#252527` | Baggrund i sidebjælken |
| `cardBg` | `#FFFFFF` | `#2C2C2E` | Kort og ark |
| `separator` | `rgba(0,0,0,0.10)` | `rgba(255,255,255,0.10)` | Streger mellem rækker |
| `textPrimary` | `#1D1D1F` | `#F5F5F7` | Overskrifter og brødtekst |
| `textSecondary` | `#636366` | `#98989D` | Undertekst og værdier |
| `accent` | `#0066CC` | `#0071E3` | Primære knapper og valgte felter |
| `onAccent` | `#FFFFFF` | `#FFFFFF` | Tekst på `accent` |
| `accentText` | `#0066CC` | `#4DA3FF` | Links og tekstknapper |
| `success` | `#248A3D` | `#30D158` | Statusprik "Logget ind" |
| `warning` | `#C93400` | `#FF9F0A` | Advarsler |
| `danger` | `#D70015` | `#FF6961` | Fejl og knapper, der fjerner noget |
| `avatar1` … `avatar8` | Se tabellen nedenfor | Se tabellen nedenfor | Avatarer |

De 8 avatarfarver bygger på Apples systemfarver. De er ens i lyst og mørkt tema.

| Token | Farve | Tekst |
|---|---|---|
| `avatar1` | `#0A7AFF` (blå) | `#FFFFFF` |
| `avatar2` | `#AF52DE` (lilla) | `#FFFFFF` |
| `avatar3` | `#E0356B` (lyserød) | `#FFFFFF` |
| `avatar4` | `#E5352B` (rød) | `#FFFFFF` |
| `avatar5` | `#E66A00` (orange) | `#FFFFFF` |
| `avatar6` | `#FFCC00` (gul) | `#1D1D1F` |
| `avatar7` | `#28A745` (grøn) | `#FFFFFF` |
| `avatar8` | `#0E8FA8` (turkis) | `#FFFFFF` |

Statusfarverne må kun farve prikker og ikoner. Status i tekst bruger `textSecondary`.

### Skrift

Applikationen bruger skrifttypen Inter, som ligner Apples San Francisco. Inter følger med applikationen.

| Token | Størrelse | Vægt | Brug |
|---|---|---|---|
| `largeTitle` | 26 px | 700 | Overskrift i indholdsfeltet |
| `title` | 17 px | 600 | Overskrift i ark |
| `headline` | 13 px | 600 | Navne i sidebjælken, overskrifter på kort |
| `body` | 13 px | 400 | Tekst i rækker |
| `caption` | 11 px | 400 | Undertekst og forklaringer |

### Mål og bevægelse

| Token | Værdi |
|---|---|
| `radiusCard` | 10 px |
| `radiusControl` | 6 px |
| `rowHeight` | 44 px |
| `sidebarWidth` | 220 px |
| `spacing` | 4, 8, 12, 16, 24 px |
| `animFast` | 150 ms, `Easing.OutCubic` |
| `animSheet` | 250 ms, `Easing.OutCubic` |
| Standardstørrelse på vinduet | 960 × 620 px |
| Mindste størrelse på vinduet | 820 × 540 px |

### Kontroller

- Primær knap: udfyldt med `accent`, tekst i `onAccent`, højde 28 px.
- Sekundær knap: `cardBg` med en tynd kant i `separator`, tekst i `textPrimary`.
- Knap, der fjerner noget: tekst i `danger`.
- Til/fra-indstillinger, fx "Synkroniser filer i roden", bruger en kontakt som på iOS og macOS.
- Afkrydsningsfelter i mappetræet er 14 px, har afrundede hjørner og fyldes med `accent`.
- Et fokuseret element får en ring på 3 px i `accent` med 50 % gennemsigtighed.

### Ikoner

Applikationen bruger ikonerne fra Lucide som erstatning for SF Symbols. Ikonerne er SVG med en stregbredde på 1,5 px.
Ikonerne tager farve efter teksten ved siden af dem.

## Plan

1. `onedrive_gui/assets/fonts/` — tilføj Inter (Regular, SemiBold og Bold) og filen `OFL.txt`.
2. `onedrive_gui/assets/icons/` — tilføj de Lucide-ikoner, som vinduerne bruger, og filen `LICENSE`.
3. `onedrive_gui/theme.py` — et `QObject` med alle tokens fra afsnittet Designværdier som properties. Modulet vælger lyst eller mørkt ud fra `QGuiApplication.styleHints().colorScheme()` og sender et signal ved `colorSchemeChanged`.
4. `onedrive_gui/theme.py` — funktionen `avatar_color(account)`, der giver hver konto en fast farve ud fra dens `confdir`.
5. `onedrive_gui/app.py` — indlæs skrifterne med `QFontDatabase`, sæt Inter som standardskrift, registrér `Theme` som singleton i QML, og start `QQmlApplicationEngine`.
6. `onedrive_gui/qml/components/` — genbrugelige komponenter: `Card.qml`, `Row.qml`, `PrimaryButton.qml`, `SecondaryButton.qml`, `Toggle.qml`, `CheckBox.qml`, `Avatar.qml`, `StatusDot.qml`, `Sheet.qml`, `Icon.qml`.
7. `onedrive_gui/qml/Main.qml` — vinduet med sidebjælke, indholdsfelt og tom tilstand.
8. `onedrive_gui/qml/AccountPage.qml` — kontoens overskrift og kort med rækkerne "Synkmappe", "Status", "Log ind" og "Vælg mapper".
9. `onedrive_gui/qml/sheets/` — `AddAccountSheet.qml`, `LoginSheet.qml` (med `WebEngineView`), `FolderPickerSheet.qml` og `ConfirmRemovalSheet.qml`.
10. `onedrive_gui/viewmodels.py` — Python-objekter, som QML binder til. De giver QML kontolisten og kalder logikken fra feature 0001 og 0002.

## Tests

Testene kører med `pytest`. Tests, der indlæser QML, bruger `QT_QPA_PLATFORM=offscreen`.

Tema:
- Hvert token i afsnittet Designværdier skal findes i både lyst og mørkt tema.
- Ved `Qt.ColorScheme.Dark` skal `windowBg` være `#1E1E1E`. Ved `Qt.ColorScheme.Light` skal den være `#F5F5F7`.
- Ved `Qt.ColorScheme.Unknown` skal applikationen vælge tema ud fra lysstyrken i systemets `QPalette.Window`.
- Når systemet skifter fra lyst til mørkt, skal `Theme` sende sit signal, og `windowBg` skal skifte uden en genstart.

Kontrast (WCAG 2.1 AA):
- `textPrimary` og `textSecondary` skal have en kontrast på mindst 4,5:1 mod `windowBg`, `sidebarBg` og `cardBg` i begge temaer.
- `onAccent` skal have en kontrast på mindst 4,5:1 mod `accent` i begge temaer.
- `accentText` skal have en kontrast på mindst 4,5:1 mod `windowBg` og `cardBg` i begge temaer.
- `success`, `warning` og `danger` skal have en kontrast på mindst 3:1 mod `cardBg` og `sidebarBg` i begge temaer.
- Avatarens tekstfarve skal have en kontrast på mindst 3:1 mod hver avatarfarve.

Avatar:
- Den samme `confdir` skal altid give den samme avatarfarve, også efter en genstart.
- "Firma 2" skal give initialerne "F2". "Privat" skal give "P". "Søren Ærø" skal give "SÆ".
- Et visningsnavn med kun 1 tegn skal give 1 initial og ikke fejle.

Skrift og filer:
- Efter start skal `QFontDatabase` kende skriftfamilien "Inter".
- Hvert ikon, som QML-filerne henviser til, skal findes i `assets/icons/`.
- Ingen `.qml`-fil i `onedrive_gui/qml/` må indeholde en farvekode af formen `#RRGGBB`.

QML:
- `Main.qml` skal indlæses uden QML-fejl eller -advarsler.
- Uden konti skal `Main.qml` vise teksten "Ingen konti endnu".
- Med 2 konti skal sidebjælken vise 2 rækker.
- Vinduet må ikke kunne blive mindre end 820 × 540 px.

**Eksisterende tests, der ændrer sig:** Feature 0001 og 0002 er ikke bygget endnu. Deres logiktests ændrer sig ikke. Deres planer henviser allerede til QML-filerne i denne feature.

## Verifikation

Afhængighederne skal være installeret:

```bash
sudo apt install python3-pyside6.qtwebenginequick python3-pyside6.qtsvg
```

Testene skal bestå:

```bash
python3 -m pytest
```

Manuel afprøvning:

1. Start applikationen med KDE i mørkt tema. Vinduet skal være mørkt.
2. Skift KDE til lyst tema i Systemindstillinger. Vinduet skal skifte til lyst uden en genstart.
3. Sidebjælken skal vise begge konti med avatar, navn og en statusprik, der svarer til servicens tilstand.
4. Klik "Tilføj konto". Arket skal glide ned fra toppen, og resten af vinduet skal blive dæmpet.
5. Tryk Tab flere gange. Hvert fokuseret element skal have en synlig fokusring.
6. Gør vinduet så lille som muligt. Ingen tekst må blive skåret over eller overlappe.
7. Sammenlign vinduet med "Systemindstillinger" på macOS. Opdelingen, kortene og rækkerne skal ligne.

## Åbne spørgsmål
