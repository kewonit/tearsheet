import json
from datetime import UTC, datetime, timedelta

import pytest

from tearsheet.core.cache import Cache
from tearsheet.core.session import SessionState, write_session
from tearsheet.server import collect_status


def session_state(expires):
    cookie = {"name": "sessionid", "value": "x", "domain": ".tijorifinance.com", "expires": expires}
    return {"cookies": [cookie]}


@pytest.fixture
def cache(tmp_path):
    instance = Cache(tmp_path / "cache.sqlite3")
    yield instance
    instance.close()


@pytest.fixture
def session_file(tmp_path):
    return tmp_path / "session.json"


@pytest.fixture
def filings(tmp_path):
    return tmp_path / "filings"


def add_filing(filings, name="a.xml"):
    filings.mkdir(exist_ok=True)
    (filings / name).write_text("x")


def in_days(days):
    return (datetime.now(UTC) + timedelta(days=days)).timestamp()


def test_ready_state_has_no_warnings(session_file, cache, filings):
    write_session(session_state(in_days(30)), session_file)
    add_filing(filings)
    status = collect_status(session_file, cache, filings)
    assert status.data.session is SessionState.SAVED
    assert status.data.filings_found == 1
    assert status.warnings == []


def test_no_session_says_how_to_sign_in(session_file, cache, filings):
    add_filing(filings)
    status = collect_status(session_file, cache, filings)
    assert status.data.session is SessionState.NONE
    assert "tearsheet login" in status.warnings[0]


def test_expired_session_says_how_to_sign_in(session_file, cache, filings):
    write_session(session_state(in_days(-1)), session_file)
    add_filing(filings)
    status = collect_status(session_file, cache, filings)
    assert status.data.session is SessionState.EXPIRED
    assert "expired" in status.warnings[0]


def test_corrupt_session_is_reported(session_file, cache, filings):
    session_file.write_text("not json")
    add_filing(filings)
    status = collect_status(session_file, cache, filings)
    assert status.data.session is SessionState.UNREADABLE
    assert "can't be read" in status.warnings[0]


def test_warns_when_others_can_read_the_session(session_file, cache, filings):
    write_session(session_state(in_days(30)), session_file)
    session_file.chmod(0o644)
    add_filing(filings)
    assert "chmod 600" in collect_status(session_file, cache, filings).warnings[0]


def test_missing_filings_folder_is_a_warning_not_a_crash(session_file, cache, filings):
    write_session(session_state(in_days(30)), session_file)
    status = collect_status(session_file, cache, filings)
    assert status.data.filings_found == 0
    assert "No filings found" in status.warnings[0]


def test_counts_filings_in_subfolders_and_ignores_other_files(session_file, cache, filings):
    add_filing(filings, "a.XML")
    add_filing(filings, "b.pdf")
    add_filing(filings, "notes.txt")
    (filings / "sub").mkdir()
    (filings / "sub" / "c.xbrl").write_text("x")
    assert collect_status(session_file, cache, filings).data.filings_found == 3


def test_reports_cache_counts(session_file, cache, filings):
    cache.put("financials", "A", 1, ttl_s=60)
    assert collect_status(session_file, cache, filings).data.cache_entries == {"financials": 1}


def test_status_never_contains_the_cookie_value(session_file, cache, filings):
    state = session_state(in_days(30))
    state["cookies"][0]["value"] = "fake-secret-cookie-value"
    write_session(state, session_file)
    status = collect_status(session_file, cache, filings)
    assert "fake-secret-cookie-value" not in json.dumps(status.model_dump(mode="json"))
