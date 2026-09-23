"""Regler i sync_list (feature 0002)."""

import pytest

from onedrive_gui.synclist import (
    CheckState,
    Selection,
    SelectionError,
    parse_sync_list,
    read_sync_list,
    write_sync_list,
)

from conftest import make_account_dir

TREE = {
    "": ["Arbejde", "Dokumenter", "Billeder"],
    "Arbejde": ["Arbejde/Kunder", "Arbejde/Intern"],
    "Arbejde/Kunder": [],
    "Arbejde/Intern": [],
}


def children(path):
    return TREE.get(path)


def test_fully_selected_folder_gives_one_rule(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    selection = Selection()
    selection.toggle("Dokumenter", children)

    write_sync_list(confdir, False, selection.paths, [])

    assert (confdir / "sync_list").read_text() == "/Dokumenter/\n"


def test_partially_selected_folder_gives_rules_for_subfolders(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    selection = Selection()
    selection.toggle("Arbejde/Kunder", children)

    assert selection.state("Arbejde") is CheckState.PARTIAL
    write_sync_list(confdir, False, selection.paths, [])

    lines = (confdir / "sync_list").read_text().splitlines()
    assert lines == ["/Arbejde/Kunder/"]


def test_unchecking_subfolder_of_checked_folder_keeps_siblings():
    selection = Selection(["Arbejde"])

    selection.toggle("Arbejde/Intern", children)

    assert selection.paths == ["Arbejde/Kunder"]
    assert selection.state("Arbejde") is CheckState.PARTIAL
    assert selection.state("Arbejde/Intern") is CheckState.UNCHECKED


def test_checking_all_subfolders_checks_the_folder():
    selection = Selection(["Arbejde/Kunder"])

    selection.toggle("Arbejde/Intern", children)

    assert selection.paths == ["Arbejde"]
    assert selection.state("Arbejde") is CheckState.CHECKED


def test_sync_all_removes_sync_list(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    (confdir / "sync_list").write_text("/Dokumenter/\n")

    write_sync_list(confdir, True, [], [])

    assert not (confdir / "sync_list").exists()


def test_no_folders_and_not_sync_all_is_an_error(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    (confdir / "sync_list").write_text("/Dokumenter/\n")

    with pytest.raises(SelectionError):
        write_sync_list(confdir, False, [], ["# kommentar"])

    assert (confdir / "sync_list").read_text() == "/Dokumenter/\n"


def test_names_with_spaces_and_danish_letters_are_kept_exactly(home):
    confdir = make_account_dir(home, "onedrive-x", config="")

    write_sync_list(confdir, False, ["Mine Dokumenter/Æbler og Pærer"], [])

    assert (confdir / "sync_list").read_text(encoding="utf-8") == "/Mine Dokumenter/Æbler og Pærer/\n"
    assert read_sync_list(confdir).folders == ["Mine Dokumenter/Æbler og Pærer"]


def test_unknown_rules_stay_on_top_unchanged(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    (confdir / "sync_list").write_text("# Mine regler\n/Gammel/\n!/Hemmelig/*\n")

    current = read_sync_list(confdir)
    assert current.folders == ["Gammel"]
    assert current.unknown == ["# Mine regler", "!/Hemmelig/*"]
    write_sync_list(confdir, False, ["Dokumenter"], current.unknown)

    assert (confdir / "sync_list").read_text().splitlines() == [
        "# Mine regler", "!/Hemmelig/*", "/Dokumenter/"]


def test_sync_list_with_dokumenter_shows_it_as_checked(home):
    confdir = make_account_dir(home, "onedrive-x", config="")
    (confdir / "sync_list").write_text("/Dokumenter/\n")

    current = read_sync_list(confdir)
    selection = Selection(current.folders)

    assert current.exists is True
    assert selection.state("Dokumenter") is CheckState.CHECKED
    assert selection.state("Billeder") is CheckState.UNCHECKED


def test_missing_sync_list_means_sync_all(home):
    confdir = make_account_dir(home, "onedrive-x", config="")

    assert read_sync_list(confdir).exists is False


def test_rules_without_leading_slash_or_with_wildcards_are_unknown():
    parsed = parse_sync_list("Dokumenter\n/Billeder/*\n/A/B/\n\n-/C/\n/D\n")

    assert parsed.folders == ["A/B"]
    assert parsed.unknown == ["Dokumenter", "/Billeder/*", "", "-/C/", "/D"]
