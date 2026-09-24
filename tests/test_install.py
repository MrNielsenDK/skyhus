"""Install Skyhus on the desktop (feature 0013)."""

import logging
import stat
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from skyhus import install

from conftest import RecordingRun

ROOT = Path(__file__).resolve().parent.parent
PYTHON = "/usr/bin/python3"


def found(name):
    return object()


def missing_webengine(name):
    return None if name == "PySide6.QtWebEngineQuick" else object()


def missing_quick(name):
    return None if name == "PySide6.QtQuick" else object()


def paths(home):
    return {
        "script": home / ".local" / "bin" / "skyhus",
        "desktop": home / ".local" / "share" / "applications" / "skyhus.desktop",
        "icon": home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "skyhus.svg",
    }


def do_install(home, run=None, find_spec=found):
    return install.install(home, ROOT, python=PYTHON, run=run or RecordingRun(), find_spec=find_spec)


# Installation

def test_install_writes_the_three_files(home):
    result = do_install(home)

    assert result.error == ""
    p = paths(home)
    assert sorted(result.written) == sorted(p.values())
    for path in p.values():
        assert path.is_file()


def test_script_is_executable_and_points_at_the_project(home):
    do_install(home)
    script = paths(home)["script"]

    assert stat.S_IMODE(script.stat().st_mode) == 0o755
    text = script.read_text()
    assert text.startswith("#!/bin/sh\n")
    assert install.MARKER in text
    assert str(ROOT) in text
    assert f"exec {PYTHON} -m skyhus.app" in text


def test_desktop_file_has_full_exec_path_icon_and_marker(home):
    do_install(home)
    lines = paths(home)["desktop"].read_text().splitlines()

    assert lines[0] == "[Desktop Entry]"
    assert f"Exec={paths(home)['script']}" in lines
    assert "Icon=skyhus" in lines
    assert "Name=Skyhus" in lines
    assert "StartupWMClass=skyhus" in lines
    assert "X-Skyhus-Installer=true" in lines


def test_desktop_file_text_is_english(home):
    do_install(home)
    lines = paths(home)["desktop"].read_text().splitlines()

    assert "GenericName=OneDrive accounts" in lines
    assert "Comment=Multiple OneDrive accounts on Linux" in lines


def test_script_has_english_marker(home):
    do_install(home)

    assert install.MARKER == "Installed by Skyhus"
    assert "# Installed by Skyhus." in paths(home)["script"].read_text()


def test_icon_has_marker(home):
    do_install(home)

    assert "<!-- Installed by Skyhus -->" in paths(home)["icon"].read_text()


@pytest.mark.parametrize("which", ["script", "desktop", "icon"])
def test_foreign_file_stops_installation(home, which):
    p = paths(home)
    p[which].parent.mkdir(parents=True)
    p[which].write_text("something else\n")

    result = do_install(home)

    assert str(p[which]) in result.error
    assert result.written == []
    assert p[which].read_text() == "something else\n"
    for name, path in p.items():
        if name != which:
            assert not path.exists()


def test_foreign_symlink_stops_installation(home, tmp_path):
    target = tmp_path / "other-program"
    target.write_text(f"#!/bin/sh\n# {install.MARKER}\n")
    script = paths(home)["script"]
    script.parent.mkdir(parents=True)
    script.symlink_to(target)

    result = do_install(home)

    assert str(script) in result.error
    assert script.is_symlink()


def test_own_files_are_overwritten(home):
    do_install(home)
    script = paths(home)["script"]
    script.write_text(f"#!/bin/sh\n# {install.MARKER}\nold\n")

    result = do_install(home)

    assert result.error == ""
    assert "old\n" not in script.read_text()
    assert str(ROOT) in script.read_text()


# Files from version 0.9.0 have the old marker

def write_legacy_files(home):
    p = paths(home)
    for name in ("script", "icon"):
        p[name].parent.mkdir(parents=True, exist_ok=True)
    p["script"].write_text(f"#!/bin/sh\n# {install.LEGACY_MARKER}.\nold\n")
    p["icon"].write_text(f"<svg><!-- {install.LEGACY_MARKER} --></svg>\n")
    return p


def test_files_with_the_old_marker_are_overwritten(home):
    p = write_legacy_files(home)

    result = do_install(home)

    assert result.error == ""
    assert install.LEGACY_MARKER not in p["script"].read_text()
    assert install.MARKER in p["script"].read_text()
    assert install.LEGACY_MARKER not in p["icon"].read_text()
    assert install.MARKER in p["icon"].read_text()


def test_files_with_the_old_marker_are_removed_on_uninstall(home):
    p = write_legacy_files(home)

    result = install.uninstall(home, run=RecordingRun())

    assert not p["script"].exists()
    assert not p["icon"].exists()
    assert sorted(result.removed) == sorted([p["script"], p["icon"]])
    assert result.warnings == []


def test_old_marker_does_not_count_for_the_desktop_file(home):
    desktop = paths(home)["desktop"]
    desktop.parent.mkdir(parents=True)
    desktop.write_text(f"[Desktop Entry]\n# {install.LEGACY_MARKER}\n")

    result = do_install(home)

    assert str(desktop) in result.error
    assert result.written == []


def test_install_refreshes_the_menu(home):
    run = RecordingRun()

    do_install(home, run=run)

    applications = str(paths(home)["desktop"].parent)
    assert ["update-desktop-database", applications] in run.calls
    assert ["kbuildsycoca6"] in run.calls


def test_failing_menu_refresh_gives_a_warning(home):
    def run(args, **kwargs):
        if args[0] == "kbuildsycoca6":
            raise FileNotFoundError(args[0])
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="error")

    result = do_install(home, run=run)

    assert result.error == ""
    assert any("update-desktop-database" in w for w in result.warnings)
    assert all(path.exists() for path in paths(home).values())


def test_missing_qtquick_stops_before_writing(home):
    result = do_install(home, find_spec=missing_quick)

    assert "sudo apt install" in result.error
    assert result.written == []
    assert not (home / ".local").exists()


def test_missing_webengine_gives_a_warning(home):
    result = do_install(home, find_spec=missing_webengine)

    assert result.error == ""
    assert any("sign-in" in w.lower() for w in result.warnings)
    assert paths(home)["script"].exists()


# Uninstall

def test_uninstall_removes_own_files(home):
    do_install(home)

    result = install.uninstall(home, run=RecordingRun())

    assert result.error == ""
    assert not any(path.exists() for path in paths(home).values())
    assert sorted(result.removed) == sorted(paths(home).values())


def test_uninstall_keeps_foreign_file(home):
    do_install(home)
    desktop = paths(home)["desktop"]
    desktop.write_text("[Desktop Entry]\nName=Other\n")

    result = install.uninstall(home, run=RecordingRun())

    assert desktop.read_text() == "[Desktop Entry]\nName=Other\n"
    assert any(str(desktop) in w for w in result.warnings)
    assert not paths(home)["script"].exists()


def test_uninstall_keeps_config(home):
    config = home / ".config" / "skyhus"
    config.mkdir()
    (config / "accounts.json").write_text("{}")
    do_install(home)

    install.uninstall(home, run=RecordingRun())

    assert (config / "accounts.json").exists()


# Safe mode

def test_safe_mode_does_not_write_under_the_real_home(monkeypatch):
    from skyhus import sideeffects
    real = sideeffects.real_home()
    written = []
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: written.append(self))
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: written.append(self))
    monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: written.append(self))
    monkeypatch.setattr(install.os, "chmod", lambda *a, **k: written.append(a[0]))

    install.install(real, ROOT, python=PYTHON, find_spec=found)
    install.uninstall(real)

    assert written == []


# The application and the project

def test_app_sets_desktop_file_name_and_window_icon():
    text = (ROOT / "skyhus" / "app.py").read_text(encoding="utf-8")

    assert 'setDesktopFileName("skyhus")' in text
    assert "setWindowIcon" in text


def test_icon_is_plain_svg():
    path = ROOT / "skyhus" / "assets" / "skyhus.svg"
    tree = ET.parse(path)

    assert tree.getroot().tag == "{http://www.w3.org/2000/svg}svg"
    for element in tree.iter():
        assert not element.tag.endswith("}text"), element.tag
        assert not any(key.endswith("href") for key in element.attrib), element.attrib


def test_pyproject_has_no_pip_dependencies_and_ships_the_icon():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "dependencies" not in data["project"]
    assert "assets/skyhus.svg" in data["tool"]["setuptools"]["package-data"]["skyhus"]


def test_readme_explains_install_without_pip():
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "python3 -m skyhus.install" in text
    assert "--uninstall" in text
    assert "pip install" not in text


def test_main_prints_result(home, monkeypatch, capsys, caplog):
    monkeypatch.setattr(install, "install", lambda *a, **k: install.Result(written=[home / "x"]))

    assert install.main(["skyhus.install"]) == 0

    assert str(home / "x") in capsys.readouterr().out


def test_missing_kbuildsycoca6_gives_no_warning(home):
    """GNOME has no kbuildsycoca6 (feature 0015)."""
    def run(args, **kwargs):
        if args[0] == "kbuildsycoca6":
            raise FileNotFoundError(args[0])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    result = do_install(home, run=run)

    assert result.error == ""
    assert result.warnings == []
