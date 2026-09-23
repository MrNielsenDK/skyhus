"""sync_root_files og skip_dir i kontoens config (feature 0002)."""

from skyhus.config import (
    DEFAULT_SKIP_FILE,
    read_skip_dirs,
    read_skip_dotfiles,
    read_skip_files,
    read_sync_root_files,
    write_sync_root_files,
)

from conftest import make_account_dir

CONFIG = '# Min config\nsync_dir = "~/OneDrive-X"\n\n# sync_root_files = "true"\nmonitor_interval = "300"\n'


def test_enabling_root_files_keeps_other_lines(home):
    confdir = make_account_dir(home, "onedrive-x", config=CONFIG)

    write_sync_root_files(confdir, True)

    text = (confdir / "config").read_text()
    assert text == CONFIG + 'sync_root_files = "true"\n'
    assert read_sync_root_files(confdir) is True


def test_existing_line_is_changed_in_place(home):
    confdir = make_account_dir(home, "onedrive-x",
                               config='sync_dir = "~/X"\nsync_root_files = "true"\nskip_dotfiles = "true"\n')

    write_sync_root_files(confdir, False)

    assert (confdir / "config").read_text() == (
        'sync_dir = "~/X"\nsync_root_files = "false"\nskip_dotfiles = "true"\n')
    assert read_sync_root_files(confdir) is False


def test_missing_value_means_false(home):
    confdir = make_account_dir(home, "onedrive-x", config=CONFIG)

    assert read_sync_root_files(confdir) is False


def test_config_without_final_newline(home):
    confdir = make_account_dir(home, "onedrive-x", config='sync_dir = "~/X"')

    write_sync_root_files(confdir, True)

    assert (confdir / "config").read_text() == 'sync_dir = "~/X"\nsync_root_files = "true"\n'


def test_skip_dir_values_are_split_and_joined(home):
    confdir = make_account_dir(home, "onedrive-x", config=(
        'skip_dir = "Desktop|Documents/IISExpress"\n# skip_dir = "Ikke"\nskip_dir = "/Eksplicit/Sti"\n'))

    assert read_skip_dirs(confdir) == ["Desktop", "Documents/IISExpress", "/Eksplicit/Sti"]


# Feature 0006: skip_file og skip_dotfiles.


def test_skip_file_default_when_missing(home):
    confdir = make_account_dir(home, "onedrive-x", config=CONFIG)

    assert DEFAULT_SKIP_FILE == "~*|.~*|*.tmp|*.swp|*.partial"
    assert read_skip_files(confdir) == ["~*", ".~*", "*.tmp", "*.swp", "*.partial"]


def test_skip_file_values_replace_default_and_are_joined(home):
    confdir = make_account_dir(home, "onedrive-x", config=(
        'skip_file = "*.bak|~*"\n# skip_file = "*.ikke"\nskip_file = "/Documents/keepass.kdbx"\n'))

    assert read_skip_files(confdir) == ["*.bak", "~*", "/Documents/keepass.kdbx"]


def test_empty_skip_file_skips_nothing(home):
    confdir = make_account_dir(home, "onedrive-x", config='skip_file = ""\n')

    assert read_skip_files(confdir) == []


def test_skip_dotfiles_default_false(home):
    assert read_skip_dotfiles(make_account_dir(home, "onedrive-x", config=CONFIG)) is False
    assert read_skip_dotfiles(make_account_dir(home, "onedrive-y", config='skip_dotfiles = "true"\n')) is True
