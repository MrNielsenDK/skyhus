# Sikker tilstand: markering ved afbrudt resync og signaler i login

Version: 0.7.1
Status: udviklet
Oprettet: 2026-09-23

## Problem

Sikker tilstand (feature 0007) har 2 huller efter feature 0010.

1. **Markering uden stop.** "Afbryd resync" kalder `service_control.cancel_resync()`. I sikker tilstand blokerer applikationen `systemctl --user stop`, men funktionen skriver alligevel markeringen i `~/.config/onedrive-gui/state.json`. Servicen kører videre med sin resync. Kortet viser derefter "Resync afbrudt", også når applikationen senere kører uden sikker tilstand. Markeringen forsvinder først, når servicen får en ny kørsel.
2. **Signaler uden om `sideeffects`.** `AuthSession._stop_process()` i `onedrive_gui/auth.py` kalder `process.terminate()` og `process.kill()` direkte. AST-testen for signaler i `tests/test_sideeffects.py` fanger det ikke. Testen `test_no_module_sends_signals_directly` ser kun efter `send_signal` og bestemte navne. Testen `test_apply_does_not_terminate_or_kill_directly` ser kun på `apply.py`.

Reproduktion af fejl 1:
1. Start `python3 -m onedrive_gui.app --safe`, mens en konto kører en resync.
2. Klik "Afbryd resync", og bekræft.
3. Loggen viser `SAFE MODE: systemctl --user stop …`, men `state.json` indeholder en markering for servicen.
4. Start applikationen uden `--safe`. Kortet viser "Resync afbrudt", selvom servicen stadig kører sin resync.

## Løsning

1. I sikker tilstand skriver "Afbryd resync" ikke markeringen, når applikationen selv har blokeret stoppet. Kortet bliver ved med at vise "Resynkroniserer". Loggen får linjen `SAFE MODE: skriver ikke markeringen for <service>`.
2. `AuthSession` stopper login-processen med `sideeffects.signal_process`. Ingen modul uden for `sideeffects.py` må sende signaler direkte. En AST-test dækker alle moduler.

## Afgrænsning

- Featuren ændrer ikke, hvad "Afbryd resync" gør uden sikker tilstand.
- Featuren fjerner ikke markeringer, der allerede ligger i `state.json`. Mappen `~/.config/onedrive-gui/` findes ikke på maskinen i dag.
- Featuren ændrer ikke tidsgrænsen for stop af login-processen (`STOP_TIMEOUT_SECONDS`).
- Featuren ændrer ikke andre regler i sikker tilstand.

## Plan

1. `onedrive_gui/service_control.py` — `cancel_resync()` skriver kun markeringen, når stoppet faktisk nåede `systemctl`. Det gælder, når sikker tilstand er slået fra, eller når kalderen har givet sin egen `run`. Ellers logger funktionen `SAFE MODE: skriver ikke markeringen for <service>`.
2. `onedrive_gui/auth.py` — `AuthSession` får parameteren `send_signal`, som standard `sideeffects.signal_process`. `_stop_process()` sender `SIGTERM`, venter `STOP_TIMEOUT_SECONDS` og sender derefter `SIGKILL` via `send_signal`. En injiceret `send_signal` går foran sikker tilstand, som `run` og `popen` gør.
3. `onedrive_gui/login_flow.py` og `onedrive_gui/viewmodels.py` — send `send_signal` videre til `AuthSession`, så testene kan give deres egen.
4. `tests/test_sideeffects.py` — erstat `test_apply_does_not_terminate_or_kill_directly` med en test, der gennemgår alle moduler undtagen `sideeffects.py`. Testen må ikke finde kald til `.terminate()`, `.kill()`, `.send_signal()`, `os.kill()` eller `os.killpg()`.

## Tests

Markering:
- I sikker tilstand uden en injiceret `run` må `cancel_resync()` ikke skrive `state.json`, og loggen skal have `SAFE MODE: skriver ikke markeringen`.
- I sikker tilstand med en injiceret `run` skal `cancel_resync()` stadig kalde `stop` på den injicerede `run` og skrive markeringen.
- Uden sikker tilstand skal `cancel_resync()` skrive markeringen efter et vellykket stop, som i feature 0010.
- I sikker tilstand skal kortet efter "Afbryd resync" stadig vise "Resynkroniserer" og ikke "Resync afbrudt".

Signaler i login:
- Når brugeren annullerer login, skal login-processen få `SIGTERM` via `send_signal`.
- Når processen ikke stopper inden `STOP_TIMEOUT_SECONDS`, skal den få `SIGKILL` via `send_signal`.
- I sikker tilstand uden en injiceret `send_signal` må applikationen ikke sende et signal, og loggen skal have `SAFE MODE: sender ikke SIGTERM`.
- En proces, der allerede er stoppet, må ikke få et signal.

Kildekode:
- Ingen modul i `onedrive_gui/` uden for `sideeffects.py` må kalde `.terminate()`, `.kill()`, `.send_signal()`, `os.kill()` eller `os.killpg()`.

**Eksisterende tests, der ændrer sig:** Tests i `tests/test_auth.py` og `tests/test_login_flow.py`, der forventer, at en falsk proces får `terminate()` eller `kill()`, skal nu give en falsk `send_signal` og forvente `SIGTERM` eller `SIGKILL`. Testen `test_apply_does_not_terminate_or_kill_directly` forsvinder, fordi den nye test dækker alle moduler.

## Verifikation

```bash
python3 -m pytest
```

Manuel afprøvning med `--safe` og en falsk `HOME`:

1. Kør `HOME=$(mktemp -d) python3 -m onedrive_gui.app` med en konto, hvis status er "Resynkroniserer".
2. Klik "Afbryd resync", og bekræft. Loggen skal vise `SAFE MODE: skriver ikke markeringen`.
3. `state.json` i den falske `HOME` må ikke indeholde en markering.

## Åbne spørgsmål
