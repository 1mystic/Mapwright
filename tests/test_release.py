import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_single_sourced():
    toml = (ROOT / "pyproject.toml").read_text()
    project = toml.split("[project]", 1)[1].split("\n[", 1)[0]
    assert 'dynamic = ["version"]' in project and not re.search(r"^version\s*=", project, re.M)
    assert 'path = "src/mapwright/__init__.py"' in toml
    assert 'name = "mapwright-agent"' in project
    assert re.search(r'__version__ = "\d+\.\d+\.\d+"', (ROOT / "src/mapwright/__init__.py").read_text())


def test_release_workflow_uses_trusted_publishing():
    wf = (ROOT / ".github/workflows/release.yml").read_text()
    assert "id-token: write" in wf and "gh-action-pypi-publish" in wf and "password" not in wf
