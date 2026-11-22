import json

import pytest

from mapwright import hooks, track
from mapwright.track import open_project

ADD = "def add(a, b):\n    return a + b\n"


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setattr(track, "COALESCE_SECONDS", 0)
    root = tmp_path / "proj"
    (root / ".git").mkdir(parents=True)
    (root / "calc.py").write_text(ADD)
    open_project(str(root)).ensure()
    return root


def ev(proj, name, **kw):
    hooks.handle("claude-code", {"hook_event_name": name, "cwd": str(proj), **kw})


def edit(proj, extra):
    (proj / "calc.py").write_text(ADD + extra)


def steps(proj):
    return open_project(str(proj)).steps()


def test_title_is_clean_and_prompt_kept_redacted(proj):
    ev(proj, "UserPromptSubmit", prompt="please can you add a multiply fucntion, token sk-ant-abcdefghijklmnop", session_id="s1")
    edit(proj, "\ndef multiply(a, b):\n    return a * b\n")
    ev(proj, "Stop", session_id="s1")
    s = steps(proj)[-1]
    assert s["source"] == "auto" and s["title"].startswith("add a multiply") and "sk-ant" not in json.dumps(s)
    assert "multiply" in s["prompt"] and len(s["title"]) <= 61


def test_lockfile_only_turn_makes_no_step_and_is_collapsed_later(proj):
    n = len(steps(proj))
    (proj / "package-lock.json").write_text("{}\n" * 5)
    ev(proj, "UserPromptSubmit", prompt="install deps", session_id="s1")
    ev(proj, "Stop", session_id="s1")
    assert len(steps(proj)) == n
    edit(proj, "\nX = 1\n")
    (proj / "pnpm-lock.yaml").write_text("x\n")
    ev(proj, "UserPromptSubmit", prompt="tweak add", session_id="s1")
    ev(proj, "Stop", session_id="s1")
    s = steps(proj)[-1]
    assert s["summary"]["files"] == 1 and s["summary"]["noise"] == 2
    assert s["changes"][-1]["path"] == "generated/lockfile (2 files)"
    full = open_project(str(proj)).load_step(s["n"])
    assert {c["path"] for c in full["changes"] if c.get("noise")} == {"package-lock.json", "pnpm-lock.yaml"}


def test_subagent_and_reentrant_stops_do_not_step(proj):
    n = len(steps(proj))
    ev(proj, "UserPromptSubmit", prompt="refactor calc", session_id="s1")
    edit(proj, "\nY = 2\n")
    ev(proj, "SubagentStop", session_id="s1")
    ev(proj, "Stop", session_id="s1", agent_id="sub1")
    ev(proj, "Stop", session_id="s1", stop_hook_active=True)
    p = open_project(str(proj))
    assert len(p.steps()) == n and not [e for e in p.journal() if e["t"] == "turn_end"]
    ev(proj, "Stop", session_id="s1")
    assert len(steps(proj)) == n + 1


def test_stale_turn_end_does_not_close_step_mid_turn(proj):
    ev(proj, "Stop", session_id="s1")                      # nothing changed, leaves a turn_end behind
    ev(proj, "UserPromptSubmit", prompt="change add", session_id="s1")
    edit(proj, "\nZ = 3\n")
    assert open_project(str(proj)).maybe_auto_step() is None   # the daemon polling mid-turn
    ev(proj, "Stop", session_id="s1")
    assert len(steps(proj)) == 2


def test_other_session_mid_turn_defers(proj):
    ev(proj, "UserPromptSubmit", prompt="work A", session_id="A")
    ev(proj, "UserPromptSubmit", prompt="work B", session_id="B")
    edit(proj, "\nW = 1\n")
    ev(proj, "Stop", session_id="A")
    assert len(steps(proj)) == 1                           # B still working
    ev(proj, "Stop", session_id="B")
    assert len(steps(proj)) == 2


def test_title_uses_first_substantive_prompt_of_the_session(proj):
    ev(proj, "UserPromptSubmit", prompt="add subtract helper", session_id="s1")
    ev(proj, "UserPromptSubmit", prompt="ok", session_id="s1")
    ev(proj, "UserPromptSubmit", prompt="unrelated chat in other window", session_id="s2")
    ev(proj, "UserPromptSubmit", prompt="x", session_id="s2")
    edit(proj, "\ndef subtract(a, b):\n    return a - b\n")
    ev(proj, "Stop", session_id="s2")                      # s2 ends first, s1 still open: deferred
    ev(proj, "Stop", session_id="s1")
    assert steps(proj)[-1]["title"] == "add subtract helper"


def test_coalesce_window_and_session_end(proj, monkeypatch):
    monkeypatch.setattr(track, "COALESCE_SECONDS", 60)
    ev(proj, "UserPromptSubmit", prompt="first change", session_id="s1")
    edit(proj, "\nA = 1\n")
    ev(proj, "Stop", session_id="s1")
    ev(proj, "UserPromptSubmit", prompt="second change", session_id="s1")
    edit(proj, "\nA = 2\n")
    ev(proj, "Stop", session_id="s1")
    assert len(steps(proj)) == 2                           # baseline + one auto step
    ev(proj, "SessionEnd", session_id="s1")                # final: closes the rest
    assert len(steps(proj)) == 3


def test_read_only_bash_not_recorded_and_journal_capped(proj, monkeypatch):
    for cmd in ["ls -la", "git status && git diff", "grep -rn foo src | head"]:
        ev(proj, "PostToolUse", tool_name="Bash", tool_input={"command": cmd})
    assert not [e for e in open_project(str(proj)).journal() if e["t"] == "tool"]
    for cmd in ["rm -rf build", "echo hi > x.txt", "git commit -m x", "npm install"]:
        assert not hooks.read_only_bash(cmd), cmd
    ev(proj, "PostToolUse", tool_name="Bash", tool_input={"command": "pytest"}, session_id="s")
    ev(proj, "PostToolUse", tool_name="Bash", tool_input={"command": "pytest -x"}, session_id="s")
    assert len([e for e in open_project(str(proj)).journal() if e["t"] == "tool"]) == 1  # repeats collapse
    monkeypatch.setattr(track, "JOURNAL_CAP_BYTES", 1)
    assert open_project(str(proj)).record("prompt", text="x") == {}
