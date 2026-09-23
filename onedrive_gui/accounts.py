"""Modellen for en OneDrive-konto og de faste stier, som resten bruger."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ONEDRIVE = "/usr/bin/onedrive"
DEFAULT_CONFDIR_NAME = "onedrive"
CONFDIR_PREFIX = "onedrive-"
GUI_DIR_NAME = "onedrive-gui"
DEFAULT_SYNC_DIR = "~/OneDrive"


@dataclass
class Account:
    name: str
    """Visningsnavnet, som brugeren selv vælger."""
    confdir: Path
    sync_dir: str
    """Værdien, som klienten bruger, fx ``~/OneDrive-Privat``."""
    service: str
    """Navnet på kontoens systemd-user-unit, eller tom, hvis der ikke er en."""
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
