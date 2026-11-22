import json

import pytest

from mapwright import connect


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return root


def test_uninstall_claude_code_removes_files_and_empty_dir(proj):
    root = str(proj)
    connect.install("claude-code", "project", root)
    changed = connect.uninstall("claude-code", "project", root)
    assert str(proj / ".mcp.json") in changed and str(proj / ".claude" / "settings.local.json") in changed
    assert not (proj / ".mcp.json").exists()
    assert not (proj / ".claude" / "settings.local.json").exists()
    assert not (proj / ".claude").exists()
    assert proj.exists()


def test_uninstall_keeps_other_entries_and_keys(proj):
    root = str(proj)
    (proj / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    (proj / ".claude").mkdir()
    (proj / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
    connect.install("claude-code", "project", root)
    connect.uninstall("claude-code", "project", root)
    assert json.loads((proj / ".mcp.json").read_text()) == {"mcpServers": {"other": {"command": "x"}}}
    assert json.loads((proj / ".claude" / "settings.local.json").read_text()) == {"permissions": {"allow": ["Bash(ls)"]}}
    assert (proj / ".claude").is_dir()


@pytest.mark.parametrize("target,scope,rel,gone_dir", [
    ("cursor", "project", ".cursor/mcp.json", ".cursor"),
    ("vscode", "project", ".vscode/mcp.json", ".vscode"),
    ("gemini", "project", ".gemini/settings.json", ".gemini"),
    ("opencode", "project", "opencode.json", None),
    ("codex", "user", ".codex/config.toml", None),
])
def test_uninstall_removes_file_only_when_empty(proj, tmp_path, target, scope, rel, gone_dir):
    root = str(proj)
    f = (tmp_path / "home" / rel) if scope == "user" else (proj / rel)
    connect.install(target, scope, root)
    assert f.exists()
    connect.uninstall(target, scope, root)
    assert not f.exists()
    if gone_dir:
        assert not (proj / gone_dir).exists()


def test_uninstall_keeps_nonempty_vscode_and_opencode_files(proj):
    root = str(proj)
    (proj / ".vscode").mkdir()
    (proj / ".vscode" / "mcp.json").write_text(json.dumps({"servers": {"other": {"command": "x"}}}))
    (proj / "opencode.json").write_text(json.dumps({"$schema": "https://opencode.ai/config.json", "model": "m", "mcp": {}}))
    connect.install("vscode", "project", root)
    connect.install("opencode", "project", root)
    connect.uninstall("vscode", "project", root)
    connect.uninstall("opencode", "project", root)
    assert json.loads((proj / ".vscode" / "mcp.json").read_text()) == {"servers": {"other": {"command": "x"}}}
    assert json.loads((proj / "opencode.json").read_text()) == {"$schema": "https://opencode.ai/config.json", "model": "m"}


def test_uninstall_codex_keeps_other_toml(proj, tmp_path):
    cfg = tmp_path / "home" / ".codex" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('model = "x"\n')
    connect.install("codex", "user", str(proj))
    connect.uninstall("codex", "user", str(proj))
    assert cfg.read_text() == 'model = "x"\n'


def test_uninstall_twice_is_a_noop(proj):
    root = str(proj)
    connect.install("claude-code", "project", root)
    assert connect.uninstall("claude-code", "project", root)
    assert connect.uninstall("claude-code", "project", root) == []
    assert not (proj / ".mcp.json").exists()


def test_uninstall_user_scope_claude_code(proj, tmp_path):
    cc_dir = tmp_path / "claude"
    cc_json = tmp_path / "claude.json"
    cc_dir.mkdir()
    (cc_dir / "settings.json").write_text(json.dumps({"theme": "dark"}))
    connect.install("claude-code", "user", str(proj))
    connect.uninstall("claude-code", "user", str(proj))
    assert not cc_json.exists()
    assert json.loads((cc_dir / "settings.json").read_text()) == {"theme": "dark"}


def test_uninstall_user_scope_removes_empty_settings(proj, tmp_path):
    cc_dir = tmp_path / "claude"
    connect.install("claude-code", "user", str(proj))
    assert (cc_dir / "settings.json").exists()
    connect.uninstall("claude-code", "user", str(proj))
    assert not (cc_dir / "settings.json").exists()
    assert not (tmp_path / "claude.json").exists()
    assert cc_dir.is_dir()
