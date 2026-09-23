"""Udfør en ændring af mappevalget (feature 0002).

Testene kalder ikke onedrive eller systemctl. ``ScriptedRun`` og
``FakeUploadPopen`` optager kaldene, og papirkurven er en attrap.
"""

import pytest

from onedrive_gui import apply, sideeffects
from onedrive_gui.accounts import ONEDRIVE, Account
from onedrive_gui.apply import ApplyError, execute, prepare
from onedrive_gui.synclist import SelectionError

from conftest import make_account_dir
from fakes import FakeUploadPopen, ScriptedRun

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
    (root / "B" / "fil.txt").write_text("data")
    return Account("X", confdir, "~/OneDrive-X", service, True)


def drop_in(home):
    return home / ".config" / "systemd" / "user" / f"{SERVICE}.d" / "zz-onedrive-gui-resync.conf"


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
    popen = FakeUploadPopen(["ERROR: netværksfejl"], returncode=1)
    moved = []
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    with pytest.raises(ApplyError, match="netværksfejl"):
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
    (p / "cgroup").write_text("0::/user.slice/user@1000.service/app.slice/konsol.scope\n")

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


# Feature 0006: papirkurven respekterer alle regler.

def test_unknown_rule_that_cannot_be_interpreted_stops_prepare(home, proc):
    account = make_account(home, sync_list="/*\n/A/\n/B/\n")
    run = ScriptedRun(outputs={"cat": CAT})

    with pytest.raises(ApplyError, match=r"/\*"):
        prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    assert (account.confdir / "sync_list").read_text() == "/*\n/A/\n/B/\n"
    assert run.calls == []
    assert (home / "OneDrive-X" / "B" / "fil.txt").exists()


def test_prepare_uses_unknown_rules_and_config(home, proc):
    account = make_account(home, sync_list="!/B/Lokal/*\n/A/\n/B/\n")
    (account.confdir / "config").write_text('sync_dir = "~/OneDrive-X"\nskip_dotfiles = "true"\n')
    root = home / "OneDrive-X"
    (root / "B" / "Lokal").mkdir()
    (root / "B" / "Lokal" / "kun-lokal.txt").write_text("x")
    (root / "B" / ".env").write_text("x")
    (root / "B" / "noter.tmp").write_text("x")

    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    assert [r.path for r in change.removed] == [root / "B" / "fil.txt"]


# Feature 0009: fremdrift for de 5 trin.

UPLOAD_LINES = [
    "Reading configuration file: /home/bruger/.config/onedrive-x/config",
    "Configuration file successfully loaded",
    "Performing a database consistency and integrity check on locally stored data ..... ",
    "Scanning the local file system '~/OneDrive-X' for new data to upload ..... ",
    "New items to upload to Microsoft OneDrive: 3",
    "Uploading new file: ./A/noter.md ... done",
    "Uploading new file: ./A/budget.ods ... done",
    "Uploading new file: ./A/plan.txt ... done",
    "Sync with Microsoft OneDrive is complete",
]


class Steps:
    """Optag kaldene til ``on_step``. ``states`` er den seneste tilstand for hvert trin."""

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
        """(trin, tilstand) uden gentagelser af den samme tilstand."""
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
        "Stopper servicen", "Uploader lokale ændringer", "Skriver de nye regler",
        "Flytter til papirkurven", "Starter servicen med resync"]


def test_upload_reports_the_files_from_stdout(home, proc):
    seen = []

    def on_line(line):
        # Når klienten skriver næste linje, har on_step allerede fået den forrige.
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
    # conftest stopper testen, hvis subprocess.Popen bliver kaldt. onedrive startede altså ikke.
    assert (account.confdir / "sync_list").read_text() == "/A/\n/B/\n"
