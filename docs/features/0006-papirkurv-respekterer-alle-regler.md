# Papirkurven respekterer alle regler

Version: 0.5.2
Status: udviklet
Oprettet: 2026-09-23

## Problem

Feature 0002 finder de lokale stier, der skal i papirkurven, når brugeren fravælger en mappe.
Funktionen `find_removed` i `onedrive_gui/removal.py` ser kun på de regler, som mappevælgeren styrer.
Den ser ikke på de ukendte regler i `sync_list` eller på `skip_file` og `skip_dotfiles` i `config`.
Derfor kan applikationen lægge lokale filer i papirkurven, som klienten aldrig har synkroniseret. De filer findes kun på computeren.
Applikationen kan også lægge en mappe i papirkurven, som en ukendt regel stadig inkluderer.

Reproduktion 1:
1. `sync_list` indeholder `!/Arbejde/Hemmelig/*` og `/Arbejde/`.
2. Brugeren fravælger `Arbejde`.
3. Bekræftelsen viser hele `Arbejde`, også `Arbejde/Hemmelig`, som kun findes lokalt.

Reproduktion 2:
1. `sync_list` indeholder `Documents/` og `/Arbejde/`.
2. Brugeren fravælger `Arbejde`.
3. Bekræftelsen viser `Arbejde/Documents`, selvom reglen `Documents/` stadig inkluderer den.

Reproduktion 3:
1. `~/OneDrive-X/Arbejde/noter.tmp` findes lokalt. `skip_file` udelukker `*.tmp` som standard.
2. Brugeren fravælger `Arbejde`.
3. Bekræftelsen viser hele `Arbejde`, også `noter.tmp`.

## Løsning

Applikationen lægger kun en lokal sti i papirkurven, når begge betingelser gælder:
- Klienten synkroniserede stien med de gamle regler.
- Klienten synkroniserer ikke stien med de nye regler.

"Regler" betyder her alle regler: mappevælgerens regler, de ukendte regler i `sync_list`, `skip_dir`, `skip_file`, `skip_dotfiles` og `sync_root_files`.

Indeholder en mappe mindst 1 sti, som ikke skal i papirkurven, lægger applikationen ikke hele mappen i papirkurven.
Applikationen går så ned i mappen og lægger kun de stier i papirkurven, der opfylder begge betingelser.
Mappen og de stier, der skal blive, bliver liggende.

Kan applikationen ikke tolke en ukendt regel, viser den reglen og ændrer ikke noget.

## Afgrænsning

- Featuren ændrer ikke, hvordan mappevælgeren skriver `sync_list`.
- Featuren ændrer ikke, hvilke stier klienten synkroniserer.
- Applikationen tolker ikke `skip_symlinks`, `skip_size` eller `check_nosync`. Symlinks og filer med `.nosync` lægger applikationen aldrig i papirkurven.
- Applikationen tolker ikke regler, som klientens dokumentation ikke beskriver.
- Featuren viser ikke i bekræftelsen, hvilke stier der bliver liggende.

## Plan

1. `onedrive_gui/rules.py` (ny) — klassen `RuleSet`, der svarer på `includes(rel, is_dir)`. Den samler mappevælgerens regler, de ukendte regler og felterne fra `config`.
2. `onedrive_gui/rules.py` — tolk reglerne i `sync_list` efter klientens dokumentation i `/usr/share/doc/onedrive/usage.md.gz`. En regel med `!` foran udelukker. En regel med `/` foran gælder kun fra roden. En regel uden `/` foran gælder overalt. En regel med `/` bagerst gælder kun mapper. `*` gælder inden for ét led, og `**` gælder over flere led. Udelukkelse vinder over inkludering.
3. `onedrive_gui/rules.py` — en regel, som punkt 2 ikke dækker, giver `UnknownRuleError` med reglens tekst.
4. `onedrive_gui/config.py` — læs `skip_file` (standard `~*|.~*|*.tmp|*.swp|*.partial`) og `skip_dotfiles` (standard `false`).
5. `onedrive_gui/removal.py` — `find_removed` bruger 2 `RuleSet`, ét for de gamle og ét for de nye regler. En mappe kommer kun på listen, hvis ingen sti i den skal blive. Ellers går funktionen ned i mappen.
6. `onedrive_gui/removal.py` — symlinks og mapper med filen `.nosync` kommer aldrig på listen.
7. `onedrive_gui/apply.py` — `prepare()` viser fejlen fra `UnknownRuleError` og stopper, før applikationen ændrer noget.

## Tests

- Ved `!/Arbejde/Hemmelig/*` og `/Arbejde/`, og brugeren fravælger `Arbejde`, må `Arbejde/Hemmelig` ikke komme på listen. De andre stier i `Arbejde` skal på listen.
- I samme tilfælde må mappen `Arbejde` ikke selv komme på listen.
- Ved `Documents/` og `/Arbejde/`, og brugeren fravælger `Arbejde`, må `Arbejde/Documents` ikke komme på listen.
- Ved en lokal fil `Arbejde/noter.tmp` og standardværdien for `skip_file` må `noter.tmp` ikke komme på listen.
- Ved `skip_dotfiles = "true"` og en lokal fil `Arbejde/.env` må `.env` ikke komme på listen.
- Ved `skip_dotfiles = "false"` skal `Arbejde/.env` på listen, når brugeren fravælger `Arbejde`.
- Ved en fravalgt mappe uden udelukkede stier skal kun mappen selv stå på listen og ikke dens indhold.
- Ved en symlink i en fravalgt mappe må symlinket ikke komme på listen.
- Ved en fravalgt mappe med filen `.nosync` må mappen ikke komme på listen.
- Ved `!**/node_modules/*` og en fravalgt mappe med `node_modules` på 3. niveau må `node_modules` ikke komme på listen.
- Ved en regel, som applikationen ikke kan tolke, skal `prepare()` vise reglen og ikke ændre `sync_list`, servicen eller filerne.
- Ved en ændring fra "alle mapper" til `/A/` skal resultatet være det samme som i feature 0002, når `config` ikke har `skip_file`.

**Eksisterende tests, der ændrer sig:** Testene i `tests/test_removal.py` fra feature 0002, der forventer hele `B` på listen, gælder stadig, når `B` ikke indeholder udelukkede stier. Tests, der bruger en fil med `.tmp` eller et navn med `~`, skal forvente, at filen bliver liggende.

## Verifikation

```bash
python3 -m pytest
```

Manuel afprøvning med en testkonto:

1. Skriv `!/Test/Lokal/*` øverst i testkontoens `sync_list`, og opret `~/OneDrive-Test/Test/Lokal/fil.txt`.
2. Fravælg `Test` i mappevælgeren. Bekræftelsen må ikke vise `Test/Lokal`.
3. Klik OK. `~/OneDrive-Test/Test/Lokal/fil.txt` skal stadig findes.

## Åbne spørgsmål

- Klientens egen tolkning af `sync_list` har flere særtilfælde, end dokumentationen beskriver. Implementeringen skal sammenligne med `clientSideFiltering.d` i klientens kildekode, hvis den er tilgængelig.
