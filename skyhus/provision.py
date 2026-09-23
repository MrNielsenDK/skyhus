"""Opret config-mappen og synkmappen for en ny konto."""

from __future__ import annotations

import os
from pathlib import Path

from . import sideeffects


def validate_sync_dir(sync_dir: str) -> str:
    if not sync_dir.strip():
        raise ValueError("Vælg en synkmappe.")
    if '"' in sync_dir or "\n" in sync_dir or "\r" in sync_dir:
        raise ValueError("Synkmappen må ikke indeholde anførselstegn eller linjeskift.")
    return sync_dir


def provision_account(confdir: Path, sync_dir: str) -> None:
    """Opret ``confdir`` med en ``config``, der kun sætter ``sync_dir``.

    Mappen må ikke findes i forvejen. Synkmappen bliver oprettet, hvis den
    mangler.
    """
    validate_sync_dir(sync_dir)
    confdir = Path(confdir)
    if sideeffects.guard_write(confdir):
        confdir.parent.mkdir(parents=True, exist_ok=True)
        confdir.mkdir(mode=0o700)
        (confdir / "config").write_text(f'sync_dir = "{sync_dir}"\n', encoding="utf-8")
    sync_path = Path(os.path.expanduser(sync_dir))
    if sideeffects.guard_write(sync_path):
        sync_path.mkdir(parents=True, exist_ok=True)
