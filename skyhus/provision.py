"""Create the config folder and the sync folder for a new account."""

from __future__ import annotations

import os
from pathlib import Path

from . import sideeffects


def validate_sync_dir(sync_dir: str) -> str:
    if not sync_dir.strip():
        raise ValueError("Choose a sync folder.")
    if '"' in sync_dir or "\n" in sync_dir or "\r" in sync_dir:
        raise ValueError("The sync folder must not contain quotation marks or line breaks.")
    return sync_dir


def provision_account(confdir: Path, sync_dir: str) -> None:
    """Create ``confdir`` with a ``config`` that only sets ``sync_dir``.

    The folder must not exist before. The sync folder is created if it
    is missing.
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
