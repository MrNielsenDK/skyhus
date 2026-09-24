"""The tray icon, the single instance and the close behavior (feature 0020)."""

import os
import time
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QObject  # noqa: E402

from skyhus import autostart, install, settings  # noqa: E402
from skyhus.service_state import AccountStatus, ServiceState  # noqa: E402
from skyhus.tray import Tray, render_icon  # noqa: E402
from skyhus.viewmodels import STATUS_INTERVAL_HIDDEN_MS, STATUS_INTERVAL_MS, TRAY_HINT, AppController  # noqa: E402

from conftest import make_account_dir  # noqa: E402
from fakes import ScriptedRun  # noqa: E402
from test_qml import load, visible_items  # noqa: E402,F401


def make_controller(home, tmp_path, **kwargs):
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    kwargs.setdefault("run", ScriptedRun())
    return AppController(home, proc_root=proc, **kwargs)


def service_account(home, name):
    confdir = make_account_dir(home, name, config="", refresh_token=True)
    unit = home / ".config" / "systemd" / "user" / f"{name}.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f'[Service]\nExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/{name}"\n')
    return confdir


def set_state(controller, confdir, key):
    controller.accounts.set_statuses({str(confdir): AccountStatus(ServiceState(key))})
    controller.statusesChanged.emit()


def texts(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


class Recorder:
    def __init__(self, signal):
        self.count = 0
        self.args = []
        signal.connect(self)

    def __call__(self, *args):
        self.count += 1
        self.args.append(args)


# The tray icon

def test_icon_tone_tooltip_and_menu_follow_the_states(app, home, tmp_path):
    a = service_account(home, "onedrive-a")
    b = service_account(home, "onedrive-b")
    controller = make_controller(home, tmp_path)
    tray = Tray(controller, home)

    set_state(controller, a, "running")
    set_state(controller, b, "running")
    assert tray.tone == "success"
    assert tray.icon.toolTip().splitlines() == ["Skyhus", "a: Running", "b: Running"]

    set_state(controller, b, "needs_resync")

    assert tray.tone == "danger"
    assert "b: Needs resync" in tray.icon.toolTip()
    assert texts(tray.menu) == ["Open Skyhus", "a — Running", "Restart a", "b — Needs resync",
                                "Restart b with resync …", "Start Skyhus at login", "Quit Skyhus"]


def test_icon_with_dot_differs_from_the_quiet_icon(app):
    quiet = render_icon("success").pixmap(32, 32).toImage()
    danger = render_icon("danger").pixmap(32, 32).toImage()
    warning = render_icon("warning").pixmap(32, 32).toImage()

    assert quiet != danger
    assert danger != warning


def test_restart_item_calls_the_card_action(app, home, tmp_path):
    a = service_account(home, "onedrive-a")
    controller = make_controller(home, tmp_path)
    tray = Tray(controller, home)
    set_state(controller, a, "running")
    called = []
    controller.serviceAction = lambda confdir: called.append(confdir)

    next(x for x in tray.menu.actions() if x.text() == "Restart a").trigger()

    assert called == [str(a)]


def test_resync_item_shows_the_window_and_the_confirmation(app, home, tmp_path):
    a = service_account(home, "onedrive-a")
    controller = make_controller(home, tmp_path)
    tray = Tray(controller, home)
    set_state(controller, a, "needs_resync")
    shown = Recorder(controller.showWindowRequested)

    next(x for x in tray.menu.actions() if x.text() == "Restart a with resync …").trigger()

    assert shown.count == 1
    assert controller.resyncAccountName == "a"


def test_autostart_item_follows_the_file(app, home, tmp_path):
    script = install.script_path(home)
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n")
    controller = make_controller(home, tmp_path)
    tray = Tray(controller, home)
    item = next(x for x in tray.menu.actions() if x.text() == "Start Skyhus at login")
    assert item.isEnabled() and not item.isChecked()

    item.setChecked(True)

    assert autostart.state(home) == autostart.ON
    item = next(x for x in tray.menu.actions() if x.text() == "Start Skyhus at login")
    assert item.isChecked()


def test_autostart_item_is_disabled_without_the_start_script(app, home, tmp_path):
    controller = make_controller(home, tmp_path)
    tray = Tray(controller, home)

    item = next(x for x in tray.menu.actions() if x.text() == "Start Skyhus at login")

    assert not item.isEnabled()
    assert "python3 -m skyhus.install" in item.toolTip()


def test_quit_item_calls_quit(app, home, tmp_path):
    controller = make_controller(home, tmp_path)
    controller.setTrayActive(True)
    tray = Tray(controller, home)
    ready = Recorder(controller.quitReady)

    next(x for x in tray.menu.actions() if x.text() == "Quit Skyhus").trigger()

    assert ready.count == 1


# Close and quit

def test_close_with_tray_hides_the_window_and_shows_the_hint_once(app, home, tmp_path):
    controller = make_controller(home, tmp_path)
    controller.setTrayActive(True)
    hidden = Recorder(controller.hideWindowRequested)
    messages = Recorder(controller.trayMessageRequested)

    assert controller.requestClose() is False
    assert controller.requestClose() is False

    assert hidden.count == 2
    assert messages.args == [("Skyhus", TRAY_HINT)]
    assert settings.get_flag(settings.TRAY_HINT_SHOWN, home) is True


def test_close_without_tray_works_as_before(app, home, tmp_path):
    controller = make_controller(home, tmp_path)
    hidden = Recorder(controller.hideWindowRequested)

    assert controller.requestClose() is True
    assert hidden.count == 0


def test_quit_during_a_critical_action_shows_the_window_and_waits(app, home, tmp_path):
    controller = make_controller(home, tmp_path)
    controller.setTrayActive(True)
    shown = Recorder(controller.showWindowRequested)
    ready = Recorder(controller.quitReady)
    controller._begin_critical("job", "Restarting onedrive-x.service")

    controller.quit()

    assert shown.count == 1
    assert controller.closing is True
    assert ready.count == 0

    controller._end_critical("job")
    controller._poll_close()

    assert ready.count == 1
    assert controller.requestClose() is True


def test_toggle_window(app, home, tmp_path):
    controller = make_controller(home, tmp_path)
    controller.setTrayActive(True)
    shown = Recorder(controller.showWindowRequested)
    hidden = Recorder(controller.hideWindowRequested)

    controller.setWindowVisible(True)
    controller.toggleWindow()
    controller.setWindowVisible(False)
    controller.toggleWindow()

    assert (hidden.count, shown.count) == (1, 1)


# Status in the background

def test_hidden_window_with_tray_reads_the_state_every_30_seconds(app, home, tmp_path):
    controller = make_controller(home, tmp_path)
    controller.setTrayActive(True)

    controller.setWindowVisible(False)

    assert controller._status_timer.isActive()
    assert controller._status_timer.interval() == STATUS_INTERVAL_HIDDEN_MS
    assert not controller._progress_timer.isActive()
    assert not controller._activity_timer.isActive()

    controller.setWindowVisible(True)

    assert controller._status_timer.interval() == STATUS_INTERVAL_MS
    assert controller._progress_timer.isActive()


def test_hidden_window_without_tray_stops_the_timer(app, home, tmp_path):
    controller = make_controller(home, tmp_path)
    controller.setWindowVisible(True)

    controller.setWindowVisible(False)

    assert not controller._status_timer.isActive()


# Single instance

def test_second_start_tells_the_first_to_show(app):
    from skyhus.app import single_instance
    name = f"skyhus-test-{uuid.uuid4().hex}"
    shown = []
    first = single_instance(name, lambda: shown.append(1))
    assert first is not None

    second = single_instance(name, lambda: shown.append(2))

    assert second is None
    end = time.monotonic() + 5
    while not shown and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    assert shown == [1]
    first.close()


def test_left_socket_file_does_not_stop_the_start(app, tmp_path):
    from PySide6.QtNetwork import QLocalServer
    from skyhus.app import single_instance
    name = f"skyhus-test-{uuid.uuid4().hex}"
    stale = QLocalServer()
    assert stale.listen(name)
    stale_path = stale.fullServerName()
    stale.close()
    # A crash leaves the socket file. close() removes it, so the test makes it again.
    open(stale_path, "w").close()

    server = single_instance(name, lambda: None)

    assert server is not None and server.isListening()
    server.close()


# QML

def test_window_can_start_hidden(load, home):
    from PySide6 import QtQml
    from skyhus.app import load_main
    engine = QtQml.QQmlApplicationEngine()
    controller = AppController(home, run=ScriptedRun())
    load_main(engine, controller, start_hidden=True)
    root = engine.rootObjects()[0]

    assert root.property("visible") is False

    controller.showWindow()
    QtWidgets.QApplication.instance().processEvents()
    assert root.property("visible") is True

    controller.hideWindowRequested.emit()
    QtWidgets.QApplication.instance().processEvents()
    assert root.property("visible") is False
    controller.shutdown()
    engine.deleteLater()
