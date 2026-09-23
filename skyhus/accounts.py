"""The model for a OneDrive account and the fixed paths that the other modules use."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ONEDRIVE = "/usr/bin/onedrive"
DEFAULT_CONFDIR_NAME = "onedrive"
CONFDIR_PREFIX = "onedrive-"
GUI_DIR_NAME = "skyhus"
DEFAULT_SYNC_DIR = "~/OneDrive"


@dataclass
class Account:
    name: str
    """The display name that the user chooses."""
    confdir: Path
    sync_dir: str
    """The value that the client uses, for example ``~/OneDrive-Privat``."""
    service: str
    """The name of the systemd user unit of the account, or empty if there is none."""
    logged_in: bool

    @property
    def sync_path(self) -> Path:
        return Path(os.path.expanduser(self.sync_dir))


def home_dir(home: Path | None = None) -> Path:
    return Path(home) if home is not None else Path.home()


def config_home(home: Path | None = None) -> Path:
    return home_dir(home) / ".config"


def unit_dir(home: Path | None = None) -> Path:
    return config_home(home) / "systemd" / "user"


def gui_dir(home: Path | None = None) -> Path:
    return config_home(home) / GUI_DIR_NAME
