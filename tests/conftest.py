import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture(autouse=True)
def mw_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPWRIGHT_HOME", str(tmp_path / "mwhome"))
    monkeypatch.setenv("MAPWRIGHT_PORT", "17991")
    monkeypatch.setenv("MAPWRIGHT_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("MAPWRIGHT_CLAUDE_JSON", str(tmp_path / "claude.json"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from mapwright import track
    track._PROJECTS.clear()
    return tmp_path
