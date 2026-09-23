"""The application is called Skyhus (feature 0012)."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_NAMES = re.compile(r"onedrive-gui|onedrive_gui|OneDriveGui", re.IGNORECASE)
LEGACY_ENV_VAR = "ONEDRIVE_GUI_SAFE_MODE"
# The old environment variable still turns on safe mode.
LEGACY_ALLOWED = {"skyhus/sideeffects.py", "tests/test_sideeffects.py", "tests/conftest.py"}


def _files():
    for path in sorted((ROOT / "skyhus").rglob("*")) + sorted((ROOT / "tests").glob("*.py")):
        if path.is_file() and path.suffix in (".py", ".qml", ".svg", ".txt"):
            yield path
    for name in ("README.md", "CLAUDE.md", "pyproject.toml", ".gitignore"):
        yield ROOT / name


def test_no_file_uses_the_old_name():
    found = []
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == "tests/test_name.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if rel in LEGACY_ALLOWED:
                line = line.replace(LEGACY_ENV_VAR, "")
            if OLD_NAMES.search(line):
                found.append(f"{rel}:{number}: {line.strip()}")
    assert found == []


def test_old_package_is_gone():
    assert not (ROOT / "onedrive_gui").exists()


def test_pyproject_names_skyhus():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["name"] == "skyhus"
    assert data["project"]["scripts"] == {"skyhus": "skyhus.app:main"}


def test_window_title_is_skyhus():
    text = (ROOT / "skyhus" / "qml" / "Main.qml").read_text(encoding="utf-8")

    assert re.search(r'^\s*title: "Skyhus"$', text, re.MULTILINE)
    assert 'title: "OneDrive' not in text


def test_application_display_name_is_skyhus():
    text = (ROOT / "skyhus" / "app.py").read_text(encoding="utf-8")

    assert 'setApplicationDisplayName("Skyhus")' in text
    assert 'setApplicationName("skyhus")' in text


def test_qml_imports_skyhus():
    from skyhus import theme
    assert theme.QML_IMPORT_NAME == "Skyhus"
    for path in (ROOT / "skyhus" / "qml").rglob("*.qml"):
        text = path.read_text(encoding="utf-8")
        if "Theme." in text:
            assert re.search(r"^import Skyhus$", text, re.MULTILINE), path.name


def test_paths_use_skyhus():
    from skyhus import accounts, service_control
    assert accounts.GUI_DIR_NAME == "skyhus"
    assert service_control.RESYNC_DROP_IN == "zz-skyhus-resync.conf"
