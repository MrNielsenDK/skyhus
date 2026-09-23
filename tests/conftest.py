"""Fælles fixtures. Testene kører med en midlertidig HOME og kalder aldrig
den rigtige onedrive, systemctl eller Microsoft Graph.

Sikker tilstand (feature 0007) er slået til i alle tests. Blokeringen af
``subprocess`` og ``urlopen`` gælder stadig."""

import subprocess
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def safe_mode_on(monkeypatch):
    """Slå sikker tilstand til, og vurdér den forfra i hver test."""
    from onedrive_gui import sideeffects

    monkeypatch.setenv("ONEDRIVE_GUI_SAFE_MODE", "1")
    sideeffects.reset()
    yield
    sideeffects.reset()


@pytest.fixture(autouse=True)
def no_real_processes(monkeypatch):
    """Stop testen, hvis koden prøver at starte en rigtig proces."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"Testen prøvede at starte en rigtig proces: {args!r}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Stop testen, hvis koden prøver at kalde en rigtig URL."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"Testen prøvede at kalde en rigtig URL: {args!r}")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """En tom, midlertidig HOME med ~/.config."""
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home


def make_account_dir(home: Path, name: str, *, config: str | None = None,
                     refresh_token: bool = False, items: bool = False) -> Path:
    """Opret en config-mappe under ~/.config med de valgte filer."""
    confdir = home / ".config" / name
    confdir.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (confdir / "config").write_text(config)
    if refresh_token:
        (confdir / "refresh_token").write_text("token")
    if items:
        (confdir / "items.sqlite3").write_bytes(b"")
    return confdir


def make_unit(home: Path, name: str, exec_start: str) -> Path:
    """Skriv en user-unit i ~/.config/systemd/user/."""
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    path = unit_dir / name
    path.write_text(f"[Unit]\nDescription=test\n\n[Service]\nExecStart={exec_start}\n")
    return path


class RecordingRun:
    """Erstatning for subprocess.run, der gemmer kaldene."""

    def __init__(self, fail_on: str | None = None, stderr: str = ""):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on
        self.stderr = stderr

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        failed = self.fail_on is not None and self.fail_on in args
        return subprocess.CompletedProcess(
            args, 1 if failed else 0, stdout="", stderr=self.stderr if failed else "")


@pytest.fixture
def recording_run():
    return RecordingRun()
