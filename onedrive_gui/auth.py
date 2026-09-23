"""Login med ``onedrive --auth-files``.

Klienten skriver login-URL'en i ``auth.url`` og venter på ``response.url``.
Login-vinduet fanger Microsofts videresendelse til ``nativeclient``, og
applikationen skriver den i ``response.url``. Klienten gemmer derefter
``refresh_token`` i kontoens config-mappe.

Med ``reauth`` får klienten også ``--reauth``. Klienten sletter så den gamle
``refresh_token`` og beder om et nyt login (feature 0005). Applikationen tager
først en kopi af ``refresh_token`` i arbejdsmappen. Fejler login, eller
afbryder brugeren det, lægger applikationen kopien tilbage.

Klassen starter ikke tråde. Den, der bruger den, kalder ``poll()`` jævnligt,
fx fra en ``QTimer``.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from . import sideeffects
from .accounts import ONEDRIVE

log = logging.getLogger(__name__)

NATIVE_CLIENT_URL = "https://login.microsoftonline.com/common/oauth2/nativeclient"
EXIT_GRACE_SECONDS = 30.0
"""Så længe må klienten køre videre, efter at ``refresh_token`` findes."""
STOP_TIMEOUT_SECONDS = 5.0


class AuthState(Enum):
    STARTING = "starting"
    """Klienten kører, men har endnu ikke skrevet ``auth.url``."""
    WAITING_FOR_USER = "waiting_for_user"
    """Login-vinduet viser Microsofts login-side."""
    WAITING_FOR_TOKEN = "waiting_for_token"
    """``response.url`` er skrevet. Klienten henter ``refresh_token``."""
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED = {AuthState.SUCCEEDED, AuthState.FAILED, AuthState.CANCELLED}


@dataclass(frozen=True)
class Redirect:
    url: str
    code: str
    error: str
    error_description: str


def parse_redirect(url: str) -> Redirect | None:
    """Tolk en URL fra login-vinduet. Er det ikke ``nativeclient``, gives ``None``."""
    parts = urlsplit(url)
    base = f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path}"
    if base != NATIVE_CLIENT_URL:
        return None
    query = parse_qs(parts.query)

    def first(key: str) -> str:
        return query.get(key, [""])[0]

    return Redirect(url=url, code=first("code"), error=first("error"),
                    error_description=first("error_description"))


class AuthSession:
    def __init__(self, confdir: Path, *, reauth: bool = False, onedrive: str = ONEDRIVE,
                 popen: Callable[..., subprocess.Popen] | None = None,
                 clock: Callable[[], float] | None = None,
                 tmp_base: Path | None = None,
                 exit_grace: float = EXIT_GRACE_SECONDS,
                 send_signal: Callable[[object, int], None] | None = None):
        self.confdir = Path(confdir)
        self.reauth = reauth
        self.onedrive = onedrive
        self._popen = popen
        self._send_signal = send_signal or sideeffects.signal_process
        self._clock = clock or time.monotonic
        self._tmp_base = tmp_base
        self._exit_grace = exit_grace
        self._process = None
        self._log_file = None
        self._workdir: Path | None = None
        self._initial_token: bytes | None = None
        self._backup: Path | None = None
        self._token_seen_at: float | None = None
        self.state = AuthState.STARTING
        self.auth_url = ""
        self.error = ""

    @property
    def token_path(self) -> Path:
        return self.confdir / "refresh_token"

    def start(self) -> None:
        self._workdir = Path(tempfile.mkdtemp(prefix="onedrive-gui-auth-", dir=self._tmp_base))
        self._auth_path = self._workdir / "auth.url"
        self._response_path = self._workdir / "response.url"
        self._initial_token = self._read_token()
        log_path = self._workdir / "onedrive.log"
        if sideeffects.guard_write(log_path):
            self._log_file = open(log_path, "w+b")
        args = [self.onedrive, f"--confdir={self.confdir}"]
        if self.reauth:
            try:
                self._backup_token()
            except OSError as exc:
                self._fail(f"Kan ikke tage en kopi af refresh_token: {exc}")
                return
            args.append("--reauth")
        args += ["--auth-files", f"{self._auth_path}:{self._response_path}"]
        popen = self._popen or sideeffects.popen
        log.info("Starter %s", " ".join(args))
        try:
            self._process = popen(args, stdin=subprocess.DEVNULL, stdout=self._log_file or subprocess.DEVNULL,
                                  stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            self._fail(f"Kan ikke starte {self.onedrive}: {exc}")

    def poll(self) -> AuthState:
        if self.state in FINISHED:
            return self.state
        code = self._process.poll()

        if self._token_ready():
            if self._token_seen_at is None:
                self._token_seen_at = self._clock()
            if code is None and self._clock() - self._token_seen_at >= self._exit_grace:
                log.info("onedrive afsluttede ikke selv efter login. Stopper processen.")
                self._stop_process()
                code = self._process.poll()
            if code is not None:
                self.state = AuthState.SUCCEEDED
                self._finish()
            return self.state

        if code is not None:
            tail = self._log_tail()
            if code != 0:
                message = f"onedrive stoppede med exit-kode {code}."
            elif self._initial_token and not self.auth_url:
                message = ("onedrive bad ikke om et nyt login. "
                           "Kontoen har allerede en refresh_token.")
            else:
                message = "onedrive stoppede, uden at kontoen blev logget ind."
            self._fail(f"{message} {tail}".strip())
            return self.state

        if self.state is AuthState.STARTING:
            url = self._read_auth_url()
            if url:
                self.auth_url = url
                self.state = AuthState.WAITING_FOR_USER
        return self.state

    def submit_redirect(self, url: str) -> bool:
        """Giv klienten URL'en fra login-vinduet.

        Returnerer ``True``, når URL'en er ``nativeclient`` og derfor afslutter
        login-siden. Andre URL'er ændrer intet.
        """
        if self.state is not AuthState.WAITING_FOR_USER:
            return False
        redirect = parse_redirect(url)
        if redirect is None:
            return False
        if redirect.error or not redirect.code:
            reason = redirect.error_description or redirect.error or "svaret indeholdt ingen kode"
            self._stop_process()
            self._fail(f"Microsoft afviste login: {reason}")
            return True
        if sideeffects.guard_write(self._response_path):
            tmp = self._response_path.with_name("response.url.tmp")
            tmp.write_text(url, encoding="utf-8")
            os.replace(tmp, self._response_path)
        self.state = AuthState.WAITING_FOR_TOKEN
        return True

    def cancel(self) -> None:
        if self.state in FINISHED:
            return
        self._stop_process()
        self.state = AuthState.CANCELLED
        self._finish()

    def close(self) -> None:
        """Stop processen, hvis den kører, og fjern de midlertidige filer."""
        if self.state not in FINISHED and self._process is not None:
            self.cancel()
        self._finish()

    # Hjælpefunktioner

    def _read_token(self) -> bytes | None:
        try:
            return self.token_path.read_bytes()
        except OSError:
            return None

    def _backup_token(self) -> None:
        """Kopiér ``refresh_token`` til arbejdsmappen med de samme filrettigheder."""
        if self._initial_token is None:
            return
        backup = self._workdir / "refresh_token"
        if sideeffects.guard_write(backup):
            shutil.copy2(self.token_path, backup)
            self._backup = backup

    def _restore_token(self) -> None:
        """Læg kopien af ``refresh_token`` tilbage i config-mappen."""
        backup = self._backup
        self._backup = None
        if backup is None or not sideeffects.guard_write(self.token_path):
            return
        tmp = self.token_path.with_name("refresh_token.onedrive-gui.tmp")
        try:
            data = backup.read_bytes()
            mode = backup.stat().st_mode & 0o777
            # Filen får aldrig bredere rettigheder end 0600, heller ikke et øjeblik.
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), 0o600)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, self.token_path)
            log.info("Lagde den oprindelige refresh_token tilbage i %s", self.confdir)
        except OSError as exc:
            log.error("Kan ikke lægge refresh_token tilbage i %s: %s", self.confdir, exc)
            self.error = (f"{self.error} Den oprindelige refresh_token kunne ikke lægges tilbage: {exc}"
                          ).strip()

    def _token_ready(self) -> bool:
        token = self._read_token()
        return bool(token) and token != self._initial_token

    def _read_auth_url(self) -> str:
        try:
            text = self._auth_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return text if text.startswith("https://") else ""

    def _log_tail(self) -> str:
        if self._log_file is None:
            return ""
        try:
            self._log_file.flush()
            self._log_file.seek(0)
            lines = self._log_file.read().decode("utf-8", "replace").splitlines()
        except (OSError, ValueError):
            return ""
        lines = [line.strip() for line in lines if line.strip()]
        return lines[-1][:300] if lines else ""

    def _stop_process(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        self._send_signal(process, signal.SIGTERM)
        try:
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self._send_signal(process, signal.SIGKILL)
            process.wait()

    def _fail(self, message: str) -> None:
        log.warning("Login fejlede for %s: %s", self.confdir, message)
        self.error = message
        self.state = AuthState.FAILED
        self._finish()

    def _finish(self) -> None:
        if self.state in (AuthState.FAILED, AuthState.CANCELLED):
            self._restore_token()
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        if self._workdir is not None:
            if sideeffects.guard_write(self._workdir):
                shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None
