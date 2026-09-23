"""Udfør en ændring af mappevalget (feature 0002).

Testene kalder ikke onedrive eller systemctl. ``ScriptedRun`` optager kaldene,
og papirkurven er en attrap.
"""

import pytest

from onedrive_gui.accounts import ONEDRIVE, Account
from onedrive_gui.apply import ApplyError, execute, prepare
from onedrive_gui.synclist import SelectionError

from conftest import make_account_dir
from fakes import ScriptedRun

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
        name = "upload" if args[0] == ONEDRIVE else args[2]
        order.append((name, sync_list.read_text(),
                      drop_in(home).read_text() if drop_in(home).exists() else None))

    def trash(path):
        order.append(("trash", sync_list.read_text(), None))
        return True

    run = ScriptedRun(outputs={"cat": CAT}, on_call=on_call)
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)
    assert [r.path for r in change.removed] == [home / "OneDrive-X" / "B"]

    result = execute(change, home=home, run=run, trash=trash, proc_root=proc)

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
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    execute(change, home=home, run=run, trash=lambda p: True, proc_root=proc)

    upload = [c for c in run.calls if c[0] == ONEDRIVE]
    assert upload == [[ONEDRIVE, f"--confdir={account.confdir}", "--sync",
                       "--upload-only", "--no-remote-delete"]]


def test_drop_in_is_gone_after_restart(home, proc):
    account = make_account(home)
    run = ScriptedRun(outputs={"cat": CAT})
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    execute(change, home=home, run=run, trash=lambda p: True, proc_root=proc)

    assert ["systemctl", "--user", "restart", SERVICE] in run.calls
    assert not drop_in(home).exists()


def test_account_without_items_only_writes_files(home, proc):
    account = make_account(home, synced=False, service="")
    run = ScriptedRun()
    moved = []
    change = prepare(account, sync_all=False, folders=["A"], root_files=True, home=home, proc_root=proc)

    result = execute(change, home=home, run=run, trash=moved.append, proc_root=proc)

    assert run.calls == []
    assert moved == []
    assert (account.confdir / "sync_list").read_text() == "/A/\n"
    assert 'sync_root_files = "true"' in (account.confdir / "config").read_text()
    assert (home / "OneDrive-X" / "B").exists()
    assert result.resynced is False


def test_failed_upload_changes_nothing_and_starts_service_without_resync(home, proc):
    account = make_account(home)
    run = ScriptedRun(outputs={"cat": CAT}, fail={"--upload-only"}, stderr="netværksfejl")
    moved = []
    change = prepare(account, sync_all=False, folders=["A"], root_files=False, home=home, proc_root=proc)

    with pytest.raises(ApplyError, match="netværksfejl"):
        execute(change, home=home, run=run, trash=moved.append, proc_root=proc)

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
    result = execute(change, home=home, run=run, trash=trash, proc_root=proc)

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
