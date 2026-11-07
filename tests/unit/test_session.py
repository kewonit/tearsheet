import json
import stat
from datetime import UTC, datetime

import pytest

from tearsheet.core.session import SessionState, read_session_info, write_session

NOW = datetime(2026, 11, 8, tzinfo=UTC)
LATER = int(datetime(2026, 12, 8, tzinfo=UTC).timestamp())
EARLIER = int(datetime(2026, 10, 8, tzinfo=UTC).timestamp())
SECRET = "fake-secret-cookie-value"


def state(*, name="sessionid", domain=".tijorifinance.com", expires=LATER):
    cookie = {"name": name, "value": SECRET, "domain": domain, "expires": expires}
    return {"cookies": [cookie], "origins": []}


@pytest.fixture
def path(tmp_path):
    return tmp_path / "session.json"


def test_write_is_owner_only_and_round_trips(path):
    write_session(state(), path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == state()


def test_write_replaces_an_existing_session(path):
    write_session(state(expires=EARLIER), path)
    write_session(state(expires=LATER), path)
    assert json.loads(path.read_text())["cookies"][0]["expires"] == LATER


def test_failed_write_keeps_the_old_session_and_leaves_no_temp_file(path, tmp_path):
    write_session(state(), path)
    with pytest.raises(TypeError):
        write_session({"cookies": object()}, path)
    assert json.loads(path.read_text()) == state()
    assert [p.name for p in tmp_path.iterdir()] == ["session.json"]


def test_no_file_means_no_session(path):
    assert read_session_info(path).state is SessionState.NONE


def test_live_cookie_is_saved_with_its_expiry(path):
    write_session(state(), path)
    info = read_session_info(path, now=NOW)
    assert info.state is SessionState.SAVED
    assert info.expires_at == datetime.fromtimestamp(LATER, UTC)
    assert info.saved_at is not None
    assert info.loose_permissions is False


def test_past_expiry_is_expired(path):
    write_session(state(expires=EARLIER), path)
    assert read_session_info(path, now=NOW).state is SessionState.EXPIRED


def test_browser_session_cookie_has_no_expiry(path):
    write_session(state(expires=-1), path)
    info = read_session_info(path, now=NOW)
    assert info.state is SessionState.SAVED
    assert info.expires_at is None


@pytest.mark.parametrize("domain", ["www.tijorifinance.com", "tijorifinance.com"])
def test_accepts_tijori_domains(path, domain):
    write_session(state(domain=domain), path)
    assert read_session_info(path, now=NOW).state is SessionState.SAVED


@pytest.mark.parametrize(
    "bad",
    [
        state(name="csrftoken"),
        state(domain="example.com"),
        state(domain="nottijorifinance.com"),
        {"cookies": []},
        {},
    ],
)
def test_no_tijori_session_cookie_is_unreadable(path, bad):
    write_session(bad, path)
    assert read_session_info(path, now=NOW).state is SessionState.UNREADABLE


@pytest.mark.parametrize("content", ["not json", "[]", '{"cookies": 5}', '{"cookies": [1]}'])
def test_corrupt_file_is_unreadable_not_a_crash(path, content):
    path.write_text(content)
    assert read_session_info(path, now=NOW).state is SessionState.UNREADABLE


def test_flags_a_session_others_can_read(path):
    write_session(state(), path)
    path.chmod(0o644)
    assert read_session_info(path, now=NOW).loose_permissions is True


def test_info_never_contains_the_cookie_value(path):
    write_session(state(), path)
    assert SECRET not in repr(read_session_info(path, now=NOW))
