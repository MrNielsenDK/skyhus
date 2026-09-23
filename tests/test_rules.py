"""The client's rules in sync_list and config (feature 0006)."""

import pytest

from skyhus.rules import RuleSet, UnknownRuleError


@pytest.mark.parametrize("rule", ["/", "/*", "!/*", "-/", "./Work", "/A/../B/", "/A**/", "!"])
def test_rule_that_cannot_be_interpreted_gives_error_with_rule(rule):
    with pytest.raises(UnknownRuleError, match=__import__("re").escape(rule)):
        RuleSet(["A"], False, [rule])


def test_comments_and_empty_lines_are_not_rules():
    rules = RuleSet(["A"], False, ["# comment", "; comment", "", "   "])

    assert rules.includes("A/x.txt", False)
    assert not rules.includes("B/x.txt", False)


def test_sync_list_without_rules_includes_everything():
    rules = RuleSet([], False, ["# only a comment"])

    assert rules.includes("B/x.txt", False)


def test_exclusion_wins_over_inclusion():
    rules = RuleSet(["A"], False, ["!/A/B/*"])

    assert not rules.includes("A/B", True)
    assert not rules.includes("A/B/x.txt", False)
    assert rules.includes("A/C/x.txt", False)


def test_dash_is_also_exclusion():
    rules = RuleSet(["A"], False, ["-/A/B/*"])

    assert not rules.includes("A/B/x.txt", False)


def test_rooted_rule_applies_only_from_root():
    rules = RuleSet([], False, ["/Backup"])

    assert rules.includes("Backup", False)
    assert rules.includes("Backup/x.txt", False)
    assert not rules.includes("A/Backup/x.txt", False)


def test_rule_without_leading_slash_applies_anywhere():
    rules = RuleSet([], False, ["notes.txt"])

    assert rules.includes("notes.txt", False)
    assert rules.includes("A/B/notes.txt", False)
    assert not rules.includes("A/B/other.txt", False)


def test_trailing_slash_applies_only_to_folders():
    rules = RuleSet([], False, ["Documents/"])

    assert rules.includes("A/Documents", True)
    assert rules.includes("A/Documents/x.txt", False)
    assert not rules.includes("A/Documents", False)


def test_single_star_stays_within_one_segment():
    rules = RuleSet([], False, ["/A/*.pdf"])

    assert rules.includes("A/x.pdf", False)
    assert not rules.includes("A/B/x.txt", False)


def test_double_star_spans_several_segments():
    rules = RuleSet([], False, ["/A/**/build/*"])

    assert rules.includes("A/x/y/build/out.bin", False)
    assert not rules.includes("A/x/y/src/main.c", False)


def test_sync_list_is_case_sensitive():
    rules = RuleSet(["Work"], False)

    assert not rules.includes("work/x.txt", False)


def test_skip_file_default_and_case():
    rules = RuleSet(None, False)

    assert not rules.includes("A/NOTES.TMP", False)
    assert not rules.includes("A/~lock", False)
    assert rules.includes("A/notes.txt", False)


def test_skip_file_with_full_path():
    rules = RuleSet(None, False, skip_files=["/Documents/keepass.kdbx"])

    assert not rules.includes("Documents/keepass.kdbx", False)
    assert rules.includes("Other/keepass.kdbx", False)
    assert rules.includes("A/notes.tmp", False)


def test_skip_dotfiles_applies_to_folders_and_files():
    rules = RuleSet(None, False, skip_dotfiles=True)

    assert not rules.includes(".config", True)
    assert not rules.includes(".config/x.txt", False)
    assert not rules.includes("A/.env", False)


def test_skip_dir_applies_to_everything_below():
    rules = RuleSet(None, False, skip_dirs=["cache"])

    assert not rules.includes("A/cache", True)
    assert not rules.includes("A/cache/x.txt", False)
    assert rules.includes("A/x.txt", False)


def test_root_files_follow_sync_root_files():
    assert RuleSet(["A"], True).includes("root.txt", False)
    assert not RuleSet(["A"], False).includes("root.txt", False)
