"""The test suite itself: one shared QGuiApplication (feature 0008)."""

import re
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
CREATES_APP = re.compile(r"\bQ(?:Core|Gui)?Application\(")

_seen = []


@pytest.mark.parametrize("round", [1, 2])
def test_conftest_gives_the_same_qguiapplication_to_all_tests(app, round):
    QtGui = pytest.importorskip("PySide6.QtGui")

    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    assert isinstance(app, QtGui.QGuiApplication)
    assert isinstance(app, QtWidgets.QApplication)
    assert app is QtGui.QGuiApplication.instance()
    _seen.append(app)
    assert all(seen is app for seen in _seen)


def test_no_test_file_creates_its_own_application():
    offenders = []
    for path in sorted(TESTS_DIR.glob("*.py")):
        if path.name == "conftest.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if CREATES_APP.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")

    assert offenders == []
