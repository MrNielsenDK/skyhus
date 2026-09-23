"""Servicens tilstand for hver konto (feature 0004).

Svarene fra ``systemctl show`` er optaget fra en rigtig maskine.
"""

from datetime import datetime

from onedrive_gui import service_state
from onedrive_gui.accounts import Account
from onedrive_gui.service_state import StatusReader, format_since

from conftest import make_account_dir
from fakes import ScriptedRun
from test_process import add_process

PROPERTIES = ("Id,LoadState,ActiveState,SubState,Result,ExecMainStatus,MainPID,"
              "ActiveEnterTimestamp,InactiveEnterTimestamp")

RUNNING = """\
Id=onedrive.service
LoadState=loaded
ActiveState=active
SubState=running
ActiveEnterTimestamp=Wed 2026-09-23 07:32:52 CEST
InactiveEnterTimestamp=Wed 2026-09-23 07:32:37 CEST
MainPID=287024
Result=success
ExecMainStatus=0
"""

FAILED_TIMEOUT = """\
Id=onedrive-privat.service
LoadState=loaded
ActiveState=failed
SubState=failed
ActiveEnterTimestamp=Wed 2026-09-23 03:00:48 CEST
InactiveEnterTimestamp=Wed 2026-09-23 06:07:46 CEST
MainPID=0
Result=timeout
ExecMainStatus=9
"""

NOT_FOUND = """\
Id=onedrive-findes-ikke.service
LoadState=not-found
ActiveState=inactive
SubState=dead
ActiveEnterTimestamp=
InactiveEnterTimestamp=
MainPID=0
Result=success
ExecMainStatus=0
"""


def unit(name, **values):
    """Et svar fra ``systemctl show`` for 1 unit. ``values`` erstatter felterne."""
    fields = {
        "Id": name, "LoadState": "loaded", "ActiveState": "active", "SubState": "running",
        "ActiveEnterTimestamp": "Wed 2026-09-23 08:37:00 CEST",
        "InactiveEnterTimestamp": "Wed 2026-09-23 08:36:40 CEST",
        "MainPID": "4242", "Result": "success", "ExecMainStatus": "0",
    }
    fields.update(values)
    return "".join(f"{key}={value}\n" for key, value in fields.items())


def systemctl_calls(run):
    return [c for c in run.calls if c[0] == "systemctl"]


def show_output(*units):
    return "\n".join(units)


def account(home, name, service, *, logged_in=True):
    confdir = make_account_dir(home, name, config="", refresh_token=logged_in)
    return Account(name=name, confdir=confdir, sync_dir="~/OneDrive", service=service, logged_in=logged_in)


def read(home, tmp_path, accounts, output, *, run=None, now=None):
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    run = run or ScriptedRun(outputs={"show": output})
    reader = StatusReader(home=home, run=run, proc_root=proc,
                          now=now or (lambda: datetime(2026, 9, 23, 12, 0)))
    return reader.read(accounts), run


def state_of(home, tmp_path, output, *, service="onedrive-privat.service", logged_in=True):
    a = account(home, "onedrive-privat", service, logged_in=logged_in)
    statuses, run = read(home, tmp_path, [a], output)
    return statuses[str(a.confdir)].state


# Tilstand

def test_active_running_is_running_with_restart(home, tmp_path):
    state = state_of(home, tmp_path, unit("onedrive-privat.service"))

    assert state.label == "Kører"
    assert state.tone == "success"
    assert state.action == "restart"
    assert state.action_label == "Genstart"


def test_activating_is_starting(home, tmp_path):
    state = state_of(home, tmp_path, unit("onedrive-privat.service", ActiveState="activating",
                                          SubState="start-pre", MainPID="99"))

    assert state.label == "Starter"
    assert state.tone == "warning"
    assert state.action_label == "Genstart"


def test_deactivating_is_stopping_without_button(home, tmp_path):
    state = state_of(home, tmp_path, unit("onedrive-privat.service", ActiveState="deactivating",
                                          SubState="stop-sigterm"))

    assert state.label == "Stopper"
    assert state.tone == "warning"
    assert state.action == ""


def test_failed_with_timeout_is_failed_with_start(home, tmp_path):
    state = state_of(home, tmp_path, FAILED_TIMEOUT)

    assert state.label == "Fejlet"
    assert state.tone == "danger"
    assert state.action == "start"
    assert state.action_label == "Start"


def test_failed_with_126_needs_resync(home, tmp_path):
    state = state_of(home, tmp_path, unit("onedrive-privat.service", ActiveState="failed",
                                          SubState="failed", Result="exit-code",
                                          ExecMainStatus="126", MainPID="0"))

    assert state.label == "Kræver resync"
    assert state.tone == "danger"
    assert state.action == "resync"
    assert state.action_label == "Genstart med resync"


def test_126_while_activating_is_starting(home, tmp_path):
    """Under ExecStartPre kan ExecMainStatus stadig være 126 fra sidste kørsel."""
    state = state_of(home, tmp_path, unit("onedrive-privat.service", ActiveState="activating",
                                          SubState="start-pre", ExecMainStatus="126"))

    assert state.label == "Starter"


def test_inactive_with_status_0_is_stopped(home, tmp_path):
    state = state_of(home, tmp_path, unit("onedrive-privat.service", ActiveState="inactive",
                                          SubState="dead", MainPID="0", ExecMainStatus="0"))

    assert state.label == "Stoppet"
    assert state.tone == "textSecondary"
    assert state.action == "start"
    assert state.action_label == "Start"


def test_foreign_process_is_running_outside_service(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")
    proc = tmp_path / "proc"
    add_process(proc, 555, ["onedrive", f"--confdir={a.confdir}", "--monitor"])
    output = FAILED_TIMEOUT

    statuses, run = read(home, tmp_path, [a], output)

    state = statuses[str(a.confdir)].state
    assert state.label == "Kører uden for servicen"
    assert state.tone == "warning"
    assert state.action == ""
    assert state.action_label == ""


def test_process_that_is_main_pid_is_not_foreign(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")
    proc = tmp_path / "proc"
    # Processen står ikke i servicens cgroup. Kun MainPID viser, at den hører til servicen.
    add_process(proc, 4242, ["/usr/bin/onedrive", "--monitor", f"--confdir={a.confdir}"])

    statuses, run = read(home, tmp_path, [a], unit("onedrive-privat.service", MainPID="4242"))

    assert statuses[str(a.confdir)].state.label == "Kører"


def test_process_in_service_cgroup_is_not_foreign(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")
    proc = tmp_path / "proc"
    add_process(proc, 4243, ["/usr/bin/onedrive", "--monitor", f"--confdir={a.confdir}"],
                "0::/user.slice/user-1000.slice/user@1000.service/app.slice/onedrive-privat.service\n")

    statuses, run = read(home, tmp_path, [a], unit("onedrive-privat.service", MainPID="4242"))

    assert statuses[str(a.confdir)].state.label == "Kører"


def test_not_logged_in_wins_over_failed(home, tmp_path):
    state = state_of(home, tmp_path, FAILED_TIMEOUT, logged_in=False)

    assert state.label == "Ikke logget ind"
    assert state.tone == "textSecondary"
    assert state.action == ""


def test_account_without_service_does_not_call_systemctl(home, tmp_path):
    a = account(home, "onedrive-ny", "")
    run = ScriptedRun()

    statuses, run = read(home, tmp_path, [a], "", run=run)

    state = statuses[str(a.confdir)].state
    assert state.label == "Ingen service"
    assert state.tone == "textSecondary"
    assert state.action == ""
    assert run.calls == []


def test_only_accounts_with_service_are_asked(home, tmp_path):
    with_service = account(home, "onedrive-privat", "onedrive-privat.service")
    without = account(home, "onedrive-ny", "")

    statuses, run = read(home, tmp_path, [with_service, without], FAILED_TIMEOUT)

    assert systemctl_calls(run) == [["systemctl", "--user", "show", "onedrive-privat.service", "-p", PROPERTIES]]
    assert statuses[str(without.confdir)].state.label == "Ingen service"


def test_not_found_is_no_service(home, tmp_path):
    state = state_of(home, tmp_path, NOT_FOUND, service="onedrive-findes-ikke.service")

    assert state.label == "Ingen service"
    assert state.action == ""


def test_three_units_give_each_account_its_own_state(home, tmp_path):
    firma = account(home, "onedrive", "onedrive.service")
    privat = account(home, "onedrive-privat", "onedrive-privat.service")
    gammel = account(home, "onedrive-gammel", "onedrive-findes-ikke.service")

    statuses, run = read(home, tmp_path, [firma, privat, gammel],
                         show_output(RUNNING, FAILED_TIMEOUT, NOT_FOUND))

    assert systemctl_calls(run) == [["systemctl", "--user", "show", "onedrive.service", "onedrive-privat.service",
                          "onedrive-findes-ikke.service", "-p", PROPERTIES]]
    assert statuses[str(firma.confdir)].state.label == "Kører"
    assert statuses[str(privat.confdir)].state.label == "Fejlet"
    assert statuses[str(gammel.confdir)].state.label == "Ingen service"


def test_failing_show_keeps_last_state_and_says_so(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")
    proc = tmp_path / "proc"
    proc.mkdir()
    run = ScriptedRun(outputs={"show": unit("onedrive-privat.service")})
    reader = StatusReader(home=home, run=run, proc_root=proc)
    assert reader.read([a])[str(a.confdir)].state.label == "Kører"

    run.fail = {"show"}
    run.stderr = "Failed to connect to bus: No medium found"
    status = reader.read([a])[str(a.confdir)]

    assert status.state.label == "Kører"
    assert status.stale is True
    assert "Kan ikke læse status" in status.message
    assert "Failed to connect to bus" in status.message


def test_read_state_for_one_account(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")
    proc = tmp_path / "proc"
    proc.mkdir()
    run = ScriptedRun(outputs={"show": FAILED_TIMEOUT})
    reader = StatusReader(home=home, run=run, proc_root=proc)

    assert reader.read_state(a).key == service_state.FAILED
    assert run.calls == [["systemctl", "--user", "show", "onedrive-privat.service", "-p", PROPERTIES]]


# Tid

NOW = datetime(2026, 9, 23, 12, 0)


def test_since_today():
    assert format_since("Wed 2026-09-23 08:37:12 CEST", NOW) == "i dag kl. 08:37"


def test_since_yesterday():
    assert format_since("Tue 2026-09-22 08:37:12 CEST", NOW) == "i går kl. 08:37"


def test_since_earlier_date():
    assert format_since("Sun 2026-09-20 08:37:00 CEST", NOW) == "20. sep. kl. 08:37"


def test_since_across_new_year():
    assert format_since("Thu 2026-12-31 23:05:00 CET", datetime(2027, 1, 1, 9, 0)) == "i går kl. 23:05"


def test_empty_since_gives_no_text():
    assert format_since("", NOW) == ""
    assert format_since("n/a", NOW) == ""


def test_running_state_uses_active_enter_timestamp(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")

    statuses, run = read(home, tmp_path, [a], unit("onedrive-privat.service",
                                                   ActiveEnterTimestamp="Wed 2026-09-23 08:37:00 CEST"))

    assert statuses[str(a.confdir)].state.since == "i dag kl. 08:37"


def test_failed_state_uses_inactive_enter_timestamp(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")

    statuses, run = read(home, tmp_path, [a], FAILED_TIMEOUT)

    assert statuses[str(a.confdir)].state.since == "i dag kl. 06:07"


def test_no_service_has_no_since(home, tmp_path):
    a = account(home, "onedrive-ny", "")

    statuses, run = read(home, tmp_path, [a], "")

    assert statuses[str(a.confdir)].state.since == ""


# Fejllinjen i kortet

JOURNAL_TIMEOUT = (
    '{"SYSLOG_IDENTIFIER":"systemd","_PID":"1","MESSAGE":"onedrive-privat.service: '
    'Failed with result \'timeout\'."}\n')


def test_failed_state_reads_error_line_once(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")
    proc = tmp_path / "proc"
    proc.mkdir()
    run = ScriptedRun(outputs={"show": FAILED_TIMEOUT, "journalctl": JOURNAL_TIMEOUT})
    reader = StatusReader(home=home, run=run, proc_root=proc)

    first = reader.read([a])[str(a.confdir)]
    second = reader.read([a])[str(a.confdir)]

    assert first.error_line == "onedrive-privat.service: Failed with result 'timeout'."
    assert second.error_line == first.error_line
    journal_calls = [c for c in run.calls if c[0] == "journalctl"]
    assert journal_calls == [["journalctl", "--user", "-u", "onedrive-privat.service",
                              "-n", "500", "-o", "json", "--no-pager"]]


def test_running_state_does_not_call_journalctl(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")

    statuses, run = read(home, tmp_path, [a], unit("onedrive-privat.service"))

    assert statuses[str(a.confdir)].error_line == ""
    assert [c for c in run.calls if c[0] == "journalctl"] == []


def test_initial_status_before_first_read(home):
    a = account(home, "onedrive-privat", "onedrive-privat.service")
    ny = account(home, "onedrive-ny", "")
    ude = account(home, "onedrive-ude", "onedrive-ude.service", logged_in=False)

    assert service_state.initial_status(ny).state.label == "Ingen service"
    assert service_state.initial_status(ude).state.label == "Ikke logget ind"
    assert service_state.initial_status(a).state.action == ""
