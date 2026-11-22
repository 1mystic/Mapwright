import json
import os

import pytest

from mapwright import analyze as A
from mapwright import config
from mapwright import ignore as I


def M(text, **kw):
    m = I.Matcher("/nonexistent", [ln for ln in text.splitlines()], **kw)
    return m.is_ignored


def test_basic_patterns():
    ig = M("*.pdf\n# comment\n\n/top.txt\nbuild-out/\n")
    assert ig("a/b/doc.pdf")
    assert ig("top.txt") and not ig("sub/top.txt")
    assert ig("x/build-out", True) and not ig("x/build-out")
    assert ig("build-out/file.py")
    assert not ig("a/b/doc.py")


def test_negation_and_order():
    ig = M("*.log\n!keep.log\n")
    assert ig("a.log") and not ig("keep.log") and not ig("d/keep.log")


def test_negation_cannot_reinclude_under_ignored_dir():
    ig = M("gen/\n!gen/keep.txt\n")
    assert ig("gen/keep.txt")


def test_anchoring_and_doublestar():
    ig = M("public/question-bank/**\napps/*/dist\n**/fixtures/*.json\na/**/z\n")
    assert ig("public/question-bank/x/1.json")
    assert not ig("other/public/question-bank/1.json")
    assert ig("apps/web/dist", True) and not ig("apps/web/x/dist", True)
    assert ig("t/fixtures/a.json") and ig("fixtures/a.json")
    assert ig("a/z") and ig("a/b/c/z") and not ig("b/a/z")


def test_question_mark_and_classes():
    ig = M("f?.txt\nv[0-9].js\nw[!a-c].js\n")
    assert ig("fa.txt") and not ig("fab.txt")
    assert ig("v3.js") and not ig("vx.js")
    assert ig("wz.js") and not ig("wb.js")


def test_plain_name_backward_compat():
    ig = M("legacy\n")
    assert ig("legacy", True) and ig("a/legacy/x.py") and not ig("legacy2/x.py")


def test_nested_and_exclude_files(tmp_path):
    (tmp_path / ".git" / "info").mkdir(parents=True)
    (tmp_path / ".git" / "info" / "exclude").write_text("local.txt\n")
    (tmp_path / ".gitignore").write_text("*.tmp\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / ".gitignore").write_text("/only-here.py\n!x.tmp\n")
    m = I.Matcher(str(tmp_path))
    assert m.is_ignored("local.txt") and m.is_ignored("a.tmp")
    assert m.is_ignored("pkg/only-here.py") and not m.is_ignored("only-here.py") and not m.is_ignored("pkg/sub/only-here.py")
    assert not m.is_ignored("pkg/x.tmp")
    assert not I.Matcher(str(tmp_path), respect_gitignore=False).is_ignored("a.tmp")
    assert I.Matcher(str(tmp_path), ["*.py"], respect_gitignore=False).is_ignored("pkg/only-here.py")


def test_user_negation_overrides_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("*.tmp\n")
    assert not I.Matcher(str(tmp_path), ["!keep.tmp"]).is_ignored("keep.tmp")


def test_settings_accept_globs(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPWRIGHT_HOME", str(tmp_path))
    s = config.save_settings({"ignore": ["public/question-bank/**", "*.pdf", "legacy"], "respect_gitignore": False})
    assert s["ignore"][0] == "public/question-bank/**" and s["respect_gitignore"] is False
    with pytest.raises(ValueError):
        config.save_settings({"ignore": [""]})
    with pytest.raises(ValueError):
        config.save_settings({"respect_gitignore": "yes"})


def _tree(root, spec):
    for rel in spec:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x = 1\n" if rel.endswith(".py") else "{}\n")


def test_scan_skips_ignored_and_no_global_mutation(tmp_path):
    _tree(tmp_path, ["a.py", "keep/b.py", "data/1.json", "data/2.json", "gen/c.py", "n/x.tmp"])
    (tmp_path / ".gitignore").write_text("gen/\n")
    before = set(A.IGNORE_DIRS)
    out, trunc = A.scan(str(tmp_path), I.Matcher(str(tmp_path), ["data/**"]))
    assert sorted(out) == [".gitignore", "a.py", "keep/b.py"] and not trunc
    assert A.IGNORE_DIRS == before
    out2, _ = A.scan(str(tmp_path))
    assert "data/1.json" in out2 and "gen/c.py" in out2


def test_truncation_deterministic_and_reported(tmp_path):
    _tree(tmp_path, [f"big/f{i:02}.py" for i in range(10)] + [f"z/g{i}.py" for i in range(3)] + ["a.py"])
    info = {}
    out, trunc = A.scan(str(tmp_path), max_files=5, info=info)
    assert trunc and len(out) == 5
    assert info["seen"] == 14 and info["cap"] == 5
    assert info["top"][0] == {"dir": "(root)", "files": 1} or info["top"][0]["dir"] == "big"
    assert list(out) == list(A.scan(str(tmp_path), max_files=5)[0])


def test_project_state_truncated_info(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPWRIGHT_HOME", str(tmp_path / "home"))
    proj = tmp_path / "proj"
    _tree(proj, [f"d/f{i}.py" for i in range(8)] + ["e.py"])
    config.save_settings({"max_files": 4})
    from mapwright.track import Project
    p = Project(str(proj))
    p.refresh()
    st = p.state()
    assert st["truncated"] and st["truncated_info"]["cap"] == 4 and st["truncated_info"]["seen"] == 9
    assert st["truncated_info"]["top"][0]["dir"] == "d"
    config.save_settings({"max_files": 5000, "ignore": ["d/"]})
    p.refresh()
    assert not p.state()["truncated"] and p.state()["truncated_info"] is None


def test_suggest_ignores_synthetic(tmp_path):
    files = {}
    for i in range(300):
        files[f"public/question-bank/shard{i}.json"] = 2000
    for i in range(40):
        files[f"raw/pdfs/doc{i}.pdf"] = 5_000_000
    files["storybook-static/index.html"] = 10
    files.update({f"src/mod{i}.py": 100 for i in range(30)})
    files.update({f"vendor-js/a{i}.min.js": 10 for i in range(3)})
    sug = I.suggest_ignores(files)
    pats = [s["pattern"] for s in sug]
    assert "public/question-bank/" in pats
    assert "raw/pdfs/" in pats  # 200MB of binary
    assert "storybook-static/" in pats
    assert not any(p.startswith("src") for p in pats)
    assert "public/" not in pats  # the specific child is the one reported
    assert sug[0]["pattern"] == "public/question-bank/"


def test_survey_and_suggest_end_to_end(tmp_path):
    for i in range(210):
        d = tmp_path / "web" / "static"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"s{i}.json").write_text("[]")
    _tree(tmp_path, ["app.py"])
    sug = I.suggest_ignores(I.survey(str(tmp_path), I.Matcher(str(tmp_path))))
    assert [s["pattern"] for s in sug] == ["web/static/"]
    m = I.Matcher(str(tmp_path), [sug[0]["pattern"]])
    assert not I.suggest_ignores(I.survey(str(tmp_path), m))
