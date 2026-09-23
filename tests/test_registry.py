"""The registry of display names (feature 0001)."""

import json

from skyhus.discovery import discover_accounts
from skyhus.registry import Registry, default_name

from conftest import make_account_dir


def registry_path(home):
    return home / ".config" / "skyhus" / "accounts.json"


def test_rename_is_saved_and_survives_restart(home):
    confdir = make_account_dir(home, "onedrive", refresh_token=True)

    Registry.for_home(home).set_name(confdir, "Firma 1")

    data = json.loads(registry_path(home).read_text())
    assert [a["name"] for a in data["accounts"]] == ["Firma 1"]

    # A new instance is the same as a restart of the application.
    accounts = discover_accounts(home, Registry.for_home(home))
    assert accounts[0].name == "Firma 1"


def test_registry_stores_confdir_and_service(home):
    confdir = make_account_dir(home, "onedrive-firma-2", config="")

    registry = Registry.for_home(home)
    registry.add(confdir, "Firma 2")
    registry.set_service(confdir, "onedrive-firma-2.service")

    entry = json.loads(registry_path(home).read_text())["accounts"][0]
    assert entry == {"name": "Firma 2", "confdir": str(confdir),
                     "service": "onedrive-firma-2.service"}


def test_default_name_without_registry_entry(home):
    make_account_dir(home, "onedrive", refresh_token=True)
    make_account_dir(home, "onedrive-privat", config="")

    names = {a.confdir.name: a.name for a in discover_accounts(home, Registry.for_home(home))}

    assert names == {"onedrive": "OneDrive", "onedrive-privat": "privat"}
    assert default_name(home / ".config" / "onedrive-firma-2") == "firma-2"


def test_broken_registry_still_shows_accounts(home):
    make_account_dir(home, "onedrive", refresh_token=True)
    registry_path(home).parent.mkdir(parents=True)
    registry_path(home).write_text("{not json")

    accounts = discover_accounts(home, Registry.for_home(home))

    assert [a.name for a in accounts] == ["OneDrive"]


def test_registry_with_wrong_shape_is_ignored(home):
    make_account_dir(home, "onedrive", refresh_token=True)
    registry_path(home).parent.mkdir(parents=True)
    registry_path(home).write_text('{"accounts": [1, {"name": 2}, "x"]}')

    accounts = discover_accounts(home, Registry.for_home(home))

    assert [a.name for a in accounts] == ["OneDrive"]
