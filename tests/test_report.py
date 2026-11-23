import json
import subprocess

from mapwright import cli


def git(root, *a):
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True, capture_output=True)


def make(tmp_path):
    r = tmp_path / "proj"
    (r / "app").mkdir(parents=True)
    (r / "app/util.py").write_text("def f(x):\n    return x\n")
    (r / "app/main.py").write_text("from app import util\n\ndef run():\n    return util.f(1)\n")
    git(r, "init", "-q")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "one")
    (r / "app/db.py").write_text("import requests\nfrom sqlalchemy import Column, Integer\n\nclass User:\n    __tablename__ = 'users'\n    id = Column(Integer, primary_key=True)\n")
    (r / "app/main.py").write_text("from app import util, db\n\ndef run():\n    if 1:\n        pass\n    return util.f(1)\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "two")
    return r


def test_report_md_and_json(tmp_path, capsys):
    r = make(tmp_path)
    assert cli.main(["report", "--since", "HEAD~1", "--path", str(r)]) == 0
    out = capsys.readouterr().out
    for s in ("# Architecture report", "## Summary", "## Modules", "`app/db.py`", "`app/main.py`", "```mermaid", "flowchart LR", "## Architecture rules"):
        assert s in out
    assert "| Modules | 2 → 3 (+1) |" in out
    assert "## Tables" in out and "`users`" in out
    assert cli.main(["report", "--since", "HEAD~1", "--format", "json", "--path", str(r)]) == 0
    d = json.loads(capsys.readouterr().out)
    assert {"counts", "modules", "routes", "tables", "mechanisms", "packages", "hotspots", "rules", "verification", "diagram"} <= set(d)
    assert d["counts"]["modules"] == [2, 3]
    assert [m["file"] for m in d["modules"]["new"]] == ["app/db.py"]
    assert "requests" in d["packages"]["new"]
    assert d["tables"]["new"] == ["users"]


def test_report_since_step_and_output_file(tmp_path, capsys):
    r = make(tmp_path)
    from mapwright.track import open_project
    p = open_project(str(r))
    p.refresh()
    p.step("baseline-ish", source="user")
    (r / "app/new.py").write_text("def g():\n    return 2\n")
    out = tmp_path / "rep.md"
    assert cli.main(["report", "--since", "1", "-o", str(out), "--path", str(r)]) == 0
    text = out.read_text()
    assert "`app/new.py`" in text and "step 1" in text
    assert cli.main(["report", "--since", "nonsense-ref", "--path", str(r)]) == 1
