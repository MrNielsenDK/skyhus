"""Carry out a change of the folder selection (feature 0002).

The tests do not call onedrive or systemctl. ``ScriptedRun`` and
``FakeUploadPopen`` record the calls, and Trash is a fake.
"""

import pytest

from skyhus import apply, sideeffects
from skyhus.accounts import ONEDRIVE, Account
from skyhus.apply import ApplyError, execute, prepare
from skyhus.synclist import SelectionError

from conftest import make_account_dir
from fakes import FakeSignals, FakeStoppablePopen, FakeUploadPopen, ScriptedRun

SERVICE = "onedrive-x.service"
CAT = """\
# /home/x/.config/systemd/user/onedrive-x.service
[Service]
ExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-x"
"""


@pytest.fixture
def proc(tmp_path):
    root = tmp_path / "proc"
    root.mkdir()
    return root


def make_account(home, *, synced=True, service=SERVICE, sync_list="/A/\n/B/\n"):
    confdir = make_account_dir(home, "onedrive-x", config='sync_dir = "~/OneDrive-X"\n',
                               refresh_token=True, items=synced)
    if sync_list is not None:
        (confdir / "sync_list").write_text(sync_list)
    root = home / "OneDrive-X"
    (root / "A").mkdir(parents=True)
    (root / "B").mkdir()
    (root / "B" / "file.txt").write_text("data")
    return Account("X", confdir, "~/OneDrive-X", service, True)


def drop_in(home):
    return home / ".config" / "systemd" / "user" / f"{SERVICE}.d" / "zz-skyhus-resync.conf"


def test_synced_account_runs_steps_in_order(home, proc):
    account = make_account(home)
    sync_list = account.confdir / "sync_list"
    order = []

    def on_call(args):
        order.append((args[2], sync_list.read_text(),
                      drop_in(home).read_text() if drop_in(home).exists() else None))

    uploads = FakeUploadPopen()

    def popen(args, **kwargs):
        order.append(("upload" if args[0] == ONEDRIVE else args[0], sync_list.read_text(), None))
        return uploads(args, **kwargs)

    def trash(path):
        order.append(("trash", sync_list.read_text(), None))
        return True

    run = ScriptedRun(outputs={"cat": CAT}, on_call=on_call)
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)
    assert [r.path for r in change.removed] == [home / "OneDrive-X" / "B"]

    result = execute(change, home=home, run=run, popen=popen, trash=trash, proc_root=proc)

    assert [step[0] for step in order] == [
        "stop", "upload", "trash", "cat", "daemon-reload", "restart", "daemon-reload"]
    assert order[0][1] == "/A/\n/B/\n"
    assert order[1][1] == "/A/\n/B/\n"
    assert order[2][1] == "/A/\n"
    restart = order[5]
    assert "--resync --resync-auth" in restart[2]
    assert result.trash_failures == []
    assert result.resynced is True


def test_upload_uses_upload_only_and_no_remote_delete(home, proc):
    account = make_account(home)
    run = ScriptedRun(outputs={"cat": CAT})
    popen = FakeUploadPopen()
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    execute(change, home=home, run=run, popen=popen, trash=lambda p: True, proc_root=proc)

    assert [c for c in run.calls if c[0] == ONEDRIVE] == []
    assert popen.calls == [[ONEDRIVE, f"--confdir={account.confdir}", "--sync",
                            "--upload-only", "--no-remote-delete"]]


def test_drop_in_is_gone_after_restart(home, proc):
    account = make_account(home)
    run = ScriptedRun(outputs={"cat": CAT})
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    execute(change, home=home, run=run, popen=FakeUploadPopen(), trash=lambda p: True, proc_root=proc)

    assert ["systemctl", "--user", "restart", SERVICE] in run.calls
    assert not drop_in(home).exists()


def test_account_without_items_only_writes_files(home, proc):
    account = make_account(home, synced=False, service="")
    run = ScriptedRun()
    popen = FakeUploadPopen()
    moved = []
    change = prepare(account, sync_all=False, folders=["A"], root_files=True, home=home, proc_root=proc)

    result = execute(change, home=home, run=run, popen=popen, trash=moved.append, proc_root=proc)

    assert run.calls == []
    assert popen.calls == []
    assert moved == []
    assert (account.confdir / "sync_list").read_text() == "/A/\n"
    assert 'sync_root_files = "true"' in (account.confdir / "config").read_text()
    assert (home / "OneDrive-X" / "B").exists()
    assert result.resynced is False


def test_failed_upload_changes_nothing_and_starts_service_without_resync(home, proc):
    account = make_account(home)
    run = ScriptedRun(outputs={"cat": CAT})
    popen = FakeUploadPopen(["ERROR: network failure"], returncode=1)
    moved = []
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    with pytest.raises(ApplyError, match="network failure"):
        execute(change, home=home, run=run, popen=popen, trash=moved.append, proc_root=proc)

    assert (account.confdir / "sync_list").read_text() == "/A/\n/B/\n"
    assert moved == []
    assert run.calls[0] == ["systemctl", "--user", "stop", SERVICE]
    assert run.calls[-1] == ["systemctl", "--user", "start", SERVICE]
    assert not any("--resync" in " ".join(c) for c in run.calls)
    assert not drop_in(home).exists()


def test_other_onedrive_process_blocks_the_change(home, proc):
    account = make_account(home)
    p = proc / "4242"
    p.mkdir()
    (p / "cmdline").write_bytes(f"/usr/bin/onedrive\0--confdir={account.confdir}\0--resync\0".encode())
    (p / "cgroup").write_text("0::/user.slice/user@1000.service/app.slice/console.scope\n")

    with pytest.raises(ApplyError, match="4242"):
        prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    assert (account.confdir / "sync_list").read_text() == "/A/\n/B/\n"


def test_service_process_does_not_block_the_change(home, proc):
    account = make_account(home)
    p = proc / "4242"
    p.mkdir()
    (p / "cmdline").write_bytes(f"/usr/bin/onedrive\0--monitor\0--confdir={account.confdir}\0".encode())
    (p / "cgroup").write_text(f"0::/user.slice/user@1000.service/app.slice/{SERVICE}\n")

    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    assert change.removed


def test_trash_failure_is_reported_and_resync_still_runs(home, proc):
    account = make_account(home)
    (home / "OneDrive-X" / "C").mkdir()
    (account.confdir / "sync_list").write_text("/A/\n/B/\n/C/\n")
    run = ScriptedRun(outputs={"cat": CAT})
    tried = []

    def trash(path):
        tried.append(path.name)
        return path.name != "B"

    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)
    result = execute(change, home=home, run=run, popen=FakeUploadPopen(), trash=trash, proc_root=proc)

    assert tried == ["B", "C"]
    assert result.trash_failures == [home / "OneDrive-X" / "B"]
    assert ["systemctl", "--user", "restart", SERVICE] in run.calls


def test_synced_account_without_service_is_an_error(home, proc):
    account = make_account(home, service="")

    with pytest.raises(ApplyError, match="service"):
        prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    assert (account.confdir / "sync_list").read_text() == "/A/\n/B/\n"


def test_no_folders_and_not_sync_all_is_an_error(home, proc):
    account = make_account(home)

    with pytest.raises(SelectionError):
        prepare(account, sync_all=False, folders=[], root_files=False, home=home, proc_root=proc)


def test_only_adding_folders_removes_nothing(home, proc):
    account = make_account(home)

    change = prepare(account, sync_all=True, folders=[], root_files=False, home=home, proc_root=proc)

    assert change.removed == []


# Feature 0006: Trash respects all rules.

def test_unknown_rule_that_cannot_be_interpreted_stops_prepare(home, proc):
    account = make_account(home, sync_list="/*\n/A/\n/B/\n")
    run = ScriptedRun(outputs={"cat": CAT})

    with pytest.raises(ApplyError, match=r"/\*"):
        prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    assert (account.confdir / "sync_list").read_text() == "/*\n/A/\n/B/\n"
    assert run.calls == []
    assert (home / "OneDrive-X" / "B" / "file.txt").exists()


def test_prepare_uses_unknown_rules_and_config(home, proc):
    account = make_account(home, sync_list="!/B/Local/*\n/A/\n/B/\n")
    (account.confdir / "config").write_text('sync_dir = "~/OneDrive-X"\nskip_dotfiles = "true"\n')
    root = home / "OneDrive-X"
    (root / "B" / "Local").mkdir()
    (root / "B" / "Local" / "only-local.txt").write_text("x")
    (root / "B" / ".env").write_text("x")
    (root / "B" / "notes.tmp").write_text("x")

    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    assert [r.path for r in change.removed] == [root / "B" / "file.txt"]


# Feature 0009: progress for the 5 steps.

UPLOAD_LINES = [
    "Reading configuration file: /home/user/.config/onedrive-x/config",
    "Configuration file successfully loaded",
    "Performing a database consistency and integrity check on locally stored data ..... ",
    "Scanning the local file system '~/OneDrive-X' for new data to upload ..... ",
    "New items to upload to Microsoft OneDrive: 3",
    "Uploading new file: ./A/notes.md ... done",
    "Uploading new file: ./A/budget.ods ... done",
    "Uploading new file: ./A/plan.txt ... done",
    "Sync with Microsoft OneDrive is complete",
]


class Steps:
    """Record the calls to ``on_step``. ``states`` is the latest state for each step."""

    def __init__(self):
        self.calls = []

    def __call__(self, step, state, progress):
        self.calls.append((step, state, progress))

    @property
    def states(self):
        result = {step: apply.WAITING for step in apply.STEPS}
        for step, state, _ in self.calls:
            result[step] = state
        return result

    def changes(self):
        """(step, state) without repeats of the same state."""
        found = []
        for step, state, _ in self.calls:
            if not found or found[-1] != (step, state):
                found.append((step, state))
        return found


def run_change(home, proc, *, popen=None, trash=lambda p: True, sync_list="/A/\n/B/\n", folders=("A",)):
    account = make_account(home, sync_list=sync_list)
    run = ScriptedRun(outputs={"cat": CAT})
    steps = Steps()
    change = prepare(account, sync_all=False, folders=list(folders), root_files=False,
                     home=home, proc_root=proc)
    error = None
    try:
        execute(change, home=home, run=run, popen=popen or FakeUploadPopen(UPLOAD_LINES),
                trash=trash, proc_root=proc, on_step=steps)
    except ApplyError as exc:
        error = exc
    return steps, run, error


def test_on_step_reports_all_five_steps_in_order(home, proc):
    steps, run, error = run_change(home, proc)

    assert error is None
    assert steps.changes() == [
        (1, apply.RUNNING), (1, apply.DONE),
        (2, apply.RUNNING), (2, apply.DONE),
        (3, apply.RUNNING), (3, apply.DONE),
        (4, apply.RUNNING), (4, apply.DONE),
        (5, apply.RUNNING), (5, apply.DONE),
    ]
    assert list(apply.STEPS) == [1, 2, 3, 4, 5]
    assert [apply.STEPS[s] for s in apply.STEPS] == [
        "Stopping the service", "Uploading local changes", "Writing the new rules",
        "Moving to Trash", "Starting the service with resync"]


def test_upload_reports_the_files_from_stdout(home, proc):
    seen = []

    def on_line(line):
        # When the client writes the next line, on_step has already received the previous one.
        seen.append(line)

    steps, run, error = run_change(home, proc, popen=FakeUploadPopen(UPLOAD_LINES, on_line=on_line))

    upload = [p for step, state, p in steps.calls if step == 2 and state == apply.RUNNING and p is not None]
    counts = []
    for p in upload:
        if p.total == 3 and (not counts or counts[-1] != (p.done, p.total)):
            counts.append((p.done, p.total))
    assert counts == [(0, 3), (1, 3), (2, 3), (3, 3)]
    assert upload[-1].latest == "A/plan.txt"
    final = [p for step, state, p in steps.calls if step == 2 and state == apply.DONE][0]
    assert (final.done, final.total) == (3, 3)
    assert len(seen) == len(UPLOAD_LINES)


def test_upload_reads_stdout_as_text_lines(home, proc):
    popen = FakeUploadPopen(UPLOAD_LINES)

    run_change(home, proc, popen=popen)

    kwargs = popen.kwargs[0]
    assert kwargs["stdout"] == apply.subprocess.PIPE
    assert kwargs["stderr"] == apply.subprocess.STDOUT
    assert kwargs["stdin"] == apply.subprocess.DEVNULL
    assert kwargs["text"] is True


def test_failed_upload_marks_step_2_failed_and_the_rest_waiting(home, proc):
    popen = FakeUploadPopen(["ERROR: Cannot connect to Microsoft OneDrive Service"], returncode=1)

    steps, run, error = run_change(home, proc, popen=popen)

    assert "Cannot connect" in str(error)
    assert steps.states == {1: apply.DONE, 2: apply.FAILED, 3: apply.WAITING,
                            4: apply.WAITING, 5: apply.WAITING}


def test_trash_step_counts_every_path(home, proc):
    account = make_account(home, sync_list="/A/\n/B/\n/C/\n/D/\n/E/\n")
    root = home / "OneDrive-X"
    for name in "CDE":
        (root / name).mkdir()
    run = ScriptedRun(outputs={"cat": CAT})
    steps = Steps()
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)
    assert len(change.removed) == 4

    execute(change, home=home, run=run, popen=FakeUploadPopen(), trash=lambda p: True,
            proc_root=proc, on_step=steps)

    counts = [(p.done, p.total) for step, state, p in steps.calls
              if step == 4 and state == apply.RUNNING and p.done > 0]
    assert counts == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_upload_in_safe_mode_uses_sideeffects_popen_and_fails(home, proc, monkeypatch):
    used = []
    real = sideeffects.popen

    def spy(args, **kwargs):
        used.append(list(args))
        return real(args, **kwargs)

    monkeypatch.setattr(sideeffects, "popen", spy)
    account = make_account(home)
    run = ScriptedRun(outputs={"cat": CAT})
    steps = Steps()
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    with pytest.raises(ApplyError):
        execute(change, home=home, run=run, trash=lambda p: True, proc_root=proc, on_step=steps)

    assert used == [apply.upload_command(account.confdir)]
    assert steps.states[2] == apply.FAILED
    assert steps.states[3] == apply.WAITING
    # conftest stops the test if subprocess.Popen is called. So onedrive did not start.
    assert (account.confdir / "sync_list").read_text() == "/A/\n/B/\n"


# Feature 0010: stop the upload.

SIGTERM, SIGKILL = 15, 9
CANCEL_LINES = [
    "New items to upload to Microsoft OneDrive: 3",
    "Uploading new file: ./A/notes.md ... done",
]


def cancelling_popen(flag, *, stops_on=(SIGTERM,), exit_code=None, at="notes.md", lines=CANCEL_LINES):
    """An upload where the user clicks "Stop" when the line with ``at`` comes."""

    def on_line(line):
        if at in line:
            assert flag.request() is True

    return FakeStoppablePopen(lines, stops_on=stops_on, exit_code=exit_code, on_line=on_line)


def cancel_change(home, proc, *, popen_for=None, service_active=True, clock=None, moved=None):
    from fakes import SteppingClock
    account = make_account(home)
    run = ScriptedRun(outputs={"cat": CAT})
    steps = Steps()
    flag = apply.CancelFlag()
    clock = clock or SteppingClock()
    signals = FakeSignals(clock)
    popen = (popen_for or cancelling_popen)(flag)
    moved = [] if moved is None else moved
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)
    result = execute(change, home=home, run=run, popen=popen, trash=lambda p: moved.append(p) or True,
                     proc_root=proc, on_step=steps, cancel=flag, service_active=service_active,
                     send_signal=signals, clock=clock, sleep=clock.sleep)
    return result, account, run, steps, signals, moved


def test_cancel_during_upload_sends_sigterm(home, proc):
    result, account, run, steps, signals, moved = cancel_change(home, proc)

    assert signals.signals == [SIGTERM]


def test_upload_that_ignores_sigterm_gets_sigkill_after_30_seconds(home, proc):
    from fakes import SteppingClock
    clock = SteppingClock()

    result, account, run, steps, signals, moved = cancel_change(
        home, proc, clock=clock, popen_for=lambda flag: cancelling_popen(flag, stops_on=(SIGKILL,)))

    assert signals.signals == [SIGTERM, SIGKILL]
    (_, term_at), (_, kill_at) = signals.sent
    assert kill_at - term_at >= 30
    assert kill_at - term_at < 32
    assert result.outcome == apply.CANCELLED


def test_cancel_leaves_sync_list_and_trash_alone(home, proc):
    result, account, run, steps, signals, moved = cancel_change(home, proc)

    assert (account.confdir / "sync_list").read_text() == "/A/\n/B/\n"
    assert moved == []
    assert (home / "OneDrive-X" / "B" / "file.txt").exists()


def test_cancel_starts_a_running_service_again_without_resync(home, proc):
    result, account, run, steps, signals, moved = cancel_change(home, proc)

    assert run.calls[0] == ["systemctl", "--user", "stop", SERVICE]
    assert run.calls[-1] == ["systemctl", "--user", "start", SERVICE]
    assert not any("--resync" in " ".join(c) for c in run.calls)
    assert not any("restart" in c or "daemon-reload" in c for c in run.calls)
    assert not drop_in(home).exists()


def test_cancel_does_not_start_a_service_that_was_stopped(home, proc):
    result, account, run, steps, signals, moved = cancel_change(home, proc, service_active=False)

    assert run.calls == [["systemctl", "--user", "stop", SERVICE]]


def test_cancel_result_is_cancelled(home, proc):
    result, account, run, steps, signals, moved = cancel_change(home, proc)

    assert result.outcome == apply.CANCELLED
    assert result.resynced is False
    assert steps.states == {1: apply.DONE, 2: apply.CANCELLED, 3: apply.WAITING,
                            4: apply.WAITING, 5: apply.WAITING}


def test_cancel_when_the_upload_ends_with_exit_0_is_still_cancelled(home, proc):
    def popen_for(flag):
        def on_line(line):
            if "plan.txt" in line:
                assert flag.request() is True

        return FakeUploadPopen(UPLOAD_LINES, returncode=0, on_line=on_line)

    result, account, run, steps, signals, moved = cancel_change(home, proc, popen_for=popen_for)

    assert result.outcome == apply.CANCELLED
    assert (account.confdir / "sync_list").read_text() == "/A/\n/B/\n"
    assert moved == []
    assert run.calls[-1] == ["systemctl", "--user", "start", SERVICE]


def test_cancel_outside_step_2_does_nothing(home, proc):
    account = make_account(home)
    run = ScriptedRun(outputs={"cat": CAT})
    flag = apply.CancelFlag()
    answers = []

    def on_step(step, state, progress):
        if state == apply.RUNNING and step in (apply.STOP, apply.WRITE, apply.TRASH, apply.RESYNC):
            answers.append((step, flag.request()))

    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)
    result = execute(change, home=home, run=run, popen=FakeUploadPopen(UPLOAD_LINES), trash=lambda p: True,
                     proc_root=proc, on_step=on_step, cancel=flag, send_signal=FakeSignals())

    assert answers and all(answer is False for _, answer in answers)
    assert {step for step, _ in answers} == {apply.STOP, apply.WRITE, apply.TRASH, apply.RESYNC}
    assert result.outcome == apply.DONE
    assert (account.confdir / "sync_list").read_text() == "/A/\n"


def test_flag_is_checked_every_second_without_new_lines(home, proc):
    import threading
    import time
    account = make_account(home)
    run = ScriptedRun(outputs={"cat": CAT})
    flag = apply.CancelFlag()
    popen = FakeStoppablePopen(["New items to upload to Microsoft OneDrive: 3"])
    signals = FakeSignals()
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)
    results = []
    worker = threading.Thread(target=lambda: results.append(execute(
        change, home=home, run=run, popen=popen, trash=lambda p: True, proc_root=proc,
        cancel=flag, send_signal=signals)))
    worker.start()
    end = time.monotonic() + 5
    while not popen.processes and time.monotonic() < end:
        time.sleep(0.01)
    time.sleep(0.1)

    assert flag.request() is True
    requested = time.monotonic()
    worker.join(5)

    assert signals.signals == [SIGTERM]
    assert time.monotonic() - requested < 2.5
    assert results[0].outcome == apply.CANCELLED


def test_upload_signals_go_through_sideeffects(home, proc, monkeypatch):
    sent = []
    monkeypatch.setattr(sideeffects, "signal_process", lambda process, sig: sent.append(sig) or process.receive(sig))
    flag = apply.CancelFlag()
    account = make_account(home)
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    result = execute(change, home=home, run=ScriptedRun(outputs={"cat": CAT}), popen=cancelling_popen(flag),
                     trash=lambda p: True, proc_root=proc, cancel=flag)

    assert sent == [SIGTERM]
    assert result.outcome == apply.CANCELLED
