"""Visningsnavne og de slugs, der giver config-mappe og service."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .accounts import CONFDIR_PREFIX, GUI_DIR_NAME, Account, config_home, unit_dir

_DANISH = str.maketrans({"æ": "ae", "ø": "oe", "å": "aa"})
RESERVED_SLUGS = {GUI_DIR_NAME.removeprefix(CONFDIR_PREFIX)}


class NamingError(ValueError):
    """Navnet kan ikke bruges. Beskeden kan vises direkte til brugeren."""


@dataclass(frozen=True)
class NewAccount:
    name: str
    slug: str
    confdir: Path
    service: str


def slugify(name: str) -> str:
    """"Firma 2" → ``firma-2``. Æ, ø og å bliver til ae, oe og aa."""
    text = name.strip().lower().translate(_DANISH)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def validate_display_name(name: str, accounts: Iterable[Account],
                          exclude: Path | None = None) -> str:
    """Returnér navnet uden mellemrum i enderne, eller rejs ``NamingError``.

    ``exclude`` er kontoen selv, når brugeren omdøber den.
    """
    clean = " ".join(name.split())
    if not clean:
        raise NamingError("Skriv et visningsnavn.")
    for account in accounts:
        if exclude is not None and Path(account.confdir) == Path(exclude):
            continue
        if account.name.strip().casefold() == clean.casefold():
            raise NamingError(f'Der findes allerede en konto, der hedder "{account.name}".')
    return clean


def plan_new_account(name: str, accounts: Iterable[Account],
                     home: Path | None = None) -> NewAccount:
    """Kontrollér navnet og find stierne til en ny konto. Opretter ingen filer."""
    accounts = list(accounts)
    clean = validate_display_name(name, accounts)
    slug = slugify(clean)
    if not slug:
        raise NamingError("Visningsnavnet skal indeholde mindst ét bogstav eller tal.")
    if slug in RESERVED_SLUGS:
        raise NamingError(f'Navnet "{clean}" er reserveret. Vælg et andet navn.')
    confdir = config_home(home) / f"{CONFDIR_PREFIX}{slug}"
    if confdir.exists():
        raise NamingError(f"Mappen {confdir} findes allerede. Vælg et andet navn.")
    service = f"{CONFDIR_PREFIX}{slug}.service"
    if (unit_dir(home) / service).exists():
        raise NamingError(f"Servicen {service} findes allerede. Vælg et andet navn.")
    return NewAccount(name=clean, slug=slug, confdir=confdir, service=service)


def suggest_sync_dir(name: str) -> str:
    """Forslaget ``~/OneDrive-<Navn>``. Mellemrum bliver til bindestreger."""
    clean = "-".join(name.replace("/", " ").split())
    return f"~/OneDrive-{clean}" if clean else "~/OneDrive-"
