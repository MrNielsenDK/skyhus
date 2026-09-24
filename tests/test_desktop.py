"""GNOME support: the title bar plugin on Wayland (feature 0015)."""

import ast
from pathlib import Path

import pytest

from skyhus.desktop import is_gnome_wayland, is_kde, wayland_decoration

ROOT = Path(__file__).resolve().parent.parent
GNOME_WAYLAND = {"XDG_CURRENT_DESKTOP": "GNOME", "WAYLAND_DISPLAY": "wayland-0"}


@pytest.fixture
def plugin_dir(tmp_path):
    folder = tmp_path / "plugins"
    (folder / "wayland-decoration-client").mkdir(parents=True)
    (folder / "wayland-decoration-client" / "libadwaita.so").write_bytes(b"")
    return folder


def test_gnome_on_wayland_with_plugin_gives_adwaita(plugin_dir):
    assert wayland_decoration(GNOME_WAYLAND, plugin_dir) == "adwaita"


@pytest.mark.parametrize("desktop", ["ubuntu:GNOME", "gnome", "GNOME-Classic:GNOME"])
def test_gnome_in_a_desktop_list_gives_adwaita(plugin_dir, desktop):
    environ = {**GNOME_WAYLAND, "XDG_CURRENT_DESKTOP": desktop}

    assert wayland_decoration(environ, plugin_dir) == "adwaita"


def test_kde_gives_none(plugin_dir):
    environ = {**GNOME_WAYLAND, "XDG_CURRENT_DESKTOP": "KDE"}

    assert wayland_decoration(environ, plugin_dir) is None


def test_x11_gives_none(plugin_dir):
    environ = {"XDG_CURRENT_DESKTOP": "GNOME"}

    assert wayland_decoration(environ, plugin_dir) is None


def test_user_value_wins(plugin_dir):
    environ = {**GNOME_WAYLAND, "QT_WAYLAND_DECORATION": "bradient"}

    assert wayland_decoration(environ, plugin_dir) is None


def test_missing_plugin_gives_none(tmp_path):
    assert wayland_decoration(GNOME_WAYLAND, tmp_path) is None
    assert wayland_decoration(GNOME_WAYLAND, None) is None


@pytest.mark.parametrize("value, expected", [
    ("KDE", True), ("ubuntu:KDE", True), ("kde", True), ("GNOME", False), ("", False),
])
def test_is_kde(value, expected):
    assert is_kde({"XDG_CURRENT_DESKTOP": value}) is expected
    assert is_kde({}) is False


def test_is_gnome_wayland():
    assert is_gnome_wayland(GNOME_WAYLAND)
    assert not is_gnome_wayland({"XDG_CURRENT_DESKTOP": "GNOME"})
    assert not is_gnome_wayland({"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"})


def _call_lines(function, name):
    lines = []
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if called == name:
                lines.append(node.lineno)
    return lines


def test_main_chooses_the_decoration_before_it_makes_the_application():
    tree = ast.parse((ROOT / "skyhus" / "app.py").read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")

    decoration = _call_lines(main, "use_gnome_title_bar")
    application = _call_lines(main, "QApplication")
    assert decoration and application
    assert max(decoration) < min(application)


def test_use_gnome_title_bar_sets_the_variable(monkeypatch):
    from skyhus import app, desktop
    monkeypatch.setattr(desktop, "wayland_decoration", lambda environ, plugin_dir: "adwaita")
    environ = dict(GNOME_WAYLAND)

    app.use_gnome_title_bar(environ)

    assert environ["QT_WAYLAND_DECORATION"] == "adwaita"


def test_use_gnome_title_bar_logs_a_missing_plugin(monkeypatch, caplog):
    from skyhus import app, desktop
    monkeypatch.setattr(desktop, "wayland_decoration", lambda environ, plugin_dir: None)
    environ = dict(GNOME_WAYLAND)

    with caplog.at_level("INFO"):
        app.use_gnome_title_bar(environ)

    assert "QT_WAYLAND_DECORATION" not in environ
    assert "adwaita title bar plugin is missing" in caplog.text


def test_use_gnome_title_bar_does_nothing_on_kde(monkeypatch):
    from skyhus import app
    environ = {"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"}

    app.use_gnome_title_bar(environ)

    assert "QT_WAYLAND_DECORATION" not in environ


def test_readme_names_the_supported_desktops():
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    for phrase in ("Supported desktops", "GNOME 46", "KDE Plasma 6", "PySide6 6.8"):
        assert phrase in text, phrase
