"""Display names and slugs (feature 0001)."""

import pytest

from skyhus.accounts import Account
from skyhus.naming import (
    NamingError,
    plan_new_account,
    slugify,
    suggest_sync_dir,
    validate_display_name,
)

from conftest import make_account_dir


def account(home, dirname, name):
    return Account(name=name, confdir=home / ".config" / dirname, sync_dir="~/OneDrive",
                   service="", logged_in=True)


def test_slug_firma_2():
    assert slugify("Firma 2") == "firma-2"


def test_slug_danish_letters():
    assert slugify("Søstrenes Æbler") == "soestrenes-aebler"  # allow-danish: input that slugify must accept
    assert slugify("Ålborg Ø") == "aalborg-oe"  # allow-danish: input that slugify must accept


def test_new_account_paths(home):
    new = plan_new_account("Firma 2", [], home)

    assert new.name == "Firma 2"
    assert new.slug == "firma-2"
    assert new.confdir == home / ".config" / "onedrive-firma-2"
    assert new.service == "onedrive-firma-2.service"


def test_existing_display_name_fails_before_files(home):
    existing = [account(home, "onedrive-privat", "Privat")]
    before = sorted(p.name for p in (home / ".config").iterdir())

    with pytest.raises(NamingError):
        plan_new_account("privat ", existing, home)

    assert sorted(p.name for p in (home / ".config").iterdir()) == before


def test_existing_confdir_fails_before_files(home):
    make_account_dir(home, "onedrive-firma-2")
    before = sorted(p.name for p in (home / ".config").rglob("*"))

    with pytest.raises(NamingError):
        plan_new_account("Firma 2", [], home)

    assert sorted(p.name for p in (home / ".config").rglob("*")) == before


def test_existing_unit_fails_before_files(home):
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "onedrive-firma-2.service").write_text("[Service]\n")

    with pytest.raises(NamingError):
        plan_new_account("Firma 2", [], home)

    assert not (home / ".config" / "onedrive-firma-2").exists()


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_empty_name_fails(home, name):
    with pytest.raises(NamingError):
        plan_new_account(name, [], home)
    with pytest.raises(NamingError):
        validate_display_name(name, [])


def test_name_without_usable_letters_fails(home):
    with pytest.raises(NamingError):
        plan_new_account("!!!", [], home)


def test_name_skyhus_gives_its_own_confdir(home):
    """The folder ``~/.config/skyhus`` of the application cannot be mistaken for an account (feature 0012)."""
    plan = plan_new_account("Skyhus", [], home)

    assert plan.confdir == home / ".config" / "onedrive-skyhus"


def test_rename_may_keep_own_name(home):
    privat = account(home, "onedrive-privat", "Privat")

    assert validate_display_name(" Privat ", [privat], exclude=privat.confdir) == "Privat"
    with pytest.raises(NamingError):
        validate_display_name("Privat", [privat])


def test_suggested_sync_dir():
    assert suggest_sync_dir("Privat") == "~/OneDrive-Privat"
    assert suggest_sync_dir(" Firma 2 ") == "~/OneDrive-Firma-2"
