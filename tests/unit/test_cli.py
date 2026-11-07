import pytest
from playwright.sync_api import Error as PlaywrightError

from tearsheet import cli, login
from tearsheet.login import LoginCancelledError, LoginTimeoutError


@pytest.fixture(autouse=True)
def private_home(monkeypatch, tmp_path):
    monkeypatch.setenv("TEARSHEET_HOME", str(tmp_path))


def login_raises(monkeypatch, error):
    def fake(path):
        raise error

    monkeypatch.setattr(login, "login", fake)


def test_success_says_where_the_session_went(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(login, "login", lambda path: None)
    assert cli.main(["login"]) == 0
    assert str(tmp_path / "session.json") in capsys.readouterr().out


@pytest.mark.parametrize(
    "error", [LoginCancelledError("closed early"), LoginTimeoutError("too slow")]
)
def test_cancel_and_timeout_fail_without_blaming_chromium(monkeypatch, capsys, error):
    login_raises(monkeypatch, error)
    assert cli.main(["login"]) == 1
    err = capsys.readouterr().err
    assert str(error) in err
    assert "Chromium" not in err


def test_missing_chromium_gets_the_install_hint(monkeypatch, capsys):
    login_raises(monkeypatch, PlaywrightError("Executable doesn't exist at /some/path"))
    assert cli.main(["login"]) == 1
    assert "playwright install chromium" in capsys.readouterr().err


def test_other_browser_failures_get_no_install_hint(monkeypatch, capsys):
    login_raises(monkeypatch, PlaywrightError("something else broke"))
    assert cli.main(["login"]) == 1
    err = capsys.readouterr().err
    assert "something else broke" in err
    assert "playwright install" not in err
