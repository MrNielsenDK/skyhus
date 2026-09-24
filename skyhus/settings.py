"""Read and write ``~/.config/skyhus/settings.json`` (feature 0020).

The file has flags that Skyhus remembers between starts, for example that it
has shown the tray message.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import sideeffects
from .accounts import gui_dir

log = logging.getLogger(__name__)

TRAY_HINT_SHOWN = "tray_hint_shown"


def settings_path(home: Path | None = None) -> Path:
    return gui_dir(home) / "settings.json"


def load(home: Path | None = None) -> dict:
    try:
        data = json.loads(settings_path(home).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Cannot read %s: %s", settings_path(home), exc)
        return {}
    return data if isinstance(data, dict) else {}


def get_flag(key: str, home: Path | None = None) -> bool:
    return load(home).get(key) is True


def set_flag(key: str, value: bool = True, home: Path | None = None) -> None:
    path = settings_path(home)
    if not sideeffects.guard_write(path):
        return
    data = load(home)
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
