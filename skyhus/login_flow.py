"""The flow from sign-in to a running service for one account.

``LoginFlow`` connects ``auth.AuthSession`` with ``service``. Sign-in and
service are 2 steps: ``poll()`` moves the sign-in to ``LOGGED_IN``, and
``activate_service()`` creates or restarts the service after that. Then
the user interface can add a step between them and run ``systemctl`` in a thread.

If the account already has a ``refresh_token``, the flow signs in again with
``--reauth`` (feature 0005). If the service runs, the flow stops it before the sign-in
and starts it again after, also when the sign-in fails or is cancelled.
``start()`` can wait for ``systemctl stop``. The user interface runs it in a thread.
``cancel()`` also works while the service stops (feature 0008). Then
the flow does not start the client when the stop is done.
"""

from __future__ import annotations

import logging
import subprocess
import threading
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
    """The account is signed in. The service is not created or restarted yet."""
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
"""The values of ``ActiveState`` where the service runs or is starting."""


class LoginFlow:
    def __init__(self, confdir: Path, name: str, service: str, *,
                 registry: Registry, home: Path | None = None,
                 popen: Callable[..., subprocess.Popen] | None = None,
                 run: Callable[..., subprocess.CompletedProcess] | None = None,
                 clock: Callable[[], float] | None = None,
                 tmp_base: Path | None = None, proc_root: Path = PROC_ROOT,
                 send_signal: Callable[[object, int], None] | None = None):
        self.confdir = Path(confdir)
        self.name = name
        self.service = service
        """The existing service of the account, or empty for a new account."""
        self.registry = registry
        self.home = home
        self._run = run
        self._proc_root = Path(proc_root)
        self.reauth = (self.confdir / "refresh_token").exists()
        """The account has a ``refresh_token``. The sign-in uses ``--reauth``."""
        self.auth = AuthSession(self.confdir, reauth=self.reauth, popen=popen, clock=clock,
                                tmp_base=tmp_base, send_signal=send_signal)
        self.state = FlowState.STARTING
        self.service_error = ""
        self.service_stopped = False
        """The flow stopped the service and has not started it again yet."""
        self.service_was_active = False
        """The service ran when the user clicked "Sign in"."""
        self.cancel_requested = False
        """The user clicked "Cancel". The flow does not start the client after the stop."""
        self._error = ""
        # cancel() can come from the main thread while start() runs in a different thread.
        self._lock = threading.Lock()
        self._auth_started = False

    @property
    def auth_url(self) -> str:
        return self.auth.auth_url

    @property
    def error(self) -> str:
        return self._error or self.auth.error

    @property
    def needs_restart(self) -> bool:
        """The sign-in failed or was cancelled, and the service must start again."""
        return self.service_stopped and self.state in (FlowState.FAILED, FlowState.CANCELLED)

    def start(self) -> None:
        if self.reauth and not self._prepare_reauth():
            self.state = FlowState.FAILED
            return
        with self._lock:
            if self.cancel_requested:
                log.info("Sign-in for %s was cancelled before the client started", self.confdir)
                self.state = FlowState.CANCELLED
                return
            self._auth_started = True
            self.auth.start()
            self.poll()

    def _prepare_reauth(self) -> bool:
        """Refuse other processes, and stop the service if it runs."""
        others = [p for p in find_processes(self.confdir, home=self.home, proc_root=self._proc_root)
                  if not self.service or p.unit != self.service]
        if others:
            lines = [f"PID {p.pid}: {' '.join(p.args)}" for p in others]
            self._error = "\n".join(["Another onedrive process uses the account. Stop it first.", *lines])
            log.warning("Sign-in for %s: %s", self.confdir, self._error)
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
            log.warning("Cannot stop %s before sign-in: %s", self.service, exc)
            self._error = f"Could not stop the service {self.service} before sign-in:\n{exc}"
            return False
        return True

    def restore_service(self) -> None:
        """Start the service again if the flow stopped it. An error goes in ``service_error``."""
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
        """Cancel the sign-in. While the service stops, ``start()`` ends the flow after the stop."""
        with self._lock:
            if self.state not in (FlowState.STARTING, FlowState.WAITING_FOR_USER,
                                  FlowState.WAITING_FOR_TOKEN):
                return
            self.cancel_requested = True
            if not self._auth_started:
                return
            self.auth.cancel()
            self.poll()

    def activate_service(self) -> None:
        """Create and start the service, or restart the existing one.

        Does nothing if the account is not signed in. An error from ``systemctl``
        goes in ``service_error``. The account is still signed in. With ``reauth``
        the flow starts the service again only if it ran before the sign-in.
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
