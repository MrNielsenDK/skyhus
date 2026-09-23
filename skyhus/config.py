"""Read and write single values in the ``config`` of the account.

The application changes only the value that it must change. All other lines and
comments stay the same.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from . import sideeffects
from .discovery import _CONFIG_LINE, read_config_value

log = logging.getLogger(__name__)

DEFAULT_SKIP_FILE = "~*|.~*|*.tmp|*.swp|*.partial"
"""The default value of the client for ``skip_file``."""


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def read_config_values(confdir: Path, key: str) -> list[str]:
    """All values for ``key`` in sequence. Lines with ``#`` do not count."""
    try:
        text = (Path(confdir) / "config").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    values = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _CONFIG_LINE.match(line)
        if match and match.group(1) == key:
            values.append(match.group(2) if match.group(2) is not None else match.group(3))
    return values


def read_sync_root_files(confdir: Path) -> bool:
    return _is_true(read_config_value(confdir, "sync_root_files"))


def read_skip_dirs(confdir: Path) -> list[str]:
    """The patterns from all ``skip_dir`` lines. ``|`` separates the patterns."""
    patterns = []
    for value in read_config_values(confdir, "skip_dir"):
        patterns.extend(p.strip() for p in value.split("|") if p.strip())
    return patterns


def read_skip_dir_strict(confdir: Path) -> bool:
    return _is_true(read_config_value(confdir, "skip_dir_strict_match"))


def read_skip_files(confdir: Path) -> list[str]:
    """The patterns from all ``skip_file`` lines. ``|`` separates the patterns.

    If there is no line, the default value of the client applies. A line replaces
    the default value, as in the client.
    """
    values = read_config_values(confdir, "skip_file")
    if not values:
        values = [DEFAULT_SKIP_FILE]
    patterns = []
    for value in values:
        patterns.extend(p.strip() for p in value.split("|") if p.strip())
    return patterns


def read_skip_dotfiles(confdir: Path) -> bool:
    return _is_true(read_config_value(confdir, "skip_dotfiles"))


def write_sync_root_files(confdir: Path, value: bool) -> None:
    """Set ``sync_root_files``. If the line exists, the application changes it in place."""
    path = Path(confdir) / "config"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    new_line = f'sync_root_files = "{"true" if value else "false"}"'
    lines = text.splitlines(keepends=True)
    found = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        match = _CONFIG_LINE.match(line.rstrip("\r\n"))
        if match and match.group(1) == "sync_root_files":
            ending = line[len(line.rstrip("\r\n")):]
            lines[i] = new_line + (ending or "\n")
            found = True
    if not found:
        if not value:
            # The default value is false. The file must not change.
            return
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line + "\n")
    new_text = "".join(lines)
    if new_text == text:
        return
    if not sideeffects.guard_write(path):
        return
    tmp = path.with_name("config.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    if path.exists():
        os.chmod(tmp, path.stat().st_mode & 0o777)
    os.replace(tmp, path)
    log.info("Set %s in %s", new_line, path)
