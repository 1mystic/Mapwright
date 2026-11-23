"""Diagrams as Mermaid text plus a node map, so the UI can make every box clickable.

Each renderer returns {"mermaid": str, "nodes": {mermaid id: {kind, ref, file, line}}, "note": str}.
`marks` (from analyze.diff_models) outlines what is new, changed or removed since the step the
user compares against.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter

from . import concepts as C
from .analyze import LAYER_TITLES, LAYERS

STYLE = {"new": "stroke:#5FB865,stroke-width:3px", "changed": "stroke:#5A9CF8,stroke-width:3px",
         "removed": "stroke:#DB5C5C,stroke-width:2px,stroke-dasharray:5 4"}
KIND_SHAPE = {"app": ('["', '"]'), "container": ('["', '"]'), "function": ('[\\"', '"\\]'), "db": ('[("', '")]'),
              "cache": ('{{"', '"}}'), "queue": ('[["', '"]]'), "storage": ('[("', '")]'), "search": ('{{"', '"}}'),
              "external": ('(["', '"])'), "ci": ('[/"', '"\\]'), "cdn": ('{{"', '"}}'), "cloud": ('[/"', '"/]')}


def nid(prefix: str, key: str) -> str:
    return prefix + hashlib.sha1(key.encode()).hexdigest()[:8]


def label(text: str, n: int = 56) -> str:
    text = re.sub(r"[\"`<>{}\[\]|#;\\\n\r]", " ", str(text)).strip()
    text = " ".join(text.split())
    return (text[: n - 1] + "…") if len(text) > n else text or "?"


def word(text: str, default: str = "x") -> str:
    w = re.sub(r"\W+", "_", str(text)).strip("_")
    return w if w and not w[0].isdigit() else (f"_{w}" if w else default)


def _classdefs(marks: dict[str, str], ids: dict[str, str]) -> list[str]:
    out = [f"  classDef {k} {v}" for k, v in STYLE.items() if k in marks.values()]
    for state in STYLE:
        nodes = [ids[k] for k, v in marks.items() if v == state and k in ids]
        if nodes:
            out.append(f"  class {','.join(nodes)} {state}")
    return out


def _with_removed(cur: dict, prev: dict | None, marks: dict) -> dict:
    out = dict(cur)
    for k, v in marks.items():
        if v == "removed" and prev and k in prev:
            out[k] = prev[k]
    return out


# ------------------------------------------------------------------ architecture (layers)
def architecture(model: dict, marks: dict, prev: dict | None = None, show_tests: bool = False) -> dict:
    mods = _with_removed(model["modules"], (prev or {}).get("modules"), marks.get("modules", {}))
    mk = marks.get("modules", {})
    if not mods:
        return {"mermaid": 'flowchart LR\n  empty["No Python or JS/TS modules yet"]', "nodes": {}, "note": ""}
    tests = {k for k, m in mods.items() if m.get("layer") in ("test", "tooling")}
    trivial = {k for k, m in mods.items() if m["file"].endswith("__init__.py") and m["loc"] <= 3 and not m.get("functions") and not m.get("classes")
               and not any(k in o["deps"] for o in mods.values())}
    shown = {k: m for k, m in mods.items() if (show_tests or k not in tests) and k not in trivial}
    lines, nodes = ["flowchart LR"], {}
    package_level = len(shown) > 60
    if package_level:
        pk = {k: m["pkg"] for k, m in shown.items()}
        groups: dict[str, dict[str, int]] = {}
        for k, m in shown.items():
            groups.setdefault(m.get("layer") or "core", Counter())[m["pkg"]] += 1
        ids = {p: nid("p", p) for p in set(pk.values())}
        for layer in LAYERS:
            if layer in groups:
                lines.append(f'  subgraph {nid("L", layer)}["{LAYER_TITLES[layer]}"]')
                for p, n in sorted(groups[layer].items()):
                    lines.append(f'    {ids[p]}["{label(p)}/ · {n}"]')
                    nodes[ids[p]] = {"kind": "package", "ref": p}
                lines.append("  end")
        edges = Counter((pk[k], pk[d]) for k, m in shown.items() for d in m["deps"] if d in pk and pk[d] != pk[k])
        lines += [f"  {ids[a]} -->|{n}| {ids[b]}" for (a, b), n in sorted(edges.items())]
        note = f"{len(shown)} modules drawn as {len(ids)} packages"
        return {"mermaid": "\n".join(lines), "nodes": nodes, "note": note}
    ids = {k: nid("m", k) for k in shown}
    by_layer: dict[str, list[str]] = {}
    for k, m in shown.items():
        by_layer.setdefault(m.get("layer") or "core", []).append(k)
    for layer in LAYERS:
        if layer not in by_layer:
            continue
        lines.append(f'  subgraph {nid("L", layer)}["{LAYER_TITLES[layer]}"]')
        lines.append("    direction TB")
        for k in sorted(by_layer[layer]):
            m = shown[k]
            extra = f" · {len(m.get('functions', []))} fn" if m.get("functions") else ""
            lines.append(f'    {ids[k]}["{label(os.path.basename(m["file"]))}{extra}"]')
            nodes[ids[k]] = {"kind": "module", "ref": k, "file": m["file"]}
        lines.append("  end")
    if tests and not show_tests:
        lines.append(f'  {nid("t", "tests")}[/"tests · {len(tests)} modules"/]')
        nodes[nid("t", "tests")] = {"kind": "layer", "ref": "test"}
    ext = Counter(e for m in shown.values() for e in m["ext"])
    top = [e for e, _ in ext.most_common(10)]
    if top:
        lines.append('  subgraph Lext["External packages"]')
        for e in top:
            lines.append(f'    {nid("x", e)}(["{label(e)}"])')
            nodes[nid("x", e)] = {"kind": "package", "ref": e}
        lines.append("  end")
    for k in sorted(shown):
        lines += [f"  {ids[k]} --> {ids[d]}" for d in shown[k]["deps"] if d in ids]
        lines += [f'  {ids[k]} -.-> {nid("x", e)}' for e in shown[k]["ext"] if e in top]
    lines += ["  classDef default font-size:13px"] + _classdefs(mk, ids)
    return {"mermaid": "\n".join(lines), "nodes": nodes, "note": ""}


# ------------------------------------------------------------------ file organisation
def files(file_rows: list[dict], max_depth: int = 3, per_dir: int = 10) -> dict:
    tree: dict = {}
    for f in file_rows:
        cur = tree
        parts = f["path"].split("/")
        for p in parts[:-1]:
            cur = cur.setdefault(p + "/", {})
        cur[parts[-1]] = f
    lines, nodes = ["flowchart LR", '  root(["/"])'], {"root": {"kind": "dir", "ref": ""}}
    marks: dict[str, str] = {}
    ids: dict[str, str] = {}

    def walk(node: dict, parent: str, path: str, depth: int) -> None:
        dirs = sorted(k for k in node if k.endswith("/"))
        leaves = sorted(k for k in node if not k.endswith("/"))
        for d in dirs:
            full = path + d
            i = nid("d", full)
            count = sum(1 for _ in _iter_files(node[d]))
            lines.append(f'  {i}["{label(d)} · {count}"]')
            lines.append(f"  {parent} --> {i}")
            nodes[i] = {"kind": "dir", "ref": full.rstrip("/")}
            ch = {x["status"] for x in _iter_files(node[d]) if x.get("status")}
            if ch:
                ids[full], marks[full] = i, "new" if ch == {"A"} else "removed" if ch == {"D"} else "changed"
            if depth < max_depth:
                walk(node[d], i, full, depth + 1)
        shown = leaves[:per_dir]
        for leaf in shown:
            f = node[leaf]
            i = nid("f", path + leaf)
            lines.append(f'  {i}("{label(leaf, 40)}")')
            lines.append(f"  {parent} --- {i}")
            nodes[i] = {"kind": "file", "ref": f["path"], "file": f["path"]}
            if f.get("status"):
                ids[f["path"]], marks[f["path"]] = i, {"A": "new", "M": "changed", "D": "removed"}[f["status"]]
        if len(leaves) > per_dir:
            i = nid("more", path)
            lines.append(f'  {i}["+{len(leaves) - per_dir} more"]:::muted')
            lines.append(f"  {parent} --- {i}")
    walk(tree, "root", "", 1)
    lines += ["  classDef muted stroke-dasharray:3 3,color:#868A91"] + _classdefs(marks, ids)
    return {"mermaid": "\n".join(lines), "nodes": nodes, "note": "" if len(file_rows) < 400 else "large tree: deep folders are collapsed"}


def _iter_files(node: dict):
    for k, v in node.items():
        if k.endswith("/"):
            yield from _iter_files(v)
        else:
            yield v


# ------------------------------------------------------------------ classes
def classes(model: dict, marks: dict, prev: dict | None = None) -> dict:
    cls = _with_removed(model["classes"], (prev or {}).get("classes"), marks.get("classes", {}))
    mk = marks.get("classes", {})
    if not cls:
        return {"mermaid": "classDiagram\n  class NoClassesYet", "nodes": {}, "note": ""}
    by_name: dict[str, list[str]] = {}
    for k, c in cls.items():
        by_name.setdefault(c["name"], []).append(k)
    degree, rel = Counter(), []
    for k, c in cls.items():
        for b in c["bases"]:
            for target in by_name.get(b.split(".")[-1].split("[")[0], [])[:1]:
                rel.append((target, k, "<|--"))
                degree[target] += 1
                degree[k] += 1
        seen = set()
        for _, typ in c["attrs"]:
            for w in re.findall(r"[A-Za-z_]\w*", typ or ""):
                for target in by_name.get(w, [])[:1]:
                    if target != k and target not in seen:
                        seen.add(target)
                        rel.append((k, target, "-->"))
                        degree[target] += 1
                        degree[k] += 1
    keep = sorted(cls, key=lambda k: (k not in mk, -degree[k], k))[:45]
    names, nodes = {}, {}
    for k in keep:
        base = word(cls[k]["name"], "Class")
        names[k] = base if base not in names.values() else word(f'{cls[k]["module"].split(".")[-1].split("/")[-1]}_{base}')
        nodes["class:" + names[k]] = {"kind": "class", "ref": k, "file": cls[k]["file"], "line": cls[k].get("line")}
    lines = ["classDiagram"]
    for k in sorted(keep):
        c = cls[k]
        lines.append(f"  class {names[k]} {{")
        if c.get("kind") == "interface":
            lines.append("    <<interface>>")
        for a, typ in c["attrs"][:7]:
            t = re.match(r"[A-Za-z_][\w.]*", typ or "")
            lines.append(f'    +{word(a)}{" " + word(t.group(0).split(".")[-1]) if t else ""}')
        for meth in [x for x in c["methods"] if not x.startswith("_")][:7]:
            lines.append(f"    +{word(meth)}()")
        if len(c["attrs"]) > 7 or len(c["methods"]) > 7:
            lines.append(f'    +more_{len(c["attrs"])}_attrs_{len(c["methods"])}_methods')
        lines.append("  }")
    lines += sorted({f"  {names[a]} {arrow} {names[b]}" for a, b, arrow in rel if a in names and b in names})
    lines += [f"  style {names[k]} {STYLE[v]}" for k, v in sorted(mk.items()) if k in names]
    return {"mermaid": "\n".join(lines), "nodes": nodes,
            "note": f"{len(cls) - len(keep)} more classes not drawn" if len(cls) > len(keep) else ""}


# ------------------------------------------------------------------ data model
def erd(model: dict, marks: dict, prev: dict | None = None) -> dict:
    tables = _with_removed(model["tables"], (prev or {}).get("tables"), marks.get("tables", {}))
    if not tables:
        return {"mermaid": 'erDiagram\n  NO_TABLES_YET {\n    string hint "SQL, SQLAlchemy, Django, Prisma, zod or Firestore collections appear here"\n  }',
                "nodes": {}, "note": ""}
    names = {k: word(k, "table") for k in tables}
    low = {k.lower(): k for k in tables}
    lines, nodes = ["erDiagram"], {}
    for k in sorted(tables):
        nodes["entity:" + names[k]] = {"kind": "table", "ref": k, "file": tables[k]["file"], "line": tables[k].get("line")}
        lines.append(f"  {names[k]} {{")
        for c in tables[k]["columns"][:30]:
            key = " PK" if c["pk"] else " FK" if c["fk"] else ""
            lines.append(f'    {word(c["type"], "col")} {word(c["name"], "col")}{key}')
        for op, cond in list(tables[k].get("ops", {}).items())[:8]:  # Firestore rules: allowed operations
            lines.append(f'    rule {word(op, "op")} "{label(cond, 40)}"')
        lines.append("  }")
    for k in sorted(tables):
        for c in tables[k]["columns"]:
            target = low.get((c["fk"] or "").lower()) or low.get((c["fk"] or "").lower() + "s")
            if target:
                lines.append(f'  {names[target]} ||--o{{ {names[k]} : "{label(c["name"], 30)}"')
    status = {names[k]: v for k, v in marks.get("tables", {}).items() if k in names}
    return {"mermaid": "\n".join(lines), "nodes": nodes, "marks": status, "note": ""}


# ------------------------------------------------------------------ cloud / infrastructure
def cloud(inf: dict) -> dict:
    ns = inf.get("nodes", [])
    if not ns:
        return {"mermaid": 'flowchart LR\n  none["No infrastructure files found yet: Dockerfile, compose, Terraform, k8s, CI, .env.example"]',
                "nodes": {}, "note": ""}
    lines, nodes = ["flowchart LR"], {}
    groups: dict[str, list[dict]] = {}
    for n in ns:
        groups.setdefault(n.get("group") or "services", []).append(n)
    order = ["application", "containers", "docker compose", "processes", "kubernetes", "serverless", "terraform", "hosting", "services", "delivery"]
    for g in sorted(groups, key=lambda x: order.index(x) if x in order else 99):
        lines.append(f'  subgraph {nid("g", g)}["{label(g.title())}"]')
        for n in groups[g]:
            a, b = KIND_SHAPE.get(n["kind"], ('["', '"]'))
            i = "i_" + word(n["id"])
            lines.append(f'    {i}{a}{label(n["label"], 40)}{b}:::{n["kind"]}')
            nodes[i] = {"kind": "infra", "ref": n["id"], "file": (n.get("sources") or [None])[0]}
        lines.append("  end")
    for e in inf.get("edges", []):
        lines.append(f'  i_{word(e["from"])} -->|{label(e["label"], 20)}| i_{word(e["to"])}')
    lines += ["  classDef app stroke:#3574F0,stroke-width:2.5px", "  classDef db stroke:#C77DBB,stroke-width:2px",
              "  classDef cache stroke:#E5A13E,stroke-width:2px", "  classDef queue stroke:#E5A13E,stroke-width:2px",
              "  classDef external stroke:#57965C,stroke-width:2px", "  classDef cloud stroke:#5A9CF8,stroke-width:2px",
              "  classDef ci stroke-dasharray:4 3"]
    return {"mermaid": "\n".join(lines), "nodes": nodes, "note": ""}


# ------------------------------------------------------------------ API & core processes
def processes(model: dict, focus: str | None = None, depth: int = 2) -> dict:
    fns, routes = model["functions"], model["routes"]
    lines, nodes = ["flowchart LR"], {}
    entries = []
    if routes:
        for r in routes[:30]:
            entries.append((f'{r["method"]} {r["path"]}', r.get("fid"), r))
    else:
        for fid, f in fns.items():
            if f["name"] in ("main", "run", "cli", "handler", "lambda_handler", "start", "serve") or any("command" in d for d in f["decorators"]):
                entries.append((f["qual"] + "()", fid, None))
        entries = entries[:20]
    if focus:
        entries = [e for e in entries if e[0] == focus or e[1] == focus] or entries
    if not entries:
        return {"mermaid": 'flowchart LR\n  none["No HTTP routes or entry points found yet"]', "nodes": {}, "note": ""}
    seen_fn, tables, ext = set(), set(), set()
    lines.append('  subgraph Lroutes["Entry points"]')
    for title, fid, r in entries:
        i = nid("r", title)
        lines.append(f'    {i}(["{label(title, 44)}"]):::route')
        nodes[i] = {"kind": "route", "ref": title, "file": r["file"] if r else fns.get(fid, {}).get("file"),
                    "line": r["line"] if r else fns.get(fid, {}).get("line")}
    lines.append("  end")
    edges = set()

    def visit(fid: str, d: int) -> None:
        if fid not in fns:
            return
        f = fns[fid]
        if fid not in seen_fn:
            seen_fn.add(fid)
            i = nid("f", fid)
            hints = [h for h in f["hints"] if h in ("database query", "HTTP call", "retry with backoff", "async I/O")]
            lines.append(f'  {i}["{label(f["qual"], 36)}()' + (f' · {label(hints[0], 16)}' if hints else "") + '"]')
            nodes[i] = {"kind": "function", "ref": fid, "file": f["file"], "line": f["line"]}
            for t in f.get("tables", []):
                tables.add(t)
                edges.add((i, nid("t", t), "reads/writes"))
            if "HTTP call" in f["hints"]:
                ext.add("HTTP")
                edges.add((i, "extHTTP", "calls"))
        if d >= depth:
            return
        for c in f["callees"][:6]:
            if c != fid and fns.get(c, {}).get("module", "").split(".")[0] not in ("tests", "test"):
                edges.add((nid("f", fid), nid("f", c), ""))
                visit(c, d + 1)
    for title, fid, r in entries:
        if fid:
            edges.add((nid("r", title), nid("f", fid), ""))
            visit(fid, 0)
    for t in sorted(tables):
        lines.append(f'  {nid("t", t)}[("{label(t, 30)}")]:::table')
        nodes[nid("t", t)] = {"kind": "table", "ref": t, "file": model["tables"].get(t, {}).get("file")}
    if ext:
        lines.append('  extHTTP(["external HTTP"]):::ext')
    for a, b, lab in sorted(edges):
        lines.append(f"  {a} -->|{lab}| {b}" if lab else f"  {a} --> {b}")
    lines += ["  classDef route stroke:#3574F0,stroke-width:2px", "  classDef table stroke:#C77DBB,stroke-width:2px",
              "  classDef ext stroke:#57965C,stroke-width:2px"]
    return {"mermaid": "\n".join(lines), "nodes": nodes,
            "note": "" if routes else "no HTTP routes found: showing entry-point functions"}


# ------------------------------------------------------------------ call graph
def calls(model: dict, marks: dict, focus: str | None = None, limit: int = 40) -> dict:
    fns = model["functions"]
    mk = marks.get("functions", {})
    if not fns:
        return {"mermaid": 'flowchart LR\n  none["No functions yet"]', "nodes": {}, "note": ""}
    if focus and focus in fns:
        keep = {focus}
        for c in fns[focus]["callees"]:
            keep.add(c)
            keep |= set(fns.get(c, {}).get("callees", [])[:4])
        for c in fns[focus]["callers"][:8]:
            keep.add(c)
            keep |= set(fns.get(c, {}).get("callers", [])[:3])
        note = f"callers and callees of {fns[focus]['qual']}"
    else:
        score = {fid: len(f["callees"]) + len(f["callers"]) + (5 if fid in mk else 0) for fid, f in fns.items()
                 if f["module"].split(".")[0].split("/")[0] not in ("tests", "test") and "test" != (f["file"].split("/")[0])}
        keep = {fid for fid, _ in sorted(score.items(), key=lambda kv: -kv[1])[:limit] if score[fid] > 0}
        note = f"the {len(keep)} most connected functions of {len(fns)}" if len(fns) > len(keep) else ""
    by_mod: dict[str, list[str]] = {}
    for fid in keep:
        if fid in fns:
            by_mod.setdefault(fns[fid]["module"], []).append(fid)
    lines, nodes, ids = ["flowchart LR"], {}, {}
    for mod in sorted(by_mod):
        lines.append(f'  subgraph {nid("M", mod)}["{label(mod, 40)}"]')
        for fid in sorted(by_mod[mod]):
            f = fns[fid]
            ids[fid] = nid("c", fid)
            heavy = ":::hot" if f["complexity"] >= 10 else ""
            lines.append(f'    {ids[fid]}["{label(f["qual"], 34)}()"]{heavy}')
            nodes[ids[fid]] = {"kind": "function", "ref": fid, "file": f["file"], "line": f["line"]}
        lines.append("  end")
    for fid in sorted(ids):
        for c in fns[fid]["callees"]:
            if c in ids:
                lines.append(f"  {ids[fid]} --> {ids[c]}" if c != fid else f"  {ids[fid]} -.->|recursion| {ids[fid]}")
    if focus and focus in ids:
        lines.append(f"  class {ids[focus]} focus")
    lines += ["  classDef hot stroke:#E5A13E,stroke-width:2px", "  classDef focus stroke:#3574F0,stroke-width:3px"] + _classdefs(mk, ids)
    return {"mermaid": "\n".join(lines), "nodes": nodes, "note": note}


# ------------------------------------------------------------------ concept map
def concept_map(model: dict, concepts: dict, claims: list[dict]) -> dict:
    if not concepts and not claims:
        return {"mermaid": 'flowchart LR\n  none["No mechanisms detected yet"]', "nodes": {}, "note": ""}
    lines, nodes = ["flowchart LR"], {}
    groups: dict[str, list[str]] = {}
    for cid in list(concepts) + [c["concept"] for c in claims if c["concept"] not in concepts]:
        if cid in C.CATALOG and cid not in groups.get(C.CATALOG[cid][2], []):
            groups.setdefault(C.CATALOG[cid][2], []).append(cid)
    files_used: dict[str, str] = {}
    for g in [x for x in C.GROUPS if x in groups]:
        lines.append(f'  subgraph {nid("G", g)}["{C.GROUPS[g]}"]')
        for cid in groups[g]:
            i = "k_" + word(cid)
            lines.append(f'    {i}(["{label(C.CATALOG[cid][0], 32)}"])')
            nodes[i] = {"kind": "concept", "ref": cid}
        lines.append("  end")
    edges = set()
    for cid, evs in concepts.items():
        for e in evs[:4]:
            f = e["file"]
            files_used.setdefault(f, nid("f", f))
            edges.add(("k_" + word(cid), files_used[f], "", "-.-"))
    for c in claims:
        f = c.get("file")
        if not f:
            continue
        files_used.setdefault(f, nid("f", f))
        edges.add(("k_" + word(c["concept"]), files_used[f], "claimed" if c.get("status") == "verified" else "claimed?", "-->"))
    for f, i in sorted(files_used.items()):
        lines.append(f'  {i}["{label(f, 40)}"]:::file')
        nodes[i] = {"kind": "file", "ref": f, "file": f}
    for a, b, lab, arrow in sorted(edges):
        lines.append(f"  {a} {arrow}|{lab}| {b}" if lab else f"  {a} {arrow} {b}")
    lines.append("  classDef file font-size:12px")
    return {"mermaid": "\n".join(lines), "nodes": nodes, "note": "dotted: detected in code · solid: claimed by the agent"}


KINDS = {"architecture": "Architecture", "files": "Files", "classes": "Classes", "data": "Data model", "cloud": "Cloud & infra",
         "processes": "API & processes", "calls": "Call graph", "concepts": "Concept map"}
