"""The project is in English only (feature 0014)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DANISH_LETTERS = re.compile(r"[æøåÆØÅ]")
DANISH_WORDS = (
    "og", "ikke", "til", "med", "af", "det", "der", "på", "kan", "skal", "når", "eller", "hvis",
    "efter", "før", "konto", "konti", "mappe", "mapper", "fejl", "applikationen", "servicen",
    "klienten", "brugeren", "findes", "ingen", "alle", "ændrer",
)
DANISH_WORD = re.compile(r"(?<![\w-])(" + "|".join(DANISH_WORDS) + r")(?![\w-])", re.IGNORECASE)
ALLOW = "allow-danish"


def _files():
    for folder, patterns in (("skyhus", ("*.py", "*.qml", "*.svg")), ("tests", ("*.py",))):
        for pattern in patterns:
            yield from sorted((ROOT / folder).rglob(pattern))
    for name in ("README.md", "CLAUDE.md", "CHANGELOG.md", "pyproject.toml"):
        yield ROOT / name


def find_danish(text: str) -> list[tuple[int, str]]:
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if ALLOW in line:
            continue
        if DANISH_LETTERS.search(line) or DANISH_WORD.search(line):
            found.append((number, line.strip()))
    return found


def test_no_file_contains_danish():
    found = []
    for path in _files():
        if path.name == "test_language.py":
            continue
        for number, line in find_danish(path.read_text(encoding="utf-8")):
            found.append(f"{path.relative_to(ROOT)}:{number}: {line}")
    assert found == [], f"{len(found)} lines with Danish text:\n" + "\n".join(found[:200])


def test_detector_finds_danish_words_and_letters():
    assert find_danish("Kontoen er ikke logget ind")
    assert find_danish("Flyt til papirkurven")
    assert find_danish("Kører")
    assert not find_danish("The account is not signed in")
    assert not find_danish("--resync-auth and sync_list")


def test_allow_marker_skips_the_line():
    assert not find_danish('"æ": "ae",  # allow-danish: input that slugify must accept')
