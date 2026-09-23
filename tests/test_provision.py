"""Creation of the config folder and the sync folder (feature 0001)."""

import pytest

from skyhus.provision import provision_account


def test_config_contains_exactly_the_chosen_sync_dir(home):
    confdir = home / ".config" / "onedrive-firma-2"

    provision_account(confdir, "~/OneDrive-Firma 2")

    assert (confdir / "config").read_text() == 'sync_dir = "~/OneDrive-Firma 2"\n'


def test_missing_sync_dir_is_created(home):
    confdir = home / ".config" / "onedrive-firma-2"

    provision_account(confdir, "~/Cloud/OneDrive-Firma-2")

    assert (home / "Cloud" / "OneDrive-Firma-2").is_dir()


def test_existing_sync_dir_is_kept(home):
    sync = home / "OneDrive-X"
    sync.mkdir()
    (sync / "file.txt").write_text("content")

    provision_account(home / ".config" / "onedrive-x", str(sync))

    assert (sync / "file.txt").read_text() == "content"


def test_existing_confdir_is_not_overwritten(home):
    confdir = home / ".config" / "onedrive-x"
    confdir.mkdir()
    (confdir / "config").write_text('sync_dir = "~/Old"\n')

    with pytest.raises(FileExistsError):
        provision_account(confdir, "~/New")

    assert (confdir / "config").read_text() == 'sync_dir = "~/Old"\n'


@pytest.mark.parametrize("sync_dir", ["", "  ", '~/With"Quote', "~/Two\nLines"])
def test_invalid_sync_dir_fails_before_files(home, sync_dir):
    confdir = home / ".config" / "onedrive-x"

    with pytest.raises(ValueError):
        provision_account(confdir, sync_dir)

    assert not confdir.exists()
