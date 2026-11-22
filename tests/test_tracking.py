import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from mapwright import brief, config, connect, hooks, mcp
from mapwright.server import Daemon
from mapwright.track import open_project


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    (root / ".git").mkdir(parents=True)
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (root / ".env").write_text("SECRET=hunter2hunter2\n")
    return root


def tool(p, name, **args):
    out = mcp.handle(p, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": args}})
    assert not out["result"]["isError"], out
    return out["result"]["content"][0]["text"]


def test_baseline_steps_and_computed_changes(proj):
    p = open_project(str(proj))
    p.refresh()
    assert [s["title"] for s in p.steps()] == ["baseline (before tracking started)"]
    (proj / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (proj / "util.py").write_text("X = 1\n")
    data = p.step("Add subtraction")
    assert {c["path"]: c["kind"] for c in data["changes"]} == {"calc.py": "modified", "util.py": "added"}
    assert data["summary"]["added"] == 5 and data["summary"]["delta"]["functions"] == {"new": 1}
    assert p.pending() == []
    (proj / "util.py").unlink()
    p.refresh()
    assert p.pending()[0] == {"path": "util.py", "kind": "deleted", "added": 0, "removed": 1}


def test_secret_files_are_tracked_but_never_read(proj):
    p = open_project(str(proj))
    p.refresh()
    assert p.text(".env") is None and p.index[".env"].startswith("secret:")
    (proj / ".env").write_text("SECRET=changed-value-123\n")
    ch = p.step("rotate")["changes"]
    assert ch == [{"path": ".env", "kind": "modified", "note": "secret-looking or binary: content not read"}]
    blobs = b"".join(f.read_bytes() for f in (p.dir / "blobs").rglob("*.gz"))
    import gzip
    assert b"hunter2" not in b"".join(gzip.decompress(f.read_bytes()) for f in (p.dir / "blobs").rglob("*.gz")) and blobs


def test_verification_catches_dishonest_annotations(proj):
    p = open_project(str(proj))
    p.refresh()
    tool(p, "todo", action="add", text="cache lookups")
    (proj / "calc.py").write_text("from functools import lru_cache\n\n\n@lru_cache\ndef fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\n")
    assert "verified" in tool(p, "claim", concept="caching", symbol="fib")
    assert "unverified" in tool(p, "claim", concept="retry-backoff", symbol="fib")
    assert "missing" in tool(p, "claim", concept="caching", symbol="nope")
    assert "T1 done · verified" in tool(p, "todo", action="done", id="T1", evidence="fib")
    tool(p, "step", title="Cache fibonacci")
    tool(p, "todo", action="add", text="write tests")         # added after the last change to calc.py
    assert "unverified: calc.py has not changed" in tool(p, "todo", action="done", id="T2", evidence="calc.py")
    assert "without evidence" in p.todo_done("T2") ["reason"]
    receipt = tool(p, "step", title="Add tests for fib")
    assert "title mentions a test file" in receipt
    kinds = sorted(x["kind"] for x in p.verify()["problems"])
    assert kinds == ["claim", "claim", "step", "todo"]
    assert "error: unknown concept" in mcp.handle(p, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "claim", "arguments": {"concept": "magic", "symbol": "fib"}}})["result"]["content"][0]["text"]


def test_notes_and_links_go_stale_when_code_disappears(proj):
    p = open_project(str(proj))
    p.refresh()
    assert p.note("add", "adds two numbers")["status"] == "ok"
    (proj / "x.py").write_text("def mul(a, b):\n    return a * b\n")
    assert p.link("add", "mul", "same family")["status"] == "ok"
    (proj / "x.py").unlink()
    p.refresh()
    v = p.verify()
    assert v["links"][0]["status"] == "stale"
    (proj / "calc.py").write_text("Y = 2\n")
    p.refresh()
    assert p.verify()["notes"][0]["status"] == "stale"


def test_mcp_protocol(proj):
    p = open_project(str(proj))
    r = mcp.handle(p, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    assert r["result"]["protocolVersion"] == "2025-03-26" and "instructions" in r["result"]
    assert mcp.handle(p, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = mcp.handle(p, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in tools} == {"map", "find", "symbol", "step", "todo", "claim", "note", "link", "catalog"}
    assert len(json.dumps(tools)) < 3000                       # tool definitions are sent every turn: keep them small
    assert mcp.handle(p, {"jsonrpc": "2.0", "id": 3, "method": "bogus"})["error"]["code"] == -32601
    text = tool(p, "map")
    assert "calc.py" in text and len(text) <= config.settings()["brief_budget"] + 200
    assert "calc:add" in tool(p, "find", query="add")


def test_mcp_over_stdio(proj):
    env = {**os.environ, "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "src")}
    proc = subprocess.run([sys.executable, "-m", "mapwright", "mcp"], cwd=proj, env=env, capture_output=True, text=True, timeout=30,
                          input="\n".join(json.dumps(m) for m in [
                              {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                              {"jsonrpc": "2.0", "method": "notifications/initialized"},
                              {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "symbol", "arguments": {"name": "add"}}}]) + "\n")
    lines = [json.loads(x) for x in proc.stdout.splitlines()]
    assert [x["id"] for x in lines] == [1, 2] and "function calc:add(a, b)" in lines[1]["result"]["content"][0]["text"]


def test_brief_respects_budget(proj):
    for i in range(60):
        (proj / f"mod{i}.py").write_text("".join(f"def f{j}():\n    return {j}\n\n" for j in range(8)))
    p = open_project(str(proj))
    for budget in (600, 2400):
        assert len(brief.project_brief(p, budget)) <= budget + 200


def test_hooks_record_and_close_steps_at_turn_end(proj):
    p = open_project(str(proj))
    p.refresh()
    hooks.handle("claude-code", {"hook_event_name": "UserPromptSubmit", "prompt": "add multiply with token sk-ant-abcdefghijklmnop", "cwd": str(proj)})
    (proj / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    hooks.handle("claude-code", {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(proj / "calc.py")}, "cwd": str(proj)})
    hooks.handle("claude-code", {"hook_event_name": "Stop", "cwd": str(proj)})
    s = p.steps()[-1]
    assert s["source"] == "auto" and "add multiply" in s["title"] and "sk-ant" not in json.dumps(p.journal())
    assert [e["t"] for e in p.journal() if e["t"] in ("prompt", "tool", "turn_end")] == ["prompt", "tool", "turn_end"]
    hooks.handle("claude-code", {"hook_event_name": "Stop", "cwd": str(proj)})   # nothing changed: no empty step
    assert p.steps()[-1]["n"] == s["n"]
    assert hooks.main(["claude-code"]) == 0                                       # garbage on stdin never raises


def test_connect_writes_and_removes_configs(proj, tmp_path):
    root = str(proj)
    (proj / ".cursor").mkdir()
    (proj / ".cursor" / "mcp.json").write_text('{"mcpServers": {"other": {"command": "x"}}}')
    files = connect.install("cursor", "project", root)
    data = json.loads((proj / ".cursor" / "mcp.json").read_text())
    assert set(data["mcpServers"]) == {"other", "mapwright"} and files
    connect.install("claude-code", "project", root)
    hooks_cfg = json.loads((proj / ".claude" / "settings.local.json").read_text())["hooks"]
    assert {"UserPromptSubmit", "PostToolUse", "Stop"} <= set(hooks_cfg)
    assert json.loads((proj / ".mcp.json").read_text())["mcpServers"]["mapwright"]["type"] == "stdio"
    connect.install("vscode", "project", root)
    assert "mapwright" in json.loads((proj / ".vscode" / "mcp.json").read_text())["servers"]
    connect.install("opencode", "project", root)
    assert json.loads((proj / "opencode.json").read_text())["mcp"]["mapwright"]["type"] == "local"
    connect.install("codex", "user", root)
    connect.install("codex", "user", root)
    toml = (tmp_path / "home" / ".codex" / "config.toml").read_text()
    assert toml.count("[mcp_servers.mapwright]") == 1
    st = {t["id"]: t for t in connect.status(root)}
    assert st["cursor"]["scopes"]["project"]["connected"] and st["codex"]["scopes"]["user"]["connected"] and not st["gemini"]["scopes"]["project"]["connected"]
    for t, sc in (("cursor", "project"), ("claude-code", "project"), ("codex", "user")):
        connect.uninstall(t, sc, root)
    assert set(json.loads((proj / ".cursor" / "mcp.json").read_text())["mcpServers"]) == {"other"}
    assert "mapwright" not in (proj / ".claude" / "settings.local.json").read_text()
    assert "mapwright" not in (tmp_path / "home" / ".codex" / "config.toml").read_text()
    (proj / ".vscode" / "mcp.json").write_text("{ // comments are not JSON\n}")
    with pytest.raises(ValueError):
        connect.install("vscode", "project", root)
    assert connect.write_agents_md(root) and connect.write_agents_md(root)
    assert (proj / "AGENTS.md").read_text().count("mapwright:start") == 1


def test_daemon_api(proj):
    p = open_project(str(proj))
    p.refresh()
    (proj / "calc.py").write_text("def add(a, b):\n    if a:\n        return a + b\n    return b\n")
    p.step("Handle empty a")
    d = Daemon(watch=False).start()
    try:
        def call(path, body=None, token=None, host=None):
            req = urllib.request.Request(config.base_url() + path, method="POST" if body is not None else "GET",
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Bearer {token or config.token()}", "Content-Type": "application/json",
                                                  **({"Host": host} if host else {})})
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")
        k = p.key
        assert call("/v1/projects")[1]["projects"][0]["key"] == k
        st = call(f"/v1/p/{k}/state")[1]
        assert st["counts"]["functions"] == 1 and len(st["steps"]) == 2
        for kind in ("architecture", "files", "classes", "data", "cloud", "processes", "calls", "concepts"):
            code, dg = call(f"/v1/p/{k}/diagram/{kind}?step=live")
            assert code == 200 and dg["mermaid"], kind
        assert call(f"/v1/p/{k}/diagram/architecture?step=1")[1]["delta"] == {"modules": {"changed": 1}, "functions": {"changed": 1}}
        fl = call(f"/v1/p/{k}/flow?fid=calc:add&step=live")[1]
        assert "a?" in fl["mermaid"] and fl["function"]["complexity"] == 2
        assert call(f"/v1/p/{k}/file?path=calc.py&step=0")[1]["text"].startswith("def add(a, b):\n    return")
        assert call(f"/v1/p/{k}/file?path=.env&step=live")[1]["secret"] is True
        assert call(f"/v1/p/{k}/file?path=../../etc/passwd&step=live")[0] == 404
        assert "+    if a:" in call(f"/v1/p/{k}/diff?path=calc.py&from=0&to=1")[1]["diff"]
        assert call(f"/v1/p/{k}/brief")[1]["tokens"] > 0
        assert call(f"/v1/p/{k}/todo", {"action": "add", "text": "from the UI"})[1]["tid"] == "T1"
        assert call(f"/v1/p/{k}/step", {"title": "user step"})[1]["n"] == 2
        assert call("/v1/settings", {"theme": "light"})[1]["settings"]["theme"] == "light"
        assert call("/v1/settings", {"theme": "neon"})[0] == 400
        assert call("/v1/connect", {"target": "cursor", "scope": "project", "key": k})[0] == 200
        assert call("/v1/projects", {"root": str(os.path.expanduser("~"))})[0] == 400
        assert call("/v1/ping", token="wrong")[0] == 401
        assert call("/v1/ping", host="evil.example:17991")[0] == 403
        assert call(f"/v1/p/{k}/diagram/nope?step=live")[0] == 404
    finally:
        d.shutdown()


def test_demo_session_end_to_end(tmp_path):
    import demo_session
    key = demo_session.run(str(tmp_path / "shop"), quiet=True)
    from mapwright.track import by_key
    p = by_key(key)
    st = p.state()
    assert len(st["steps"]) == 8 and st["counts"]["tables"] == 3 and st["counts"]["routes"] == 3
    assert {"retry-backoff", "caching", "queue-jobs", "orm", "payments"} <= {c["id"] for c in st["concepts"]}
    assert len(st["problems"]) == 3
    assert {n["kind"] for n in st["infra"]["nodes"]} >= {"db", "cache", "storage", "ci", "external"}
