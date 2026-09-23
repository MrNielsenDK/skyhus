"""Start med --resync via en midlertidig drop-in (feature 0002)."""

import pytest

from onedrive_gui import service_control
from onedrive_gui.service import SystemctlError

from fakes import ScriptedRun

CAT = """\
# /home/x/.config/systemd/user/onedrive-privat.service
[Unit]
Description=OneDrive

[Service]
ExecStartPre=/bin/sh -c 'sleep 15'
ExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-privat"
Restart=on-failure
"""

CAT_WITH_DROP_IN = CAT + """
# /home/x/.config/systemd/user/onedrive-privat.service.d/override.conf
[Service]
ExecStart=
ExecStart=/usr/bin/onedrive --monitor --verbose --confdir="%h/.config/onedrive-privat"
"""


def drop_in(home):
    return (home / ".config" / "systemd" / "user" / "onedrive-privat.service.d"
            / "zz-onedrive-gui-resync.conf")


def test_effective_exec_start():
    assert service_control.effective_exec_start(CAT) == (
        '/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-privat"')
    assert service_control.effective_exec_start(CAT_WITH_DROP_IN) == (
        '/usr/bin/onedrive --monitor --verbose --confdir="%h/.config/onedrive-privat"')


def test_restart_with_resync_uses_drop_in_and_removes_it(home):
    seen = {}

    def on_call(args):
        if "restart" in args:
            seen["drop_in"] = drop_in(home).read_text()

    run = ScriptedRun(outputs={"cat": CAT}, on_call=on_call)

    service_control.restart_with_resync("onedrive-privat.service", home=home, run=run)

    assert run.calls == [
        ["systemctl", "--user", "cat", "onedrive-privat.service"],
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "restart", "onedrive-privat.service"],
        ["systemctl", "--user", "daemon-reload"],
    ]
    assert seen["drop_in"] == (
        "# Midlertidig. onedrive-gui fjerner filen efter genstart.\n"
        "[Service]\nExecStart=\n"
        'ExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-privat" --resync --resync-auth\n')
    assert not drop_in(home).exists()
    assert not drop_in(home).parent.exists()


def test_drop_in_is_removed_when_restart_fails(home):
    run = ScriptedRun(outputs={"cat": CAT}, fail={"restart"}, stderr="Job failed")

    with pytest.raises(SystemctlError, match="Job failed"):
        service_control.restart_with_resync("onedrive-privat.service", home=home, run=run)

    assert not drop_in(home).exists()
    assert run.calls[-1] == ["systemctl", "--user", "daemon-reload"]


def test_other_drop_ins_are_left_alone(home):
    other = drop_in(home).parent / "override.conf"
    other.parent.mkdir(parents=True)
    other.write_text("[Service]\n")
    run = ScriptedRun(outputs={"cat": CAT})

    service_control.restart_with_resync("onedrive-privat.service", home=home, run=run)

    assert other.read_text() == "[Service]\n"
    assert not drop_in(home).exists()


def test_stop_and_start(home):
    run = ScriptedRun()

    service_control.stop("onedrive-privat.service", run=run)
    service_control.start("onedrive-privat.service", run=run)

    assert run.calls == [
        ["systemctl", "--user", "stop", "onedrive-privat.service"],
        ["systemctl", "--user", "start", "onedrive-privat.service"],
    ]


# Start, Genstart og ventetiden (feature 0004)

class FakeClock:
    """Et ur, der går 1 sekund frem, hver gang koden sover."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def states(*keys):
    """En read_state, der giver tilstandene i rækkefølge og bliver ved den sidste."""
    remaining = list(keys)

    def read_state():
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]
    return read_state


def test_restart_resets_failed_state_first(home):
    run = ScriptedRun()
    clock = FakeClock()

    result = service_control.perform("restart", "onedrive-privat.service", states("running"),
                                     home=home, run=run, clock=clock, sleep=clock.sleep)

    assert result == "running"
    assert run.calls == [
        ["systemctl", "--user", "reset-failed", "onedrive-privat.service"],
        ["systemctl", "--user", "restart", "onedrive-privat.service"],
    ]


def test_start_uses_the_same_commands(home):
    run = ScriptedRun()
    clock = FakeClock()

    service_control.perform("start", "onedrive-privat.service", states("running"),
                            home=home, run=run, clock=clock, sleep=clock.sleep)

    assert run.calls == [
        ["systemctl", "--user", "reset-failed", "onedrive-privat.service"],
        ["systemctl", "--user", "restart", "onedrive-privat.service"],
    ]


def test_perform_waits_until_service_settles(home):
    clock = FakeClock()

    result = service_control.perform("restart", "onedrive-privat.service",
                                     states("stopping", "starting", "starting", "failed"),
                                     home=home, run=ScriptedRun(), clock=clock, sleep=clock.sleep)

    assert result == "failed"
    assert len(clock.sleeps) == 3


def test_needs_resync_also_ends_the_wait(home):
    clock = FakeClock()

    result = service_control.perform("restart", "onedrive-privat.service",
                                     states("starting", "needs_resync"),
                                     home=home, run=ScriptedRun(), clock=clock, sleep=clock.sleep)

    assert result == "needs_resync"


def test_service_that_never_settles_times_out_after_120_seconds(home):
    clock = FakeClock()

    with pytest.raises(service_control.ServiceTimeoutError, match="Servicen svarer ikke"):
        service_control.perform("restart", "onedrive-privat.service", states("starting"),
                                home=home, run=ScriptedRun(), clock=clock, sleep=clock.sleep)

    assert 120 <= clock.now <= 121


def test_failing_restart_raises_message_from_systemctl(home):
    run = ScriptedRun(fail={"restart"},
                      stderr="Job for onedrive-privat.service failed because the control process "
                             "exited with error code.")
    clock = FakeClock()

    with pytest.raises(SystemctlError, match="Job for onedrive-privat.service failed"):
        service_control.perform("restart", "onedrive-privat.service", states("running"),
                                home=home, run=run, clock=clock, sleep=clock.sleep)


def test_resync_restarts_with_flags_and_removes_drop_in(home):
    seen = {}

    def on_call(args):
        if "restart" in args:
            seen["drop_in"] = drop_in(home).read_text()

    run = ScriptedRun(outputs={"cat": CAT}, on_call=on_call)
    clock = FakeClock()

    result = service_control.perform("resync", "onedrive-privat.service", states("running"),
                                     home=home, run=run, clock=clock, sleep=clock.sleep)

    assert result == "running"
    assert run.calls[0] == ["systemctl", "--user", "reset-failed", "onedrive-privat.service"]
    assert ["systemctl", "--user", "restart", "onedrive-privat.service"] in run.calls
    assert seen["drop_in"].rstrip().endswith("--resync --resync-auth")
    assert not drop_in(home).exists()
