from mapwright import mcp
from mapwright.track import open_project


def _call(p, tool, **args):
    out = mcp.handle(p, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
    assert not out["result"]["isError"], out
    return out["result"]["content"][0]["text"]


def _proj(tmp_path):
    root = tmp_path / "proj"
    (root / ".git").mkdir(parents=True)
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n" + "# filler line to make the file bigger\n" * 200)
    (root / "util.py").write_text("def helper():\n    return add(1, 2)\n" + "# filler\n" * 100)
    return open_project(str(root))


def test_no_calls_means_zero_savings(tmp_path):
    p = _proj(tmp_path)
    s = p.state()["savings"]
    assert s == {"served_tokens": 0, "counterfactual_tokens": 0, "saved_tokens": 0, "calls": 0}


def test_mcp_calls_are_journaled_and_estimated(tmp_path):
    p = _proj(tmp_path)
    text = _call(p, "map")
    _call(p, "find", query="add")
    _call(p, "symbol", name="add")
    evs = [e for e in p.journal() if e["t"] == "mcp"]
    assert [e["tool"] for e in evs] == ["map", "find", "symbol"]
    assert evs[0]["chars"] == len(text)
    s = p.state()["savings"]
    assert s["calls"] == 3 and s["served_tokens"] > 0
    assert s["counterfactual_tokens"] > s["served_tokens"]
    assert s["saved_tokens"] == s["counterfactual_tokens"] - s["served_tokens"]


def test_files_counted_once_per_step_and_never_negative(tmp_path):
    p = _proj(tmp_path)
    _call(p, "find", query="add")
    one = p.state()["savings"]["counterfactual_tokens"]
    assert one > 0
    _call(p, "find", query="add")
    assert p.state()["savings"]["counterfactual_tokens"] == one  # same file, same step
    p.step("a step")
    _call(p, "find", query="add")
    assert p.state()["savings"]["counterfactual_tokens"] == 2 * one  # a new step reads it again
    p.append({"t": "mcp", "tool": "map", "chars": 10_000_000, "files": []})
    assert p.state()["savings"]["saved_tokens"] >= 0
