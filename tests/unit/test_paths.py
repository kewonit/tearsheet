import stat

from tearsheet.core import paths


def test_defaults_to_a_private_folder_in_the_user_home(monkeypatch, tmp_path):
    monkeypatch.delenv("TEARSHEET_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    home = paths.home_dir()
    assert home == tmp_path / ".tearsheet"
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_env_var_moves_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("TEARSHEET_HOME", str(tmp_path / "custom"))
    monkeypatch.delenv("TEARSHEET_FILINGS_DIR", raising=False)
    assert paths.session_path() == tmp_path / "custom" / "session.json"
    assert paths.cache_path() == tmp_path / "custom" / "cache.sqlite3"
    assert paths.filings_dir() == tmp_path / "custom" / "filings"


def test_filings_folder_can_live_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setenv("TEARSHEET_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TEARSHEET_FILINGS_DIR", str(tmp_path / "mine"))
    assert paths.filings_dir() == tmp_path / "mine"


def test_leaves_an_existing_folders_permissions_alone(monkeypatch, tmp_path):
    existing = tmp_path / "shared"
    existing.mkdir(mode=0o755)
    existing.chmod(0o755)
    monkeypatch.setenv("TEARSHEET_HOME", str(existing))
    paths.home_dir()
    assert stat.S_IMODE(existing.stat().st_mode) == 0o755
