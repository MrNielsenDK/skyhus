"""The README describes all functions from feature 0001-0007 (feature 0008)."""

from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_names_the_features():
    text = README.read_text(encoding="utf-8")

    for phrase in ("Choose folders", "Trash", "Restart with resync", "--reauth"):
        assert phrase in text, phrase
