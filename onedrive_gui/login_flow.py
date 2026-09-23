"""Forløbet fra login til en kørende service for én konto.

``LoginFlow`` binder ``auth.AuthSession`` sammen med ``service``. Login og
service er 2 trin: ``poll()`` fører login frem til ``LOGGED_IN``, og
``activate_service()`` opretter eller genstarter servicen bagefter. Så kan
brugerfladen indsætte et trin imellem og køre ``systemctl`` i en tråd.

Har kontoen allerede en ``refresh_token``, logger flowet ind igen med
``--reauth`` (feature 0005). Kører servicen, stopper flowet den før login og
starter den igen bagefter, også når login fejler eller bliver afbrudt.
``start()`` kan vente på ``systemctl stop``. Brugerfladen kører den i en tråd.
"""

from __future__ import annotations

import logging
import subprocess
from enum import Enum
from pathlib import Path
from typing import Callable

from . import service as service_mod
from . import service_control
from .auth import AuthSession, AuthState
from .process import PROC_ROOT, find_processes
from .registry import Registry
from .service_state import read_units

log = logging.getLogger(__name__)


class FlowState(Enum):
    STARTING = "starting"
    WAITING_FOR_USER = "waiting_for_user"
    WAITING_FOR_TOKEN = "waiting_for_token"
    LOGGED_IN = "logged_in"
    """Kontoen er logget ind. Servicen er endnu ikke oprettet eller genstartet."""
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


_FROM_AUTH = {
    AuthState.STARTING: FlowState.STARTING,
    AuthState.WAITING_FOR_USER: FlowState.WAITING_FOR_USER,
    AuthState.WAITING_FOR_TOKEN: FlowState.WAITING_FOR_TOKEN,
    AuthState.SUCCEEDED: FlowState.LOGGED_IN,
    AuthState.FAILED: FlowState.FAILED,
    AuthState.CANCELLED: FlowState.CANCELLED,
}

ACTIVE_STATES = frozenset({"active", "activating", "reloading", "refreshing"})
"""Værdierne af ``ActiveState``, hvor servicen kører eller er ved at starte."""


class LoginFlow:
    def __init__(self, confdir: Path, name: str, service: str, *,
                 registry: Registry, home: Path | None = None,
                 popen: Callable[..., subprocess.Popen] | None = None,
                 run: Callable[..., subprocess.CompletedProcess] | None = None,
                 clock: Callable[[], float] | None = None,
                 tmp_base: Path | None = None, proc_root: Path = PROC_ROOT):
        self.confdir = Path(confdir)
        self.name = name
        self.service = service
        """Kontoens eksisterende service, eller tom for en ny konto."""
        self.registry = registry
        self.home = home
        self._run = run
        self._proc_root = Path(proc_root)
        self.reauth = (self.confdir / "refresh_token").exists()
        """Kontoen har en ``refresh_token``. Login bruger ``--reauth``."""
        self.auth = AuthSession(self.confdir, reauth=self.reauth, popen=popen, clock=clock,
                                tmp_base=tmp_base)
        self.state = FlowState.STARTING
        self.service_error = ""
        self.service_stopped = False
        """Flowet har stoppet servicen og har endnu ikke startet den igen."""
        self.service_was_active = False
        """Servicen kørte, da brugeren klikkede "Log ind"."""
        self._error = ""

    @property
    def auth_url(self) -> str:
        return self.auth.auth_url

    @property
    def error(self) -> str:
        return self._error or self.auth.error

    @property
    def needs_restart(self) -> bool:
        """Login fejlede eller blev afbrudt, og servicen skal startes igen."""
        return self.service_stopped and self.state in (FlowState.FAILED, FlowState.CANCELLED)

    def start(self) -> None:
        if self.reauth and not self._prepare_reauth():
            self.state = FlowState.FAILED
            return
        self.auth.start()
        self.poll()

    def _prepare_reauth(self) -> bool:
        """Afvis fremmede processer, og stop servicen, hvis den kører."""
        others = [p for p in find_processes(self.confdir, home=self.home, proc_root=self._proc_root)
                  if not self.service or p.unit != self.service]
        if others:
            lines = [f"PID {p.pid}: {' '.join(p.args)}" for p in others]
            self._error = "\n".join(["En anden onedrive-proces bruger kontoen. Stop den først.", *lines])
            log.warning("Login for %s: %s", self.confdir, self._error)
            return False
        if not self.service:
            return True
        try:
            unit = read_units([self.service], run=self._run).get(self.service)
            if unit is not None and unit.active_state in ACTIVE_STATES:
                self.service_was_active = True
                service_control.stop(self.service, run=self._run)
                self.service_stopped = True
        except service_mod.SystemctlError as exc:
            log.warning("Kan ikke stoppe %s før login: %s", self.service, exc)
            self._error = f"Servicen {self.service} kunne ikke stoppes før login:\n{exc}"
            return False
        return True

    def restore_service(self) -> None:
        """Start servicen igen, hvis flowet stoppede den. En fejl står i ``service_error``."""
        if not self.service_stopped:
            return
        self.service_stopped = False
        try:
            service_control.reset_and_restart(self.service, run=self._run)
        except service_mod.SystemctlError as exc:
            log.warning("Service for %s: %s", self.confdir, exc)
            self.service_error = str(exc)

    def poll(self) -> FlowState:
        if self.state in (FlowState.STARTING, FlowState.WAITING_FOR_USER, FlowState.WAITING_FOR_TOKEN):
            self.state = _FROM_AUTH[self.auth.poll()]
        return self.state

    def submit_redirect(self, url: str) -> bool:
        handled = self.auth.submit_redirect(url)
        self.poll()
        return handled

    def cancel(self) -> None:
        self.auth.cancel()
        self.poll()

    def activate_service(self) -> None:
        """Opret og start servicen, eller genstart den eksisterende.

        Gør intet, hvis kontoen ikke er logget ind. En fejl fra ``systemctl``
        står i ``service_error``. Kontoen er stadig logget ind. Ved ``reauth``
        starter flowet kun servicen igen, hvis den kørte før login.
        """
        if self.state is not FlowState.LOGGED_IN:
            return
        if self.reauth:
            self.restore_service()
            self.state = FlowState.DONE
            return
        try:
            if self.service:
                service_mod.restart(self.service, run=self._run)
            else:
                self.service = service_mod.write_unit(self.confdir, self.name, self.home)
                self.registry.set_service(self.confdir, self.service)
                service_mod.enable_now(self.service, run=self._run)
        except (service_mod.SystemctlError, OSError) as exc:
            log.warning("Service for %s: %s", self.confdir, exc)
            self.service_error = str(exc)
        self.state = FlowState.DONE
