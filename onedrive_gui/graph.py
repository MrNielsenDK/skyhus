"""Mapperne på OneDrive, hentet direkte fra Microsoft Graph.

Applikationen bruger kontoens ``refresh_token`` til et access-token. Svaret
fra Microsoft indeholder også en ny ``refresh_token``. Applikationen gemmer
den ikke. Klienten ejer filen ``refresh_token`` i config-mappen.

Kaldene bruger kun standardbiblioteket. ``opener`` svarer til
``urllib.request.urlopen``, så testene kan give optagne svar.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode

from .auth import NATIVE_CLIENT_URL
from .discovery import read_config_value

log = logging.getLogger(__name__)

TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_URL = "https://graph.microsoft.com/v1.0"
CLIENT_ID = "d50ca740-c83f-4d1b-b616-12c519384f0c"
"""Klientens egen ``client_id``. Kontoens ``refresh_token`` hører til den."""
SCOPES = "Files.ReadWrite Files.ReadWrite.All Sites.ReadWrite.All offline_access"
READ_ONLY_SCOPES = "Files.Read Files.Read.All Sites.Read.All offline_access"
"""Klientens scopes, når ``read_only_auth_scope = "true"``."""
TIMEOUT_SECONDS = 30
TOKEN_MARGIN_SECONDS = 60


class GraphError(RuntimeError):
    """Et kald til Microsoft fejlede. Beskeden kan vises for brugeren."""


class NotLoggedInError(GraphError):
    def __init__(self) -> None:
        super().__init__("Kontoen er ikke logget ind.")


class LoginRequiredError(GraphError):
    def __init__(self, detail: str = "") -> None:
        message = "Microsoft afviste kontoens login. Log kontoen ind igen."
        super().__init__(f"{message}\n{detail}".strip())


@dataclass(frozen=True)
class Folder:
    id: str
    name: str
    path: str
    """Stien fra roden uden ``/`` i enderne, fx ``Arbejde/Kunder``."""
    has_children: bool


class GraphClient:
    def __init__(self, confdir: Path, *, opener: Callable | None = None,
                 clock: Callable[[], float] | None = None):
        self.confdir = Path(confdir)
        self._opener = opener or urllib.request.urlopen
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0

    def access_token(self) -> str:
        with self._lock:
            if self._token and self._clock() < self._expires_at:
                return self._token
            self._token, lifetime = self._fetch_token()
            self._expires_at = self._clock() + max(lifetime - TOKEN_MARGIN_SECONDS, 0)
            return self._token

    def list_folders(self, item_id: str = "", parent_path: str = "") -> list[Folder]:
        """Undermapperne i roden eller i mappen ``item_id``. Filer er ikke med."""
        if item_id:
            url = f"{GRAPH_URL}/me/drive/items/{quote(item_id, safe='')}/children"
        else:
            url = f"{GRAPH_URL}/me/drive/root/children"
        url += "?$select=id,name,folder&$top=999"
        folders = []
        while url:
            page = self._get(url)
            for item in page.get("value", []):
                if not isinstance(item, dict) or not isinstance(item.get("folder"), dict):
                    continue
                name = item.get("name", "")
                folders.append(Folder(
                    id=item.get("id", ""),
                    name=name,
                    path=f"{parent_path}/{name}" if parent_path else name,
                    has_children=bool(item["folder"].get("childCount", 0)),
                ))
            url = page.get("@odata.nextLink", "")
        return sorted(folders, key=lambda f: f.name.casefold())

    # Hjælpefunktioner

    def _read_refresh_token(self) -> str:
        try:
            token = (self.confdir / "refresh_token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if not token:
            raise NotLoggedInError()
        return token

    def _fetch_token(self) -> tuple[str, float]:
        read_only = (read_config_value(self.confdir, "read_only_auth_scope") or "").lower() == "true"
        form = {
            "client_id": read_config_value(self.confdir, "application_id") or CLIENT_ID,
            "redirect_uri": NATIVE_CLIENT_URL,
            "grant_type": "refresh_token",
            "refresh_token": self._read_refresh_token(),
            "scope": READ_ONLY_SCOPES if read_only else SCOPES,
        }
        request = urllib.request.Request(
            TOKEN_URL, data=urlencode(form).encode("ascii"), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            answer = self._open(request)
        except urllib.error.HTTPError as exc:
            body = _error_body(exc)
            if body.get("error") in ("invalid_grant", "interaction_required"):
                raise LoginRequiredError(body.get("error_description", "")) from None
            raise GraphError(_describe(exc, body)) from None
        token = answer.get("access_token")
        if not isinstance(token, str) or not token:
            raise GraphError("Microsoft sendte ikke et access-token.")
        try:
            lifetime = float(answer.get("expires_in", 0))
        except (TypeError, ValueError):
            lifetime = 0.0
        return token, lifetime

    def _get(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.access_token()}", "Accept": "application/json"})
        try:
            return self._open(request)
        except urllib.error.HTTPError as exc:
            raise GraphError(_describe(exc, _error_body(exc))) from None

    def _open(self, request: urllib.request.Request) -> dict:
        log.info("%s %s", request.get_method(), request.full_url.split("?", 1)[0])
        try:
            with self._opener(request, timeout=TIMEOUT_SECONDS) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as exc:
            raise GraphError(f"Kan ikke kontakte Microsoft: {exc.reason}") from None
        except (OSError, ValueError) as exc:
            raise GraphError(f"Ugyldigt svar fra Microsoft: {exc}") from None
        if not isinstance(data, dict):
            raise GraphError("Ugyldigt svar fra Microsoft.")
        return data


def _error_body(exc: urllib.error.HTTPError) -> dict:
    try:
        data = json.loads(exc.read().decode("utf-8", "replace"))
    except (OSError, ValueError, AttributeError):
        return {}
    if not isinstance(data, dict):
        return {}
    error = data.get("error")
    if isinstance(error, dict):
        # Graph svarer med {"error": {"code": ..., "message": ...}}.
        return {"error": error.get("code", ""), "error_description": error.get("message", "")}
    return data


def _describe(exc: urllib.error.HTTPError, body: dict) -> str:
    detail = body.get("error_description") or body.get("error") or exc.reason
    return f"Microsoft svarede {exc.code}: {detail}"
