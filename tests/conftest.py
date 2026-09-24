"""Shared fixtures. The tests run with a temporary HOME and never call
the real onedrive, systemctl or Microsoft Graph.

Safe mode (feature 0007) is on in all tests. The block on
``subprocess`` and ``urlopen`` still applies."""

import gc
import os
import subprocess
import urllib.request
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def app():
    """One shared QGuiApplication for all tests (feature 0008).

    Qt allows only 1 application object per process. If a test creates a
    QCoreApplication first, a later test that needs QGuiApplication crashes."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # QApplication, because the tray icon needs Qt Widgets (feature 0020).
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def collect_qt_garbage():
    """Clean up after the test in the main thread (feature 0008).

    A test often leaves an AppController in a reference cycle. Python can
    clean up the cycle in any thread, for example in a _Job thread from a later test.
    Then a QTimer can stay without its object, and Qt crashes with
    "Segmentation fault" in a later test."""
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def safe_mode_on(monkeypatch):
    """Turn on safe mode, and check it again in each test."""
    from skyhus import sideeffects

    monkeypatch.setenv("SKYHUS_SAFE_MODE", "1")
    # The old variable (feature 0012) must not keep safe mode on in tests of normal mode.
    monkeypatch.delenv("ONEDRIVE_GUI_SAFE_MODE", raising=False)
    sideeffects.reset()
    yield
    sideeffects.reset()


@pytest.fixture(autouse=True)
def no_real_processes(monkeypatch):
    """Stop the test if the code tries to start a real process."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"The test tried to start a real process: {args!r}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Stop the test if the code tries to call a real URL."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"The test tried to call a real URL: {args!r}")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """An empty, temporary HOME with ~/.config."""
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home


def make_account_dir(home: Path, name: str, *, config: str | None = None,
                     refresh_token: bool = False, items: bool = False) -> Path:
    """Create a config folder under ~/.config with the selected files."""
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
    """Write a user unit in ~/.config/systemd/user/."""
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    path = unit_dir / name
    path.write_text(f"[Unit]\nDescription=test\n\n[Service]\nExecStart={exec_start}\n")
    return path


class RecordingRun:
    """A replacement for subprocess.run that records the calls."""

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
