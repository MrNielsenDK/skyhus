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
              "ActiveEnterTimestamp,InactiveEnterTimestamp,InvocationID")

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


# Resync i servicen (feature 0009)

INVOCATION = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


def journal_line(message, cursor, when=1790143816.0):
    import json
    return json.dumps({"SYSLOG_IDENTIFIER": "onedrive", "_PID": "4242", "_TRANSPORT": "stdout",
                       "_SYSTEMD_INVOCATION_ID": INVOCATION, "__CURSOR": cursor,
                       "__REALTIME_TIMESTAMP": str(int(when * 1_000_000)), "MESSAGE": message}) + "\n"


def resync_journal(*messages, start=0):
    return "".join(journal_line(m, f"s=1;i={start + i}", 1790143816.0 + start + i)
                   for i, m in enumerate(messages))


RESYNC_START = (
    "Reading configuration file: /home/bruger/.config/onedrive-privat/config",
    "Fetching items from the OneDrive API for Drive ID: 0a1b2c3d4e5f6789 ....",
    "Processing 5821 applicable JSON items received from Microsoft OneDrive .... ",
    "Number of items to download from Microsoft OneDrive: 120",
    "Downloading file: Ferie/Strand/IMG_0001.JPG ... done",
    "Downloading file: Ferie/Strand/IMG_0002.JPG ... done",
    "Downloading file: Tegninger/hus.psd ... failed!",
    "Downloading: Ferie/Klip/klip_0001.avi ... 45%   |  ETA    00:01:10",
)


def resync_reader(home, tmp_path, journal_text, *, args=("--monitor", "--resync", "--resync-auth"),
                  pid="4242"):
    a = account(home, "onedrive-privat", "onedrive-privat.service")
    proc = tmp_path / "proc"
    add_process(proc, 4242, ["/usr/bin/onedrive", *args, f"--confdir={a.confdir}"],
                "0::/user.slice/user-1000.slice/user@1000.service/app.slice/onedrive-privat.service\n")
    run = ScriptedRun(outputs={"show": unit("onedrive-privat.service", MainPID=pid, InvocationID=INVOCATION),
                               "journalctl": journal_text})
    reader = StatusReader(home=home, run=run, proc_root=proc, now=lambda: datetime(2026, 9, 23, 12, 0))
    return reader, a, run


def journal_calls(run):
    return [c for c in run.calls if c[0] == "journalctl"]


def test_resync_without_a_final_line_is_resyncing(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(*RESYNC_START))

    status = reader.read([a])[str(a.confdir)]

    assert status.state.key == service_state.RESYNCING
    assert status.state.label == "Resynkroniserer"
    assert status.state.tone == "warning"
    assert status.state.action == ""
    assert status.progress.phase == "Downloader filer"
    assert (status.progress.done, status.progress.total) == (2, 120)
    assert status.progress.latest == "Ferie/Klip/klip_0001.avi"
    assert status.progress.percent == 45


def test_journalctl_filters_on_the_current_invocation(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(*RESYNC_START))

    reader.read([a])

    assert journal_calls(run) == [["journalctl", "--user", "-u", "onedrive-privat.service",
                                   f"_SYSTEMD_INVOCATION_ID={INVOCATION}", "-o", "json", "--no-pager"]]


def test_resync_with_complete_line_is_running_and_shows_the_result(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(
        *RESYNC_START, "Sync with Microsoft OneDrive is complete"))

    status = reader.read([a])[str(a.confdir)]

    assert status.state.key == service_state.RUNNING
    assert status.state.label == "Kører"
    assert status.progress.result == "complete"
    assert status.progress_text == "Resync er færdig"


def test_resync_with_failed_items_is_complete_with_errors(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(
        *RESYNC_START,
        "Failed items to download to/from Microsoft OneDrive: 2",
        "Sync with Microsoft OneDrive has completed, however there are items that failed to sync."))

    status = reader.read([a])[str(a.confdir)]

    assert status.state.label == "Kører"
    assert status.progress.failed == 2
    assert status.progress_text == "Resync er færdig med fejl"


def test_main_process_without_resync_is_never_resyncing(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(*RESYNC_START), args=("--monitor",))

    status = reader.read([a])[str(a.confdir)]

    assert status.state.key == service_state.RUNNING
    assert status.progress is None
    assert journal_calls(run) == []


def test_resync_process_that_is_not_main_pid_is_not_resyncing(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(*RESYNC_START), pid="999")

    status = reader.read([a])[str(a.confdir)]

    assert status.state.key != service_state.RESYNCING


def test_start_during_resync_reads_the_whole_invocation_then_only_new_lines(home, tmp_path):
    lines = [f"Downloading file: Ferie/IMG_{i:04}.JPG ... done" for i in range(30)]
    reader, a, run = resync_reader(home, tmp_path, resync_journal(
        "Number of items to download from Microsoft OneDrive: 120", *lines))

    first = reader.read([a])[str(a.confdir)]
    run.outputs["journalctl"] = resync_journal("Downloading file: Ferie/IMG_0030.JPG ... done", start=31)
    second = reader.read([a])[str(a.confdir)]

    assert (first.progress.done, first.progress.total) == (30, 120)
    assert (second.progress.done, second.progress.total) == (31, 120)
    calls = journal_calls(run)
    assert "--after-cursor=s=1;i=30" not in calls[0]
    assert calls[1][-1] == "--after-cursor=s=1;i=30"


def test_new_invocation_starts_the_progress_again(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(
        "Number of items to download from Microsoft OneDrive: 120",
        "Downloading file: A/b.txt ... done"))
    reader.read([a])

    run.outputs["show"] = unit("onedrive-privat.service", MainPID="4242", InvocationID="ny0000000000")
    run.outputs["journalctl"] = resync_journal("Fetching items from the OneDrive API for Drive ID: 0a1b ..")
    status = reader.read([a])[str(a.confdir)]

    assert status.progress.done == 0
    assert status.progress.phase == "Henter listen fra OneDrive"
    assert "--after-cursor" not in " ".join(journal_calls(run)[-1])


def test_progress_is_not_read_again_after_the_result(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(
        *RESYNC_START, "Sync with Microsoft OneDrive is complete"))
    reader.read([a])

    reader.read([a])
    reader.read_progress([a])

    assert len(journal_calls(run)) == 1


def test_read_progress_reads_only_new_lines(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(*RESYNC_START))
    reader.read([a])
    run.outputs["journalctl"] = resync_journal("Downloading file: Ferie/Strand/IMG_0003.JPG ... done",
                                               start=len(RESYNC_START))

    progress = reader.read_progress([a])[str(a.confdir)]

    assert progress.done == 3
    assert journal_calls(run)[-1][-1] == f"--after-cursor=s=1;i={len(RESYNC_START) - 1}"
    assert [c for c in run.calls if c[0] == "systemctl"] == [
        ["systemctl", "--user", "show", "onedrive-privat.service", "-p", PROPERTIES]]


def test_resyncing_counts_as_settled_after_a_click():
    assert service_state.RESYNCING in service_state.SETTLED


# Resync afbrudt (feature 0010)

def state_file(home):
    return home / ".config" / "onedrive-gui" / "state.json"


def mark(home, service="onedrive-privat.service", invocation=INVOCATION):
    service_state.mark_resync_cancelled(service, invocation, home=home)


def marked_state(home, tmp_path, output):
    mark(home)
    return state_of(home, tmp_path, output)


def test_marked_inactive_service_is_resync_cancelled(home, tmp_path):
    state = marked_state(home, tmp_path, unit("onedrive-privat.service", ActiveState="inactive", SubState="dead",
                                              MainPID="0", InvocationID=INVOCATION))

    assert state.key == service_state.RESYNC_CANCELLED
    assert state.label == "Resync afbrudt"
    assert state.action == "resync"
    assert state.action_label == "Genstart med resync"
    assert state.since == "i dag kl. 08:36"


def test_resync_cancelled_has_no_start_button(home, tmp_path):
    for active in ("inactive", "failed"):
        state = marked_state(home, tmp_path, unit("onedrive-privat.service", ActiveState=active, SubState="dead",
                                                  MainPID="0", Result="signal", InvocationID=INVOCATION))

        assert state.label == "Resync afbrudt"
        assert state.action_label != "Start"


def test_needs_resync_wins_over_resync_cancelled(home, tmp_path):
    state = marked_state(home, tmp_path, unit("onedrive-privat.service", ActiveState="failed", SubState="failed",
                                              Result="exit-code", ExecMainStatus="126", MainPID="0",
                                              InvocationID=INVOCATION))

    assert state.label == "Kræver resync"


def test_resyncing_wins_over_resync_cancelled(home, tmp_path):
    reader, a, run = resync_reader(home, tmp_path, resync_journal(*RESYNC_START))
    mark(home, invocation="gammel")

    status = reader.read([a])[str(a.confdir)]

    assert status.state.label == "Resynkroniserer"


def test_resync_cancelled_wins_over_stopped_and_failed(home, tmp_path):
    stopped = marked_state(home, tmp_path, unit("onedrive-privat.service", ActiveState="inactive",
                                                SubState="dead", MainPID="0", InvocationID=INVOCATION))
    failed = marked_state(home, tmp_path, unit("onedrive-privat.service", ActiveState="failed",
                                               SubState="failed", MainPID="0", Result="timeout",
                                               ExecMainStatus="9", InvocationID=INVOCATION))

    assert stopped.label == "Resync afbrudt"
    assert failed.label == "Resync afbrudt"


def test_foreign_process_wins_over_resync_cancelled(home, tmp_path):
    a = account(home, "onedrive-privat", "onedrive-privat.service")
    add_process(tmp_path / "proc", 555, ["onedrive", f"--confdir={a.confdir}", "--monitor"])
    mark(home)

    statuses, run = read(home, tmp_path, [a], unit("onedrive-privat.service", ActiveState="inactive",
                                                   MainPID="0", InvocationID=INVOCATION))

    assert statuses[str(a.confdir)].state.label == "Kører uden for servicen"


def test_mark_is_written_per_service_in_state_json(home):
    import json
    mark(home, "onedrive-privat.service", "aaa")
    mark(home, "onedrive.service", "bbb")

    data = json.loads(state_file(home).read_text())

    assert data["resync_cancelled"] == {"onedrive-privat.service": {"invocation": "aaa"},
                                        "onedrive.service": {"invocation": "bbb"}}
    assert service_state.cancelled_resyncs(home) == {"onedrive-privat.service": "aaa", "onedrive.service": "bbb"}


def test_mark_disappears_when_the_service_starts_again(home, tmp_path):
    mark(home)

    state = state_of(home, tmp_path, unit("onedrive-privat.service", ActiveState="activating",
                                          SubState="start-pre", InvocationID="ny0000000000"))

    assert state.label == "Starter"
    assert service_state.cancelled_resyncs(home) == {}


def test_mark_stays_while_status_still_shows_the_cancelled_run(home, tmp_path):
    """``systemctl show`` kan være læst, før stoppet var færdigt. Kørslen er den samme."""
    mark(home)

    state_of(home, tmp_path, unit("onedrive-privat.service", InvocationID=INVOCATION))

    assert service_state.cancelled_resyncs(home) == {"onedrive-privat.service": INVOCATION}


def test_clear_mark_keeps_other_services(home):
    mark(home, "onedrive-privat.service", "aaa")
    mark(home, "onedrive.service", "bbb")

    service_state.clear_resync_cancelled("onedrive-privat.service", home=home)

    assert service_state.cancelled_resyncs(home) == {"onedrive.service": "bbb"}


def test_unreadable_state_json_gives_no_marks(home):
    state_file(home).parent.mkdir(parents=True)
    state_file(home).write_text("{ikke json")

    assert service_state.cancelled_resyncs(home) == {}
