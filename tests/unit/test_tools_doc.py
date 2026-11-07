import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "generate_tools_doc", ROOT / "scripts" / "generate_tools_doc.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def test_the_tools_reference_matches_the_server(monkeypatch, tmp_path):
    monkeypatch.setenv("TEARSHEET_HOME", str(tmp_path))
    committed = (ROOT / "docs" / "TOOLS.md").read_text()
    assert committed == generator.build(), "Run: uv run python scripts/generate_tools_doc.py"
