"""Sikker tilstand (feature 0007).

``conftest.py`` slår sikker tilstand til i alle tests. Testene her erstatter
``subprocess.run``, ``subprocess.Popen`` og ``QFile.moveToTrash`` med attrapper
og kontrollerer, om kaldet når den underliggende funktion.
"""

import ast
import logging
import subprocess
from pathlib import Path

import pytest

from onedrive_gui import sideeffects

from conftest import RecordingRun

PACKAGE_DIR = Path(sideeffects.__file__).resolve().parent
REAL_HOME = sideeffects.real_home()


class RecordingPopen:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        return object()


@pytest.fixture
def underlying(monkeypatch):
    """Attrapper for de funktioner, der ændrer systemet."""
    run, popen, trashed = RecordingRun(), RecordingPopen(), []
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    from PySide6.QtCore import QFile

    def fake_trash(path):
        trashed.append(path)
        return True

    monkeypatch.setattr(QFile, "moveToTrash", fake_trash)
    return run, popen, trashed


@pytest.fixture
def normal_mode(monkeypatch):
    """Den rigtige HOME uden miljøvariablen og uden --safe."""
    monkeypatch.setenv("HOME", str(REAL_HOME))
    monkeypatch.delenv(sideeffects.ENV_VAR, raising=False)
    sideeffects.init(["onedrive-gui"])
    assert sideeffects.safe_mode() is False


# Aktivering

def test_env_var_turns_safe_mode_on(monkeypatch):
    monkeypatch.setenv("HOME", str(REAL_HOME))
    monkeypatch.setenv(sideeffects.ENV_VAR, "1")
    sideeffects.init(["onedrive-gui"])

    assert sideeffects.safe_mode() is True


def test_safe_flag_turns_safe_mode_on(monkeypatch):
    monkeypatch.setenv("HOME", str(REAL_HOME))
    monkeypatch.delenv(sideeffects.ENV_VAR, raising=False)
    sideeffects.init(["onedrive-gui", "--safe"])

    assert sideeffects.safe_mode() is True


def test_fake_home_turns_safe_mode_on(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(sideeffects.ENV_VAR, raising=False)
    sideeffects.init(["onedrive-gui"])

    assert sideeffects.safe_mode() is True


def test_real_home_without_env_and_flag_is_normal(monkeypatch):
    monkeypatch.setenv("HOME", str(REAL_HOME))
    monkeypatch.delenv(sideeffects.ENV_VAR, raising=False)
    sideeffects.init(["onedrive-gui"])

    assert sideeffects.safe_mode() is False


def test_env_var_zero_cannot_turn_off_fake_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(sideeffects.ENV_VAR, "0")
    sideeffects.init(["onedrive-gui"])

    assert sideeffects.safe_mode() is True


def test_result_is_fixed_after_start(monkeypatch):
    monkeypatch.setenv("HOME", str(REAL_HOME))
    monkeypatch.setenv(sideeffects.ENV_VAR, "1")
    sideeffects.init(["onedrive-gui"])
    monkeypatch.delenv(sideeffects.ENV_VAR)

    assert sideeffects.safe_mode() is True


# Blokering

def test_restart_is_blocked_and_logged(underlying, caplog):
    run, _, _ = underlying
    caplog.set_level(logging.INFO)

    result = sideeffects.run(["systemctl", "--user", "restart", "onedrive.service"],
                             capture_output=True, text=True)

    assert run.calls == []
    assert result.returncode == 0
    assert "SAFE MODE: systemctl --user restart onedrive.service" in caplog.text


@pytest.mark.parametrize("args", [
    ["stop", "onedrive.service"],
    ["start", "onedrive.service"],
    ["enable", "--now", "onedrive.service"],
    ["reset-failed", "onedrive.service"],
    ["daemon-reload"],
])
def test_changing_systemctl_commands_are_blocked(underlying, args):
    run, _, _ = underlying

    result = sideeffects.run(["systemctl", "--user", *args], capture_output=True, text=True)

    assert run.calls == []
    assert result.returncode == 0


@pytest.mark.parametrize("cmd", [
    ["systemctl", "--user", "show", "onedrive.service"],
    ["systemctl", "--user", "cat", "onedrive.service"],
    ["systemctl", "--user", "status", "onedrive.service"],
    ["systemctl", "--user", "is-active", "onedrive.service"],
    ["journalctl", "--user", "-u", "onedrive.service"],
])
def test_reading_commands_reach_run(underlying, cmd):
    run, _, _ = underlying

    sideeffects.run(cmd, capture_output=True, text=True)

    assert run.calls == [cmd]


def test_onedrive_is_not_started_by_popen(underlying, caplog):
    _, popen, _ = underlying
    caplog.set_level(logging.INFO)

    process = sideeffects.popen(["/usr/bin/onedrive", "--confdir=/x", "--auth-files", "a:b"])

    assert popen.calls == []
    assert process.poll() == 1
    assert process.wait() == 1
    assert "SAFE MODE: /usr/bin/onedrive --confdir=/x --auth-files a:b" in caplog.text


def test_onedrive_is_not_started_by_run(underlying):
    run, _, _ = underlying

    result = sideeffects.run(["/usr/bin/onedrive", "--sync", "--upload-only"], capture_output=True, text=True)

    assert run.calls == []
    assert result.returncode == 1
    assert result.stderr == "Sikker tilstand: onedrive blev ikke startet"


def test_trash_does_not_move_the_file(underlying, tmp_path, caplog):
    _, _, trashed = underlying
    caplog.set_level(logging.INFO)
    path = tmp_path / "fil.txt"
    path.write_text("data")

    assert sideeffects.trash(path) is True

    assert path.exists()
    assert trashed == []
    assert "SAFE MODE:" in caplog.text


def test_guard_write_blocks_systemd_unit_under_real_home(caplog):
    caplog.set_level(logging.INFO)
    path = REAL_HOME / ".config" / "systemd" / "user" / "x.service"

    assert sideeffects.guard_write(path) is False
    assert f"SAFE MODE: skriver ikke {path}" in caplog.text


def test_guard_write_allows_gui_dir_under_real_home():
    assert sideeffects.guard_write(REAL_HOME / ".config" / "onedrive-gui" / "accounts.json") is True


def test_guard_write_allows_path_outside_real_home(tmp_path):
    assert not str(tmp_path).startswith(str(REAL_HOME) + "/")

    assert sideeffects.guard_write(tmp_path / ".config" / "systemd" / "user" / "x.service") is True


def test_without_safe_mode_every_call_reaches_the_function(underlying, normal_mode, tmp_path):
    run, popen, trashed = underlying

    sideeffects.run(["systemctl", "--user", "restart", "onedrive.service"])
    sideeffects.popen(["/usr/bin/onedrive", "--auth-files", "a:b"])
    sideeffects.trash(tmp_path / "fil.txt")

    assert run.calls == [["systemctl", "--user", "restart", "onedrive.service"]]
    assert popen.calls == [["/usr/bin/onedrive", "--auth-files", "a:b"]]
    assert trashed == [str(tmp_path / "fil.txt")]
    assert sideeffects.guard_write(REAL_HOME / ".config" / "systemd" / "user" / "x.service") is True


# Signaler til en proces (feature 0010)

class SignalledProcess:
    pid = 4711

    def __init__(self):
        self.signals = []

    def send_signal(self, sig):
        self.signals.append(sig)


def test_signal_is_not_sent_in_safe_mode(caplog):
    import signal
    caplog.set_level(logging.INFO)
    process = SignalledProcess()

    sideeffects.signal_process(process, signal.SIGTERM)
    sideeffects.signal_process(process, signal.SIGKILL)

    assert process.signals == []
    assert "SAFE MODE: sender ikke SIGTERM til PID 4711" in caplog.text
    assert "SAFE MODE: sender ikke SIGKILL til PID 4711" in caplog.text


def test_signal_is_sent_without_safe_mode(normal_mode):
    import signal
    process = SignalledProcess()

    sideeffects.signal_process(process, signal.SIGTERM)

    assert process.signals == [signal.SIGTERM]


def test_signal_to_a_process_that_is_gone_is_ignored(normal_mode):
    import signal

    class Gone(SignalledProcess):
        def send_signal(self, sig):
            raise ProcessLookupError

    sideeffects.signal_process(Gone(), signal.SIGTERM)


def test_guard_write_allows_state_json_under_real_home():
    assert sideeffects.guard_write(REAL_HOME / ".config" / "onedrive-gui" / "state.json") is True


# Kildekoden

FORBIDDEN = {("subprocess", "run"), ("subprocess", "Popen"), ("QFile", "moveToTrash")}
WRITE_METHODS = {"write_text", "write_bytes", "unlink", "rmdir", "mkdir", "rmtree", "touch",
                 "rename", "symlink_to", "chmod", "replace", "remove"}


def _modules():
    return sorted(p for p in PACKAGE_DIR.glob("*.py") if p.name != "sideeffects.py")


def _annotation_nodes(tree):
    nodes = set()
    for node in ast.walk(tree):
        annotations = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.append(node.returns)
            args = node.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                if arg is not None:
                    annotations.append(arg.annotation)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        for annotation in annotations:
            if annotation is not None:
                nodes.update(id(n) for n in ast.walk(annotation))
    return nodes


def test_plan_step_3_modules_exist():
    names = {p.name for p in _modules()}
    assert {"service.py", "service_control.py", "auth.py", "apply.py", "viewmodels.py"} <= names


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_module_uses_side_effects_directly(path):
    """Kun ``sideeffects.py`` må bruge ``subprocess.run``, ``subprocess.Popen`` og ``QFile.moveToTrash``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _annotation_nodes(tree)
    found = [f"{path.name}:{node.lineno} {node.value.id}.{node.attr}"
             for node in ast.walk(tree)
             if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
             and (node.value.id, node.attr) in FORBIDDEN and id(node) not in skip]
    found += [f"{path.name}:{node.lineno} import {alias.name}"
              for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
              for alias in node.names
              if (node.module or "").endswith("subprocess") and alias.name in ("run", "Popen")]
    assert found == []


def _writes(function):
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in WRITE_METHODS:
            # str.replace og list.remove skriver ikke. os.replace og os.remove gør.
            if func.attr in ("replace", "remove") and not (
                    isinstance(func.value, ast.Name) and func.value.id in ("os", "shutil")):
                continue
            yield f"{func.attr}() linje {node.lineno}"
        elif isinstance(func, ast.Name) and func.id in ("open", "chmod"):
            mode = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg == "mode"), None)
            if func.id == "chmod" or (isinstance(mode, ast.Constant) and set(str(mode.value)) & set("wax+")):
                yield f"{func.id}() linje {node.lineno}"


def _calls_guard(function):
    return any(isinstance(n, ast.Call) and (
        (isinstance(n.func, ast.Name) and n.func.id == "guard_write")
        or (isinstance(n.func, ast.Attribute) and n.func.attr == "guard_write"))
        for n in ast.walk(function))


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_every_file_write_is_guarded(path):
    """En funktion, der skriver eller sletter en fil, skal kalde ``guard_write``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    missing = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            writes = list(_writes(node))
            if writes and not _calls_guard(node):
                missing.append(f"{path.name}:{node.name}: {', '.join(writes)}")
    assert missing == []


SIGNAL_CALLS = {("os", "kill"), ("os", "killpg")}


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_no_module_sends_signals_directly(path):
    """Signaler går gennem ``sideeffects.signal_process`` (feature 0010)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = [f"{path.name}:{node.lineno} {node.func.attr}"
             for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and (node.func.attr == "send_signal"
                  or (isinstance(node.func.value, ast.Name) and (node.func.value.id, node.func.attr) in SIGNAL_CALLS))]
    assert found == []


def test_apply_does_not_terminate_or_kill_directly():
    """Uploaden i ``apply.py`` stopper kun processen med ``sideeffects.signal_process`` (feature 0010)."""
    tree = ast.parse((PACKAGE_DIR / "apply.py").read_text(encoding="utf-8"))
    found = [node.lineno for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr in ("terminate", "kill")]
    assert found == []
