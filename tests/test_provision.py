"""Oprettelse af config-mappe og synkmappe (feature 0001)."""

import pytest

from onedrive_gui.provision import provision_account


def test_config_contains_exactly_the_chosen_sync_dir(home):
    confdir = home / ".config" / "onedrive-firma-2"

    provision_account(confdir, "~/OneDrive-Firma 2")

    assert (confdir / "config").read_text() == 'sync_dir = "~/OneDrive-Firma 2"\n'


def test_missing_sync_dir_is_created(home):
    confdir = home / ".config" / "onedrive-firma-2"

    provision_account(confdir, "~/Sky/OneDrive-Firma-2")

    assert (home / "Sky" / "OneDrive-Firma-2").is_dir()


def test_existing_sync_dir_is_kept(home):
    sync = home / "OneDrive-X"
    sync.mkdir()
    (sync / "fil.txt").write_text("indhold")

    provision_account(home / ".config" / "onedrive-x", str(sync))

    assert (sync / "fil.txt").read_text() == "indhold"


def test_existing_confdir_is_not_overwritten(home):
    confdir = home / ".config" / "onedrive-x"
    confdir.mkdir()
    (confdir / "config").write_text('sync_dir = "~/Gammel"\n')

    with pytest.raises(FileExistsError):
        provision_account(confdir, "~/Ny")

    assert (confdir / "config").read_text() == 'sync_dir = "~/Gammel"\n'


@pytest.mark.parametrize("sync_dir", ["", "  ", '~/Med"Citat', "~/To\nLinjer"])
def test_invalid_sync_dir_fails_before_files(home, sync_dir):
    confdir = home / ".config" / "onedrive-x"

    with pytest.raises(ValueError):
        provision_account(confdir, sync_dir)

    assert not confdir.exists()
