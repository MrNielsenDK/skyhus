"""Local paths that disappear when the selection changes (feature 0002)."""

import pytest

from skyhus.removal import Rules, find_removed, format_size, total_size
from skyhus.rules import RuleSet

ALL = Rules(None, False)


@pytest.fixture
def sync(home):
    """~/OneDrive-X with the folders A, B and C and 2 files in the root."""
    root = home / "OneDrive-X"
    for folder in ("A/B", "A/C", "B", "C"):
        (root / folder).mkdir(parents=True)
    (root / "A" / "i-a.txt").write_text("12345")
    (root / "A" / "B" / "i-b.txt").write_text("1")
    (root / "A" / "C" / "i-c.txt").write_text("123")
    (root / "B" / "i-b.txt").write_text("12")
    (root / "root.txt").write_text("r")
    (root / "root2.txt").write_text("r")
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

    assert names(removed, sync) == ["B", "C", "root.txt", "root2.txt"]


def test_from_all_folders_to_a_with_root_files_keeps_root_files(sync):
    removed = find_removed(sync, ALL, Rules(["A"], True))

    assert names(removed, sync) == ["B", "C"]


def test_turning_root_files_off_removes_root_files_only(sync):
    removed = find_removed(sync, Rules(["A", "B"], True), Rules(["A", "B"], False))

    assert names(removed, sync) == ["root.txt", "root2.txt"]


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
    (sync / "Local").mkdir()

    removed = find_removed(sync, Rules(["A", "B"], False), Rules(["A"], False))

    assert names(removed, sync) == ["B"]


def test_total_size_counts_files_in_folders(sync):
    removed = find_removed(sync, ALL, Rules(["C"], False))

    assert names(removed, sync) == ["A", "B", "root.txt", "root2.txt"]
    assert total_size(removed) == 5 + 1 + 3 + 2 + 1 + 1


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(1536) == "1.5 kB"
    assert format_size(5 * 1024 * 1024) == "5.0 MB"


# Feature 0006: Trash respects all rules.


@pytest.fixture
def work(home):
    """~/OneDrive-X with the folder Work and the folder Other."""
    root = home / "OneDrive-X"
    for folder in ("Work/Secret", "Work/Project", "Other"):
        (root / folder).mkdir(parents=True)
    (root / "Work" / "plan.txt").write_text("plan")
    (root / "Work" / "Secret" / "local.txt").write_text("only local")
    (root / "Work" / "Project" / "code.py").write_text("print()")
    return root


def test_excluded_folder_in_deselected_folder_stays(work):
    unknown = ["!/Work/Secret/*"]
    old = RuleSet(["Other", "Work"], False, unknown)
    new = RuleSet(["Other"], False, unknown)

    removed = find_removed(work, old, new)

    assert names(removed, work) == ["Work/Project", "Work/plan.txt"]


def test_folder_with_excluded_path_is_not_removed_itself(work):
    unknown = ["!/Work/Secret/*"]
    removed = find_removed(work, RuleSet(["Other", "Work"], False, unknown),
                           RuleSet(["Other"], False, unknown))

    assert "Work" not in names(removed, work)
    assert (work / "Work") not in [r.path for r in removed]


def test_anywhere_rule_keeps_matching_folder(work):
    (work / "Work" / "Documents").mkdir()
    (work / "Work" / "Documents" / "letter.txt").write_text("letter")
    unknown = ["Documents/"]

    removed = find_removed(work, RuleSet(["Other", "Work"], False, unknown),
                           RuleSet(["Other"], False, unknown))

    assert not any(n.startswith("Work/Documents") for n in names(removed, work))
    assert "Work/plan.txt" in names(removed, work)


def test_default_skip_file_keeps_tmp_file(work):
    (work / "Work" / "notes.tmp").write_text("tmp")

    removed = find_removed(work, RuleSet(["Other", "Work"], False),
                           RuleSet(["Other"], False))

    assert "Work/notes.tmp" not in names(removed, work)
    assert "Work" not in names(removed, work)
    assert "Work/plan.txt" in names(removed, work)


def test_skip_dotfiles_true_keeps_dotfile(work):
    (work / "Work" / ".env").write_text("SECRET=1")

    removed = find_removed(work, RuleSet(["Other", "Work"], False, skip_dotfiles=True),
                           RuleSet(["Other"], False, skip_dotfiles=True))

    assert "Work/.env" not in names(removed, work)
    assert "Work" not in names(removed, work)


def test_skip_dotfiles_false_removes_dotfile(work):
    (work / "Work" / ".env").write_text("SECRET=1")
    (work / "Work" / "Secret" / "local.txt").unlink()

    removed = find_removed(work, RuleSet(["Other", "Work"], False, skip_dotfiles=False),
                           RuleSet(["Other"], False, skip_dotfiles=False))

    # Work has no excluded paths. The whole folder is on the list.
    assert names(removed, work) == ["Work"]
    assert (work / "Work" / ".env").exists()


def test_deselected_folder_without_excluded_paths_is_listed_alone(work):
    removed = find_removed(work, RuleSet(["Other", "Work"], False), RuleSet(["Other"], False))

    assert names(removed, work) == ["Work"]


def test_symlink_in_deselected_folder_is_never_listed(work, tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("outside OneDrive")
    (work / "Work" / "shortcut").symlink_to(target)

    removed = find_removed(work, RuleSet(["Other", "Work"], False), RuleSet(["Other"], False))

    assert "Work/shortcut" not in names(removed, work)
    assert "Work" not in names(removed, work)
    assert "Work/plan.txt" in names(removed, work)


def test_folder_with_nosync_is_never_listed(work):
    (work / "Work" / "Project" / ".nosync").write_text("")

    removed = find_removed(work, RuleSet(["Other", "Work"], False), RuleSet(["Other"], False))

    assert not any(n.startswith("Work/Project") for n in names(removed, work))
    assert "Work" not in names(removed, work)
    assert "Work/plan.txt" in names(removed, work)


def test_globbing_exclusion_keeps_node_modules_on_level_3(work):
    deep = work / "Work" / "Project" / "web" / "node_modules"
    deep.mkdir(parents=True)
    (deep / "package.js").write_text("js")
    unknown = ["!**/node_modules/*"]

    removed = find_removed(work, RuleSet(["Other", "Work"], False, unknown),
                           RuleSet(["Other"], False, unknown))

    assert not any("node_modules" in n for n in names(removed, work))
    assert "Work/Project/code.py" in names(removed, work)


def test_from_all_folders_to_a_is_unchanged_with_default_skip_file(sync):
    removed = find_removed(sync, RuleSet(None, False), RuleSet(["A"], False))

    assert names(removed, sync) == ["B", "C", "root.txt", "root2.txt"]
