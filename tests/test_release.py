import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_single_sourced():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "version" in meta["project"]["dynamic"] and "version" not in meta["project"]
    assert meta["tool"]["hatch"]["version"]["path"] == "src/mapwright/__init__.py"
    assert meta["project"]["name"] == "mapwright-agent"
    assert re.search(r'__version__ = "\d+\.\d+\.\d+"', (ROOT / "src/mapwright/__init__.py").read_text())


def test_release_workflow_uses_trusted_publishing():
    wf = (ROOT / ".github/workflows/release.yml").read_text()
    assert "id-token: write" in wf and "gh-action-pypi-publish" in wf and "password" not in wf
