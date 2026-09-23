"""AppController binder logikken til QML (feature 0001)."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")

from onedrive_gui.registry import Registry  # noqa: E402
from onedrive_gui.viewmodels import AppController  # noqa: E402

from conftest import RecordingRun, make_account_dir  # noqa: E402
from fakes import FakeGraph, FakePopen, ScriptedRun, folder, http_error  # noqa: E402

ROOT_CHILDREN = "/v1.0/me/drive/root/children"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1"
CODE_URL = "https://login.microsoftonline.com/common/oauth2/nativeclient?code=abc"


@pytest.fixture(scope="module")
def app():
    return QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])


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
    controller = AppController(home, popen=popen, run=run)
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
    controller = make_controller(home, tmp_path, run=run,
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
    controller = make_controller(home, tmp_path, run=run, trash=lambda p: True)
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
    controller = make_controller(home, tmp_path, popen=popen, run=run)
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
