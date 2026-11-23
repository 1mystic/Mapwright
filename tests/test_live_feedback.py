import json
import time

from mapwright import config, hooks, track

TOML = """
[layers]
"app/ui/**" = "ui"
"app/db/**" = "data"
"app/svc/**" = "service"

[[forbid]]
from = "ui"
to = ["data"]
reason = "UI goes through services"

[limits]
no_cycles = true
"""


def make(tmp_path):
    root = tmp_path / "proj"
    for d in ("app/ui", "app/db", "app/svc"):
        (root / d).mkdir(parents=True)
        (root / d / "__init__.py").write_text("")
    (root / "app/__init__.py").write_text("")
    (root / "app/ui/v.py").write_text("from app.svc import s\n")
    (root / "app/svc/s.py").write_text("from app.db import m\n")
    (root / "app/db/m.py").write_text("X = 1\n")
    (root / "mapwright.toml").write_text(TOML)
    return root


def post(root, rel, capsys, tool="Edit"):
    hooks.handle("claude-code", {"hook_event_name": "PostToolUse", "cwd": str(root), "session_id": "s",
                                 "tool_name": tool, "tool_input": {"file_path": str(root / rel)}})
    return capsys.readouterr().out


def test_new_violation_reported_once(tmp_path, capsys):
    root = make(tmp_path)
    assert post(root, "app/ui/v.py", capsys) == ""
    (root / "app/ui/v.py").write_text("from app.svc import s\nfrom app.db import m\n")
    out = post(root, "app/ui/v.py", capsys)
    data = json.loads(out)["hookSpecificOutput"]
    assert data["hookEventName"] == "PostToolUse"
    assert "app/ui/v.py [ui] imports app/db/m.py [data]" in data["additionalContext"]
    assert len(data["additionalContext"]) <= 300
    assert post(root, "app/ui/v.py", capsys) == ""
    # fixed then broken again: the same text is not repeated in the session
    (root / "app/ui/v.py").write_text("from app.svc import s\n")
    assert post(root, "app/ui/v.py", capsys) == ""
    (root / "app/ui/v.py").write_text("from app.db import m\n")
    assert post(root, "app/ui/v.py", capsys) == ""


def test_new_cycle(tmp_path, capsys):
    root = make(tmp_path)
    assert post(root, "app/db/m.py", capsys) == ""
    (root / "app/db/m.py").write_text("from app.svc import s\n")
    assert "import cycle" in post(root, "app/db/m.py", capsys)


def test_preexisting_not_reported_and_off_switch(tmp_path, capsys):
    root = make(tmp_path)
    (root / "app/ui/v.py").write_text("from app.db import m\n")
    assert post(root, "app/ui/v.py", capsys) == ""  # already broken before tracking
    (root / "app/svc/s.py").write_text("from app.db import m\nY = 1\n")
    assert post(root, "app/svc/s.py", capsys) == ""
    config.save_settings({"live_feedback": False})
    (root / "app/db/m.py").write_text("from app.svc import s\n")
    assert post(root, "app/db/m.py", capsys) == ""


def test_no_rules_no_output_and_never_raises(tmp_path, capsys, monkeypatch):
    root = make(tmp_path)
    (root / "mapwright.toml").unlink()
    assert post(root, "app/ui/v.py", capsys) == ""
    (root / "mapwright.toml").write_text(TOML)
    monkeypatch.setattr(track.Project, "live_check", lambda self: 1 / 0)
    assert post(root, "app/ui/v.py", capsys) == ""


def test_latency_100_files(tmp_path, capsys):
    root = make(tmp_path)
    for i in range(100):
        (root / "app/svc" / f"m{i}.py").write_text(f"import os\n\ndef f{i}(x):\n    return x + {i}\n")
    post(root, "app/ui/v.py", capsys)
    (root / "app/ui/v.py").write_text("from app.db import m\n")
    t = time.perf_counter()
    out = post(root, "app/ui/v.py", capsys)
    dt = time.perf_counter() - t
    print("live feedback ms:", dt * 1000)
    assert out and dt < 1.0
