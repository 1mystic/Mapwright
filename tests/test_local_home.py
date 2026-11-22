import json
import os
import shlex
import stat

import pytest

from mapwright import cli, config, connect, hooks, track


@pytest.fixture
def proj(mw_home, monkeypatch):
    root = mw_home / "proj"
    (root / ".git").mkdir(parents=True)
    (root / "app.py").write_text("def hello():\n    return 1\n")
    (root / "sub" / "deep").mkdir(parents=True)
    monkeypatch.delenv("MAPWRIGHT_HOME")
    monkeypatch.chdir(root)
    config.reset_cache()
    track._PROJECTS.clear()
    yield root
    config.set_start(None)
    config.reset_cache()


def run(*argv):
    assert cli.main(list(argv)) == 0


def test_init_local_marker_gitignore_idempotent(proj):
    run("init", "--local")
    home = proj / ".mapwright"
    assert json.loads((home / "home.json").read_text())["home"] == str(home)
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert (home / "projects").is_dir()
    run("init", "--local")
    lines = (proj / ".gitignore").read_text().splitlines()
    assert lines.count(".mapwright/") == 1


def test_init_home_custom_dir(proj):
    (proj / ".gitignore").write_text("dist")
    run("init", "--home", "state/mw")
    home = proj / "state" / "mw"
    assert config.local_home(proj) == home
    assert (home / "projects").is_dir()
    gi = (proj / ".gitignore").read_text().splitlines()
    assert "dist" in gi and "state/mw/" in gi and ".mapwright/" in gi


def test_discovery_order(proj, monkeypatch):
    run("init", "--local")
    monkeypatch.delenv("MAPWRIGHT_HOME")
    config.reset_cache()
    monkeypatch.chdir(proj / "sub" / "deep")
    assert config.home() == proj / ".mapwright"
    monkeypatch.setenv("MAPWRIGHT_HOME", str(proj / "other"))
    assert config.home() == proj / "other"
    monkeypatch.delenv("MAPWRIGHT_HOME")
    monkeypatch.chdir(proj.parent)
    config.reset_cache()
    assert config.home() != proj / ".mapwright"  # outside the project: default home


def test_connect_writes_env_and_hooks(proj):
    run("init", "--local", "--connect", "claude-code")
    home = str(proj / ".mapwright")
    mcp = json.loads((proj / ".mcp.json").read_text())
    assert mcp["mcpServers"]["mapwright"]["env"] == {"MAPWRIGHT_HOME": home}
    hooks_cfg = json.loads((proj / ".claude/settings.local.json").read_text())["hooks"]
    cmds = [h["command"] for ev in hooks_cfg.values() for m in ev for h in m["hooks"]]
    assert cmds and all(c.startswith(f"MAPWRIGHT_HOME={shlex.quote(home)} ") for c in cmds)


def test_plain_connect_detects_local_home(proj):
    run("init", "--local")
    run("connect", "cursor")
    d = json.loads((proj / ".cursor/mcp.json").read_text())
    assert d["mcpServers"]["mapwright"]["env"]["MAPWRIGHT_HOME"] == str(proj / ".mapwright")


def test_no_env_without_home(proj):
    connect.install("cursor", "project", str(proj))
    assert "env" not in json.loads((proj / ".cursor/mcp.json").read_text())["mcpServers"]["mapwright"]


def test_install_formats_include_env(proj):
    h = str(proj / ".mapwright")
    connect.install("vscode", "project", str(proj), home=h)
    assert json.loads((proj / ".vscode/mcp.json").read_text())["servers"]["mapwright"]["env"]["MAPWRIGHT_HOME"] == h
    connect.install("opencode", "project", str(proj), home=h)
    assert json.loads((proj / "opencode.json").read_text())["mcp"]["mapwright"]["environment"]["MAPWRIGHT_HOME"] == h
    connect.install("codex", "user", str(proj), home=h)
    connect.install("codex", "user", str(proj), home=h)  # reinstall replaces the env table too
    import pathlib
    import tomllib
    toml = tomllib.loads((pathlib.Path.home() / ".codex/config.toml").read_text())
    assert toml["mcp_servers"]["mapwright"]["env"]["MAPWRIGHT_HOME"] == h


def test_snippets_include_env():
    h = "/x/.mapwright"
    for t in ("any", "vscode", "opencode", "codex", "zed"):
        assert h in connect.snippet(t, home=h)
        assert h not in connect.snippet(t)
    assert '"environment"' in connect.snippet("opencode", home=h)
    assert "[mcp_servers.mapwright.env]" in connect.snippet("codex", home=h)


def test_install_status_round_trip(proj, capsys):
    run("init", "--local", "--connect", "claude-code")
    assert [t for t in connect.status(str(proj)) if t["id"] == "claude-code"][0]["scopes"]["project"]["connected"]
    capsys.readouterr()
    run("status", "--json")
    assert json.loads(capsys.readouterr().out)["root"] == str(proj)
    assert any((proj / ".mapwright/projects").iterdir())


def test_hook_writes_into_local_home(proj, monkeypatch, mw_home):
    run("init", "--local")
    monkeypatch.delenv("MAPWRIGHT_HOME", raising=False)
    config.reset_cache()
    track._PROJECTS.clear()
    monkeypatch.chdir(mw_home)  # the agent's cwd is elsewhere; the payload cwd decides
    config.set_start(None)
    hooks.handle("claude-code", {"cwd": str(proj / "sub"), "hook_event_name": "UserPromptSubmit", "prompt": "hi there"})
    local = list((proj / ".mapwright/projects").rglob("*"))
    assert any(f.is_file() for f in local)
    assert not (mw_home / "home" / ".mapwright").exists()


def test_init_never_scans_home(proj):
    run("init", "--local")
    p = track.open_project(str(proj))
    p.refresh()
    assert not any(f.startswith(".mapwright") for f in p.cache)


def test_ping_reports_home(proj, monkeypatch):
    from mapwright.server import Daemon
    monkeypatch.setenv("MAPWRIGHT_HOME", str(proj / ".mapwright"))
    config.reset_cache()
    d = Daemon(watch=False).start()
    try:
        assert cli.api("GET", "/v1/ping")["home"] == str(proj / ".mapwright")
        assert cli.daemon_state() == "ours"
        monkeypatch.setenv("MAPWRIGHT_HOME", str(proj / "elsewhere"))
        assert cli.daemon_state() == "other"
    finally:
        d.shutdown()
