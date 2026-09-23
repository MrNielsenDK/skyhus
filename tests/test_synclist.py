"""Rules in sync_list (feature 0002)."""

import pytest

from skyhus.synclist import (
    CheckState,
    Selection,
    SelectionError,
    parse_sync_list,
    read_sync_list,
    write_sync_list,
)

from conftest import make_account_dir

TREE = {
    "": ["Work", "Documents", "Pictures"],
    "Work": ["Work/Customers", "Work/Internal"],
    "Work/Customers": [],
    "Work/Internal": [],
}


def children(path):
    return TREE.get(path)


def test_fully_selected_folder_gives_one_rule(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    selection = Selection()
    selection.toggle("Documents", children)

    write_sync_list(confdir, False, selection.paths, [])

    assert (confdir / "sync_list").read_text() == "/Documents/\n"


def test_partially_selected_folder_gives_rules_for_subfolders(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    selection = Selection()
    selection.toggle("Work/Customers", children)

    assert selection.state("Work") is CheckState.PARTIAL
    write_sync_list(confdir, False, selection.paths, [])

    lines = (confdir / "sync_list").read_text().splitlines()
    assert lines == ["/Work/Customers/"]


def test_unchecking_subfolder_of_checked_folder_keeps_siblings():
    selection = Selection(["Work"])

    selection.toggle("Work/Internal", children)

    assert selection.paths == ["Work/Customers"]
    assert selection.state("Work") is CheckState.PARTIAL
    assert selection.state("Work/Internal") is CheckState.UNCHECKED


def test_checking_all_subfolders_checks_the_folder():
    selection = Selection(["Work/Customers"])

    selection.toggle("Work/Internal", children)

    assert selection.paths == ["Work"]
    assert selection.state("Work") is CheckState.CHECKED


def test_sync_all_removes_sync_list(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    (confdir / "sync_list").write_text("/Documents/\n")

    write_sync_list(confdir, True, [], [])

    assert not (confdir / "sync_list").exists()


def test_no_folders_and_not_sync_all_is_an_error(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    (confdir / "sync_list").write_text("/Documents/\n")

    with pytest.raises(SelectionError):
        write_sync_list(confdir, False, [], ["# comment"])

    assert (confdir / "sync_list").read_text() == "/Documents/\n"


def test_names_with_spaces_and_danish_letters_are_kept_exactly(home):
    confdir = make_account_dir(home, "onedrive-x", config="")

    write_sync_list(confdir, False, ["Mine Dokumenter/Æbler og Pærer"], [])  # allow-danish: folder name test data

    assert (confdir / "sync_list").read_text(encoding="utf-8") == "/Mine Dokumenter/Æbler og Pærer/\n"  # allow-danish: folder name test data
    assert read_sync_list(confdir).folders == ["Mine Dokumenter/Æbler og Pærer"]  # allow-danish: folder name test data


def test_unknown_rules_stay_on_top_unchanged(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    (confdir / "sync_list").write_text("# My rules\n/Old/\n!/Secret/*\n")

    current = read_sync_list(confdir)
    assert current.folders == ["Old"]
    assert current.unknown == ["# My rules", "!/Secret/*"]
    write_sync_list(confdir, False, ["Documents"], current.unknown)

    assert (confdir / "sync_list").read_text().splitlines() == [
        "# My rules", "!/Secret/*", "/Documents/"]


def test_sync_list_with_documents_shows_it_as_checked(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    (confdir / "sync_list").write_text("/Documents/\n")

    current = read_sync_list(confdir)
    selection = Selection(current.folders)

    assert current.exists is True
    assert selection.state("Documents") is CheckState.CHECKED
    assert selection.state("Pictures") is CheckState.UNCHECKED


def test_missing_sync_list_means_sync_all(home):
    confdir = make_account_dir(home, "onedrive-x", config="")

    assert read_sync_list(confdir).exists is False


def test_rules_without_leading_slash_or_with_wildcards_are_unknown():
    parsed = parse_sync_list("Documents\n/Pictures/*\n/A/B/\n\n-/C/\n/D\n")

    assert parsed.folders == ["A/B"]
    assert parsed.unknown == ["Documents", "/Pictures/*", "", "-/C/", "/D"]
