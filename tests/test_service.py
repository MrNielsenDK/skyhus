"""Systemd user service for an account (feature 0001)."""

import pytest

from skyhus import service
from skyhus.service import ServiceExistsError, SystemctlError

from conftest import RecordingRun


def unit_path(home, name):
    return home / ".config" / "systemd" / "user" / name


def test_unit_for_firma_2_has_exec_start(home):
    confdir = home / ".config" / "onedrive-firma-2"

    name = service.write_unit(confdir, "Firma 2", home)

    assert name == "onedrive-firma-2.service"
    text = unit_path(home, name).read_text()
    assert 'ExecStart=/usr/bin/onedrive --monitor --confdir="%h/.config/onedrive-firma-2"\n' in text


def test_unit_has_on_failure_and_restart_prevent(home):
    name = service.write_unit(home / ".config" / "onedrive-firma-2", "Firma 2", home)
    lines = unit_path(home, name).read_text().splitlines()

    assert "OnFailure=onedrive-failure@%N.service" in lines
    assert "RestartPreventExitStatus=126" in lines
    assert "WantedBy=default.target" in lines


def test_description_escapes_percent_and_newlines(home):
    name = service.write_unit(home / ".config" / "onedrive-x", "100%\nFirma", home)
    lines = unit_path(home, name).read_text().splitlines()

    assert "Description=OneDrive Client for Linux (100%% Firma)" in lines


def test_existing_unit_is_not_overwritten(home):
    path = unit_path(home, "onedrive-firma-2.service")
    path.parent.mkdir(parents=True)
    path.write_text("my own unit\n")

    with pytest.raises(ServiceExistsError):
        service.write_unit(home / ".config" / "onedrive-firma-2", "Firma 2", home)

    assert path.read_text() == "my own unit\n"


def test_enable_now_runs_daemon_reload_first(recording_run):
    service.enable_now("onedrive-firma-2.service", run=recording_run)

    assert recording_run.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "onedrive-firma-2.service"],
    ]


def test_restart(recording_run):
    service.restart("onedrive.service", run=recording_run)

    assert recording_run.calls == [["systemctl", "--user", "restart", "onedrive.service"]]


def test_systemctl_failure_raises_with_message():
    run = RecordingRun(fail_on="enable", stderr="Failed to enable unit: Unit file x does not exist.")

    with pytest.raises(SystemctlError, match="Failed to enable unit"):
        service.enable_now("x.service", run=run)
