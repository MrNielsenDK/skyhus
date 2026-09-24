"""The card "Activity" and the sheet "All files" (feature 0019)."""

import json
import os
import subprocess
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtGui = pytest.importorskip("PySide6.QtGui")
from PySide6.QtCore import QObject  # noqa: E402

from skyhus.viewmodels import AppController  # noqa: E402

from conftest import make_account_dir  # noqa: E402
from test_qml import load, visible_items  # noqa: E402,F401

NOW = time.time()


def journal_line(message, cursor, pid="100", when=NOW - 60):
    return json.dumps({"SYSLOG_IDENTIFIER": "onedrive", "_PID": pid, "MESSAGE": message,
                       "__REALTIME_TIMESTAMP": str(int(when * 1_000_000)), "__CURSOR": cursor})


class FakeJournal:
    """A replacement for ``subprocess.run``. ``journalctl`` gives ``lines``, the next call gives ``later``."""

    def __init__(self, lines, later=()):
        self.lines = list(lines)
        self.later = list(later)
        self.calls = []

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        out = ""
        if args[0] == "journalctl" and "-n" in args:
            reads = [c for c in self.calls if c[0] == "journalctl" and "-n" in c]
            out = "\n".join(self.lines if len(reads) == 1 else self.later)
        return subprocess.CompletedProcess(args, 0, stdout=out + "\n" if out else "", stderr="")

    def activity_calls(self):
        return [c for c in self.calls if c[0] == "journalctl" and "-n" in c]


LINES = [
    journal_line("Downloading file: Docs/a.txt ... done", "c1", when=NOW - 60),
    journal_line("Uploading new file: Docs/b.txt ... done", "c2", when=NOW - 50),
    journal_line("Insufficient local disk space to download file", "c3", when=NOW - 40),
    journal_line("Downloading file: Photos/1.jpg ... failed!", "c4", when=NOW - 40),
    journal_line("Sync with Microsoft OneDrive is complete", "c5", when=NOW - 30),
]


def service_home(home, name="onedrive-x"):
    confdir = make_account_dir(home, name, config="", refresh_token=True)
    unit = home / ".config" / "systemd" / "user" / f"{name}.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f'[Service]\nExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/{name}"\n')
    return confdir


def pump(controller, predicate, timeout=5.0):
    app = QtGui.QGuiApplication.instance()
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        controller._poll_activity()
        app.processEvents()
        time.sleep(0.01)
    assert predicate()


def make_controller(home, tmp_path, run):
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    return AppController(home, run=run, proc_root=proc)


# Controller

def test_open_reads_24_hours_and_fills_the_card(app, home, tmp_path):
    confdir = service_home(home)
    journal = FakeJournal(LINES)
    controller = make_controller(home, tmp_path, journal)

    controller.openActivity(str(confdir))
    assert controller.activityState == "loading"
    pump(controller, lambda: controller.activityState == "ready")

    assert "--since" in journal.activity_calls()[0]
    assert controller.activitySummary.startswith("Last sync: today at ")
    assert "1 downloaded, 1 uploaded, 1 failed" in controller.activitySummary
    problems = controller.activityProblems
    assert [p["title"] for p in problems] == ["Download failed: not enough disk space"]
    assert problems[0]["tone"] == "danger"
    assert problems[0]["detail"].startswith("1 time · today at ")
    recent = controller.activityRecent
    assert [r["path"] for r in recent] == ["Photos/1.jpg", "Docs/b.txt", "Docs/a.txt"]
    assert {r["icon"] for r in recent} == {"arrow-down", "arrow-up", "circle-alert"}


def test_a_second_open_while_reading_starts_no_new_read(app, home, tmp_path):
    confdir = service_home(home)
    journal = FakeJournal(LINES)
    controller = make_controller(home, tmp_path, journal)

    controller.openActivity(str(confdir))
    controller.openActivity(str(confdir))
    first = len(journal.activity_calls())
    pump(controller, lambda: controller.activityState == "ready")

    assert first == 1


def test_timer_reads_only_the_new_lines(app, home, tmp_path):
    confdir = service_home(home)
    journal = FakeJournal(LINES, later=[journal_line("Downloading file: Docs/new.txt ... done", "c6", when=NOW - 10)])
    controller = make_controller(home, tmp_path, journal)
    controller.openActivity(str(confdir))
    pump(controller, lambda: controller.activityState == "ready")

    controller._read_current_activity()
    pump(controller, lambda: controller._activity_job is None)

    second = journal.activity_calls()[1]
    assert "--after-cursor=c5" in second
    assert "--since" not in second
    assert controller.activityRecent[0]["path"] == "Docs/new.txt"
    assert "2 downloaded" in controller.activitySummary


def test_refresh_reads_24_hours_again(app, home, tmp_path):
    confdir = service_home(home)
    journal = FakeJournal(LINES, later=LINES)
    controller = make_controller(home, tmp_path, journal)
    controller.openActivity(str(confdir))
    pump(controller, lambda: controller.activityState == "ready")

    controller.refreshActivity()
    pump(controller, lambda: controller._activity_job is None)

    assert "--since" in journal.activity_calls()[1]
    assert "1 downloaded" in controller.activitySummary


def test_account_without_service_reads_nothing(app, home, tmp_path):
    confdir = make_account_dir(home, "onedrive-y", config="", refresh_token=True)
    journal = FakeJournal(LINES)
    controller = make_controller(home, tmp_path, journal)

    controller.openActivity(str(confdir))

    assert controller.activityState == "no_service"
    assert journal.activity_calls() == []


def test_copy_problems_puts_the_text_on_the_clipboard(app, home, tmp_path):
    confdir = service_home(home)
    controller = make_controller(home, tmp_path, FakeJournal(LINES))
    controller.openActivity(str(confdir))
    pump(controller, lambda: controller.activityState == "ready")

    controller.copyProblems()

    text = QtGui.QGuiApplication.clipboard().text()
    assert text.startswith("Download failed: not enough disk space · 1 time · today at ")
    assert text.endswith("Photos/1.jpg")


def test_no_problems_gives_an_empty_list(app, home, tmp_path):
    confdir = service_home(home)
    controller = make_controller(home, tmp_path, FakeJournal(LINES[:2]))
    controller.openActivity(str(confdir))
    pump(controller, lambda: controller.activityState == "ready")

    assert controller.activityProblems == []


def test_safe_mode_runs_only_journalctl(app, home, tmp_path, monkeypatch):
    from skyhus import sideeffects
    confdir = service_home(home)
    journal = FakeJournal(LINES)
    monkeypatch.setattr(subprocess, "run", journal)
    assert sideeffects.safe_mode()
    proc = tmp_path / "proc"
    proc.mkdir()
    controller = AppController(home, proc_root=proc)

    controller.openActivity(str(confdir))
    pump(controller, lambda: controller.activityState == "ready")

    assert {c[0] for c in journal.calls} <= {"journalctl", "systemctl"}
    assert all(c[2] == "show" for c in journal.calls if c[0] == "systemctl")
    assert "1 downloaded" in controller.activitySummary


# QML

def test_card_shows_summary_problems_and_files(load, home, tmp_path):
    confdir = service_home(home)
    proc = tmp_path / "proc"
    proc.mkdir()
    engine, controller, warnings = load(home, run=FakeJournal(LINES), proc_root=proc)
    root = engine.rootObjects()[0]
    pump(controller, lambda: controller.activityState == "ready")
    pump(controller, lambda: bool(visible_items(root, "problemRow")))

    summary = visible_items(root, "activitySummary")
    assert len(summary) == 1 and "1 downloaded" in summary[0].property("text")
    assert [t.property("text") for t in visible_items(root, "problemTitle")] == \
        ["Download failed: not enough disk space"]
    assert visible_items(root, "noProblemsText") == []
    assert len(visible_items(root, "recentFileRow")) == 3

    controller.showAllFiles()
    pump(controller, lambda: bool(visible_items(root, "allFilesList")))
    assert root.findChild(QObject, "allFilesSheet").property("visible") is True
    controller.closeAllFiles()
    assert warnings == []


def test_card_says_no_problems(load, home, tmp_path):
    service_home(home)
    proc = tmp_path / "proc"
    proc.mkdir()
    engine, controller, warnings = load(home, run=FakeJournal(LINES[:2]), proc_root=proc)
    root = engine.rootObjects()[0]
    pump(controller, lambda: controller.activityState == "ready")
    pump(controller, lambda: bool(visible_items(root, "noProblemsText")))

    assert visible_items(root, "problemRow") == []
    assert warnings == []
