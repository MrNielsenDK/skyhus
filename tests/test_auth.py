"""Login via --auth-files (feature 0001)."""

import pytest

from onedrive_gui.auth import AuthSession, AuthState, parse_redirect

from conftest import make_account_dir
from fakes import FakeClock, FakePopen

AUTH_URL = ("https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            "?client_id=d50ca740-c83f-4d1b-b616-12c519384f0c&response_type=code")
CODE_URL = "https://login.microsoftonline.com/common/oauth2/nativeclient?code=abc"


@pytest.fixture
def popen():
    return FakePopen()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def session(home, tmp_path, popen, clock):
    confdir = make_account_dir(home, "onedrive-firma-2", config='sync_dir = "~/X"\n')
    s = AuthSession(confdir, popen=popen, clock=clock, tmp_base=tmp_path)
    s.start()
    yield s
    s.close()


def test_command_uses_confdir_and_auth_files(session, popen, home):
    args = popen.last.args

    assert args[0] == "/usr/bin/onedrive"
    assert args[1] == f"--confdir={home / '.config' / 'onedrive-firma-2'}"
    assert args[2] == "--auth-files"
    assert args[3] == f"{popen.last.auth_url_path}:{popen.last.response_path}"
    assert len(args) == 4


def test_waits_for_auth_url(session, popen):
    assert session.poll() is AuthState.STARTING
    assert session.auth_url == ""


def test_login_window_gets_exactly_the_auth_url(session, popen):
    popen.last.write_auth_url(AUTH_URL)

    assert session.poll() is AuthState.WAITING_FOR_USER
    assert session.auth_url == AUTH_URL


def test_nativeclient_url_is_written_to_response_url(session, popen):
    popen.last.write_auth_url(AUTH_URL)
    session.poll()

    assert session.submit_redirect(CODE_URL) is True

    assert popen.last.response_path.read_text() == CODE_URL
    assert session.poll() is AuthState.WAITING_FOR_TOKEN


def test_other_url_is_not_written(session, popen):
    popen.last.write_auth_url(AUTH_URL)
    session.poll()

    assert session.submit_redirect("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1") is False
    assert session.submit_redirect("https://example.com/nativeclient?code=abc") is False

    assert not popen.last.response_path.exists()
    assert session.poll() is AuthState.WAITING_FOR_USER


def test_error_url_fails_with_message(session, popen):
    popen.last.write_auth_url(AUTH_URL)
    session.poll()

    handled = session.submit_redirect(
        "https://login.microsoftonline.com/common/oauth2/nativeclient"
        "?error=access_denied&error_description=Brugeren+afbrød+login")

    assert handled is True
    assert session.poll() is AuthState.FAILED
    assert "Brugeren afbrød login" in session.error
    assert not popen.last.response_path.exists()
    assert popen.last.terminated


def test_cancel_stops_the_process(session, popen):
    popen.last.write_auth_url(AUTH_URL)
    session.poll()

    session.cancel()

    assert popen.last.terminated
    assert session.poll() is AuthState.CANCELLED


def test_nonzero_exit_before_refresh_token_fails(session, popen):
    popen.last.log("ERROR: Unable to connect\n")
    popen.last.exit(1)

    assert session.poll() is AuthState.FAILED
    assert "1" in session.error
    assert "Unable to connect" in session.error


def test_zero_exit_without_refresh_token_fails(session, popen):
    popen.last.write_auth_url(AUTH_URL)
    session.poll()
    session.submit_redirect(CODE_URL)
    popen.last.exit(0)

    assert session.poll() is AuthState.FAILED
    assert session.error


def test_refresh_token_and_exit_succeeds(session, popen, home):
    popen.last.write_auth_url(AUTH_URL)
    session.poll()
    session.submit_redirect(CODE_URL)
    (home / ".config" / "onedrive-firma-2" / "refresh_token").write_text("ny")

    assert session.poll() is AuthState.WAITING_FOR_TOKEN
    popen.last.exit(0)
    assert session.poll() is AuthState.SUCCEEDED
    assert not popen.last.terminated


def test_process_is_stopped_30_seconds_after_refresh_token(session, popen, home, clock):
    popen.last.write_auth_url(AUTH_URL)
    session.poll()
    session.submit_redirect(CODE_URL)
    (home / ".config" / "onedrive-firma-2" / "refresh_token").write_text("ny")
    session.poll()

    clock.now += 29.9
    assert session.poll() is AuthState.WAITING_FOR_TOKEN
    assert not popen.last.terminated

    clock.now += 0.1
    assert session.poll() is AuthState.SUCCEEDED
    assert popen.last.terminated


def test_old_refresh_token_does_not_count(home, tmp_path, popen, clock):
    confdir = make_account_dir(home, "onedrive", refresh_token=True)
    token = confdir / "refresh_token"
    s = AuthSession(confdir, popen=popen, clock=clock, tmp_base=tmp_path)
    s.start()
    popen.last.exit(0)

    assert s.poll() is AuthState.FAILED
    assert token.read_text() == "token"
    s.close()


def test_temporary_files_are_removed(session, popen):
    popen.last.write_auth_url(AUTH_URL)
    session.poll()
    session.submit_redirect(CODE_URL)
    workdir = popen.last.response_path.parent

    session.cancel()
    session.close()

    assert not workdir.exists()


def test_parse_redirect():
    assert parse_redirect("https://example.com/") is None
    assert parse_redirect(CODE_URL).code == "abc"
    assert parse_redirect(CODE_URL).error == ""
    err = parse_redirect("https://login.microsoftonline.com/common/oauth2/nativeclient?error=access_denied")
    assert err.code == ""
    assert err.error == "access_denied"


# Log ind igen med --reauth (feature 0005)

@pytest.fixture
def reauth_confdir(home):
    confdir = make_account_dir(home, "onedrive-privat", config="")
    token = confdir / "refresh_token"
    token.write_bytes(b"gammel-token\x00\xff")
    token.chmod(0o600)
    return confdir


def start_reauth(confdir, tmp_path, popen, clock):
    s = AuthSession(confdir, reauth=True, popen=popen, clock=clock, tmp_base=tmp_path)
    s.start()
    return s


def test_reauth_command_has_reauth_and_auth_files(reauth_confdir, tmp_path, popen, clock):
    s = start_reauth(reauth_confdir, tmp_path, popen, clock)
    args = popen.last.args

    assert "--reauth" in args
    assert args[args.index("--auth-files") + 1] == f"{popen.last.auth_url_path}:{popen.last.response_path}"
    s.close()


def test_reauth_waits_for_auth_url_although_token_existed(reauth_confdir, tmp_path, popen, clock):
    s = start_reauth(reauth_confdir, tmp_path, popen, clock)
    popen.last.write_auth_url(AUTH_URL)

    assert s.poll() is AuthState.WAITING_FOR_USER
    s.close()


def test_reauth_cancel_restores_token_byte_for_byte(reauth_confdir, tmp_path, popen, clock):
    token = reauth_confdir / "refresh_token"
    s = start_reauth(reauth_confdir, tmp_path, popen, clock)
    popen.last.write_auth_url(AUTH_URL)
    s.poll()
    assert not token.exists()

    s.cancel()

    assert s.poll() is AuthState.CANCELLED
    assert token.read_bytes() == b"gammel-token\x00\xff"
    assert token.stat().st_mode & 0o777 == 0o600
    s.close()


def test_reauth_nonzero_exit_restores_token(reauth_confdir, tmp_path, popen, clock):
    token = reauth_confdir / "refresh_token"
    s = start_reauth(reauth_confdir, tmp_path, popen, clock)
    popen.last.exit(1)

    assert s.poll() is AuthState.FAILED
    assert token.read_bytes() == b"gammel-token\x00\xff"
    assert token.stat().st_mode & 0o777 == 0o600
    s.close()


def test_reauth_success_keeps_new_token(reauth_confdir, tmp_path, popen, clock):
    token = reauth_confdir / "refresh_token"
    s = start_reauth(reauth_confdir, tmp_path, popen, clock)
    popen.last.write_auth_url(AUTH_URL)
    s.poll()
    s.submit_redirect(CODE_URL)
    token.write_text("ny")
    popen.last.exit(0)

    assert s.poll() is AuthState.SUCCEEDED
    s.close()
    assert token.read_text() == "ny"


def test_reauth_backup_is_removed_with_workdir(reauth_confdir, tmp_path, popen, clock):
    s = start_reauth(reauth_confdir, tmp_path, popen, clock)
    workdir = popen.last.response_path.parent
    assert (workdir / "refresh_token").read_bytes() == b"gammel-token\x00\xff"

    s.cancel()
    s.close()

    assert not workdir.exists()
