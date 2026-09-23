"""Hele forløbet fra login til service (feature 0001)."""

import pytest

from onedrive_gui.discovery import discover_accounts
from onedrive_gui.login_flow import FlowState, LoginFlow
from onedrive_gui.registry import Registry

from conftest import RecordingRun, make_account_dir, make_unit
from fakes import FakeClock, FakePopen, ScriptedRun

AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1"
CODE_URL = "https://login.microsoftonline.com/common/oauth2/nativeclient?code=abc"


@pytest.fixture
def popen():
    return FakePopen()


def make_flow(home, tmp_path, popen, run, confdir, name="Firma 2", service=""):
    registry = Registry.for_home(home)
    flow = LoginFlow(confdir, name, service, registry=registry, home=home,
                     popen=popen, run=run, clock=FakeClock(), tmp_base=tmp_path)
    flow.start()
    return flow


def complete_login(flow, popen, confdir):
    popen.last.write_auth_url(AUTH_URL)
    flow.poll()
    assert flow.submit_redirect(CODE_URL)
    (confdir / "refresh_token").write_text("ny")
    popen.last.exit(0)
    assert flow.poll() is FlowState.LOGGED_IN


def unit_dir(home):
    return home / ".config" / "systemd" / "user"


def test_new_account_creates_and_starts_service(home, tmp_path, popen):
    confdir = make_account_dir(home, "onedrive-firma-2", config='sync_dir = "~/X"\n')
    run = RecordingRun()
    flow = make_flow(home, tmp_path, popen, run, confdir)

    complete_login(flow, popen, confdir)
    assert run.calls == []
    flow.activate_service()

    assert flow.state is FlowState.DONE
    assert flow.service_error == ""
    assert (unit_dir(home) / "onedrive-firma-2.service").exists()
    assert run.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "onedrive-firma-2.service"],
    ]
    assert Registry.for_home(home).service_for(confdir) == "onedrive-firma-2.service"


def test_existing_account_restarts_its_service(home, tmp_path, popen):
    confdir = make_account_dir(home, "onedrive-privat", config="")
    make_unit(home, "onedrive-privat.service",
              '/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-privat"')
    before = sorted(p.name for p in unit_dir(home).iterdir())
    run = RecordingRun()
    flow = make_flow(home, tmp_path, popen, run, confdir, "Privat", "onedrive-privat.service")

    complete_login(flow, popen, confdir)
    flow.activate_service()

    assert run.calls == [["systemctl", "--user", "restart", "onedrive-privat.service"]]
    assert sorted(p.name for p in unit_dir(home).iterdir()) == before


def test_existing_unit_with_same_name_is_not_overwritten(home, tmp_path, popen):
    confdir = make_account_dir(home, "onedrive-firma-2", config="")
    path = unit_dir(home) / "onedrive-firma-2.service"
    path.parent.mkdir(parents=True)
    path.write_text("fremmed unit\n")
    run = RecordingRun()
    flow = make_flow(home, tmp_path, popen, run, confdir)

    complete_login(flow, popen, confdir)
    flow.activate_service()

    assert path.read_text() == "fremmed unit\n"
    assert run.calls == []
    assert "onedrive-firma-2.service" in flow.service_error


def test_systemctl_failure_shows_message_and_account_stays_logged_in(home, tmp_path, popen):
    confdir = make_account_dir(home, "onedrive-firma-2", config="")
    run = RecordingRun(fail_on="enable", stderr="Failed to enable unit: Access denied")
    flow = make_flow(home, tmp_path, popen, run, confdir)

    complete_login(flow, popen, confdir)
    flow.activate_service()

    assert flow.state is FlowState.DONE
    assert "Access denied" in flow.service_error
    account = discover_accounts(home)[0]
    assert account.logged_in is True


def test_error_redirect_shows_message_and_no_service(home, tmp_path, popen):
    confdir = make_account_dir(home, "onedrive-firma-2", config="")
    run = RecordingRun()
    flow = make_flow(home, tmp_path, popen, run, confdir)
    popen.last.write_auth_url(AUTH_URL)
    flow.poll()

    flow.submit_redirect("https://login.microsoftonline.com/common/oauth2/nativeclient"
                         "?error=access_denied&error_description=Nej+tak")

    assert flow.poll() is FlowState.FAILED
    assert "Nej tak" in flow.error
    flow.activate_service()
    assert run.calls == []
    assert not unit_dir(home).exists()


def test_closing_login_window_stops_process_and_no_service(home, tmp_path, popen):
    confdir = make_account_dir(home, "onedrive-firma-2", config="")
    run = RecordingRun()
    flow = make_flow(home, tmp_path, popen, run, confdir)
    popen.last.write_auth_url(AUTH_URL)
    flow.poll()

    flow.cancel()

    assert popen.last.terminated
    assert flow.poll() is FlowState.CANCELLED
    flow.activate_service()
    assert run.calls == []
    assert not unit_dir(home).exists()


def test_nonzero_exit_shows_error_and_no_service(home, tmp_path, popen):
    confdir = make_account_dir(home, "onedrive-firma-2", config="")
    run = RecordingRun()
    flow = make_flow(home, tmp_path, popen, run, confdir)

    popen.last.exit(3)

    assert flow.poll() is FlowState.FAILED
    assert "3" in flow.error
    flow.activate_service()
    assert run.calls == []
    assert not unit_dir(home).exists()


# Sikker tilstand (feature 0007)

def test_login_in_safe_mode_fails_without_starting_onedrive(home, tmp_path, monkeypatch):
    import subprocess
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs: started.append(args))
    confdir = make_account_dir(home, "onedrive-firma-2", config='sync_dir = "~/X"\n')
    # Flowet får ingen falsk popen. Det bruger standarden fra sideeffects.
    flow = LoginFlow(confdir, "Firma 2", "", registry=Registry.for_home(home), home=home,
                     run=RecordingRun(), clock=FakeClock(), tmp_base=tmp_path)
    flow.start()

    assert flow.poll() is FlowState.FAILED
    assert "Sikker tilstand: onedrive blev ikke startet" in flow.error
    assert started == []


# Log ind igen med --reauth (feature 0005)

SERVICE = "onedrive-privat.service"


def show(active):
    return (f"Id={SERVICE}\nLoadState=loaded\nActiveState={active}\nSubState=x\nResult=success\n"
            "ExecMainStatus=0\nMainPID=4242\n"
            "ActiveEnterTimestamp=Wed 2026-09-23 08:37:00 CEST\n"
            "InactiveEnterTimestamp=Wed 2026-09-23 08:36:00 CEST\n")


class LoggingPopen(FakePopen):
    """Skriver hvert start af klienten i den samme log som ``ScriptedRun``."""

    def __init__(self, log):
        super().__init__()
        self.log = log

    def __call__(self, args, **kwargs):
        self.log.append(("popen", list(args)))
        return super().__call__(args, **kwargs)


def add_process(proc, pid, args, unit_scope):
    d = proc / str(pid)
    d.mkdir(parents=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
    (d / "cgroup").write_text(f"0::/user.slice/user@1000.service/app.slice/{unit_scope}\n")


@pytest.fixture
def proc(tmp_path):
    root = tmp_path / "proc"
    root.mkdir()
    return root


@pytest.fixture
def privat(home):
    confdir = make_account_dir(home, "onedrive-privat", config="")
    token = confdir / "refresh_token"
    token.write_bytes(b"gammel-token")
    token.chmod(0o600)
    return confdir


def reauth_flow(home, tmp_path, proc, confdir, *, active="active", fail=(), stderr="fejl"):
    log = []
    run = ScriptedRun(outputs={"show": show(active)}, fail=fail, stderr=stderr, log=log)
    popen = LoggingPopen(log)
    flow = LoginFlow(confdir, "Privat", SERVICE, registry=Registry.for_home(home), home=home,
                     popen=popen, run=run, clock=FakeClock(), tmp_base=tmp_path, proc_root=proc)
    flow.start()
    return flow, run, popen, log


def changing_calls(run):
    return [c for c in run.calls if "show" not in c]


def test_login_with_refresh_token_uses_reauth(home, tmp_path, proc, privat):
    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat)

    assert "--reauth" in popen.last.args
    assert "--auth-files" in popen.last.args
    popen.last.write_auth_url(AUTH_URL)
    assert flow.poll() is FlowState.WAITING_FOR_USER
    flow.cancel()


def test_login_without_refresh_token_does_not_use_reauth(home, tmp_path, popen):
    confdir = make_account_dir(home, "onedrive-firma-2", config="")
    flow = make_flow(home, tmp_path, popen, RecordingRun(), confdir)

    assert "--reauth" not in popen.last.args
    assert "--auth-files" in popen.last.args
    flow.cancel()


def test_active_service_is_stopped_before_client_starts(home, tmp_path, proc, privat):
    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat)

    stop = ("run", ["systemctl", "--user", "stop", SERVICE])
    assert stop in log
    assert log.index(stop) < next(i for i, entry in enumerate(log) if entry[0] == "popen")
    assert flow.service_stopped is True
    flow.cancel()


def test_successful_reauth_restarts_service_and_keeps_new_token(home, tmp_path, proc, privat):
    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat)

    complete_login(flow, popen, privat)
    flow.activate_service()

    assert flow.state is FlowState.DONE
    assert flow.service_error == ""
    assert changing_calls(run) == [
        ["systemctl", "--user", "stop", SERVICE],
        ["systemctl", "--user", "reset-failed", SERVICE],
        ["systemctl", "--user", "restart", SERVICE],
    ]
    assert (privat / "refresh_token").read_text() == "ny"
    assert flow.service_stopped is False


def test_stopped_service_is_not_started_after_login(home, tmp_path, proc, privat):
    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat, active="inactive")

    assert flow.service_stopped is False
    complete_login(flow, popen, privat)
    flow.activate_service()

    assert flow.state is FlowState.DONE
    assert changing_calls(run) == []
    assert (privat / "refresh_token").read_text() == "ny"


def test_cancel_restores_token_and_restarts_service(home, tmp_path, proc, privat):
    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat)
    popen.last.write_auth_url(AUTH_URL)
    flow.poll()

    flow.cancel()
    assert flow.poll() is FlowState.CANCELLED
    token = privat / "refresh_token"
    assert token.read_bytes() == b"gammel-token"
    assert token.stat().st_mode & 0o777 == 0o600
    assert flow.needs_restart is True

    flow.restore_service()

    assert changing_calls(run) == [
        ["systemctl", "--user", "stop", SERVICE],
        ["systemctl", "--user", "reset-failed", SERVICE],
        ["systemctl", "--user", "restart", SERVICE],
    ]
    assert flow.needs_restart is False
    assert flow.state is FlowState.CANCELLED


def test_nonzero_exit_restores_token_and_restarts_service(home, tmp_path, proc, privat):
    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat)

    popen.last.exit(2)
    assert flow.poll() is FlowState.FAILED
    assert (privat / "refresh_token").read_bytes() == b"gammel-token"
    assert (privat / "refresh_token").stat().st_mode & 0o777 == 0o600

    flow.restore_service()

    assert changing_calls(run)[-2:] == [
        ["systemctl", "--user", "reset-failed", SERVICE],
        ["systemctl", "--user", "restart", SERVICE],
    ]
    assert "2" in flow.error


def test_failure_does_not_restart_a_service_that_was_stopped(home, tmp_path, proc, privat):
    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat, active="inactive")

    popen.last.exit(1)
    assert flow.poll() is FlowState.FAILED
    assert flow.needs_restart is False
    flow.restore_service()

    assert changing_calls(run) == []
    assert (privat / "refresh_token").read_bytes() == b"gammel-token"


def test_foreign_process_blocks_login(home, tmp_path, proc, privat):
    add_process(proc, 777, ["/usr/bin/onedrive", "--resync", f"--confdir={privat}"], "konsol.scope")

    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat)

    assert flow.state is FlowState.FAILED
    assert "777" in flow.error
    assert changing_calls(run) == []
    assert popen.processes == []
    assert flow.needs_restart is False
    assert (privat / "refresh_token").read_bytes() == b"gammel-token"


def test_process_inside_the_service_does_not_block_login(home, tmp_path, proc, privat):
    add_process(proc, 4242, ["/usr/bin/onedrive", "--monitor", f"--confdir={privat}"], SERVICE)

    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat)

    assert flow.state is FlowState.STARTING
    assert len(popen.processes) == 1
    flow.cancel()


def test_stop_failure_shows_error_and_does_not_start_client(home, tmp_path, proc, privat):
    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat, fail={"stop"},
                                        stderr="Failed to stop onedrive-privat.service: Access denied")

    assert flow.state is FlowState.FAILED
    assert "Access denied" in flow.error
    assert popen.processes == []
    assert (privat / "refresh_token").read_bytes() == b"gammel-token"


def test_restart_failure_after_login_shows_error_and_account_is_logged_in(home, tmp_path, proc, privat):
    flow, run, popen, log = reauth_flow(home, tmp_path, proc, privat, fail={"restart"},
                                        stderr="Job for onedrive-privat.service failed.")

    complete_login(flow, popen, privat)
    flow.activate_service()

    assert flow.state is FlowState.DONE
    assert "Job for onedrive-privat.service failed." in flow.service_error
    account = discover_accounts(home)[0]
    assert account.logged_in is True
