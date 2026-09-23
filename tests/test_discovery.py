"""Kontoopdagelse (feature 0001)."""

from skyhus.discovery import (
    discover_accounts,
    find_service,
    read_sync_dir,
)

from conftest import make_account_dir, make_unit


def by_confdir(accounts):
    return {a.confdir.name: a for a in accounts}


def test_finds_onedrive_and_onedrive_privat(home):
    make_account_dir(home, "onedrive", refresh_token=True, items=True)
    make_account_dir(home, "onedrive-privat", config='sync_dir = "~/OneDrive-Privat"\n')

    accounts = discover_accounts(home)

    assert len(accounts) == 2
    assert set(by_confdir(accounts)) == {"onedrive", "onedrive-privat"}


def test_refresh_token_means_logged_in(home):
    make_account_dir(home, "onedrive-a", config="", refresh_token=True)
    make_account_dir(home, "onedrive-b", config="")

    accounts = by_confdir(discover_accounts(home))

    assert accounts["onedrive-a"].logged_in is True
    assert accounts["onedrive-b"].logged_in is False


def test_skyhus_dir_is_not_an_account(home):
    gui = home / ".config" / "skyhus"
    gui.mkdir()
    (gui / "accounts.json").write_text("{}")
    (gui / "config").write_text("")

    assert discover_accounts(home) == []


def test_empty_dir_is_not_an_account(home):
    (home / ".config" / "onedrive-tom").mkdir()
    (home / ".config" / "onedrive-tom" / "andet").write_text("x")

    assert discover_accounts(home) == []


def test_unrelated_dirs_are_ignored(home):
    make_account_dir(home, "onedrivefoo", config="")
    make_account_dir(home, "andet", config="")

    assert discover_accounts(home) == []


def test_default_confdir_uses_onedrive_service(home):
    confdir = make_account_dir(home, "onedrive", refresh_token=True)

    assert find_service(confdir, home) == "onedrive.service"
    assert discover_accounts(home)[0].service == "onedrive.service"


def test_unit_with_matching_confdir_is_the_service(home):
    confdir = make_account_dir(home, "onedrive-privat", config="")
    make_unit(home, "onedrive-privat.service",
              '/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-privat"')
    make_unit(home, "andet.service", "/usr/bin/true")

    assert find_service(confdir, home) == "onedrive-privat.service"


def test_unit_for_a_longer_confdir_name_does_not_match(home):
    confdir = make_account_dir(home, "onedrive-priv", config="")
    make_unit(home, "onedrive-privat.service",
              '/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-privat"')

    assert find_service(confdir, home) == ""


def test_unit_with_absolute_or_tilde_confdir_matches(home):
    a = make_account_dir(home, "onedrive-a", config="")
    b = make_account_dir(home, "onedrive-b", config="")
    make_unit(home, "x.service", f"/usr/bin/onedrive --monitor --confdir {home}/.config/onedrive-a")
    make_unit(home, "y.service", "/usr/bin/onedrive --monitor --confdir='~/.config/onedrive-b'")

    assert find_service(a, home) == "x.service"
    assert find_service(b, home) == "y.service"


def test_confdir_without_unit_has_empty_service(home):
    confdir = make_account_dir(home, "onedrive-firma", config="")

    assert find_service(confdir, home) == ""
    assert discover_accounts(home)[0].service == ""


def test_sync_dir_from_config(home):
    confdir = make_account_dir(home, "onedrive-privat",
                               config='sync_dir = "~/OneDrive-Privat"\nskip_dir = "/Offentlig"\n')

    assert read_sync_dir(confdir) == "~/OneDrive-Privat"
    assert discover_accounts(home)[0].sync_dir == "~/OneDrive-Privat"


def test_sync_dir_defaults_to_onedrive(home):
    confdir = make_account_dir(home, "onedrive", refresh_token=True)

    assert read_sync_dir(confdir) == "~/OneDrive"


def test_commented_config_lines_are_ignored(home):
    confdir = make_account_dir(home, "onedrive-x", config=(
        '# sync_dir = "~/Forkert"\n'
        '   # sync_dir = "~/OgsaaForkert"\n'
    ))

    assert read_sync_dir(confdir) == "~/OneDrive"

    (confdir / "config").write_text('# sync_dir = "~/Forkert"\nsync_dir = "~/Rigtig"\n')
    assert read_sync_dir(confdir) == "~/Rigtig"
