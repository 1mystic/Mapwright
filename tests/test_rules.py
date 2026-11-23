from pathlib import Path

from mapwright import rules as R
from mapwright.track import open_project

TOML = """
[layers]
"app/ui/**" = "ui"     # pinned
"app/db/**" = "data"
"app/svc/**" = "service"

[[forbid]]
from = "ui"
to = ["data"]
reason = "UI goes through services"

[[forbid]]
from = "app/db/**"
to = [
  "ui",
  "service",
]

[limits]
no_cycles = true
max_complexity = 1
max_module_lines = 100
"""


def make(tmp_path: Path, toml: str = TOML) -> Path:
    root = tmp_path / "proj"
    for d in ("app/ui", "app/db", "app/svc"):
        (root / d).mkdir(parents=True)
        (root / d / "__init__.py").write_text("")
    (root / "app/__init__.py").write_text("")
    (root / "app/ui/v.py").write_text("from app.svc import s\nfrom app.db import m\n")
    (root / "app/svc/s.py").write_text("from app.db import m\ndef f(x):\n    return m.q(x)\n")
    (root / "app/db/m.py").write_text("from app.ui import v\ndef q(x):\n    if x:\n        return 1\n    return 2\n")
    if toml:
        (root / "mapwright.toml").write_text(toml)
    return root


def test_fallback_parser_matches_tomllib_subset():
    import builtins
    real = builtins.__import__

    def no_tomllib(name, *a, **k):
        if name == "tomllib":
            raise ImportError
        return real(name, *a, **k)
    builtins.__import__ = no_tomllib
    try:
        data = R.parse_toml(TOML)
    finally:
        builtins.__import__ = real
    assert data["layers"]["app/ui/**"] == "ui"
    assert data["forbid"][0] == {"from": "ui", "to": ["data"], "reason": "UI goes through services"}
    assert data["forbid"][1]["to"] == ["ui", "service"]
    assert data["limits"] == {"no_cycles": True, "max_complexity": 1, "max_module_lines": 100}


def test_violations_found(tmp_path):
    p = open_project(str(make(tmp_path)))
    p.refresh()
    found = R.check(p.model, R.load(p.root)[0])
    kinds = sorted(v["rule"] for v in found)
    assert kinds.count("forbid") == 2 and "cycle" in kinds and "complexity" in kinds and "size" not in kinds
    assert any("UI goes through services" in v["text"] for v in found)
    probs = [x for x in p.verify()["problems"] if x["kind"] == "rule"]
    assert len(probs) == len(found)


def test_no_file_no_problems_and_starter_holds(tmp_path):
    root = make(tmp_path, toml="")
    p = open_project(str(root))
    p.refresh()
    assert R.load(p.root) == (None, None)
    text = R.starter(p.model)
    assert "[limits]" in text and "no_cycles = false" in text  # the fixture has a cycle today
    assert R.check(p.model, R.parse_toml(text)) == [] or all(v["rule"] != "forbid" for v in R.check(p.model, R.parse_toml(text)))


def test_bad_file_is_a_problem_not_a_crash(tmp_path):
    root = make(tmp_path, toml="[limits\nno_cycles = = true\n")
    p = open_project(str(root))
    p.refresh()
    probs = [x for x in p.verify()["problems"] if x["kind"] == "rule"]
    assert probs and probs[0]["status"] == "error"
