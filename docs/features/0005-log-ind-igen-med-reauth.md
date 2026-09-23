# Log ind igen på en eksisterende konto

Version: 0.5.1
Status: udviklet
Oprettet: 2026-09-23

## Problem

Feature 0001 lader brugeren logge en eksisterende konto ind igen med knappen "Log ind".
Har kontoen allerede en `refresh_token`, beder klienten ikke om et nyt login. Applikationen viser så fejlen "onedrive bad ikke om et nyt login".
Applikationen stopper heller ikke kontoens service før login. Så kan 2 `onedrive`-processer bruge den samme config-mappe på samme tid.

Reproduktion:
1. Vælg en konto, der kører og har `refresh_token`.
2. Klik "Log ind".
3. Applikationen viser en fejl, og servicen kører videre under forsøget.

## Løsning

"Log ind" på en eksisterende konto gør dette:
1. Applikationen stopper kontoens service, hvis den kører.
2. Applikationen tager en kopi af `refresh_token`.
3. Applikationen starter klienten med `--reauth` og `--auth-files`. Klienten sletter den gamle `refresh_token` og beder om et nyt login.
4. Brugeren logger ind i login-arket som i feature 0001.
5. Efter login starter applikationen servicen igen, hvis den kørte før.

Afbryder brugeren login, eller fejler login, lægger applikationen kopien af `refresh_token` tilbage.
Applikationen starter derefter servicen igen, hvis den kørte før. Kontoen er så i samme tilstand som før klikket.

Kører en `onedrive`-proces uden for servicen for kontoen, viser applikationen en fejl og starter ikke login.

## Afgrænsning

- Featuren ændrer ikke login for en ny konto. En ny konto har ingen `refresh_token` og bruger ikke `--reauth`.
- Applikationen har ikke en knap til at logge ud.
- Applikationen viser ikke mappevælgeren efter et nyt login på en eksisterende konto. Kontoens `sync_list` er uændret.
- Applikationen tjekker ikke, om brugeren logger ind med den samme Microsoft-konto som før.
- Applikationen stopper ikke en `onedrive`-proces, der kører uden for servicen.

## Plan

1. `onedrive_gui/auth.py` — `AuthSession` får parameteren `reauth`. Er den sand, tilføjer applikationen `--reauth` til kommandoen.
2. `onedrive_gui/auth.py` — ved `reauth` kopierer applikationen `refresh_token` til arbejdsmappen, før klienten starter. Ved `FAILED` eller `CANCELLED` lægger applikationen kopien tilbage med de samme filrettigheder (`0600`).
3. `onedrive_gui/login_flow.py` — for en eksisterende konto med `refresh_token` bruger flowet `reauth`. Flowet gemmer, om servicen var aktiv, og stopper den med `systemctl --user stop <service>`, før login starter.
4. `onedrive_gui/login_flow.py` — flowet bruger `process.py` fra feature 0002 og afviser login, når en anden `onedrive`-proces bruger config-mappen.
5. `onedrive_gui/login_flow.py` — efter `LOGGED_IN`, `FAILED` eller `CANCELLED` starter flowet servicen igen med `reset-failed` og `restart` fra `service_control.py`, hvis den var aktiv før. En fejl fra `systemctl` står i `service_error`.
6. `onedrive_gui/viewmodels.py` og login-arket — vis teksten "Servicen er stoppet, mens du logger ind", når flowet har stoppet servicen.

## Tests

- Ved "Log ind" på en konto med `refresh_token` skal kommandoen indeholde `--reauth` og `--auth-files`.
- Ved "Log ind" på en konto uden `refresh_token` må kommandoen ikke indeholde `--reauth`.
- Ved en aktiv service skal applikationen kalde `systemctl --user stop` før klienten starter.
- Efter et vellykket login skal applikationen starte servicen igen, og den nye `refresh_token` skal ligge i config-mappen.
- Ved en service, der var stoppet før klikket, skal applikationen ikke starte den efter login.
- Når brugeren afbryder login, skal `refresh_token` være identisk med den oprindelige, byte for byte, og have rettighederne `0600`.
- Når klienten stopper med en exit-kode forskellig fra 0, skal applikationen lægge den oprindelige `refresh_token` tilbage og starte servicen igen, hvis den var aktiv.
- Når en `onedrive`-proces uden for servicen bruger config-mappen, skal applikationen vise en fejl, ikke stoppe servicen og ikke starte klienten.
- Når `systemctl --user stop` fejler, skal applikationen vise fejlen og ikke starte klienten.
- Når genstarten efter login fejler, skal applikationen vise fejlen, og kontoen skal stadig stå som logget ind.

**Eksisterende tests, der ændrer sig:** Testene i `tests/test_auth.py` og `tests/test_login_flow.py`, der forventer fejlen "onedrive bad ikke om et nyt login" for en konto med `refresh_token`, skal i stedet forvente et login med `--reauth`. Fejlen kan stadig opstå, hvis klienten med `--reauth` alligevel ikke skriver `auth.url`.

## Verifikation

```bash
python3 -m pytest
```

Manuel afprøvning med en testkonto, ikke firma- eller privatkontoen:

1. Klik "Log ind" på testkontoen, mens servicen kører. `systemctl --user status <service>` skal vise `inactive`.
2. Luk login-arket uden at logge ind. `refresh_token` skal være uændret, og servicen skal køre igen.
3. Klik "Log ind" igen, og log ind. `refresh_token` skal være ny, og servicen skal køre.

## Åbne spørgsmål

- Klienten spørger måske om en bekræftelse ved `--reauth`. Implementeringen skal afprøve det med en midlertidig config-mappe uden `refresh_token`. Spørger klienten, skal applikationen svare via stdin eller bruge en anden fremgangsmåde.
  - Svar (2026-09-23, onedrive v2.5.11): Klienten spørger ikke om en bekræftelse. Jeg afprøvede `onedrive --confdir=<tmp> --reauth --auth-files a:b` med `stdin` fra `/dev/null`. Klienten skrev "Deleting the saved authentication status ... re-authentication requested" og skrev derefter `auth.url`. Med en falsk `refresh_token` slettede klienten filen, før den skrev `auth.url`.
