"""Indlæsning af QML-filerne (feature 0001).

Testene bruger QT_QPA_PLATFORM=offscreen. LoginSheet.qml kræver QtWebEngine.
Testen springer over, hvis modulet ikke er installeret.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtGui = pytest.importorskip("PySide6.QtGui")
QtQml = pytest.importorskip("PySide6.QtQml")
from PySide6 import QtCore  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl  # noqa: E402

from onedrive_gui.app import QML_DIR, load_main  # noqa: E402
from onedrive_gui.viewmodels import AppController  # noqa: E402

from conftest import make_account_dir  # noqa: E402
from fakes import FakeGraph, ScriptedRun, folder  # noqa: E402


@pytest.fixture
def load(app):
    engines = []

    def _load(home, **kwargs):
        # Vinduet læser servicestatus, når det er synligt. Testen må ikke kalde den rigtige systemctl.
        kwargs.setdefault("run", ScriptedRun())
        controller = AppController(home, **kwargs)
        engine = QtQml.QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
        load_main(engine, controller)
        app.processEvents()
        engines.append((engine, controller))
        return engine, controller, warnings

    yield _load
    # Vinduet skal forsvinde før controlleren, som QML binder til.
    for engine, controller in engines:
        controller.shutdown()
        engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_main_qml_loads_without_warnings(load, home):
    engine, controller, warnings = load(home)

    assert engine.rootObjects(), warnings
    assert warnings == []
    root = engine.rootObjects()[0]
    assert root.findChild(QObject, "emptyLabel").property("visible") is True


def test_main_qml_lists_accounts(load, home):
    make_account_dir(home, "onedrive", refresh_token=True)
    make_account_dir(home, "onedrive-privat", config='sync_dir = "~/OneDrive-Privat"\n')

    engine, controller, warnings = load(home)

    assert warnings == []
    root = engine.rootObjects()[0]
    account_list = root.findChild(QObject, "accountList")
    assert account_list.property("count") == 2


def test_login_sheet_loads(app):
    pytest.importorskip("PySide6.QtWebEngineQuick")
    engine = QtQml.QQmlEngine()
    component = QtQml.QQmlComponent(engine, QUrl.fromLocalFile(str(QML_DIR / "sheets" / "LoginSheet.qml")))

    assert component.isReady(), component.errorString()


def test_folder_picker_and_confirmation_render_without_warnings(load, home, tmp_path):
    import time
    confdir = make_account_dir(home, "onedrive-x", config='sync_dir = "~/OneDrive-X"\n',
                               refresh_token=True, items=True)
    (confdir / "sync_list").write_text("# kommentar\n/A/\n/B/\n")
    (home / "OneDrive-X" / "B").mkdir(parents=True)
    unit = home / ".config" / "systemd" / "user" / "onedrive-x.service"
    unit.parent.mkdir(parents=True)
    unit.write_text('[Service]\nExecStart=/usr/bin/onedrive --confdir="%h/.config/onedrive-x"\n')
    proc = tmp_path / "proc"
    proc.mkdir()
    graph = FakeGraph({"/v1.0/me/drive/root/children": {"value": [folder("A"), folder("B", child_count=1)]}})
    engine, controller, warnings = load(home, opener=graph, proc_root=proc)
    app = QtGui.QGuiApplication.instance()

    controller.openFolderPicker(str(confdir))
    end = time.monotonic() + 5
    while controller.pickerState != "open" and time.monotonic() < end:
        controller._poll_picker()
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    root = engine.rootObjects()[0]
    picker = root.findChild(QObject, "folderPicker")
    assert picker.property("visible") is True
    assert root.findChild(QObject, "unknownRulesLabel").property("visible") is True

    controller.toggleFolder(1)
    controller.acceptPicker()
    end = time.monotonic() + 5
    while controller.pickerState != "confirm" and time.monotonic() < end:
        controller._poll_picker()
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert controller.pickerState == "confirm"
    assert root.findChild(QObject, "confirmRemoval").property("visible") is True
    assert warnings == []
    controller.cancelRemoval()
    controller.closePicker()
    app.processEvents()


# Design (feature 0003)

def visible_items(root, name):
    """Find synlige elementer i det visuelle træ. Delegates fra en ListView er
    ikke QObject-børn af vinduet, så findChildren finder dem ikke."""
    found = []

    def walk(item):
        if item.objectName() == name and item.isVisible():
            found.append(item)
        for child in item.childItems():
            walk(child)

    walk(root.contentItem())
    return found


def test_empty_state_shows_text_and_button(load, home):
    engine, controller, warnings = load(home)

    root = engine.rootObjects()[0]
    assert warnings == []
    assert root.findChild(QObject, "emptyState").property("visible") is True
    label = root.findChild(QObject, "emptyLabel")
    assert label.property("text") == "Ingen konti endnu"
    assert label.property("visible") is True
    assert root.findChild(QObject, "emptyAddButton").property("visible") is True
    assert root.findChild(QObject, "accountPage").property("visible") is False


def test_sidebar_shows_two_rows_with_avatars(load, home):
    make_account_dir(home, "onedrive", refresh_token=True)
    make_account_dir(home, "onedrive-privat", config='sync_dir = "~/OneDrive-Privat"\n')

    engine, controller, warnings = load(home)
    app = QtGui.QGuiApplication.instance()
    app.processEvents()

    root = engine.rootObjects()[0]
    assert warnings == []
    rows = visible_items(root, "sidebarRow")
    assert len(rows) == 2
    assert len(visible_items(root, "avatar")) >= 2
    assert root.findChild(QObject, "emptyState").property("visible") is False
    assert root.findChild(QObject, "accountPage").property("visible") is True


def test_window_has_minimum_size(load, home):
    engine, controller, warnings = load(home)
    root = engine.rootObjects()[0]

    assert root.property("width") == 960
    assert root.property("height") == 620
    assert root.property("minimumWidth") == 820
    assert root.property("minimumHeight") == 540
    # Vinduessystemet håndhæver mindstestørrelsen. Platformen "offscreen" gør det
    # ikke, så testen kontrollerer den størrelse, som vinduet giver videre.
    assert root.minimumSize() == QtCore.QSize(820, 540)


def test_main_qml_uses_theme_background(load, home):
    from PySide6.QtGui import QColor

    engine, controller, warnings = load(home)
    root = engine.rootObjects()[0]

    assert warnings == []
    content = root.findChild(QObject, "content")
    sidebar = root.findChild(QObject, "sidebar")
    theme = engine.singletonInstance("OneDriveGui", "Theme")
    assert content.property("color") == theme.property("windowBg")
    assert sidebar.property("color") == theme.property("sidebarBg")
    assert isinstance(content.property("color"), QColor)


# Servicestatus (feature 0004)

def service_show(name, active="active", status="0"):
    return (f"Id={name}\nLoadState=loaded\nActiveState={active}\nSubState=x\nResult=success\n"
            f"ExecMainStatus={status}\nMainPID=4242\n"
            "ActiveEnterTimestamp=Wed 2026-09-23 08:37:00 CEST\n"
            "InactiveEnterTimestamp=Wed 2026-09-23 08:36:00 CEST\n")


def service_home(home):
    make_account_dir(home, "onedrive-x", config="", refresh_token=True)
    unit = home / ".config" / "systemd" / "user" / "onedrive-x.service"
    unit.parent.mkdir(parents=True)
    unit.write_text('[Service]\nExecStart=/usr/bin/onedrive --confdir="%h/.config/onedrive-x"\n')


def read_status(controller):
    import time
    app = QtGui.QGuiApplication.instance()
    controller.refreshStatus()
    end = time.monotonic() + 5
    while controller._status_job is not None and time.monotonic() < end:
        controller._poll_status()
        time.sleep(0.01)
    app.processEvents()


def test_sidebar_dot_follows_service_state(load, home, tmp_path):
    from fakes import ScriptedRun
    service_home(home)
    proc = tmp_path / "proc"
    proc.mkdir()
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")})
    engine, controller, warnings = load(home, run=run, proc_root=proc)
    root = engine.rootObjects()[0]

    read_status(controller)
    dots = visible_items(root, "sidebarStatusDot")
    assert [d.property("tone") for d in dots] == ["success"]
    assert root.findChild(QObject, "serviceStateLabel").property("text") == "Kører"

    run.outputs["show"] = service_show("onedrive-x.service", "failed")
    read_status(controller)

    assert [d.property("tone") for d in visible_items(root, "sidebarStatusDot")] == ["danger"]
    assert root.findChild(QObject, "serviceStateLabel").property("text") == "Fejlet"
    assert root.findChild(QObject, "serviceActionButton").property("text") == "Start"
    assert warnings == []


def test_resync_confirmation_opens_before_anything_happens(load, home, tmp_path):
    from fakes import ScriptedRun
    service_home(home)
    proc = tmp_path / "proc"
    proc.mkdir()
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service", "failed", "126")})
    engine, controller, warnings = load(home, run=run, proc_root=proc)
    root = engine.rootObjects()[0]
    read_status(controller)
    calls = list(run.calls)

    controller.serviceAction(str(home / ".config" / "onedrive-x"))
    QtGui.QGuiApplication.instance().processEvents()

    sheet = root.findChild(QObject, "confirmResync")
    assert sheet.property("visible") is True
    assert run.calls == calls
    controller.cancelResync()
    # Arket glider ud, før det bliver usynligt.
    import time
    end = time.monotonic() + 2
    while sheet.property("visible") and time.monotonic() < end:
        QtGui.QGuiApplication.instance().processEvents()
        time.sleep(0.01)
    assert sheet.property("visible") is False
    assert warnings == []


def test_minimized_window_stops_status_timer(load, home, tmp_path):
    from PySide6.QtGui import QWindow
    from fakes import ScriptedRun
    service_home(home)
    proc = tmp_path / "proc"
    proc.mkdir()
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")})
    engine, controller, warnings = load(home, run=run, proc_root=proc)
    root = engine.rootObjects()[0]
    app = QtGui.QGuiApplication.instance()

    assert controller._status_timer.isActive() is True
    root.setVisibility(QWindow.Visibility.Minimized)
    app.processEvents()
    assert controller._status_timer.isActive() is False
    root.setVisibility(QWindow.Visibility.Windowed)
    app.processEvents()
    assert controller._status_timer.isActive() is True
    read_status(controller)


# Log ind igen med --reauth (feature 0005)

def test_login_sheet_says_that_the_service_is_stopped(load, home, tmp_path):
    import time
    from fakes import FakePopen, ScriptedRun
    service_home(home)
    proc = tmp_path / "proc"
    proc.mkdir()
    popen = FakePopen()
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")})
    engine, controller, warnings = load(home, run=run, popen=popen, proc_root=proc)
    root = engine.rootObjects()[0]
    app = QtGui.QGuiApplication.instance()
    note = root.findChild(QObject, "loginNote")
    assert note.property("visible") is False

    controller.login(str(home / ".config" / "onedrive-x"))
    end = time.monotonic() + 5
    while not popen.processes and time.monotonic() < end:
        controller._poll()
        time.sleep(0.01)
    controller._poll()
    app.processEvents()

    assert controller.loginState == "starting"
    assert note.property("text") == "Servicen er stoppet, mens du logger ind"
    assert note.property("visible") is True
    assert warnings == []


# Sikker tilstand (feature 0007)

SAFE_MODE_TEXT = "Sikker tilstand – applikationen ændrer ikke noget på systemet"


def test_safe_mode_shows_banner(load, home):
    engine, controller, warnings = load(home)
    root = engine.rootObjects()[0]

    assert warnings == []
    assert root.property("safeMode") is True
    banner = root.findChild(QObject, "safeModeBanner")
    assert banner.property("visible") is True
    assert root.findChild(QObject, "safeModeText").property("text") == SAFE_MODE_TEXT


def test_banner_is_hidden_without_safe_mode(load, home, monkeypatch):
    from onedrive_gui import sideeffects
    monkeypatch.setenv("HOME", str(sideeffects.real_home()))
    monkeypatch.delenv(sideeffects.ENV_VAR)
    sideeffects.init(["onedrive-gui"])
    assert sideeffects.safe_mode() is False

    engine, controller, warnings = load(home)
    root = engine.rootObjects()[0]

    assert warnings == []
    assert root.property("safeMode") is False
    banner = root.findChild(QObject, "safeModeBanner")
    assert banner is None or banner.property("visible") is False


# Luk under arbejde (feature 0008)

def test_closing_during_a_restart_shows_the_closing_sheet(load, home, tmp_path):
    import threading
    import time
    from fakes import ScriptedRun
    service_home(home)
    proc = tmp_path / "proc"
    proc.mkdir()
    reached, release = threading.Event(), threading.Event()

    def on_call(args):
        if "restart" in args:
            reached.set()
            release.wait(5)

    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")}, on_call=on_call)
    engine, controller, warnings = load(home, run=run, proc_root=proc)
    root = engine.rootObjects()[0]
    app = QtGui.QGuiApplication.instance()
    read_status(controller)
    controller.serviceAction(str(home / ".config" / "onedrive-x"))
    assert reached.wait(5)

    root.close()
    app.processEvents()

    assert root.property("visible") is True
    sheet = root.findChild(QObject, "closingSheet")
    assert sheet.property("visible") is True
    assert "onedrive-x.service" in root.findChild(QObject, "closingText").property("text")
    release.set()
    end = time.monotonic() + 5
    while root.property("visible") and time.monotonic() < end:
        controller._poll_status()
        controller._poll_close()
        app.processEvents()
        time.sleep(0.01)
    assert root.property("visible") is False
    assert warnings == []


# Fremdrift (feature 0009)

def pump_until(controller, predicate, timeout=5.0):
    """Kør timerne i hånden, til ``predicate`` er sand. QML ser ændringerne efter hver runde."""
    import time
    app = QtGui.QGuiApplication.instance()
    end = time.monotonic() + timeout
    while True:
        controller._poll_picker()
        controller._poll_status()
        app.processEvents()
        if predicate() or time.monotonic() >= end:
            break
        time.sleep(0.01)
    assert predicate()


def test_apply_progress_sheet_shows_the_five_steps(load, home, tmp_path):
    import threading
    from fakes import FakeUploadPopen
    confdir = make_account_dir(home, "onedrive-x", config='sync_dir = "~/OneDrive-X"\n',
                               refresh_token=True, items=True)
    (confdir / "sync_list").write_text("/A/\n")
    (home / "OneDrive-X" / "A").mkdir(parents=True)
    unit = home / ".config" / "systemd" / "user" / "onedrive-x.service"
    unit.parent.mkdir(parents=True)
    unit.write_text('[Service]\nExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-x"\n')
    proc = tmp_path / "proc"
    proc.mkdir()
    reached, release = threading.Event(), threading.Event()

    def on_line(line):
        if "budget" in line:
            reached.set()
            assert release.wait(5)

    popen = FakeUploadPopen(["New items to upload to Microsoft OneDrive: 3",
                             "Uploading new file: ./A/noter.md ... done",
                             "Uploading new file: ./A/budget.ods ... done"], on_line=on_line)
    graph = FakeGraph({"/v1.0/me/drive/root/children": {"value": [folder("A"), folder("B")]}})
    engine, controller, warnings = load(home, opener=graph, proc_root=proc, popen=popen,
                                        run=ScriptedRun(outputs={"cat": unit.read_text()}),
                                        trash=lambda p: True)
    root = engine.rootObjects()[0]
    controller.openFolderPicker(str(confdir))
    pump_until(controller, lambda: controller.pickerState == "open")
    controller.toggleFolder(1)
    controller.acceptPicker()
    pump_until(controller, reached.is_set)
    pump_until(controller, lambda: controller.applySteps and controller.applySteps[1]["detail"] == "1 af 3 filer")

    sheet = root.findChild(QObject, "applyProgressSheet")
    assert sheet.property("visible") is True
    assert sheet.property("title") == "Ændrer mappevalg"
    rows = visible_items(root, "applyStepRow")
    assert len(rows) == 5
    bars = visible_items(root, "applyStepBar")
    assert len(bars) == 1
    assert bars[0].property("indeterminate") is False
    assert bars[0].property("value") == pytest.approx(1 / 3)
    release.set()
    pump_until(controller, lambda: controller.pickerState == "closed")
    assert warnings == []


def resync_qml(home, tmp_path, *messages):
    import json
    from fakes import ScriptedRun
    from test_process import add_process
    service_home(home)
    proc = tmp_path / "proc"
    add_process(proc, 4242, ["/usr/bin/onedrive", "--monitor", "--confdir=" + str(home / ".config" / "onedrive-x"),
                             "--resync", "--resync-auth"],
                "0::/user.slice/user@1000.service/app.slice/onedrive-x.service\n")
    journal = "".join(json.dumps({"SYSLOG_IDENTIFIER": "onedrive", "_PID": "4242",
                                  "__CURSOR": f"s=1;i={i}", "__REALTIME_TIMESTAMP": "1790143816000000",
                                  "MESSAGE": m}) + "\n" for i, m in enumerate(messages))
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service") + "InvocationID=abc\n",
                               "journalctl": journal})
    return run, proc


def test_service_card_shows_a_determinate_bar_at_30_of_120(load, home, tmp_path):
    lines = [f"Downloading file: Ferie/IMG_{i:04}.JPG ... done" for i in range(30)]
    run, proc = resync_qml(home, tmp_path, "Number of items to download from Microsoft OneDrive: 120", *lines)
    engine, controller, warnings = load(home, run=run, proc_root=proc)
    root = engine.rootObjects()[0]

    read_status(controller)

    assert root.findChild(QObject, "serviceStateLabel").property("text") == "Resynkroniserer"
    assert [d.property("tone") for d in visible_items(root, "sidebarStatusDot")] == ["warning"]
    bar = root.findChild(QObject, "serviceProgressBar")
    assert bar.property("visible") is True
    assert bar.property("indeterminate") is False
    assert bar.property("value") == pytest.approx(0.25)
    assert root.findChild(QObject, "serviceProgressCounter").property("text") == "30 af 120 filer"
    assert root.findChild(QObject, "serviceProgressPhase").property("text") == "Downloader filer"
    assert warnings == []


def test_service_card_shows_an_indeterminate_bar_without_a_total(load, home, tmp_path):
    run, proc = resync_qml(home, tmp_path,
                           "Fetching items from the OneDrive API for Drive ID: 0a1b2c3d4e5f6789 ....")
    engine, controller, warnings = load(home, run=run, proc_root=proc)
    root = engine.rootObjects()[0]

    read_status(controller)

    bar = root.findChild(QObject, "serviceProgressBar")
    assert bar.property("visible") is True
    assert bar.property("indeterminate") is True
    assert root.findChild(QObject, "serviceProgressPhase").property("text") == "Henter listen fra OneDrive"
    assert warnings == []


def test_service_card_shows_that_the_resync_is_finished(load, home, tmp_path):
    run, proc = resync_qml(home, tmp_path, "Number of items to download from Microsoft OneDrive: 1",
                           "Downloading file: Ferie/IMG_0000.JPG ... done",
                           "Sync with Microsoft OneDrive is complete")
    engine, controller, warnings = load(home, run=run, proc_root=proc)
    root = engine.rootObjects()[0]

    read_status(controller)

    assert root.findChild(QObject, "serviceStateLabel").property("text") == "Kører"
    assert root.findChild(QObject, "serviceProgressBar").property("visible") is False
    assert root.findChild(QObject, "serviceProgressResult").property("text") == "Resync er færdig"
    assert warnings == []
