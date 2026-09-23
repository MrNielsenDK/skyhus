"""AppController binder logikken til QML (feature 0001)."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")

from onedrive_gui.registry import Registry  # noqa: E402
from onedrive_gui.viewmodels import AppController  # noqa: E402

from conftest import RecordingRun, make_account_dir  # noqa: E402
from fakes import FakeGraph, FakePopen, FakeSignals, FakeStoppablePopen, FakeUploadPopen, ScriptedRun, folder, http_error  # noqa: E402

ROOT_CHILDREN = "/v1.0/me/drive/root/children"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1"
CODE_URL = "https://login.microsoftonline.com/common/oauth2/nativeclient?code=abc"


def wait_for(controller, state, timeout=5.0):
    end = time.monotonic() + timeout
    while controller.loginState != state and time.monotonic() < end:
        controller._poll()
        controller._poll_picker()
        time.sleep(0.01)
    assert controller.loginState == state


def wait_for_picker(controller, state, timeout=5.0):
    end = time.monotonic() + timeout
    while controller.pickerState != state and time.monotonic() < end:
        controller._poll_picker()
        time.sleep(0.01)
    assert controller.pickerState == state, controller.pickerError


def row_of(controller, path):
    model = controller.folders
    for row in range(model.rowCount()):
        if model.data(model.index(row), model.PathRole) == path:
            return row
    raise AssertionError(f"{path} findes ikke i træet")


def check_state(controller, path):
    model = controller.folders
    return model.data(model.index(row_of(controller, path)), model.CheckStateRole)


def make_controller(home, tmp_path, **kwargs):
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    kwargs.setdefault("opener", FakeGraph({ROOT_CHILDREN: {"value": [folder("A"), folder("B")]}}))
    return AppController(home, proc_root=proc, **kwargs)


def test_add_account_logs_in_and_starts_service(app, home, tmp_path):
    popen, run = FakePopen(), RecordingRun()
    graph = FakeGraph({ROOT_CHILDREN: {"value": [folder("Dokumenter"), folder("Billeder")]}})
    controller = make_controller(home, tmp_path, popen=popen, run=run, opener=graph)

    assert controller.addAccount("Firma 2", "~/OneDrive-Firma-2") == ""
    confdir = home / ".config" / "onedrive-firma-2"
    assert (confdir / "config").read_text() == 'sync_dir = "~/OneDrive-Firma-2"\n'
    assert controller.accounts.count == 1

    popen.last.write_auth_url(AUTH_URL)
    wait_for(controller, "waiting_for_user")
    assert controller.authUrl == AUTH_URL

    assert controller.submitRedirect(CODE_URL) is True
    (confdir / "refresh_token").write_text("ny")
    popen.last.exit(0)
    wait_for(controller, "choosing_folders")

    # Servicen starter først, når brugeren har valgt mapper.
    assert run.calls == []
    wait_for_picker(controller, "open")
    # En ny konto har ingen sync_list. Derfor er "Synkroniser alle mapper" valgt.
    assert controller.syncAll is True
    controller.setSyncAll(False)
    controller.toggleFolder(row_of(controller, "Dokumenter"))
    controller.acceptPicker()
    wait_for(controller, "idle")
    assert (confdir / "sync_list").read_text() == "/Dokumenter/\n"

    assert controller.pickerState == "closed"
    assert run.calls[-1] == ["systemctl", "--user", "enable", "--now", "onedrive-firma-2.service"]
    assert "onedrive-firma-2.service" in controller.message
    assert controller.accounts.data(controller.accounts.index(0), controller.accounts.LoggedInRole) is True


def test_add_account_with_existing_name_creates_nothing(app, home):
    make_account_dir(home, "onedrive-privat", config="")
    Registry.for_home(home).set_name(home / ".config" / "onedrive-privat", "Firma 2")
    controller = AppController(home, popen=FakePopen(), run=RecordingRun())

    error = controller.addAccount("Firma 2", "~/OneDrive-Firma-2")

    assert error
    assert not (home / ".config" / "onedrive-firma-2").exists()
    assert not (home / "OneDrive-Firma-2").exists()
    assert controller.loginState == "idle"


def test_cancel_login(app, home):
    popen, run = FakePopen(), RecordingRun()
    controller = AppController(home, popen=popen, run=run, send_signal=FakeSignals())
    controller.addAccount("Firma 2", "~/OneDrive-Firma-2")

    controller.cancelLogin()

    assert popen.last.terminated
    assert controller.loginState == "idle"
    assert run.calls == []


def test_rename_survives_restart(app, home):
    confdir = make_account_dir(home, "onedrive", refresh_token=True)
    controller = AppController(home)

    assert controller.rename(str(confdir), "Firma 1") == ""
    assert controller.rename(str(confdir), "  ") != ""

    again = AppController(home)
    model = again.accounts
    assert model.data(model.index(0), model.NameRole) == "Firma 1"


def test_closing_picker_after_login_leaves_account_without_service(app, home, tmp_path):
    popen, run = FakePopen(), RecordingRun()
    controller = make_controller(home, tmp_path, popen=popen, run=run)
    controller.addAccount("Firma 2", "~/OneDrive-Firma-2")
    confdir = home / ".config" / "onedrive-firma-2"
    popen.last.write_auth_url(AUTH_URL)
    wait_for(controller, "waiting_for_user")
    controller.submitRedirect(CODE_URL)
    (confdir / "refresh_token").write_text("ny")
    popen.last.exit(0)
    wait_for(controller, "choosing_folders")
    wait_for_picker(controller, "open")

    controller.closePicker()
    wait_for(controller, "idle")

    assert run.calls == []
    assert not (home / ".config" / "systemd" / "user" / "onedrive-firma-2.service").exists()
    assert not (confdir / "sync_list").exists()
    model = controller.accounts
    assert model.data(model.index(0), model.LoggedInRole) is True
    assert model.data(model.index(0), model.ServiceRole) == ""


def test_picker_without_refresh_token_shows_not_logged_in(app, home, tmp_path):
    confdir = make_account_dir(home, "onedrive-x", config="")
    graph = FakeGraph()
    controller = make_controller(home, tmp_path, opener=graph)

    controller.openFolderPicker(str(confdir))

    assert "Kontoen er ikke logget ind" in controller.message
    assert controller.pickerState == "closed"
    assert graph.requests == []


def test_picker_with_invalid_grant_asks_to_log_in_again(app, home, tmp_path):
    confdir = make_account_dir(home, "onedrive-x", config="", refresh_token=True)
    graph = FakeGraph(token=http_error(TOKEN_URL, 400, {"error": "invalid_grant"}))
    controller = make_controller(home, tmp_path, opener=graph)

    controller.openFolderPicker(str(confdir))
    end = time.monotonic() + 5
    while not controller.pickerError and time.monotonic() < end:
        controller._poll_picker()
        time.sleep(0.01)

    assert "ind igen" in controller.pickerError
    assert controller.folders.rowCount() == 0


def test_picker_shows_current_selection_and_loads_subfolders(app, home, tmp_path):
    confdir = make_account_dir(home, "onedrive-x", config="", refresh_token=True)
    (confdir / "sync_list").write_text("# kommentar\n/A/\n")
    graph = FakeGraph({
        ROOT_CHILDREN: {"value": [folder("A", child_count=1), folder("B")]},
        "/v1.0/me/drive/items/id-A/children": {"value": [folder("Kunder")]},
    })
    controller = make_controller(home, tmp_path, opener=graph)

    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")

    assert controller.syncAll is False
    assert controller.pickerUnknownRules is True
    assert check_state(controller, "A") == 2
    assert check_state(controller, "B") == 0
    controller.expandFolder(row_of(controller, "A"))
    end = time.monotonic() + 5
    while controller.folders.rowCount() < 3 and time.monotonic() < end:
        controller._poll_picker()
        time.sleep(0.01)
    assert check_state(controller, "A/Kunder") == 2


def test_no_folders_selected_shows_error_and_writes_nothing(app, home, tmp_path):
    confdir = make_account_dir(home, "onedrive-x", config="", refresh_token=True)
    (confdir / "sync_list").write_text("/A/\n")
    controller = make_controller(home, tmp_path)
    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")

    controller.toggleFolder(row_of(controller, "A"))
    controller.acceptPicker()

    assert controller.pickerError
    assert controller.pickerState == "open"
    assert (confdir / "sync_list").read_text() == "/A/\n"


def synced_account(home):
    confdir = make_account_dir(home, "onedrive-x", config='sync_dir = "~/OneDrive-X"\n',
                               refresh_token=True, items=True)
    (confdir / "sync_list").write_text("/A/\n/B/\n")
    (home / "OneDrive-X" / "A").mkdir(parents=True)
    (home / "OneDrive-X" / "B").mkdir()
    unit = home / ".config" / "systemd" / "user" / "onedrive-x.service"
    unit.parent.mkdir(parents=True)
    unit.write_text('[Service]\nExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-x"\n')
    return confdir


def test_rejecting_confirmation_changes_nothing(app, home, tmp_path):
    confdir = synced_account(home)
    run = ScriptedRun()
    trashed = []
    controller = make_controller(home, tmp_path, run=run, trash=trashed.append)
    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")

    controller.toggleFolder(row_of(controller, "B"))
    controller.acceptPicker()

    wait_for_picker(controller, "confirm")
    assert controller.removalItems == [str(home / "OneDrive-X" / "B")]
    controller.cancelRemoval()

    assert controller.pickerState == "open"
    assert run.calls == []
    assert trashed == []
    assert (confdir / "sync_list").read_text() == "/A/\n/B/\n"


def test_confirming_removal_applies_the_change(app, home, tmp_path):
    confdir = synced_account(home)
    run = ScriptedRun(outputs={"cat": '[Service]\nExecStart=/usr/bin/onedrive --monitor\n'})
    trashed = []
    controller = make_controller(home, tmp_path, run=run, popen=FakeUploadPopen(),
                                 trash=lambda p: trashed.append(p) or True)
    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")
    controller.toggleFolder(row_of(controller, "B"))
    controller.acceptPicker()
    wait_for_picker(controller, "confirm")

    controller.confirmRemoval()
    wait_for_picker(controller, "closed")

    assert trashed == [home / "OneDrive-X" / "B"]
    assert (confdir / "sync_list").read_text() == "/A/\n"
    assert ["systemctl", "--user", "restart", "onedrive-x.service"] in run.calls


def test_only_adding_folders_skips_confirmation(app, home, tmp_path):
    confdir = synced_account(home)
    (confdir / "sync_list").write_text("/A/\n")
    run = ScriptedRun(outputs={"cat": '[Service]\nExecStart=/usr/bin/onedrive --monitor\n'})
    controller = make_controller(home, tmp_path, run=run, popen=FakeUploadPopen(), trash=lambda p: True)
    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")

    controller.toggleFolder(row_of(controller, "B"))
    controller.acceptPicker()

    states = set()
    end = time.monotonic() + 5
    while controller.pickerState != "closed" and time.monotonic() < end:
        states.add(controller.pickerState)
        controller._poll_picker()
        time.sleep(0.01)
    assert controller.pickerState == "closed"
    assert "confirm" not in states
    assert (confdir / "sync_list").read_text() == "/A/\n/B/\n"


def test_account_model_gives_initials_and_avatar_color(home):
    from onedrive_gui import theme

    make_account_dir(home, "onedrive-firma", config='sync_dir = "~/OneDrive-Firma"\n')
    Registry.for_home(home).add(home / ".config" / "onedrive-firma", "Firma 2")
    controller = AppController(home)
    model = controller.accounts
    index = model.index(0)
    account = model.accounts()[0]

    assert model.data(index, model.InitialsRole) == "F2"
    assert model.data(index, model.AvatarColorRole) == theme.avatar_color(account)
    assert model.data(index, model.AvatarTextColorRole) == theme.avatar_text_color(account)


# Servicestatus og genstart (feature 0004)

def service_show(name, active="active", status="0", pid="4242"):
    return (f"Id={name}\nLoadState=loaded\nActiveState={active}\nSubState=x\nResult=success\n"
            f"ExecMainStatus={status}\nMainPID={pid}\n"
            "ActiveEnterTimestamp=Wed 2026-09-23 08:37:00 CEST\n"
            "InactiveEnterTimestamp=Wed 2026-09-23 08:36:00 CEST\n")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def service_account(home, name="onedrive-x"):
    confdir = make_account_dir(home, name, config="", refresh_token=True)
    unit = home / ".config" / "systemd" / "user" / f"{name}.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f'[Service]\nExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/{name}"\n')
    return confdir


def role(controller, name, row=0):
    model = controller.accounts
    roles = {bytes(v).decode(): k for k, v in model.roleNames().items()}
    return model.data(model.index(row), roles[name])


def wait_until(predicate, controller, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        controller._poll_status()
        time.sleep(0.01)
    assert predicate()


def read_status_now(controller):
    controller.refreshStatus()
    wait_until(lambda: controller._status_job is None, controller)


def test_status_appears_in_the_account_model(app, home, tmp_path):
    service_account(home)
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")})
    controller = make_controller(home, tmp_path, run=run)

    read_status_now(controller)

    assert role(controller, "serviceLabel") == "Kører"
    assert role(controller, "serviceTone") == "success"
    assert role(controller, "serviceActionLabel") == "Genstart"
    assert role(controller, "serviceSince").endswith("kl. 08:37")
    assert role(controller, "serviceBusy") is False


def test_restart_calls_reset_failed_then_restart(app, home, tmp_path):
    confdir = service_account(home)
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service", "failed")})
    clock = Clock()
    controller = make_controller(home, tmp_path, run=run, clock=clock, sleep=clock.sleep)
    read_status_now(controller)
    assert role(controller, "serviceActionLabel") == "Start"

    controller.serviceAction(str(confdir))
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)

    actions = [c for c in run.calls if c[2] in ("reset-failed", "restart")]
    assert actions == [
        ["systemctl", "--user", "reset-failed", "onedrive-x.service"],
        ["systemctl", "--user", "restart", "onedrive-x.service"],
    ]


def test_resync_waits_for_confirmation(app, home, tmp_path):
    confdir = service_account(home)
    cat = '[Service]\nExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-x"\n'
    seen = {}
    drop_in = home / ".config" / "systemd" / "user" / "onedrive-x.service.d" / "zz-onedrive-gui-resync.conf"

    def on_call(args):
        if "restart" in args:
            seen["drop_in"] = drop_in.read_text()

    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service", "failed", "126", "0"),
                               "cat": cat}, on_call=on_call)
    clock = Clock()
    controller = make_controller(home, tmp_path, run=run, clock=clock, sleep=clock.sleep)
    read_status_now(controller)
    assert role(controller, "serviceActionLabel") == "Genstart med resync"
    calls_before = list(run.calls)

    controller.serviceAction(str(confdir))

    assert controller.resyncAccountName == role(controller, "name")
    assert run.calls == calls_before
    assert role(controller, "serviceBusy") is False
    controller.cancelResync()
    assert controller.resyncAccountName == ""
    assert run.calls == calls_before

    controller.serviceAction(str(confdir))
    controller.confirmResync()
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)

    assert "--resync --resync-auth" in seen["drop_in"]
    assert not drop_in.exists()
    assert controller.resyncAccountName == ""


def test_service_that_does_not_settle_shows_message(app, home, tmp_path):
    confdir = service_account(home)
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service", "activating")})
    clock = Clock()
    controller = make_controller(home, tmp_path, run=run, clock=clock, sleep=clock.sleep)
    read_status_now(controller)

    controller.serviceAction(str(confdir))
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)

    assert role(controller, "serviceMessage") == "Servicen svarer ikke."
    assert clock.now >= 120


def test_failing_restart_shows_systemctl_message(app, home, tmp_path):
    confdir = service_account(home)
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")}, fail={"restart"},
                      stderr="Failed to restart onedrive-x.service: Unit onedrive-x.service is masked.")
    clock = Clock()
    controller = make_controller(home, tmp_path, run=run, clock=clock, sleep=clock.sleep)
    read_status_now(controller)

    controller.serviceAction(str(confdir))
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)

    assert role(controller, "serviceMessage") == (
        "Failed to restart onedrive-x.service: Unit onedrive-x.service is masked.")


def test_second_click_while_waiting_does_nothing(app, home, tmp_path):
    import threading
    confdir = service_account(home)
    release = threading.Event()

    def on_call(args):
        if "restart" in args:
            release.wait(5)

    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")}, on_call=on_call)
    clock = Clock()
    controller = make_controller(home, tmp_path, run=run, clock=clock, sleep=clock.sleep)
    read_status_now(controller)

    controller.serviceAction(str(confdir))
    wait_until(lambda: ["systemctl", "--user", "restart", "onedrive-x.service"] in run.calls, controller)
    assert role(controller, "serviceBusy") is True
    controller.serviceAction(str(confdir))
    release.set()
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)

    assert run.calls.count(["systemctl", "--user", "restart", "onedrive-x.service"]) == 1
    assert run.calls.count(["systemctl", "--user", "reset-failed", "onedrive-x.service"]) == 1


def test_failing_show_keeps_state_and_says_so(app, home, tmp_path):
    service_account(home)
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")})
    controller = make_controller(home, tmp_path, run=run)
    read_status_now(controller)

    run.fail = {"show"}
    read_status_now(controller)

    assert role(controller, "serviceLabel") == "Kører"
    assert "Kan ikke læse status" in role(controller, "serviceMessage")


def test_status_timer_follows_window_visibility(app, home, tmp_path):
    service_account(home)
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")})
    controller = make_controller(home, tmp_path, run=run)

    assert controller._status_timer.isActive() is False
    controller.setWindowVisible(True)
    assert controller._status_timer.isActive() is True
    assert controller._status_timer.interval() == 3000
    controller.setWindowVisible(False)
    assert controller._status_timer.isActive() is False
    wait_until(lambda: controller._status_job is None, controller)


def test_no_status_is_read_before_the_window_is_visible(app, home, tmp_path):
    service_account(home)
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")})
    controller = make_controller(home, tmp_path, run=run)
    controller.refresh()

    assert run.calls == []
    assert role(controller, "serviceActionLabel") == ""


# Sikker tilstand (feature 0007)

CHANGING_SYSTEMCTL = {"start", "stop", "restart", "reset-failed", "daemon-reload", "enable", "disable"}


def test_restart_in_safe_mode_ends_without_error_and_changes_nothing(app, home, tmp_path, monkeypatch):
    import subprocess
    confdir = service_account(home)
    underlying = ScriptedRun(outputs={"show": service_show("onedrive-x.service")})
    monkeypatch.setattr(subprocess, "run", underlying)
    clock = Clock()
    # Controlleren får ingen falsk run. Den bruger standarden fra sideeffects.
    controller = make_controller(home, tmp_path, clock=clock, sleep=clock.sleep)
    read_status_now(controller)
    assert role(controller, "serviceActionLabel") == "Genstart"

    controller.serviceAction(str(confdir))
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)

    assert role(controller, "serviceMessage") == ""
    assert underlying.calls
    changing = [c for c in underlying.calls if c[0] == "systemctl" and c[2] in CHANGING_SYSTEMCTL]
    assert changing == []


# Log ind igen med --reauth (feature 0005)

def wait_for_client(controller, popen, timeout=5.0):
    end = time.monotonic() + timeout
    while not popen.processes and time.monotonic() < end:
        controller._poll()
        time.sleep(0.01)
    assert popen.processes


def relogin_controller(home, tmp_path, active="active", **kwargs):
    confdir = service_account(home)
    (confdir / "refresh_token").chmod(0o600)
    popen = FakePopen()
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service", active=active)}, **kwargs)
    controller = make_controller(home, tmp_path, popen=popen, run=run, send_signal=FakeSignals())
    return controller, confdir, popen, run


def changing(run):
    return [c for c in run.calls if "show" not in c]


def test_relogin_stops_service_shows_note_and_restarts(app, home, tmp_path):
    controller, confdir, popen, run = relogin_controller(home, tmp_path)

    controller.login(str(confdir))
    wait_for_client(controller, popen)
    assert "--reauth" in popen.last.args
    assert changing(run) == [["systemctl", "--user", "stop", "onedrive-x.service"]]
    popen.last.write_auth_url(AUTH_URL)
    wait_for(controller, "waiting_for_user")
    assert controller.loginNote == "Servicen er stoppet, mens du logger ind"

    assert controller.submitRedirect(CODE_URL) is True
    (confdir / "refresh_token").write_text("ny")
    popen.last.exit(0)
    wait_for(controller, "idle")

    assert controller.pickerState == "closed"
    assert changing(run)[-2:] == [["systemctl", "--user", "reset-failed", "onedrive-x.service"],
                                  ["systemctl", "--user", "restart", "onedrive-x.service"]]
    assert "onedrive-x.service kører" in controller.message
    assert controller.loginNote == ""


def test_cancelled_relogin_restores_token_and_restarts_service(app, home, tmp_path):
    controller, confdir, popen, run = relogin_controller(home, tmp_path)

    controller.login(str(confdir))
    wait_for_client(controller, popen)
    popen.last.write_auth_url(AUTH_URL)
    wait_for(controller, "waiting_for_user")
    controller.cancelLogin()
    wait_for(controller, "idle")

    assert (confdir / "refresh_token").read_text() == "token"
    assert (confdir / "refresh_token").stat().st_mode & 0o777 == 0o600
    assert changing(run) == [["systemctl", "--user", "stop", "onedrive-x.service"],
                             ["systemctl", "--user", "reset-failed", "onedrive-x.service"],
                             ["systemctl", "--user", "restart", "onedrive-x.service"]]


def test_relogin_of_stopped_service_does_not_start_it(app, home, tmp_path):
    controller, confdir, popen, run = relogin_controller(home, tmp_path, active="inactive")

    controller.login(str(confdir))
    wait_for_client(controller, popen)
    popen.last.write_auth_url(AUTH_URL)
    wait_for(controller, "waiting_for_user")
    assert controller.loginNote == ""
    controller.submitRedirect(CODE_URL)
    (confdir / "refresh_token").write_text("ny")
    popen.last.exit(0)
    wait_for(controller, "idle")

    assert changing(run) == []
    assert controller.message == "x er logget ind."


def test_failed_restart_after_cancel_is_shown(app, home, tmp_path):
    controller, confdir, popen, run = relogin_controller(home, tmp_path, fail={"restart"},
                                                         stderr="Job for onedrive-x.service failed.")

    controller.login(str(confdir))
    wait_for_client(controller, popen)
    popen.last.exit(1)
    wait_for(controller, "idle")

    assert "Login fejlede for x" in controller.message
    assert "Job for onedrive-x.service failed." in controller.message
    assert (confdir / "refresh_token").read_text() == "token"


def test_shutdown_during_relogin_restores_token_and_service(app, home, tmp_path):
    controller, confdir, popen, run = relogin_controller(home, tmp_path)

    controller.login(str(confdir))
    wait_for_client(controller, popen)
    popen.last.write_auth_url(AUTH_URL)
    wait_for(controller, "waiting_for_user")
    controller.shutdown()

    assert popen.last.terminated
    assert (confdir / "refresh_token").read_text() == "token"
    assert changing(run)[-1] == ["systemctl", "--user", "restart", "onedrive-x.service"]


# Luk under arbejde (feature 0008)

class Gate:
    """Hold et systemctl-kald tilbage, indtil testen åbner for det."""

    def __init__(self, word, service=None):
        import threading
        self.word = word
        self.service = service
        self.reached = threading.Event()
        self.release = threading.Event()

    def __call__(self, args):
        if self.word in args and (self.service is None or self.service in args):
            self.reached.set()
            assert self.release.wait(5), "Testen åbnede ikke for kaldet"


def gated_run(*gates, **kwargs):
    def on_call(args):
        for gate in gates:
            gate(args)

    return ScriptedRun(on_call=on_call, **kwargs)


def pump(controller, predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        controller._poll()
        controller._poll_picker()
        controller._poll_status()
        controller._poll_close()
        time.sleep(0.01)
    assert predicate()


def close_signals(controller):
    emitted = []
    controller.closeReady.connect(lambda: emitted.append(True))
    return emitted


def restarting_controller(home, tmp_path, gate):
    confdir = service_account(home)
    clock = Clock()
    run = gated_run(gate, outputs={"show": service_show("onedrive-x.service")})
    controller = make_controller(home, tmp_path, run=run, clock=clock, sleep=clock.sleep)
    read_status_now(controller)
    return controller, confdir, run


def test_request_close_without_critical_work_is_true(app, home, tmp_path):
    service_account(home)
    controller = make_controller(home, tmp_path, run=ScriptedRun())

    assert controller.requestClose() is True
    assert controller.busyText == ""


def test_restart_from_service_card_blocks_close(app, home, tmp_path):
    gate = Gate("restart")
    controller, confdir, run = restarting_controller(home, tmp_path, gate)
    emitted = close_signals(controller)

    controller.serviceAction(str(confdir))
    assert gate.reached.wait(5)

    assert controller.requestClose() is False
    assert "onedrive-x.service" in controller.busyText
    assert controller.closing is True
    controller._poll_close()
    assert emitted == []
    gate.release.set()
    pump(controller, lambda: bool(emitted))


def test_window_closes_when_the_work_is_done(app, home, tmp_path):
    gate = Gate("restart")
    controller, confdir, run = restarting_controller(home, tmp_path, gate)
    emitted = close_signals(controller)
    controller.serviceAction(str(confdir))
    assert gate.reached.wait(5)
    assert controller.requestClose() is False

    gate.release.set()
    pump(controller, lambda: bool(emitted))

    assert emitted == [True]
    assert controller.busyText == ""
    assert controller.requestClose() is True


def test_apply_execute_blocks_close_until_restart_is_done(app, home, tmp_path):
    confdir = synced_account(home)
    (confdir / "sync_list").write_text("/A/\n")
    gate = Gate("restart")
    run = gated_run(gate, outputs={"cat": '[Service]\nExecStart=/usr/bin/onedrive --monitor\n'})
    controller = make_controller(home, tmp_path, run=run, popen=FakeUploadPopen(), trash=lambda p: True)
    emitted = close_signals(controller)
    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")
    controller.toggleFolder(row_of(controller, "B"))
    controller.acceptPicker()
    pump(controller, gate.reached.is_set)

    assert controller.requestClose() is False
    assert controller.busyText != ""
    controller._poll_close()
    assert emitted == []
    gate.release.set()
    pump(controller, lambda: controller.pickerState == "closed")
    pump(controller, lambda: bool(emitted))

    assert ["systemctl", "--user", "restart", "onedrive-x.service"] in run.calls
    assert controller.requestClose() is True


def test_relogin_that_stops_the_service_blocks_close(app, home, tmp_path):
    gate = Gate("stop")
    controller, confdir, popen, run = relogin_controller(home, tmp_path, on_call=gate)

    controller.login(str(confdir))
    assert gate.reached.wait(5)

    assert controller.requestClose() is False
    assert "onedrive-x.service" in controller.busyText
    gate.release.set()
    wait_for_client(controller, popen)
    controller.cancelLogin()
    wait_for(controller, "idle")


def test_status_reading_alone_does_not_block_close(app, home, tmp_path):
    service_account(home)
    gate = Gate("show")
    run = gated_run(gate, outputs={"show": service_show("onedrive-x.service")})
    controller = make_controller(home, tmp_path, run=run)

    controller.refreshStatus()
    assert gate.reached.wait(5)

    assert controller.requestClose() is True
    gate.release.set()
    wait_until(lambda: controller._status_job is None, controller)


def test_force_close_closes_while_work_runs_and_logs_a_warning(app, home, tmp_path, caplog):
    import logging
    gate = Gate("restart")
    controller, confdir, run = restarting_controller(home, tmp_path, gate)
    emitted = close_signals(controller)
    controller.serviceAction(str(confdir))
    assert gate.reached.wait(5)
    assert controller.requestClose() is False
    text = controller.busyText

    with caplog.at_level(logging.WARNING, logger="onedrive_gui.viewmodels"):
        controller.forceClose()

    assert emitted == [True]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(text in r.getMessage() for r in warnings)
    assert controller.requestClose() is True
    gate.release.set()
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)


def test_window_waits_for_the_last_of_two_actions(app, home, tmp_path):
    first = service_account(home, "onedrive-x")
    second = service_account(home, "onedrive-y")
    gate_x = Gate("restart", "onedrive-x.service")
    gate_y = Gate("restart", "onedrive-y.service")
    show = service_show("onedrive-x.service") + "\n" + service_show("onedrive-y.service")
    clock = Clock()
    run = gated_run(gate_x, gate_y, outputs={"show": show})
    controller = make_controller(home, tmp_path, run=run, clock=clock, sleep=clock.sleep)
    read_status_now(controller)
    emitted = close_signals(controller)

    controller.serviceAction(str(first))
    controller.serviceAction(str(second))
    assert gate_x.reached.wait(5) and gate_y.reached.wait(5)
    assert controller.requestClose() is False
    assert "onedrive-x.service" in controller.busyText
    assert "onedrive-y.service" in controller.busyText

    gate_x.release.set()
    pump(controller, lambda: "onedrive-x.service" not in controller.busyText)
    controller._poll_close()
    assert emitted == []
    assert controller.requestClose() is False

    gate_y.release.set()
    pump(controller, lambda: bool(emitted))
    assert emitted == [True]


# Annullér under stop (feature 0008)

def test_cancel_while_the_service_stops_is_cancelling_at_once(app, home, tmp_path):
    gate = Gate("stop")
    controller, confdir, popen, run = relogin_controller(home, tmp_path, on_call=gate)
    controller.login(str(confdir))
    assert gate.reached.wait(5)

    controller.cancelLogin()

    assert controller.loginState == "cancelling"
    gate.release.set()
    wait_for(controller, "idle")


def test_cancel_during_stop_does_not_start_the_client(app, home, tmp_path):
    gate = Gate("stop")
    controller, confdir, popen, run = relogin_controller(home, tmp_path, on_call=gate)
    controller.login(str(confdir))
    assert gate.reached.wait(5)

    controller.cancelLogin()
    gate.release.set()
    wait_for(controller, "idle")

    assert popen.processes == []
    assert (confdir / "refresh_token").read_text() == "token"
    assert (confdir / "refresh_token").stat().st_mode & 0o777 == 0o600


def test_cancel_during_stop_starts_an_active_service_again(app, home, tmp_path):
    gate = Gate("stop")
    controller, confdir, popen, run = relogin_controller(home, tmp_path, on_call=gate)
    controller.login(str(confdir))
    assert gate.reached.wait(5)

    controller.cancelLogin()
    gate.release.set()
    wait_for(controller, "idle")

    assert changing(run) == [["systemctl", "--user", "stop", "onedrive-x.service"],
                             ["systemctl", "--user", "reset-failed", "onedrive-x.service"],
                             ["systemctl", "--user", "restart", "onedrive-x.service"]]


def test_failed_stop_after_cancel_shows_the_error(app, home, tmp_path):
    gate = Gate("stop")
    controller, confdir, popen, run = relogin_controller(
        home, tmp_path, on_call=gate, fail={"stop"},
        stderr="Failed to stop onedrive-x.service: Access denied")
    controller.login(str(confdir))
    assert gate.reached.wait(5)

    controller.cancelLogin()
    assert controller.loginState == "cancelling"
    gate.release.set()
    wait_for(controller, "idle")

    assert "Access denied" in controller.message
    assert popen.processes == []
    assert (confdir / "refresh_token").read_text() == "token"


# Fremdrift (feature 0009)

UPLOAD_LINES = [
    "Scanning the local file system '~/OneDrive-X' for new data to upload ..... ",
    "New items to upload to Microsoft OneDrive: 3",
    "Uploading new file: ./A/noter.md ... done",
    "Uploading new file: ./A/budget.ods ... done",
    "Uploading new file: ./A/plan.txt ... done",
    "Sync with Microsoft OneDrive is complete",
]


def start_change(home, tmp_path, popen):
    confdir = synced_account(home)
    run = ScriptedRun(outputs={"cat": '[Service]\nExecStart=/usr/bin/onedrive --monitor\n'})
    controller = make_controller(home, tmp_path, run=run, popen=popen, trash=lambda p: True)
    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")
    controller.toggleFolder(row_of(controller, "B"))
    controller.acceptPicker()
    wait_for_picker(controller, "confirm")
    controller.confirmRemoval()
    return controller, confdir, run


def step_states(controller):
    return [s["state"] for s in controller.applySteps]


def test_apply_sheet_shows_the_upload_while_it_runs(app, home, tmp_path):
    import threading
    reached, release = threading.Event(), threading.Event()

    def on_line(line):
        if "plan.txt" in line:
            reached.set()
            assert release.wait(5)

    controller, confdir, run = start_change(home, tmp_path, FakeUploadPopen(UPLOAD_LINES, on_line=on_line))
    assert reached.wait(5)
    pump(controller, lambda: controller.applySteps[1]["detail"] == "2 af 3 filer")

    assert controller.applyState == "running"
    assert [s["title"] for s in controller.applySteps] == [
        "Stopper servicen", "Uploader lokale ændringer", "Skriver de nye regler",
        "Flytter til papirkurven", "Starter servicen med resync"]
    assert step_states(controller) == ["done", "running", "waiting", "waiting", "waiting"]
    upload = controller.applySteps[1]
    assert upload["latest"] == "A/budget.ods"
    assert upload["determinate"] is True
    assert upload["value"] == pytest.approx(2 / 3)
    assert upload["stateText"] == "I gang"

    release.set()
    pump(controller, lambda: controller.pickerState == "closed")
    assert controller.applyState == ""


def test_apply_sheet_counts_the_trash_step(app, home, tmp_path):
    confdir = synced_account(home)
    gate = Gate("restart")
    run = gated_run(gate, outputs={"cat": '[Service]\nExecStart=/usr/bin/onedrive --monitor\n'})
    controller = make_controller(home, tmp_path, run=run, popen=FakeUploadPopen(UPLOAD_LINES),
                                 trash=lambda p: True)
    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")
    controller.toggleFolder(row_of(controller, "B"))
    controller.acceptPicker()
    wait_for_picker(controller, "confirm")
    controller.confirmRemoval()
    assert gate.reached.wait(5)
    pump(controller, lambda: step_states(controller)[4] == "running")

    assert step_states(controller) == ["done", "done", "done", "done", "running"]
    assert controller.applySteps[3]["detail"] == "1 af 1 sti"
    assert controller.applySteps[1]["detail"] == "3 af 3 filer"
    gate.release.set()
    pump(controller, lambda: controller.pickerState == "closed")


def test_failed_upload_keeps_the_sheet_with_the_failed_step(app, home, tmp_path):
    controller, confdir, run = start_change(
        home, tmp_path, FakeUploadPopen(["ERROR: Cannot connect to Microsoft OneDrive Service"], returncode=1))

    pump(controller, lambda: controller.pickerState == "open")

    assert controller.applyState == "failed"
    assert step_states(controller) == ["done", "failed", "waiting", "waiting", "waiting"]
    assert "Cannot connect" in controller.pickerError
    controller.closeApplyProgress()
    assert controller.applyState == ""
    assert controller.pickerState == "open"


def test_account_without_items_does_not_show_the_apply_sheet(app, home, tmp_path):
    confdir = make_account_dir(home, "onedrive-x", config='sync_dir = "~/OneDrive-X"\n', refresh_token=True)
    controller = make_controller(home, tmp_path, run=ScriptedRun(), popen=FakeUploadPopen())
    states = set()
    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")
    controller.toggleFolder(row_of(controller, "A"))
    controller.acceptPicker()
    pump(controller, lambda: states.add(controller.applyState) or controller.pickerState == "closed")

    assert states == {""}


INVOCATION = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


def resync_show(name):
    return service_show(name) + f"InvocationID={INVOCATION}\n"


def resync_journal(*messages, start=0):
    import json
    return "".join(json.dumps({"SYSLOG_IDENTIFIER": "onedrive", "_PID": "4242",
                               "_SYSTEMD_INVOCATION_ID": INVOCATION, "__CURSOR": f"s=1;i={start + i}",
                               "__REALTIME_TIMESTAMP": str((1790143816 + start + i) * 1_000_000),
                               "MESSAGE": m}) + "\n"
                   for i, m in enumerate(messages))


def resync_controller(home, tmp_path, journal_text):
    from test_process import add_process
    confdir = service_account(home)
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    add_process(proc, 4242, ["/usr/bin/onedrive", "--monitor", f"--confdir={confdir}",
                             "--resync", "--resync-auth"],
                "0::/user.slice/user@1000.service/app.slice/onedrive-x.service\n")
    run = ScriptedRun(outputs={"show": resync_show("onedrive-x.service"), "journalctl": journal_text})
    controller = make_controller(home, tmp_path, run=run)
    return controller, confdir, run


def test_resync_progress_appears_in_the_account_model(app, home, tmp_path):
    lines = [f"Downloading file: Ferie/IMG_{i:04}.JPG ... done" for i in range(30)]
    controller, confdir, run = resync_controller(home, tmp_path, resync_journal(
        "Number of items to download from Microsoft OneDrive: 120", *lines))

    read_status_now(controller)

    assert role(controller, "serviceLabel") == "Resynkroniserer"
    assert role(controller, "serviceTone") == "warning"
    progress = role(controller, "serviceProgress")
    assert progress["visible"] is True
    assert progress["active"] is True
    assert progress["phase"] == "Downloader filer"
    assert progress["counter"] == "30 af 120 filer"
    assert progress["determinate"] is True
    assert progress["value"] == pytest.approx(0.25)
    assert progress["latest"] == "Ferie/IMG_0029.JPG"
    assert progress["elapsed"].startswith("Tid siden start: ")


def test_progress_job_reads_new_lines(app, home, tmp_path):
    controller, confdir, run = resync_controller(home, tmp_path, resync_journal(
        "Number of items to download from Microsoft OneDrive: 120",
        "Downloading file: Ferie/IMG_0000.JPG ... done"))
    read_status_now(controller)
    run.outputs["journalctl"] = resync_journal("Downloading file: Ferie/IMG_0001.JPG ... done", start=2)

    controller.refreshProgress()
    wait_until(lambda: controller._progress_job is None, controller)

    assert role(controller, "serviceProgress")["counter"] == "2 af 120 filer"
    assert [c for c in run.calls if c[0] == "journalctl"][-1][-1] == "--after-cursor=s=1;i=1"


def test_progress_timer_follows_window_visibility(app, home, tmp_path):
    service_account(home)
    controller = make_controller(home, tmp_path, run=ScriptedRun(outputs={"show": service_show("onedrive-x.service")}))

    assert controller._progress_timer.interval() == 2000
    controller.setWindowVisible(True)
    assert controller._progress_timer.isActive() is True
    controller.setWindowVisible(False)
    assert controller._progress_timer.isActive() is False
    wait_until(lambda: controller._status_job is None, controller)


def test_finished_resync_shows_the_result(app, home, tmp_path):
    controller, confdir, run = resync_controller(home, tmp_path, resync_journal(
        "Number of items to download from Microsoft OneDrive: 1",
        "Downloading file: Ferie/IMG_0000.JPG ... done",
        "Sync with Microsoft OneDrive is complete"))

    read_status_now(controller)

    assert role(controller, "serviceLabel") == "Kører"
    progress = role(controller, "serviceProgress")
    assert progress["active"] is False
    assert progress["resultText"] == "Resync er færdig"


def test_service_without_resync_has_no_progress(app, home, tmp_path):
    service_account(home)
    controller = make_controller(home, tmp_path, run=ScriptedRun(outputs={"show": service_show("onedrive-x.service")}))

    read_status_now(controller)

    assert role(controller, "serviceProgress") == {"visible": False}


# Afbryd upload og resync (feature 0010)

SIGTERM = 15


def cancel_controller(home, tmp_path, *, show=None, popen=None, run=None):
    from fakes import FakeSignals
    confdir = synced_account(home)
    signals = FakeSignals()
    run = run or ScriptedRun(outputs={"cat": '[Service]\nExecStart=/usr/bin/onedrive --monitor\n',
                                      "show": show or service_show("onedrive-x.service")})
    popen = popen or FakeStoppablePopen(["New items to upload to Microsoft OneDrive: 3",
                                         "Uploading new file: ./A/noter.md ... done"])
    controller = make_controller(home, tmp_path, run=run, popen=popen, trash=lambda p: True,
                                 send_signal=signals)
    read_status_now(controller)
    controller.openFolderPicker(str(confdir))
    wait_for_picker(controller, "open")
    controller.toggleFolder(row_of(controller, "B"))
    controller.acceptPicker()
    wait_for_picker(controller, "confirm")
    controller.confirmRemoval()
    return controller, confdir, run, popen, signals


def test_cancel_apply_during_upload_stops_the_upload_and_changes_nothing(app, home, tmp_path):
    controller, confdir, run, popen, signals = cancel_controller(home, tmp_path)
    pump(controller, lambda: controller.applyCancellable)
    assert step_states(controller)[1] == "running"

    controller.cancelApply()

    assert controller.applyCancelling is True
    assert controller.applyCancellable is False
    pump(controller, lambda: controller.applyState == "cancelled")
    assert signals.signals == [SIGTERM]
    assert step_states(controller) == ["done", "cancelled", "waiting", "waiting", "waiting"]
    assert controller.applySteps[1]["stateText"] == "Afbrudt"
    assert (confdir / "sync_list").read_text() == "/A/\n/B/\n"
    assert (home / "OneDrive-X" / "B").exists()
    assert ["systemctl", "--user", "start", "onedrive-x.service"] in run.calls
    assert controller.pickerState == "open"
    assert controller.pickerError == ""
    assert controller.applyCancelling is False
    controller.closeApplyProgress()
    assert controller.applyState == ""


def test_cancel_apply_does_not_start_a_service_that_was_stopped(app, home, tmp_path):
    controller, confdir, run, popen, signals = cancel_controller(
        home, tmp_path, show=service_show("onedrive-x.service", "inactive", pid="0"))
    pump(controller, lambda: controller.applyCancellable)

    controller.cancelApply()
    pump(controller, lambda: controller.applyState == "cancelled")

    assert not any(c[2] in ("start", "restart") for c in run.calls if c[0] == "systemctl")


def test_cancel_apply_after_step_2_does_nothing(app, home, tmp_path):
    gate = Gate("restart")
    run = gated_run(gate, outputs={"cat": '[Service]\nExecStart=/usr/bin/onedrive --monitor\n',
                                   "show": service_show("onedrive-x.service")})
    controller, confdir, run, popen, signals = cancel_controller(
        home, tmp_path, run=run, popen=FakeUploadPopen(UPLOAD_LINES))
    assert gate.reached.wait(5)
    pump(controller, lambda: step_states(controller)[4] == "running")

    assert controller.applyCancellable is False
    controller.cancelApply()

    assert controller.applyCancelling is False
    gate.release.set()
    pump(controller, lambda: controller.pickerState == "closed")
    assert signals.signals == []
    assert (confdir / "sync_list").read_text() == "/A/\n"


def cancel_resync_controller(home, tmp_path, **run_kwargs):
    """Kontoen står som "Resynkroniserer". Efter ``stop`` er servicen stoppet."""
    from test_process import add_process
    confdir = service_account(home)
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    add_process(proc, 4242, ["/usr/bin/onedrive", "--monitor", f"--confdir={confdir}",
                             "--resync", "--resync-auth"],
                "0::/user.slice/user@1000.service/app.slice/onedrive-x.service\n")
    outputs = {"show": resync_show("onedrive-x.service"),
               "journalctl": resync_journal("Number of items to download from Microsoft OneDrive: 120")}
    user_on_call = run_kwargs.pop("on_call", None)

    def on_call(args):
        if user_on_call is not None:
            user_on_call(args)
        if "stop" in args and "stop" not in run.fail:
            run.outputs["show"] = service_show("onedrive-x.service", "inactive", pid="0") + f"InvocationID={INVOCATION}\n"
            (proc / "4242" / "cmdline").write_bytes(b"/usr/bin/bash\0")

    run = ScriptedRun(outputs=outputs, on_call=on_call, **run_kwargs)
    controller = make_controller(home, tmp_path, run=run)
    read_status_now(controller)
    return controller, confdir, run


def stops(run):
    return [c for c in run.calls if c[:3] == ["systemctl", "--user", "stop"]]


def test_cancel_resync_waits_for_confirmation(app, home, tmp_path):
    controller, confdir, run = cancel_resync_controller(home, tmp_path)
    assert role(controller, "serviceLabel") == "Resynkroniserer"
    assert role(controller, "serviceCancellable") is True

    controller.requestCancelResync(str(confdir))

    assert controller.cancelResyncAccountName == role(controller, "name")
    assert stops(run) == []
    controller.dismissCancelResync()
    assert controller.cancelResyncAccountName == ""
    assert stops(run) == []


def test_confirmed_cancel_stops_the_service_and_shows_resync_cancelled(app, home, tmp_path):
    controller, confdir, run = cancel_resync_controller(home, tmp_path)
    controller.requestCancelResync(str(confdir))

    controller.confirmCancelResync()
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)
    wait_until(lambda: role(controller, "serviceLabel") == "Resync afbrudt", controller)

    assert stops(run) == [["systemctl", "--user", "stop", "onedrive-x.service"]]
    assert controller.cancelResyncAccountName == ""
    import json
    data = json.loads((home / ".config" / "onedrive-gui" / "state.json").read_text())
    assert data["resync_cancelled"] == {"onedrive-x.service": {"invocation": INVOCATION}}
    assert role(controller, "serviceActionLabel") == "Genstart med resync"
    assert role(controller, "serviceCancellable") is False
    assert role(controller, "serviceMessage") == ""


def test_failing_stop_shows_the_error_and_writes_no_mark(app, home, tmp_path):
    controller, confdir, run = cancel_resync_controller(
        home, tmp_path, fail={"stop"}, stderr="Failed to stop onedrive-x.service: Access denied")
    controller.requestCancelResync(str(confdir))

    controller.confirmCancelResync()
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)

    assert role(controller, "serviceMessage") == "Failed to stop onedrive-x.service: Access denied"
    assert not (home / ".config" / "onedrive-gui" / "state.json").exists()


def test_request_close_is_false_while_the_resync_is_cancelled(app, home, tmp_path):
    gate = Gate("stop")
    controller, confdir, run = cancel_resync_controller(home, tmp_path, on_call=gate)
    controller.requestCancelResync(str(confdir))

    controller.confirmCancelResync()
    assert gate.reached.wait(5)

    assert controller.requestClose() is False
    assert "onedrive-x.service" in controller.busyText
    gate.release.set()
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)
    pump(controller, lambda: controller.busyText == "")


def test_cancel_resync_in_safe_mode_does_not_reach_run(app, home, tmp_path, monkeypatch):
    import subprocess
    from test_process import add_process
    confdir = service_account(home)
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    add_process(proc, 4242, ["/usr/bin/onedrive", "--monitor", f"--confdir={confdir}", "--resync"],
                "0::/user.slice/user@1000.service/app.slice/onedrive-x.service\n")
    underlying = ScriptedRun(outputs={"show": resync_show("onedrive-x.service"),
                                      "journalctl": resync_journal("Fetching items from the OneDrive API ..")})
    monkeypatch.setattr(subprocess, "run", underlying)
    controller = make_controller(home, tmp_path)
    read_status_now(controller)
    assert role(controller, "serviceLabel") == "Resynkroniserer"

    controller.requestCancelResync(str(confdir))
    controller.confirmCancelResync()
    wait_until(lambda: role(controller, "serviceBusy") is False, controller)

    assert role(controller, "serviceMessage") == ""
    assert stops(underlying) == []
    assert [c for c in underlying.calls if c[0] == "systemctl" and c[2] in CHANGING_SYSTEMCTL] == []
    assert not (home / ".config" / "onedrive-gui" / "state.json").exists()
    read_status_now(controller)
    assert role(controller, "serviceLabel") == "Resynkroniserer"


def test_cancel_resync_is_ignored_when_the_service_is_not_resyncing(app, home, tmp_path):
    service_account(home)
    run = ScriptedRun(outputs={"show": service_show("onedrive-x.service")})
    controller = make_controller(home, tmp_path, run=run)
    read_status_now(controller)

    controller.requestCancelResync(str(home / ".config" / "onedrive-x"))

    assert controller.cancelResyncAccountName == ""
    assert role(controller, "serviceCancellable") is False
