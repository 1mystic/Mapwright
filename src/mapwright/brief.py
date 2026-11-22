"""Compact text views for agents: the whole map in a fixed budget, and one symbol at a time.

These are what keep the token cost low. An agent asks for the map (about 600 tokens by default)
instead of listing directories and opening files to rediscover structure, and asks for one
symbol's callers, callees and tables instead of reading the file. No source code is included.
"""

from __future__ import annotations

import os

from . import analyze as A
from . import concepts as C


def _cut(items: list[str], n: int) -> str:
    return ", ".join(items[:n]) + (f" +{len(items) - n}" if len(items) > n else "")


def project_brief(p, budget: int = 2400, focus: str | None = None) -> str:
    p.ensure()
    m = p.model
    st = p.verify()
    steps = p.steps()
    pend = p.pending(counts=False)
    notes = {n.get("resolved") or n["symbol"]: n["role"] for n in st["notes"] if n.get("status") == "ok"}
    head = [f"# {p.name} · map at step {steps[-1]['n'] if steps else 0}"
            + (f" (+{len(pend)} file changes since)" if pend else "")]
    c = {"files": len(p.cache), "modules": len(m["modules"]), "functions": len(m["functions"]), "classes": len(m["classes"]),
         "tables": len(m["tables"]), "routes": len(m["routes"])}
    head.append(f"{c['files']} files · {c['modules']} modules · {c['functions']} functions · {c['classes']} classes · "
                f"{c['tables']} tables · {c['routes']} routes")
    layers = {}
    for k, mod in m["modules"].items():
        layers.setdefault(mod["layer"], []).append(k)
    head.append("Layers: " + " · ".join(f"{l_} {len(layers[l_])}" for l_ in A.LAYERS if l_ in layers))

    sections: list[tuple[str, list[str]]] = []
    if m["routes"]:
        sections.append(("Entry points", [f"{r['method']} {r['path']} → {(r.get('fid') or r.get('handler') or '?').split(':')[-1]}"
                                          for r in m["routes"]]))
    mods = []
    for layer in A.LAYERS:
        for k in sorted(layers.get(layer, [])):
            mod = m["modules"][k]
            if focus and not mod["file"].startswith(focus.rstrip("/")):
                continue
            if layer == "test" and not focus:
                continue
            fids = [f"{k}:{q}" for q in mod.get("functions", [])]
            fns = sorted((m["functions"][x] for x in fids if x in m["functions"]),
                         key=lambda f: (-(len(f["callers"]) + len(f["callees"])), f["line"]))
            syms = [f["qual"] + (f"(cx {f['complexity']})" if f["complexity"] >= 8 else "") for f in fns if not f["name"].startswith("_")]
            role = notes.get(k) or notes.get(mod["file"])
            mods.append(f"{mod['file']} [{layer}] {_cut(syms, 6 if not focus else 30)}" + (f" — {role}" if role else ""))
    if "test" in layers and not focus:
        mods.append(f"tests: {len(layers['test'])} modules")
    sections.append(("Modules [layer] key symbols — role", mods))
    if m["tables"]:
        tbl = []
        for t, d in sorted(m["tables"].items()):
            cols = [col["name"] + (" PK" if col["pk"] else f" →{col['fk']}" if col["fk"] else "") for col in d["columns"]]
            tbl.append(f"{t}({_cut(cols, 6)})")
        sections.append(("Tables", tbl))
    if p.infra["nodes"]:
        sections.append(("Infra", [f"{n['label']} [{n['kind']}] from {n['sources'][0]}" for n in p.infra["nodes"]]))
    if p.concepts:
        sections.append(("Mechanisms (detected)", [f"{cid}: {_cut(sorted({e['file'] for e in evs}), 2)}" for cid, evs in p.concepts.items()]))
    algos = [f"{', '.join(h for h in f['hints'] if h != 'async I/O')}: {fid.split(':')[-1]} ({f['file']})"
             for fid, f in m["functions"].items() if any(h not in ("async I/O", "database query", "HTTP call") for h in f["hints"])
             and A.layer_of(f["file"]) != "test"]
    if algos:
        sections.append(("Algorithms (hints)", algos))
    todos = [f"{t['id']} {t['text']}" for t in st["todos"] if t["status"] == "open"]
    if todos:
        sections.append(("Open todos", todos))
    if st["problems"]:
        sections.append(("Unverified", [x["text"] for x in st["problems"] if x["kind"] != "parse"][:8]
                         + [x["text"] for x in st["problems"] if x["kind"] == "parse"][:3]))
    if steps:
        sections.append(("Recent steps", [f"{s['n']} {s['title']} (+{s['summary']['added']}/-{s['summary']['removed']} in {s['summary']['files']} files)"
                                          for s in reversed(steps[-4:]) if s["n"] > 0] or ["only the baseline so far"]))
    tail = "Tools: find(query) · symbol(name) · step(title) after each change · todo · claim(concept, symbol)"

    # fit the budget: shrink the longest sections first, never drop the headers
    limits = {name: len(rows) for name, rows in sections}

    def render() -> str:
        out = head[:]
        for name, rows in sections:
            k = limits[name]
            if k <= 0:
                continue
            body = rows[:k]
            more = len(rows) - k
            out.append(f"{name}:" + ("\n  " + "\n  ".join(body) if body else "") + (f"\n  … {more} more" if more > 0 else ""))
        out.append(tail)
        return "\n".join(out)
    text = render()
    guard = 0
    while len(text) > budget and guard < 400:
        guard += 1
        name = max(limits, key=lambda n: (limits[n] * (2 if n.startswith("Modules") else 1), n))
        if limits[name] <= 1:
            break
        limits[name] -= 1 if limits[name] < 8 else max(1, limits[name] // 4)
        text = render()
    return text[: budget + 200]


def symbol_card(p, ref: str) -> str:
    p.ensure()
    hit = A.resolve(p.model, ref)
    if not hit:
        found = A.find_symbols(p.model, ref, 8)
        if not found:
            return f"No symbol matches {ref!r}."
        return "Ambiguous or not found. Candidates:\n" + "\n".join(f"  {f['id']} ({f['kind']}) {f['file']}:{f['line'] or ''}" for f in found)
    kind, sid, n = hit
    v = p.verify()
    lines = []
    if kind == "functions":
        lines.append(f"function {sid}({', '.join(n['args'])}) · {n['file']}:{n['line']}-{n['end']} · {n['loc']} lines · complexity {n['complexity']}")
        if n.get("doc"):
            lines.append(f"doc: {n['doc']}")
        if n["hints"]:
            lines.append("hints: " + ", ".join(n["hints"]))
        lines.append("calls: " + (_cut([c.split(':')[-1] for c in n["callees"]], 10) or "—"))
        lines.append("called by: " + (_cut([c.split(':')[-1] for c in n["callers"]], 10) or "—"))
        routes = [f"{r['method']} {r['path']}" for r in p.model["routes"] if r.get("fid") == sid]
        if routes:
            lines.append("serves: " + ", ".join(routes))
        if n.get("tables"):
            lines.append("tables: " + ", ".join(n["tables"]))
    elif kind == "classes":
        lines.append(f"class {sid} · {n['file']}:{n['line']} · bases {', '.join(n['bases']) or '—'}")
        lines.append("attributes: " + (_cut([a for a, _ in n["attrs"]], 12) or "—"))
        lines.append("methods: " + (_cut(n["methods"], 14) or "—"))
    elif kind == "tables":
        lines.append(f"table {sid} · {n['file']}:{n.get('line')}")
        lines.append("columns: " + ", ".join(c["name"] + (" PK" if c["pk"] else f" →{c['fk']}" if c["fk"] else "") for c in n["columns"]))
        users = [fid.split(":")[-1] for fid, f in p.model["functions"].items() if sid in f.get("tables", [])]
        if users:
            lines.append("used by: " + _cut(users, 10))
    else:
        lines.append(f"module {sid} · {n['file']} · layer {n['layer']} · {n['loc']} lines")
        lines.append("imports: " + (_cut(n["deps"], 10) or "—") + (" · external: " + _cut(n["ext"], 8) if n["ext"] else ""))
        lines.append("defines: " + (_cut(n.get("functions", []), 14) or "—"))
        users = [k for k, m in p.model["modules"].items() if sid in m["deps"]]
        lines.append("imported by: " + (_cut(users, 10) or "—"))
    role = next((x["role"] for x in v["notes"] if x.get("resolved") == sid), None)
    if role:
        lines.append(f"role (agent note): {role}")
    cl = [f"{c['concept']} ({c['status']})" for c in v["claims"] if c.get("resolved") == sid]
    if cl:
        lines.append("claimed: " + ", ".join(cl))
    det = [cid for cid, evs in p.concepts.items() if any(e["file"] == n["file"] and (kind == "modules" or e.get("symbol") == (n.get("qual") or n.get("name"))) for e in evs)]
    if det:
        lines.append("detected: " + ", ".join(det))
    hist = symbol_history(p, kind, sid)
    if hist:
        lines.append("history: " + hist)
    return "\n".join(lines)


def symbol_history(p, kind: str, sid: str, max_steps: int = 30) -> str:
    out, seen_prev = [], None
    for s in p.steps()[-max_steps:]:
        data = p.load_step(s["n"])
        if not data:
            continue
        node = data["model"].get(kind, {}).get(sid)
        sig = A._sig(kind, node) if node else None
        if node and seen_prev is None:
            out.append(f"added in step {s['n']}" if s["n"] > 0 else "present at baseline")
        elif node and sig != seen_prev:
            out.append(f"changed in step {s['n']}")
        elif not node and seen_prev is not None:
            out.append(f"removed in step {s['n']}")
        seen_prev = sig
    return ", ".join(out[-6:])


def catalog_text() -> str:
    rows = [f"{c['id']}: {c['meaning']}" for c in C.catalog()]
    return "Concept ids for claim(concept, symbol):\n" + "\n".join(rows)


def step_receipt(data: dict) -> str:
    s = data["summary"]
    parts = [f"step {data['n']} recorded: {s['files']} files (+{s['added']} -{s['removed']})"]
    for kind, d in s["delta"].items():
        parts.append(f"{kind}: " + ", ".join(f"{v} {k}" for k, v in d.items()))
    if data.get("title_check", "ok") != "ok":
        parts.append("check: " + data["title_check"])
    if not s["files"]:
        parts.append("note: nothing changed since the previous step")
    return " · ".join(parts)


def files_line(changes: list[dict]) -> str:
    return ", ".join(f"{c['kind'][0].upper()} {os.path.basename(c['path'])}" for c in changes[:8])
