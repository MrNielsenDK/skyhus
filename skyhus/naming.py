"""Display names and the slugs that give the config folder and the service."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .accounts import CONFDIR_PREFIX, Account, config_home, unit_dir

_DANISH = str.maketrans({"æ": "ae", "ø": "oe", "å": "aa"})  # allow-danish: input that slugify must accept


class NamingError(ValueError):
    """The name cannot be used. The message can go directly to the user."""


@dataclass(frozen=True)
class NewAccount:
    name: str
    slug: str
    confdir: Path
    service: str


def slugify(name: str) -> str:
    """"Firma 2" → ``firma-2``. Æ, ø, å become ae, oe, aa."""  # allow-danish: input that slugify must accept
    text = name.strip().lower().translate(_DANISH)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def validate_display_name(name: str, accounts: Iterable[Account],
                          exclude: Path | None = None) -> str:
    """Return the name without spaces at the ends, or raise ``NamingError``.

    ``exclude`` is the account itself when the user renames it.
    """
    clean = " ".join(name.split())
    if not clean:
        raise NamingError("Type a display name.")
    for account in accounts:
        if exclude is not None and Path(account.confdir) == Path(exclude):
            continue
        if account.name.strip().casefold() == clean.casefold():
            raise NamingError(f'An account with the name "{account.name}" already exists.')
    return clean


def plan_new_account(name: str, accounts: Iterable[Account],
                     home: Path | None = None) -> NewAccount:
    """Check the name and find the paths for a new account. Creates no files."""
    accounts = list(accounts)
    clean = validate_display_name(name, accounts)
    slug = slugify(clean)
    if not slug:
        raise NamingError("The display name must contain at least one letter or digit.")
    confdir = config_home(home) / f"{CONFDIR_PREFIX}{slug}"
    if confdir.exists():
        raise NamingError(f"The folder {confdir} already exists. Choose a different name.")
    service = f"{CONFDIR_PREFIX}{slug}.service"
    if (unit_dir(home) / service).exists():
        raise NamingError(f"The service {service} already exists. Choose a different name.")
    return NewAccount(name=clean, slug=slug, confdir=confdir, service=service)


def suggest_sync_dir(name: str) -> str:
    """The suggestion ``~/OneDrive-<Name>``. Spaces become hyphens."""
    clean = "-".join(name.replace("/", " ").split())
    return f"~/OneDrive-{clean}" if clean else "~/OneDrive-"
