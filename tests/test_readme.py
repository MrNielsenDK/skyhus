"""README beskriver alle funktioner fra feature 0001-0007 (feature 0008)."""

from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_names_the_features():
    text = README.read_text(encoding="utf-8")

    for phrase in ("Vælg mapper", "papirkurv", "Genstart med resync", "--reauth"):
        assert phrase in text, phrase
