"""`mapwright report`: a reviewer-ready summary of how the architecture changed between two points.

The "before" side is a tracked step (--since N) or a git ref (--since REF, analysed from `git archive`, never
touching the working tree). The "after" side is the live working tree, or a step (--until N)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
import tempfile
import time

from . import analyze as A
from . import concepts as C
from . import config, render
from . import ignore as ignore_mod
from . import rules as R

LAYER_ORDER = list(A.LAYERS)


def _git(root: str, *args: str, text: bool = True):
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=text, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and text else (r.stdout if r.returncode == 0 else None)


def _resolve_ref(root: str, ref: str) -> tuple[str, int] | None:
    out = _git(root, "log", "-1", "--format=%H %ct", ref + "^{commit}") if ref and not ref.startswith("-") else None
    if not out:
        return None
    sha, ts = out.split()
    return sha, int(ts)


def model_from_ref(root: str, sha: str) -> tuple[dict, int]:
    """(model, file count) of a commit's tree, analysed with the project's ignore settings."""
    data = _git(root, "archive", "--format=tar", sha, text=False)
    if data is None:
        raise ValueError(f"could not read {sha[:10]} with git archive")
    with tempfile.TemporaryDirectory(prefix="mapwright-report-") as tmp:
        base = os.path.realpath(tmp)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
            for m in tf:
                dest = os.path.realpath(os.path.join(base, m.name))
                if not m.isreg() or not dest.startswith(base + os.sep):
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                f = tf.extractfile(m)
                if f:
                    with open(dest, "wb") as out:
                        out.write(f.read())
        st = config.settings()
        matcher = ignore_mod.Matcher(base, st.get("ignore") or [], st.get("respect_gitignore", True))
        stats, _ = A.scan(base, matcher, st.get("max_files"))
        parts, agg = {}, {}
        for rel in stats:
            if os.path.splitext(rel)[1].lower() not in A.CODE_EXT:
                continue
            text = A.read_text(base, rel)
            part = A.analyze_file(rel, text) if text is not None else None
            if not part:
                continue
            parts[rel] = part
            if A.file_scope(rel) == "source":
                for cid, evs in C.detect_file(rel, text, part).items():
                    if evs:
                        agg.setdefault(cid, []).append({"file": rel, "line": evs[0].get("line"), "symbol": evs[0].get("symbol")})
        model = A.link(parts)
        model["concepts"] = agg
        return model, len(stats)


# ------------------------------------------------------------------ comparison
def _col_names(t: dict) -> list[str]:
    return [c["name"] if isinstance(c, dict) else str(c) for c in t.get("columns") or []]


def _route_key(r: dict) -> str:
    return f"{r.get('method', '?')} {r.get('path', '?')}"


def _rule_set(model: dict, rules: dict | None) -> dict[str, str]:
    return {f"{v['rule']}|{v['file']}|{v['target']}": v["text"] for v in R.check(model, rules)}


def compare(a: dict, b: dict, files: tuple[int, int], rules: dict | None) -> dict:
    marks = A.diff_models(a, b)
    am, bm = a["modules"], b["modules"]
    mods = {"new": [], "removed": [], "changed": []}
    for mid, kind in sorted(marks["modules"].items()):
        node = (bm if kind != "removed" else am)[mid]
        mods[kind].append({"id": mid, "file": node["file"], "layer": node.get("layer", "core"),
                           **({"loc": [am[mid].get("loc"), node.get("loc")]} if kind == "changed" else {})})
    ar, br = {_route_key(r): r for r in a["routes"]}, {_route_key(r): r for r in b["routes"]}
    routes = {"new": sorted(set(br) - set(ar)), "removed": sorted(set(ar) - set(br))}
    tables = {"new": sorted(set(b["tables"]) - set(a["tables"])), "removed": sorted(set(a["tables"]) - set(b["tables"])), "changed": []}
    for name in sorted(set(a["tables"]) & set(b["tables"])):
        ca, cb = _col_names(a["tables"][name]), _col_names(b["tables"][name])
        if ca != cb:
            tables["changed"].append({"table": name, "added": [c for c in cb if c not in ca], "removed": [c for c in ca if c not in cb]})
    ac, bc = a.get("concepts") or {}, b.get("concepts") or {}
    mech = {"new": sorted(set(bc) - set(ac)), "removed": sorted(set(ac) - set(bc))}
    ext = lambda m: {e for x in m["modules"].values() for e in x.get("ext", [])}  # noqa: E731
    packages = {"new": sorted(ext(b) - ext(a)), "removed": sorted(ext(a) - ext(b))}
    hot = []
    for fid, f in b["functions"].items():
        now = f.get("complexity") or 0
        was = (a["functions"].get(fid) or {}).get("complexity")
        if now > (was or 0) and now >= 5:
            hot.append({"function": f.get("qual", fid), "file": f["file"], "before": was, "after": now})
    hot.sort(key=lambda h: (-(h["after"] - (h["before"] or 0)), h["function"]))
    ra, rb = _rule_set(a, rules), _rule_set(b, rules)
    rule_status = {"configured": bool(rules), "new": [ra.get(k) or rb[k] for k in sorted(set(rb) - set(ra))],
                   "fixed": [ra[k] for k in sorted(set(ra) - set(rb))], "remaining": len(set(ra) & set(rb))}
    counts = {"files": [files[0], files[1]]}
    for k in ("modules", "functions", "classes", "tables", "routes"):
        counts[k] = [len(a[k]), len(b[k])]
    counts["mechanisms"] = [len(ac), len(bc)]
    return {"counts": counts, "modules": mods, "routes": routes, "tables": tables, "mechanisms": mech, "packages": packages,
            "hotspots": hot[:5], "rules": rule_status, "marks": {k: v for k, v in marks.items() if k == "modules"}}


def _diagram(a: dict, b: dict, mods: dict) -> str | None:
    changed = {m["id"]: k for k, lst in mods.items() for m in lst}
    ids = sorted(changed)[:25]
    if not ids:
        return None
    nodes = {m: nid for m, nid in ((m, render.nid("m", m)) for m in ids)}
    lines = ["flowchart LR"]
    for m in ids:
        node = (a if changed[m] == "removed" else b)["modules"][m]
        lines.append(f'  {nodes[m]}["{render.label(node["file"], 40)}"]:::{changed[m]}')
    seen = set()
    for m in ids:
        for d in (a if changed[m] == "removed" else b)["modules"][m].get("deps", []):
            if d in nodes and (m, d) not in seen:
                seen.add((m, d))
                lines.append(f"  {nodes[m]} --> {nodes[d]}")
    lines += ["  classDef new fill:#d1fadf,stroke:#2e7d4f", "  classDef changed fill:#fdf0c8,stroke:#b8860b",
              "  classDef removed fill:#fcdcdc,stroke:#b03030,stroke-dasharray:4 3"]
    return "\n".join(lines)


def build(p, since: str | None = None, until: int | None = None) -> dict:
    """The report as data."""
    p.ensure()
    steps = p.steps()
    since_ts, since_n, label_a = 0.0, None, ""
    if since is None:
        for ref in ("origin/main", "main"):
            if _resolve_ref(p.root, ref):
                since = ref
                break
        else:
            since = str(steps[-1]["n"]) if steps else None
    if since is None:
        raise ValueError("nothing to compare with: no steps yet and no git ref; pass --since STEP or --since REF")
    if since.isdigit():
        since_n = int(since)
        data = p.load_step(since_n)
        if not data:
            raise ValueError(f"no step {since_n}")
        a, nfiles_a, label_a = data["model"], len(data["files"]), f"step {since_n}"
        since_ts = data["ts"]
    else:
        hit = _resolve_ref(p.root, since)
        if not hit:
            raise ValueError(f"{since!r} is neither a step number nor a git ref")
        a, nfiles_a = model_from_ref(p.root, hit[0])
        label_a, since_ts = f"{since} ({hit[0][:8]})", hit[1]
    if until is not None:
        end = p.load_step(until)
        if not end:
            raise ValueError(f"no step {until}")
        b, nfiles_b, label_b = end["model"], len(end["files"]), f"step {until}"
        until_ts = end["ts"]
    else:
        b, nfiles_b, label_b, until_ts = p.model, len(p.index), "working tree", float("inf")
    rules, err = R.load(p.root)
    data = compare(a, b, (nfiles_a, nfiles_b), rules)
    data["rules"]["error"] = err
    data["range"] = {"since": label_a, "until": label_b}
    in_range = [s for s in steps if s["n"] > (since_n if since_n is not None else -1) and (since_n is not None or s["ts"] >= since_ts)
                and s["ts"] <= until_ts and (until is None or s["n"] <= until)]
    ver = {"steps": [{"n": s["n"], "title": s["title"], "source": s["source"]} for s in in_range], "problems": []}
    if in_range and until is None:
        nums = {s["n"] for s in in_range}
        for pr in p.verify()["problems"]:
            if pr["kind"] in ("claim", "note", "link", "todo") or (pr["kind"] == "step" and pr.get("id") in nums):
                ver["problems"].append(pr["text"])
    data["verification"] = ver
    data["diagram"] = _diagram(a, b, data["modules"])
    data["generated"] = time.strftime("%Y-%m-%d %H:%M")
    return data


# ------------------------------------------------------------------ Markdown
def _d(pair: list[int]) -> str:
    a, b = pair
    return f"{a} → {b} ({b - a:+d})" if a != b else f"{b}"


def _list(title: str, items: list[str], limit: int = 8) -> list[str]:
    if not items:
        return []
    if len(items) <= limit:
        return [f"**{title}** ({len(items)})", ""] + [f"- {i}" for i in items] + [""]
    return [f"<details><summary><b>{title}</b> ({len(items)})</summary>", ""] + [f"- {i}" for i in items] + ["", "</details>", ""]


def to_markdown(r: dict) -> str:
    c = r["counts"]
    md = ["# Architecture report", "", f"Changes from **{r['range']['since']}** to **{r['range']['until']}**. "
          "Built by static analysis; nothing was executed.", "", "## Summary", "", "| | Before → after |", "|---|---|"]
    md += [f"| {k.capitalize()} | {_d(v)} |" for k, v in c.items()]
    md.append("")
    m = r["modules"]
    if any(m.values()):
        md += ["## Modules", ""]
        for kind, title in (("new", "New"), ("removed", "Removed"), ("changed", "Changed")):
            by: dict[str, list[str]] = {}
            for x in m[kind]:
                by.setdefault(x["layer"], []).append(f"`{x['file']}`" + (f" ({x['loc'][0]} → {x['loc'][1]} lines)" if kind == "changed" and x.get("loc") else ""))
            if by:
                md += [f"**{title}** ({len(m[kind])})", ""]
                for layer in sorted(by, key=lambda l: LAYER_ORDER.index(l) if l in LAYER_ORDER else 99):
                    items = by[layer]
                    head = f"{A.LAYER_TITLES.get(layer, layer)}: {len(items)}"
                    md += ([f"- {head}: " + ", ".join(items)] if len(items) <= 4 else
                           [f"- <details><summary>{head}</summary>", "", *[f"  - {i}" for i in items], "", "  </details>"])
                md.append("")
    else:
        md += ["## Modules", "", "No module changed.", ""]
    if r["diagram"]:
        md += ["## Changed modules and their imports", "", "```mermaid", r["diagram"], "```", ""]
    rt, tb = r["routes"], r["tables"]
    if rt["new"] or rt["removed"]:
        md += ["## Routes", ""] + _list("New", [f"`{x}`" for x in rt["new"]]) + _list("Removed", [f"`{x}`" for x in rt["removed"]])
    if tb["new"] or tb["removed"] or tb["changed"]:
        md += ["## Tables", ""] + _list("New", [f"`{x}`" for x in tb["new"]]) + _list("Removed", [f"`{x}`" for x in tb["removed"]])
        md += _list("Changed", [f"`{t['table']}`" + "".join([f" +{', +'.join(t['added'])}" if t["added"] else "",
                                                             f" −{', −'.join(t['removed'])}" if t["removed"] else ""]) for t in tb["changed"]])
    me, pk = r["mechanisms"], r["packages"]
    if me["new"] or me["removed"] or pk["new"] or pk["removed"]:
        md += ["## Mechanisms and packages", ""]
        md += _list("New mechanisms", [f"`{x}`" for x in me["new"]]) + _list("Removed mechanisms", [f"`{x}`" for x in me["removed"]])
        md += _list("New external packages", [f"`{x}`" for x in pk["new"]]) + _list("Dropped external packages", [f"`{x}`" for x in pk["removed"]])
    if r["hotspots"]:
        md += ["## Complexity hotspots that got worse", "", "| Function | File | Before → after |", "|---|---|---|"]
        md += [f"| `{h['function']}` | `{h['file']}` | {h['before'] if h['before'] is not None else 'new'} → {h['after']} |" for h in r["hotspots"]]
        md.append("")
    ru = r["rules"]
    md += ["## Architecture rules", ""]
    if ru.get("error"):
        md += [f"⚠ {ru['error']}", ""]
    elif not ru["configured"]:
        md += ["No `mapwright.toml` rules in this project.", ""]
    else:
        md += [f"{len(ru['new'])} new violation(s), {len(ru['fixed'])} fixed, {ru['remaining']} unchanged.", ""]
        md += _list("New violations", ru["new"]) + _list("Fixed", ru["fixed"])
    v = r["verification"]
    if v["steps"]:
        md += ["## Steps and verification", ""] + _list("Steps in this range", [f"{s['n']}. {s['title']} ({s['source']})" for s in v["steps"]], 6)
        md += [f"- ⚠ {x}" for x in v["problems"][:10]] if v["problems"] else ["Every claim, todo and step title checks out."]
        md.append("")
    return "\n".join(md).rstrip() + "\n"


def render_report(p, since: str | None, until: int | None, fmt: str) -> str:
    r = build(p, since, until)
    return json.dumps(r, indent=1) + "\n" if fmt == "json" else to_markdown(r)
