"""Folders from Microsoft Graph (feature 0002).

The tests do not call Microsoft. ``FakeGraph`` gives recorded responses.
"""

from urllib.parse import parse_qs

import pytest

from skyhus.graph import (
    CLIENT_ID,
    GRAPH_URL,
    TOKEN_URL,
    GraphClient,
    LoginRequiredError,
    NotLoggedInError,
)

from conftest import make_account_dir
from fakes import FakeGraph, file_item, folder, http_error

ROOT_CHILDREN = "/v1.0/me/drive/root/children"


def test_returns_only_folders(home):
    confdir = make_account_dir(home, "onedrive-x", config="", refresh_token=True)
    graph = FakeGraph({ROOT_CHILDREN: {"value": [
        folder("Documents", child_count=2), file_item("notes.txt"), folder("Pictures")]}})

    folders = GraphClient(confdir, opener=graph).list_folders()

    assert [f.name for f in folders] == ["Documents", "Pictures"]
    by_name = {f.name: f for f in folders}
    assert by_name["Documents"].path == "Documents"
    assert by_name["Documents"].has_children is True
    assert by_name["Pictures"].has_children is False


def test_follows_next_link(home):
    confdir = make_account_dir(home, "onedrive-x", config="", refresh_token=True)
    next_url = f"{GRAPH_URL}/me/drive/root/children?$skiptoken=page2"
    graph = FakeGraph({
        ROOT_CHILDREN: {"value": [folder("A")], "@odata.nextLink": next_url},
        next_url: {"value": [folder("B")]},
    })

    folders = GraphClient(confdir, opener=graph).list_folders()

    assert [f.name for f in folders] == ["A", "B"]
    assert graph.graph_requests()[-1].full_url == next_url


def test_children_of_a_folder_get_full_path(home):
    confdir = make_account_dir(home, "onedrive-x", config="", refresh_token=True)
    graph = FakeGraph({"/v1.0/me/drive/items/id-Work/children": {"value": [folder("Customers")]}})
    client = GraphClient(confdir, opener=graph)

    folders = client.list_folders("id-Work", "Work")

    assert [f.path for f in folders] == ["Work/Customers"]
    assert graph.graph_requests()[0].get_header("Authorization") == "Bearer access"


def test_token_call_leaves_refresh_token_unchanged(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    original = b"old-token\xc3\xa9\n"
    (confdir / "refresh_token").write_bytes(original)
    graph = FakeGraph({ROOT_CHILDREN: {"value": []}})

    GraphClient(confdir, opener=graph).list_folders()

    assert (confdir / "refresh_token").read_bytes() == original
    token_request = graph.requests[0]
    assert token_request.full_url == TOKEN_URL
    form = parse_qs(token_request.data.decode())
    assert form["client_id"] == [CLIENT_ID]
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["old-tokené"]
    assert "offline_access" in form["scope"][0].split()
    assert "Files.ReadWrite.All" in form["scope"][0].split()


def test_missing_refresh_token_means_not_logged_in(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    graph = FakeGraph()

    with pytest.raises(NotLoggedInError, match="The account is not signed in"):
        GraphClient(confdir, opener=graph).list_folders()

    assert graph.requests == []


def test_invalid_grant_asks_user_to_log_in_again(home):
    confdir = make_account_dir(home, "onedrive-x", config="", refresh_token=True)
    graph = FakeGraph(token=http_error(TOKEN_URL, 400, {
        "error": "invalid_grant", "error_description": "AADSTS70000: token expired"}))

    with pytest.raises(LoginRequiredError, match="(?i)sign in .*again"):
        GraphClient(confdir, opener=graph).list_folders()
