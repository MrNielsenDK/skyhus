"""Remove an account (feature 0018)."""

import subprocess
from pathlib import Path
from signal import SIGTERM

import pytest

from skyhus import account_removal as ar
from skyhus.accounts import Account, unit_dir
from skyhus.apply import CancelFlag
from skyhus.registry import Registry
from skyhus.service import render_unit
from skyhus.service_state import cancelled_resyncs, mark_resync_cancelled

from conftest import make_account_dir
from fakes import FakeSignals, FakeStoppablePopen, FakeUploadPopen, SteppingClock

SERVICE = "onedrive-x.service"
TRIGGER = "onedrive-x.path"


class FakeSystemd:
    """A replacement for ``subprocess.run`` for ``systemctl --user``. It keeps the state of each unit.

    ``fail`` holds (verb, unit) pairs that fail. A unit in ``stuck`` stays active after ``disable --now``.
    """

    def __init__(self, units, fail=(), stuck=()):
        self.units = units
        self.fail = set(fail)
        self.stuck = set(stuck)
        self.calls = []

    @staticmethod
    def unit(fragment="", enabled=True, active=True, triggered_by="", load="loaded"):
        return {"fragment": str(fragment), "enabled": enabled, "active": active,
                "triggered_by": triggered_by, "load": load}

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        assert args[:2] == ["systemctl", "--user"], args
        verb = args[2]
        if verb == "show":
            names = args[3:args.index("-p")]
            return self._ok(args, "\n\n".join(self._show(name) for name in names) + "\n")
        unit = args[-1]
        if (verb, unit) in self.fail:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr=f"Failed to {verb} {unit}: denied")
        state = self.units.get(unit)
        if verb == "disable" and state is not None:
            state["enabled"] = False
            if unit not in self.stuck:
                state["active"] = False
        elif verb == "enable" and state is not None:
            state["enabled"] = True
        elif verb == "start" and state is not None:
            state["active"] = True
        return self._ok(args, "")

    def _show(self, name):
        state = self.units.get(name)
        if state is None:
            return f"Id={name}\nLoadState=not-found\nActiveState=inactive\nUnitFileState=\nFragmentPath=\nTriggeredBy="
        active = "active" if state["active"] else "inactive"
        if name in self.stuck and not state["enabled"]:
            active = "deactivating"
        return (f"Id={name}\nLoadState={state['load']}\nActiveState={active}\n"
                f"UnitFileState={'enabled' if state['enabled'] else 'disabled'}\n"
                f"FragmentPath={state['fragment']}\nTriggeredBy={state['triggered_by']}")

    @staticmethod
    def _ok(args, stdout):
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    def verbs(self):
        return [(c[2], c[-1]) for c in self.calls if c[2] != "show"]


class FakeTrash:
    def __init__(self, fail=()):
        self.fail = {Path(p) for p in fail}
        self.moved = []

    def __call__(self, path):
        path = Path(path)
        if path in self.fail:
            return False
        self.moved.append(path)
        return True


@pytest.fixture
def proc(tmp_path):
    folder = tmp_path / "proc"
    folder.mkdir()
    return folder


def make_account(home, *, skyhus_unit=True, sync_list=None, name="onedrive-x"):
    confdir = make_account_dir(home, name, config='sync_dir = "~/OneDrive-X"\nskip_file = "*.tmp"\n',
                               refresh_token=True, items=True)
    if sync_list is not None:
        (confdir / "sync_list").write_text(sync_list)
    sync = home / "OneDrive-X"
    (sync / "Docs").mkdir(parents=True)
    (sync / "Docs" / "a.txt").write_text("a")
    (sync / "draft.tmp").write_text("temporary")
    units = unit_dir(home)
    units.mkdir(parents=True, exist_ok=True)
    unit_file = units / SERVICE
    if skyhus_unit:
        unit_file.write_text(render_unit(name, "X"))
    else:
        unit_file.write_text("[Unit]\nDescription=Made by hand\n[Service]\nExecStart=/usr/bin/onedrive --monitor\n")
    Registry.for_home(home).add(confdir, "X", SERVICE)
    account = Account(name="X", confdir=confdir, sync_dir="~/OneDrive-X", service=SERVICE, logged_in=True)
    return account, unit_file


def systemd_for(unit_file, **kwargs):
    return FakeSystemd({
        SERVICE: FakeSystemd.unit(unit_file, triggered_by=TRIGGER),
        TRIGGER: FakeSystemd.unit(Path(unit_file).with_suffix(".path")),
    }, **kwargs)


def run_removal(home, proc, *, remove_sync=True, systemd=None, popen=None, trash=None, cancel=None,
                signals=None, account=None, unit_file=None, steps=None):
    if account is None:
        account, unit_file = make_account(home)
    systemd = systemd or systemd_for(unit_file)
    plan = ar.prepare(account, [account], home=home, run=systemd)
    clock = SteppingClock()
    trash = trash if trash is not None else FakeTrash()
    popen = popen if popen is not None else FakeUploadPopen(["Uploading file Docs/a.txt ... done"])
    result = ar.execute(plan, remove_sync_folder=remove_sync, home=home, run=systemd, popen=popen,
                        trash=trash, send_signal=signals or FakeSignals(), proc_root=proc, clock=clock,
                        sleep=clock.sleep, on_step=steps, cancel=cancel)
    return result, plan, systemd, trash, popen


# prepare

def test_prepare_finds_trigger_units_and_skyhus_unit_file(home):
    account, unit_file = make_account(home)
    systemd = systemd_for(unit_file)

    plan = ar.prepare(account, [account], home=home, run=systemd)

    assert plan.service == SERVICE
    assert plan.triggers == [TRIGGER]
    assert plan.unit_files == [unit_file]
    assert all(c[2] == "show" for c in systemd.calls)


def test_old_danish_header_counts_as_written_by_skyhus(tmp_path):
    unit = tmp_path / "old.service"
    unit.write_text('# OneDrive-konto "X". Oprettet af Skyhus.\n[Service]\n')  # allow-danish: old header

    assert ar.is_written_by_skyhus(unit)


def test_old_project_name_header_counts_as_written_by_skyhus(tmp_path):
    unit = tmp_path / "old.service"
    unit.write_text(f'# OneDrive-konto "X". {ar.LEGACY_HEADERS[1]}\n[Service]\n')  # allow-danish: old header

    assert ar.is_written_by_skyhus(unit)


def test_hand_made_unit_file_is_kept(home):
    account, unit_file = make_account(home, skyhus_unit=False)

    plan = ar.prepare(account, [account], home=home, run=systemd_for(unit_file))

    assert plan.unit_files == []
    assert SERVICE in plan.kept_units


def test_package_unit_is_never_removed(home, tmp_path):
    account, _ = make_account(home)
    package_unit = tmp_path / "usr" / "lib" / "systemd" / "user" / SERVICE
    package_unit.parent.mkdir(parents=True)
    package_unit.write_text(render_unit("onedrive-x", "X"))
    systemd = FakeSystemd({SERVICE: FakeSystemd.unit(package_unit)})

    plan = ar.prepare(account, [account], home=home, run=systemd)

    assert plan.unit_files == []
    assert SERVICE in plan.kept_units


def test_resync_drop_in_is_removed(home):
    account, unit_file = make_account(home)
    drop_in = unit_dir(home) / f"{SERVICE}.d" / "zz-skyhus-resync.conf"
    drop_in.parent.mkdir()
    drop_in.write_text("[Service]\n")

    plan = ar.prepare(account, [account], home=home, run=systemd_for(unit_file))

    assert drop_in in plan.unit_files


def test_account_without_service_has_no_service_steps(home):
    account, _ = make_account(home)
    account.service = ""
    systemd = FakeSystemd({})

    plan = ar.prepare(account, [account], home=home, run=systemd)

    assert plan.service == ""
    assert plan.triggers == []
    assert ar.TRIGGERS not in plan.steps(True)
    assert ar.SERVICE not in plan.steps(True)
    assert systemd.calls == []


def test_prepare_finds_files_that_are_only_local(home):
    account, unit_file = make_account(home, sync_list="/Docs/\n")
    sync = home / "OneDrive-X"
    (sync / "Other").mkdir()
    (sync / "Other" / "b.txt").write_text("bb")
    (sync / "Other" / "c.txt").write_text("ccc")

    plan = ar.prepare(account, [account], home=home, run=systemd_for(unit_file))

    paths = {p.path for p in plan.local_only.paths}
    assert paths == {sync / "Other", sync / "draft.tmp"}
    assert plan.local_only.files == 3
    assert plan.local_only.size == 2 + 3 + len("temporary")


def test_synced_files_are_not_only_local(home):
    account, unit_file = make_account(home)
    (home / "OneDrive-X" / "draft.tmp").unlink()

    plan = ar.prepare(account, [account], home=home, run=systemd_for(unit_file))

    assert plan.local_only.files == 0


@pytest.mark.parametrize("sync_dir, reason", [
    ("~", "home folder"),
    ("/tmp", "not inside your home folder"),
    ("~/.config/sky", "~/.config"),
])
def test_sync_folder_that_cannot_go_to_trash(home, sync_dir, reason):
    account, unit_file = make_account(home)
    account.sync_dir = sync_dir
    Path(account.sync_path).mkdir(parents=True, exist_ok=True)

    plan = ar.prepare(account, [account], home=home, run=systemd_for(unit_file))

    assert plan.sync_trashable is False
    assert reason in plan.sync_reason
    assert ar.UPLOAD not in plan.steps(True)
    assert ar.SYNC not in plan.steps(True)


def test_sync_folder_that_overlaps_another_account(home):
    account, unit_file = make_account(home)
    other_confdir = make_account_dir(home, "onedrive-y", refresh_token=True)
    other = Account(name="Y", confdir=other_confdir, sync_dir="~/OneDrive-X/Y", service="", logged_in=True)

    plan = ar.prepare(account, [account, other], home=home, run=systemd_for(unit_file))

    assert plan.sync_trashable is False
    assert "Y" in plan.sync_reason


def test_missing_sync_folder_cannot_go_to_trash(home):
    account, unit_file = make_account(home)
    account.sync_dir = "~/Gone"

    plan = ar.prepare(account, [account], home=home, run=systemd_for(unit_file))

    assert plan.sync_trashable is False
    assert "does not exist" in plan.sync_reason


def test_confdir_outside_config_is_refused(home, tmp_path):
    account, unit_file = make_account(home)
    account.confdir = tmp_path / "elsewhere" / "onedrive-x"

    with pytest.raises(ar.RemovalError):
        ar.prepare(account, [account], home=home, run=systemd_for(unit_file))


def test_confdir_with_a_different_name_is_refused(home):
    account, unit_file = make_account(home)
    other = home / ".config" / "skyhus"
    other.mkdir(exist_ok=True)
    account.confdir = other

    with pytest.raises(ar.RemovalError):
        ar.prepare(account, [account], home=home, run=systemd_for(unit_file))


# execute: order and content

def test_removal_with_sync_folder_in_order(home, proc):
    result, plan, systemd, trash, popen = run_removal(home, proc)

    assert result.outcome == ar.DONE
    assert systemd.verbs() == [("disable", TRIGGER), ("disable", SERVICE), ("daemon-reload", "daemon-reload")]
    assert len(popen.calls) == 1
    assert "--upload-only" in popen.calls[0] and "--no-remote-delete" in popen.calls[0]
    confdir = home / ".config" / "onedrive-x"
    assert trash.moved == [confdir, home / "OneDrive-X"]
    assert not (confdir / "refresh_token").exists()
    assert not (unit_dir(home) / SERVICE).exists()


def test_the_token_does_not_go_to_trash(home, proc):
    seen = {}

    class Recording(FakeTrash):
        def __call__(self, path):
            seen[Path(path)] = (Path(path) / "refresh_token").exists()
            return super().__call__(path)

    run_removal(home, proc, trash=Recording())

    assert seen[home / ".config" / "onedrive-x"] is False


def test_removal_without_sync_folder_keeps_it(home, proc):
    result, plan, systemd, trash, popen = run_removal(home, proc, remove_sync=False)

    assert result.outcome == ar.DONE
    assert popen.calls == []
    assert trash.moved == [home / ".config" / "onedrive-x"]
    assert (home / "OneDrive-X" / "Docs" / "a.txt").exists()


def test_removal_cleans_registry_and_state(home, proc):
    mark_resync_cancelled(SERVICE, "abc", home=home)

    run_removal(home, proc)

    assert Registry.for_home(home).name_for(home / ".config" / "onedrive-x") is None
    assert SERVICE not in cancelled_resyncs(home)


def test_hand_made_unit_is_disabled_but_kept(home, proc):
    account, unit_file = make_account(home, skyhus_unit=False)

    result, plan, systemd, trash, popen = run_removal(home, proc, account=account, unit_file=unit_file)

    assert unit_file.exists()
    assert ("disable", SERVICE) in systemd.verbs()
    assert ("daemon-reload", "daemon-reload") not in systemd.verbs()


def test_steps_are_reported_in_order(home, proc):
    reported = []

    run_removal(home, proc, steps=lambda step, state, progress: reported.append((step, state)))

    done = [step for step, state in reported if state == ar.DONE]
    assert done == [ar.TRIGGERS, ar.SERVICE, ar.UPLOAD, ar.UNITS, ar.TOKEN, ar.CONFIG, ar.SYNC, ar.CLEANUP]


# execute: refusals, errors and undo

def test_foreign_onedrive_process_is_refused(home, proc):
    from test_process import add_process
    account, unit_file = make_account(home)
    add_process(proc, 4242, ["/usr/bin/onedrive", "--monitor", f"--confdir={account.confdir}"], "0::/user.slice\n")
    systemd = systemd_for(unit_file)

    with pytest.raises(ar.RemovalError, match="Another onedrive process"):
        run_removal(home, proc, account=account, unit_file=unit_file, systemd=systemd)

    assert systemd.verbs() == []


def test_failing_trigger_disable_changes_nothing(home, proc):
    account, unit_file = make_account(home)
    systemd = systemd_for(unit_file, fail={("disable", TRIGGER)})

    with pytest.raises(ar.RemovalError, match=TRIGGER):
        run_removal(home, proc, account=account, unit_file=unit_file, systemd=systemd)

    assert ("disable", SERVICE) not in systemd.verbs()
    assert (account.confdir / "refresh_token").exists()


def test_failing_service_disable_enables_the_triggers_again(home, proc):
    account, unit_file = make_account(home)
    systemd = systemd_for(unit_file, fail={("disable", SERVICE)})
    trash = FakeTrash()

    with pytest.raises(ar.RemovalError) as error:
        run_removal(home, proc, account=account, unit_file=unit_file, systemd=systemd, trash=trash)

    assert systemd.units[TRIGGER]["enabled"] and systemd.units[TRIGGER]["active"]
    assert trash.moved == []
    assert (account.confdir / "refresh_token").exists()
    assert SERVICE in str(error.value)


def test_service_that_does_not_stop_is_undone(home, proc):
    account, unit_file = make_account(home)
    systemd = systemd_for(unit_file, stuck={SERVICE})
    trash = FakeTrash()

    with pytest.raises(ar.RemovalError, match="does not respond"):
        run_removal(home, proc, account=account, unit_file=unit_file, systemd=systemd, trash=trash)

    assert systemd.units[SERVICE]["enabled"]
    assert systemd.units[TRIGGER]["enabled"]
    assert trash.moved == []


def test_failing_upload_undoes_everything(home, proc):
    account, unit_file = make_account(home)
    systemd = systemd_for(unit_file)
    trash = FakeTrash()

    with pytest.raises(ar.RemovalError, match="exit code 1"):
        run_removal(home, proc, account=account, unit_file=unit_file, systemd=systemd, trash=trash,
                    popen=FakeUploadPopen(["ERROR: network"], returncode=1))

    assert systemd.units[SERVICE] == {**systemd.units[SERVICE], "enabled": True, "active": True}
    assert systemd.units[TRIGGER]["enabled"] and systemd.units[TRIGGER]["active"]
    assert unit_file.exists()
    assert (account.confdir / "refresh_token").exists()
    assert trash.moved == []


def test_undo_restores_only_what_was_enabled_and_active(home, proc):
    account, unit_file = make_account(home)
    systemd = FakeSystemd({
        SERVICE: FakeSystemd.unit(unit_file, enabled=True, active=False, triggered_by=TRIGGER),
        TRIGGER: FakeSystemd.unit(enabled=False, active=False),
    })

    with pytest.raises(ar.RemovalError):
        run_removal(home, proc, account=account, unit_file=unit_file, systemd=systemd,
                    popen=FakeUploadPopen([], returncode=1))

    assert ("enable", SERVICE) in systemd.verbs()
    assert ("start", SERVICE) not in systemd.verbs()
    assert ("enable", TRIGGER) not in systemd.verbs()
    assert ("start", TRIGGER) not in systemd.verbs()


def test_stop_during_upload_undoes_everything(home, proc):
    account, unit_file = make_account(home)
    systemd = systemd_for(unit_file)
    flag = CancelFlag()
    signals = FakeSignals()
    trash = FakeTrash()

    def on_line(line):
        if "a.txt" in line:
            assert flag.request() is True

    popen = FakeStoppablePopen(["Uploading file Docs/a.txt ..."], stops_on=(SIGTERM,), on_line=on_line)
    result, plan, systemd, trash, popen = run_removal(home, proc, account=account, unit_file=unit_file,
                                                      systemd=systemd, popen=popen, cancel=flag,
                                                      signals=signals, trash=trash)

    assert result.outcome == ar.CANCELLED
    assert signals.signals == [SIGTERM]
    assert systemd.units[SERVICE]["enabled"] and systemd.units[SERVICE]["active"]
    assert systemd.units[TRIGGER]["enabled"]
    assert trash.moved == []
    assert (account.confdir / "refresh_token").exists()


def test_failing_config_trash_names_the_folder(home, proc):
    account, unit_file = make_account(home)
    trash = FakeTrash(fail=[account.confdir])

    with pytest.raises(ar.RemovalError) as error:
        run_removal(home, proc, account=account, unit_file=unit_file, trash=trash)

    assert str(account.confdir) in str(error.value)
    assert "disabled" in str(error.value)


def test_failing_sync_trash_still_removes_the_account(home, proc):
    account, unit_file = make_account(home)
    trash = FakeTrash(fail=[home / "OneDrive-X"])

    result, *_ = run_removal(home, proc, account=account, unit_file=unit_file, trash=trash)

    assert result.outcome == ar.DONE
    assert result.sync_folder_left == home / "OneDrive-X"
    assert Registry.for_home(home).name_for(account.confdir) is None


# Safe mode

def test_safe_mode_changes_nothing(home, proc, monkeypatch):
    from skyhus import sideeffects
    account, unit_file = make_account(home)
    systemd = systemd_for(unit_file)
    monkeypatch.setattr(subprocess, "run", systemd)
    monkeypatch.setattr(sideeffects, "real_home", lambda: home)
    assert sideeffects.safe_mode()

    plan = ar.prepare(account, [account], home=home)
    result = ar.execute(plan, remove_sync_folder=True, home=home, proc_root=proc)

    assert result.outcome == ar.DONE
    assert [c for c in systemd.calls if c[2] != "show"] == []
    assert (account.confdir / "refresh_token").exists()
    assert unit_file.exists()
    assert Registry.for_home(home).name_for(account.confdir) == "X"
