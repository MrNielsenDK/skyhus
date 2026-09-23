"""Lokale stier, der forsvinder, når valget ændrer sig (feature 0002)."""

import pytest

from skyhus.removal import Rules, find_removed, format_size, total_size
from skyhus.rules import RuleSet

ALL = Rules(None, False)


@pytest.fixture
def sync(home):
    """~/OneDrive-X med mapperne A, B og C og 2 filer i roden."""
    root = home / "OneDrive-X"
    for folder in ("A/B", "A/C", "B", "C"):
        (root / folder).mkdir(parents=True)
    (root / "A" / "i-a.txt").write_text("12345")
    (root / "A" / "B" / "i-b.txt").write_text("1")
    (root / "A" / "C" / "i-c.txt").write_text("123")
    (root / "B" / "i-b.txt").write_text("12")
    (root / "rod.txt").write_text("r")
    (root / "rod2.txt").write_text("r")
    return root


def names(removed, root):
    return sorted(str(r.path.relative_to(root)) for r in removed)


def test_removing_rule_b_removes_folder_b(sync):
    removed = find_removed(sync, Rules(["A", "B"], False), Rules(["A"], False))

    assert names(removed, sync) == ["B"]


def test_narrowing_a_to_a_b_removes_siblings_and_files_in_a(sync):
    removed = find_removed(sync, Rules(["A"], False), Rules(["A/B"], False))

    assert names(removed, sync) == ["A/C", "A/i-a.txt"]


def test_from_all_folders_to_a_removes_other_root_items(sync):
    removed = find_removed(sync, ALL, Rules(["A"], False))

    assert names(removed, sync) == ["B", "C", "rod.txt", "rod2.txt"]


def test_from_all_folders_to_a_with_root_files_keeps_root_files(sync):
    removed = find_removed(sync, ALL, Rules(["A"], True))

    assert names(removed, sync) == ["B", "C"]


def test_turning_root_files_off_removes_root_files_only(sync):
    removed = find_removed(sync, Rules(["A", "B"], True), Rules(["A", "B"], False))

    assert names(removed, sync) == ["rod.txt", "rod2.txt"]


def test_skip_dir_never_disappears(sync):
    removed = find_removed(sync, Rules(["A", "B", "C"], False), Rules(["A"], False),
                           skip_dirs=["C"])

    assert names(removed, sync) == ["B"]


def test_skip_dir_with_full_path(sync):
    removed = find_removed(sync, Rules(["A"], False), Rules(["A/B"], False),
                           skip_dirs=["/A/C"])

    assert names(removed, sync) == ["A/i-a.txt"]


def test_only_adding_folders_removes_nothing(sync):
    assert find_removed(sync, Rules(["A"], False), Rules(["A", "B", "C"], False)) == []
    assert find_removed(sync, Rules(["A"], False), ALL) == []
    assert find_removed(sync, Rules(["A/B"], False), Rules(["A"], False)) == []


def test_folder_that_was_not_synced_is_left_alone(sync):
    (sync / "Lokal").mkdir()

    removed = find_removed(sync, Rules(["A", "B"], False), Rules(["A"], False))

    assert names(removed, sync) == ["B"]


def test_total_size_counts_files_in_folders(sync):
    removed = find_removed(sync, ALL, Rules(["C"], False))

    assert names(removed, sync) == ["A", "B", "rod.txt", "rod2.txt"]
    assert total_size(removed) == 5 + 1 + 3 + 2 + 1 + 1


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(1536) == "1,5 kB"
    assert format_size(5 * 1024 * 1024) == "5,0 MB"


# Feature 0006: papirkurven respekterer alle regler.


@pytest.fixture
def work(home):
    """~/OneDrive-X med mappen Arbejde og mappen Andet."""
    root = home / "OneDrive-X"
    for folder in ("Arbejde/Hemmelig", "Arbejde/Projekt", "Andet"):
        (root / folder).mkdir(parents=True)
    (root / "Arbejde" / "plan.txt").write_text("plan")
    (root / "Arbejde" / "Hemmelig" / "lokal.txt").write_text("kun lokalt")
    (root / "Arbejde" / "Projekt" / "kode.py").write_text("print()")
    return root


def test_excluded_folder_in_deselected_folder_stays(work):
    unknown = ["!/Arbejde/Hemmelig/*"]
    old = RuleSet(["Andet", "Arbejde"], False, unknown)
    new = RuleSet(["Andet"], False, unknown)

    removed = find_removed(work, old, new)

    assert names(removed, work) == ["Arbejde/Projekt", "Arbejde/plan.txt"]


def test_folder_with_excluded_path_is_not_removed_itself(work):
    unknown = ["!/Arbejde/Hemmelig/*"]
    removed = find_removed(work, RuleSet(["Andet", "Arbejde"], False, unknown),
                           RuleSet(["Andet"], False, unknown))

    assert "Arbejde" not in names(removed, work)
    assert (work / "Arbejde") not in [r.path for r in removed]


def test_anywhere_rule_keeps_matching_folder(work):
    (work / "Arbejde" / "Documents").mkdir()
    (work / "Arbejde" / "Documents" / "brev.txt").write_text("brev")
    unknown = ["Documents/"]

    removed = find_removed(work, RuleSet(["Andet", "Arbejde"], False, unknown),
                           RuleSet(["Andet"], False, unknown))

    assert not any(n.startswith("Arbejde/Documents") for n in names(removed, work))
    assert "Arbejde/plan.txt" in names(removed, work)


def test_default_skip_file_keeps_tmp_file(work):
    (work / "Arbejde" / "noter.tmp").write_text("tmp")

    removed = find_removed(work, RuleSet(["Andet", "Arbejde"], False),
                           RuleSet(["Andet"], False))

    assert "Arbejde/noter.tmp" not in names(removed, work)
    assert "Arbejde" not in names(removed, work)
    assert "Arbejde/plan.txt" in names(removed, work)


def test_skip_dotfiles_true_keeps_dotfile(work):
    (work / "Arbejde" / ".env").write_text("HEMMELIG=1")

    removed = find_removed(work, RuleSet(["Andet", "Arbejde"], False, skip_dotfiles=True),
                           RuleSet(["Andet"], False, skip_dotfiles=True))

    assert "Arbejde/.env" not in names(removed, work)
    assert "Arbejde" not in names(removed, work)


def test_skip_dotfiles_false_removes_dotfile(work):
    (work / "Arbejde" / ".env").write_text("HEMMELIG=1")
    (work / "Arbejde" / "Hemmelig" / "lokal.txt").unlink()

    removed = find_removed(work, RuleSet(["Andet", "Arbejde"], False, skip_dotfiles=False),
                           RuleSet(["Andet"], False, skip_dotfiles=False))

    # Arbejde har ingen udelukkede stier. Hele mappen står på listen.
    assert names(removed, work) == ["Arbejde"]
    assert (work / "Arbejde" / ".env").exists()


def test_deselected_folder_without_excluded_paths_is_listed_alone(work):
    removed = find_removed(work, RuleSet(["Andet", "Arbejde"], False), RuleSet(["Andet"], False))

    assert names(removed, work) == ["Arbejde"]


def test_symlink_in_deselected_folder_is_never_listed(work, tmp_path):
    target = tmp_path / "udenfor.txt"
    target.write_text("uden for OneDrive")
    (work / "Arbejde" / "genvej").symlink_to(target)

    removed = find_removed(work, RuleSet(["Andet", "Arbejde"], False), RuleSet(["Andet"], False))

    assert "Arbejde/genvej" not in names(removed, work)
    assert "Arbejde" not in names(removed, work)
    assert "Arbejde/plan.txt" in names(removed, work)


def test_folder_with_nosync_is_never_listed(work):
    (work / "Arbejde" / "Projekt" / ".nosync").write_text("")

    removed = find_removed(work, RuleSet(["Andet", "Arbejde"], False), RuleSet(["Andet"], False))

    assert not any(n.startswith("Arbejde/Projekt") for n in names(removed, work))
    assert "Arbejde" not in names(removed, work)
    assert "Arbejde/plan.txt" in names(removed, work)


def test_globbing_exclusion_keeps_node_modules_on_level_3(work):
    deep = work / "Arbejde" / "Projekt" / "web" / "node_modules"
    deep.mkdir(parents=True)
    (deep / "pakke.js").write_text("js")
    unknown = ["!**/node_modules/*"]

    removed = find_removed(work, RuleSet(["Andet", "Arbejde"], False, unknown),
                           RuleSet(["Andet"], False, unknown))

    assert not any("node_modules" in n for n in names(removed, work))
    assert "Arbejde/Projekt/kode.py" in names(removed, work)


def test_from_all_folders_to_a_is_unchanged_with_default_skip_file(sync):
    removed = find_removed(sync, RuleSet(None, False), RuleSet(["A"], False))

    assert names(removed, sync) == ["B", "C", "rod.txt", "rod2.txt"]
