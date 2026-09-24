"""The total state, the tooltip and the menu of the tray icon, and the autostart file (feature 0020)."""

from pathlib import Path

from conftest import RecordingRun

import pytest

from skyhus import autostart, install, settings
from skyhus.accounts import Account
from skyhus.service_state import AccountStatus, ServiceState
from skyhus.tray_state import ACTION, LABEL, RESYNC, menu_items, tooltip, total_tone


def account(name, service="onedrive-x.service"):
    return Account(name=name, confdir=Path(f"/c/{name}"), sync_dir="~/X", service=service, logged_in=True)


def status(key):
    return AccountStatus(ServiceState(key))


def statuses(*pairs):
    return {f"/c/{name}": status(key) for name, key in pairs}


# total_tone

@pytest.mark.parametrize("keys, tone", [
    (["failed", "running"], "danger"),
    (["needs_resync", "resyncing"], "danger"),
    (["resyncing", "running"], "warning"),
    (["resync_cancelled"], "warning"),
    (["running", "running"], "success"),
    ([], "success"),
    (["stopped", "logged_out", "no_service", "running"], "success"),
])
def test_total_tone(keys, tone):
    assert total_tone(status(k) for k in keys) == tone


def test_tooltip_lists_each_account():
    accounts = [account("OneDrive"), account("privat")]

    text = tooltip(accounts, statuses(("OneDrive", "running"), ("privat", "needs_resync")))

    assert text.splitlines() == ["Skyhus", "OneDrive: Running", "privat: Needs resync"]


def test_menu_items_follow_the_card_actions():
    accounts = [account("a"), account("b"), account("c"), account("d")]

    items = menu_items(accounts, statuses(("a", "running"), ("b", "failed"), ("c", "needs_resync"),
                                          ("d", "resyncing")))

    assert [(i.kind, i.text) for i in items] == [
        (LABEL, "a — Running"), (ACTION, "Restart a"),
        (LABEL, "b — Failed"), (ACTION, "Start b"),
        (LABEL, "c — Needs resync"), (RESYNC, "Restart c with resync …"),
        (LABEL, "d — Resyncing"),
    ]
    assert items[1].confdir == "/c/a"


def test_account_without_service_has_no_action():
    items = menu_items([account("a", service="")], statuses(("a", "stopped")))

    assert [i.kind for i in items] == [LABEL]


# autostart

def install_script(home):
    script = install.script_path(home)
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\n")
    return script


def test_enable_writes_the_file_and_disable_removes_it(home):
    script = install_script(home)

    assert autostart.state(home) == autostart.OFF
    assert autostart.enable(home) is True

    path = install.autostart_path(home)
    text = path.read_text()
    assert f"Exec={script} --background" in text
    assert "X-Skyhus-Installer=true" in text
    assert autostart.state(home) == autostart.ON

    assert autostart.disable(home) is True
    assert not path.exists()
    assert autostart.state(home) == autostart.OFF


def test_foreign_file_is_never_changed(home):
    install_script(home)
    path = install.autostart_path(home)
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nName=Mine\n")

    assert autostart.state(home) == autostart.FOREIGN
    assert autostart.enable(home) is False
    assert autostart.disable(home) is False
    assert path.read_text() == "[Desktop Entry]\nName=Mine\n"


def test_without_the_start_script_nothing_is_written(home):
    assert autostart.state(home) == autostart.NOT_INSTALLED
    assert autostart.enable(home) is False
    assert not install.autostart_path(home).exists()


def test_safe_mode_does_not_write_under_the_real_home(home, monkeypatch):
    from skyhus import sideeffects
    install_script(home)
    monkeypatch.setattr(sideeffects, "real_home", lambda: home)
    assert sideeffects.safe_mode()

    assert autostart.enable(home) is False
    assert not install.autostart_path(home).exists()


def test_uninstall_removes_our_autostart_file(home):
    install_script(home)
    autostart.enable(home)

    install.uninstall(home, run=RecordingRun(), environ={})

    assert not install.autostart_path(home).exists()


def test_uninstall_keeps_a_foreign_autostart_file(home):
    path = install.autostart_path(home)
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nName=Mine\n")

    result = install.uninstall(home, run=RecordingRun(), environ={})

    assert path.exists()
    assert any(str(path) in w for w in result.warnings)


def test_install_needs_qtwidgets_and_qtnetwork(home):
    result = install.install(home, install.REPO_DIR, python="/usr/bin/python3", run=RecordingRun(),
                             find_spec=lambda name: None if name == "PySide6.QtWidgets" else object(), environ={})

    assert "PySide6.QtWidgets" in result.error
    assert "python3-pyside6.qtwidgets" in result.error


# settings

def test_flag_is_remembered(home):
    assert settings.get_flag(settings.TRAY_HINT_SHOWN, home) is False

    settings.set_flag(settings.TRAY_HINT_SHOWN, home=home)

    assert settings.get_flag(settings.TRAY_HINT_SHOWN, home) is True
    assert settings.settings_path(home).parent == home / ".config" / "skyhus"
