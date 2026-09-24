"""The button and the sheet "Remove account?" (feature 0018)."""

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtGui = pytest.importorskip("PySide6.QtGui")
from PySide6.QtCore import QObject  # noqa: E402

from skyhus.registry import Registry  # noqa: E402
from skyhus.viewmodels import AppController  # noqa: E402

from conftest import make_account_dir  # noqa: E402
from fakes import FakeSignals, FakeStoppablePopen, FakeUploadPopen  # noqa: E402
from test_account_removal import SERVICE, TRIGGER, FakeSystemd, FakeTrash, make_account  # noqa: E402
from test_qml import load, visible_items  # noqa: E402,F401


class MovingTrash(FakeTrash):
    """Moves the path into a Trash folder in the test folder, as the real Trash does."""

    def __init__(self, folder, fail=()):
        super().__init__(fail)
        self.folder = Path(folder)
        self.folder.mkdir(exist_ok=True)

    def __call__(self, path):
        import shutil
        if not super().__call__(path):
            return False
        shutil.move(str(path), str(self.folder / Path(path).name))
        return True


def systemd_with_status(unit_file):
    systemd = FakeSystemd({
        SERVICE: FakeSystemd.unit(unit_file, triggered_by=TRIGGER),
        TRIGGER: FakeSystemd.unit(),
    })
    original = systemd._show

    def show(name):
        # The status reader asks for more properties. The fake gives the same block.
        return original(name) + "\nSubState=running\nResult=success\nExecMainStatus=0\nMainPID=0"

    systemd._show = show
    return systemd


def setup(home, tmp_path, *, popen=None, trash=None):
    account, unit_file = make_account(home)
    systemd = systemd_with_status(unit_file)
    proc = tmp_path / "proc"
    proc.mkdir(exist_ok=True)
    trash = trash if trash is not None else MovingTrash(tmp_path / "Trash")
    controller = AppController(home, run=systemd, proc_root=proc, trash=trash,
                               popen=popen if popen is not None else FakeUploadPopen(["Uploading file Docs/a.txt"]),
                               send_signal=FakeSignals())
    return controller, account, systemd, trash


def pump(controller, predicate, timeout=5.0):
    app = QtGui.QGuiApplication.instance()
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        controller._poll_remove()
        controller._poll_status()
        controller._poll_close()
        app.processEvents()
        time.sleep(0.01)
    assert predicate()


def open_confirmation(controller, account):
    controller.requestRemoveAccount(str(account.confdir))
    pump(controller, lambda: controller.removeState in ("confirm", "failed"))
    assert controller.removeState == "confirm", controller.removeError


# Controller

def test_request_shows_what_skyhus_removes_and_keeps(app, home, tmp_path):
    controller, account, systemd, trash = setup(home, tmp_path)

    open_confirmation(controller, account)

    plan = controller.removePlan
    assert plan["name"] == "X"
    assert controller.removeSyncFolder is True
    assert any(SERVICE in line and "unit file removed" in line for line in plan["removes"])
    assert any(TRIGGER in line and "stays" in line for line in plan["removes"])
    assert any("config folder" in line and "token is deleted" in line for line in plan["removes"])
    assert any("sync folder" in line for line in plan["removes"])
    assert plan["keeps"] == ["The files on OneDrive"]
    assert plan["localOnlyText"] == "1 file is only on this computer (9 B)"
    assert plan["localOnlyPaths"] == ["draft.tmp"]
    assert [c for c in systemd.calls if c[2] != "show"] == []


def test_unchecking_the_sync_folder_moves_it_to_keeps(app, home, tmp_path):
    controller, account, systemd, trash = setup(home, tmp_path)
    open_confirmation(controller, account)

    controller.setRemoveSyncFolder(False)

    plan = controller.removePlan
    assert not any("sync folder" in line for line in plan["removes"])
    assert any(str(home / "OneDrive-X") in line for line in plan["keeps"])


def test_cancel_changes_nothing(app, home, tmp_path):
    controller, account, systemd, trash = setup(home, tmp_path)
    open_confirmation(controller, account)

    controller.closeRemoveAccount()

    assert controller.removeState == ""
    assert [c for c in systemd.calls if c[2] != "show"] == []
    assert (account.confdir / "refresh_token").exists()


def test_confirm_removes_the_account(app, home, tmp_path):
    controller, account, systemd, trash = setup(home, tmp_path)
    open_confirmation(controller, account)

    controller.confirmRemoveAccount()
    assert controller.requestClose() is False
    pump(controller, lambda: controller.removeState == "")

    assert controller.accounts.rowCount() == 0
    assert controller.message == "The account X is removed."
    assert trash.moved == [account.confdir, home / "OneDrive-X"]
    assert Registry.for_home(home).name_for(account.confdir) is None
    assert controller.requestClose() is True


def test_confirm_without_sync_folder_keeps_it(app, home, tmp_path):
    controller, account, systemd, trash = setup(home, tmp_path)
    open_confirmation(controller, account)
    controller.setRemoveSyncFolder(False)

    controller.confirmRemoveAccount()
    pump(controller, lambda: controller.removeState == "")

    assert trash.moved == [account.confdir]
    assert (home / "OneDrive-X" / "Docs" / "a.txt").exists()


def test_failed_upload_shows_the_error_and_keeps_the_account(app, home, tmp_path):
    controller, account, systemd, trash = setup(home, tmp_path,
                                                popen=FakeUploadPopen(["ERROR: network"], returncode=1))
    open_confirmation(controller, account)

    controller.confirmRemoveAccount()
    pump(controller, lambda: controller.removeState == "failed")

    assert "exit code 1" in controller.removeError
    assert "enabled the service again" in controller.removeError
    assert controller.accounts.rowCount() == 1
    assert trash.moved == []
    controller.closeRemoveAccount()
    assert controller.removeState == ""


def test_stop_during_upload_undoes_the_removal(app, home, tmp_path):
    popen = FakeStoppablePopen(["Uploading file Docs/a.txt ..."])
    controller, account, systemd, trash = setup(home, tmp_path, popen=popen)
    open_confirmation(controller, account)

    controller.confirmRemoveAccount()
    pump(controller, lambda: controller.removeCancellable)
    controller.stopRemoveAccount()
    pump(controller, lambda: controller.removeState == "cancelled")

    assert controller.accounts.rowCount() == 1
    assert systemd.units[SERVICE]["enabled"] and systemd.units[SERVICE]["active"]
    assert trash.moved == []


def test_request_is_ignored_during_sign_in(app, home, tmp_path):
    controller, account, systemd, trash = setup(home, tmp_path)
    controller._login_state = "waiting_for_user"

    controller.requestRemoveAccount(str(account.confdir))

    assert controller.removeState == ""


def test_prepare_error_is_shown(app, home, tmp_path):
    controller, account, systemd, trash = setup(home, tmp_path)
    account_in_model = controller.accounts.accounts()[0]
    account_in_model.confdir = tmp_path / "elsewhere"

    controller.requestRemoveAccount(str(account_in_model.confdir))
    pump(controller, lambda: controller.removeState == "failed")

    assert "does not remove the folder" in controller.removeError


# QML

def test_sheet_shows_the_confirmation_and_removes_the_account(load, home, tmp_path):
    account, unit_file = make_account(home)
    other = make_account_dir(home, "onedrive-y", config='sync_dir = "~/OneDrive-Y"\n', refresh_token=True)
    systemd = systemd_with_status(unit_file)
    proc = tmp_path / "proc"
    proc.mkdir()
    engine, controller, warnings = load(home, run=systemd, proc_root=proc, trash=MovingTrash(tmp_path / "Trash"),
                                        popen=FakeUploadPopen([]), send_signal=FakeSignals())
    root = engine.rootObjects()[0]
    assert visible_items(root, "removeAccountButton")

    open_confirmation(controller, account)
    pump(controller, lambda: bool(visible_items(root, "removeConfirmButton")))

    boxes = visible_items(root, "removeSyncFolderBox")
    assert len(boxes) == 1 and boxes[0].property("checked") is True
    assert [t.property("text") for t in visible_items(root, "localOnlyText")] == \
        ["1 file is only on this computer (9 B)"]
    assert visible_items(root, "microsoftNote")
    assert len(visible_items(root, "removeLine")) == 4

    controller.confirmRemoveAccount()
    pump(controller, lambda: controller.removeState == "")
    pump(controller, lambda: root.findChild(QObject, "accountList").property("count") == 1)

    assert visible_items(root, "removeConfirmButton") == []
    account_list = root.findChild(QObject, "accountList")
    assert account_list.property("currentIndex") == 0
    assert controller.accounts.accounts()[0].confdir == other
    assert warnings == []


def test_sheet_without_trashable_sync_folder_shows_the_reason(load, home, tmp_path):
    account, unit_file = make_account(home)
    (home / "OneDrive-X").rename(home / "Moved")
    systemd = systemd_with_status(unit_file)
    proc = tmp_path / "proc"
    proc.mkdir()
    engine, controller, warnings = load(home, run=systemd, proc_root=proc)
    root = engine.rootObjects()[0]

    open_confirmation(controller, account)
    pump(controller, lambda: bool(visible_items(root, "removeConfirmButton")))

    assert visible_items(root, "removeSyncFolderBox") == []
    reasons = visible_items(root, "removeSyncReason")
    assert len(reasons) == 1 and "does not exist" in reasons[0].property("text")
    controller.closeRemoveAccount()
    assert warnings == []
