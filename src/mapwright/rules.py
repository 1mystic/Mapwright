"""Architecture rules: constraints the team writes once in `mapwright.toml` (project root, committed) and Mapwright
checks against the map at every step. Violations show up in Problems, in the agent's `map`, in exports, and make
`mapwright check` exit non-zero for CI.

    [layers]                      # optional: pin paths to layers (glob = layer); overrides the heuristics
    "src/app/web/**" = "ui"

    [[forbid]]                    # an import that must not exist
    from = "ui"                   # a layer name, or a path glob ("src/app/web/**")
    to = ["data"]                 # layers or globs
    except = ["src/app/db/types.py"]   # optional
    reason = "UI goes through services"

    [limits]
    no_cycles = true              # import cycles between modules
    max_complexity = 25           # cyclomatic complexity per function
    max_module_lines = 800

Stdlib only. Python 3.11+ reads the file with tomllib; 3.10 uses the small parser below (tables, arrays of tables,
strings, numbers, booleans, string arrays, inline tables of strings).
"""

from __future__ import annotations

import json
import os
import re

FILE = "mapwright.toml"
RANK = {"ui": 4, "interface": 4, "service": 3, "integration": 2, "data": 2, "core": 1, "util": 0, "config": 0}
_CACHE: dict[str, tuple[float, dict | None, str | None]] = {}


# ------------------------------------------------------------------ parsing
def _value(raw: str):
    raw = raw.strip()
    if raw.startswith("["):
        inner = raw[1:-1].strip()
        return [_value(x) for x in _split(inner)] if inner else []
    if raw.startswith("{"):
        out = {}
        for item in _split(raw[1:-1]):
            k, _, v = item.partition("=")
            out[_key(k)] = _value(v)
        return out
    if raw[:1] in "\"'":
        return json.loads(raw) if raw[0] == '"' else raw[1:-1]
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        return float(raw)


def _split(s: str) -> list[str]:
    """Split on top-level commas (outside quotes and brackets)."""
    out, depth, cur, q = [], 0, "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "\"'":
            q, cur = ch, cur + ch
        elif ch in "[{":
            depth, cur = depth + 1, cur + ch
        elif ch in "]}":
            depth, cur = depth - 1, cur + ch
        elif ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out if x.strip()]


def _key(k: str) -> str:
    k = k.strip()
    return k[1:-1] if k[:1] in "\"'" else k


def _strip_comment(line: str) -> str:
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#":
            return line[:i]
    return line


def parse_toml(text: str) -> dict:
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads(text)
    except ImportError:
        pass
    data: dict = {}
    cur = data
    pending = ""
    for n, line in enumerate(text.splitlines(), 1):
        line = _strip_comment(line).strip()
        if pending:  # a value continued over several lines (multi-line arrays)
            pending += " " + line
            if pending.count("[") > pending.count("]"):
                continue
            line, pending = pending, ""
        if not line:
            continue
        if line.startswith("[["):
            name = _key(line[2:-2])
            cur = {}
            data.setdefault(name, []).append(cur)
        elif line.startswith("["):
            cur = data.setdefault(_key(line[1:-1]), {})
        else:
            k, eq, v = line.partition("=")
            if not eq:
                raise ValueError(f"{FILE}: line {n}: expected key = value")
            if v.count("[") > v.count("]"):
                pending = line
                continue
            cur[_key(k)] = _value(v)
    return data


def load(root: str) -> tuple[dict | None, str | None]:
    """(rules, error). No file → (None, None)."""
    path = os.path.join(root, FILE)
    try:
        mt = os.stat(path).st_mtime
    except OSError:
        return None, None
    hit = _CACHE.get(path)
    if hit and hit[0] == mt:
        return hit[1], hit[2]
    try:
        with open(path, encoding="utf-8") as fh:
            rules, err = parse_toml(fh.read()), None
    except (OSError, ValueError) as e:
        rules, err = None, f"{FILE} could not be read: {e}"
    _CACHE[path] = (mt, rules, err)
    return rules, err


# ------------------------------------------------------------------ matching
def _glob_re(pat: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pat.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pat[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pat[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pat[i]), i + 1
    return re.compile(out + "$")


def _is_layer(sel: str) -> bool:
    return not any(c in sel for c in "/*.?")


def _match(sel: str, file: str, layer: str) -> bool:
    return sel == layer if _is_layer(sel) else bool(_glob_re(sel.rstrip("/") if not sel.endswith("/") else sel + "**").match(file))


def _as_list(v) -> list[str]:
    return [v] if isinstance(v, str) else [x for x in (v or []) if isinstance(x, str)]


# ------------------------------------------------------------------ checking
def _modules(model: dict, rules: dict) -> dict[str, tuple[str, str]]:
    pins = [(_glob_re(g), lay) for g, lay in (rules.get("layers") or {}).items() if isinstance(lay, str)]
    out = {}
    for mid, m in (model.get("modules") or {}).items():
        layer = m.get("layer") or "core"
        for rx, lay in pins:
            if rx.match(m["file"]):
                layer = lay
                break
        out[mid] = (m["file"], layer)
    return out


def _cycles(model: dict, mods: dict) -> list[list[str]]:
    """Strongly connected components with more than one module (Tarjan, iterative)."""
    graph = {mid: [d for d in (m.get("deps") or []) if d in mods] for mid, m in (model.get("modules") or {}).items() if mid in mods}
    index, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
    for start in graph:
        if start in index:
            continue
        work = [(start, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter[0]
                counter[0] += 1
                stack.append(v)
                on.add(v)
            for j in range(i, len(graph[v])):
                w = graph[v][j]
                if w not in index:
                    work.append((v, j + 1))
                    work.append((w, 0))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        out.append(sorted(comp))
                if work:
                    u = work[-1][0]
                    low[u] = min(low[u], low[v])
    return out


def check(model: dict, rules: dict | None) -> list[dict]:
    """Every violation as {rule, file, target, text}."""
    if not rules:
        return []
    mods = _modules(model, rules)
    tests = bool((rules.get("limits") or {}).get("include_tests"))
    live = {mid: v for mid, v in mods.items() if tests or v[1] != "test"}
    out = []
    for r in rules.get("forbid") or []:
        if not isinstance(r, dict):
            continue
        frm, to, exc = _as_list(r.get("from")), _as_list(r.get("to")), _as_list(r.get("except"))
        reason = r.get("reason") or ""
        for mid, (file, layer) in live.items():
            if not any(_match(s, file, layer) for s in frm):
                continue
            for dep in (model["modules"][mid].get("deps") or []):
                if dep not in live:
                    continue
                tfile, tlayer = live[dep]
                if any(_match(s, tfile, tlayer) for s in to) and not any(_match(s, tfile, tlayer) or _match(s, file, layer) for s in exc):
                    out.append({"rule": "forbid", "file": file, "target": tfile,
                                "text": f"{file} [{layer}] imports {tfile} [{tlayer}]" + (f": {reason}" if reason else "")})
    lim = rules.get("limits") or {}
    if lim.get("no_cycles"):
        for comp in _cycles(model, live)[:10]:
            files = [live[m][0] for m in comp]
            out.append({"rule": "cycle", "file": files[0], "target": files[-1],
                        "text": "import cycle: " + " → ".join(files[:6]) + (" …" if len(files) > 6 else "") + f" → {files[0]}"})
    mx = lim.get("max_complexity")
    if isinstance(mx, int) and mx > 0:
        files = {v[0] for v in live.values()}
        hot = sorted(((f.get("complexity") or 0, fid, f) for fid, f in (model.get("functions") or {}).items()
                      if f.get("file") in files and (f.get("complexity") or 0) > mx), key=lambda x: -x[0])
        for cx, fid, f in hot[:20]:
            out.append({"rule": "complexity", "file": f["file"], "target": fid,
                        "text": f"{f.get('qual', fid)} in {f['file']} has complexity {cx} (limit {mx})"})
    ml = lim.get("max_module_lines")
    if isinstance(ml, int) and ml > 0:
        for mid, (file, _) in live.items():
            loc = model["modules"][mid].get("loc") or 0
            if loc > ml:
                out.append({"rule": "size", "file": file, "target": file, "text": f"{file} has {loc} lines (limit {ml})"})
    return out


def problems(root: str, model: dict) -> list[dict]:
    rules, err = load(root)
    if err:
        return [{"kind": "rule", "status": "error", "text": err}]
    return [{"kind": "rule", "status": v["rule"], "text": v["text"], "file": v["file"]} for v in check(model, rules)]


# ------------------------------------------------------------------ starter file
def starter(model: dict) -> str:
    """A mapwright.toml that holds for the code as it is today: forbids every 'upward' layer import that does not
    happen yet, keeps cycles out if there are none, and caps complexity just above today's worst function."""
    mods = _modules(model, {})
    live = {mid: v for mid, v in mods.items() if v[1] != "test"}
    edges = set()
    for mid, (_, layer) in live.items():
        for dep in model["modules"][mid].get("deps") or []:
            if dep in live:
                edges.add((layer, live[dep][1]))
    present = sorted({v[1] for v in live.values()} & set(RANK))
    lines = ["# Architecture rules for Mapwright: checked at every step, shown in Problems and in the agent's map;",
             "# `mapwright check` exits non-zero when one is broken (use it in CI). Generated from the code as it is today.", ""]
    lines += ["# [layers]", '# "src/app/web/**" = "ui"     # pin paths to layers when the heuristics guess wrong', ""]
    for low in present:
        ups = [hi for hi in present if RANK[hi] > RANK[low] and (low, hi) not in edges]
        if ups:
            lines += ["[[forbid]]", f'from = "{low}"', "to = [" + ", ".join(f'"{u}"' for u in ups) + "]",
                      f'reason = "{low} code must not depend on higher layers"', ""]
    cyc = bool(_cycles(model, live))
    worst = max([f.get("complexity") or 0 for f in (model.get("functions") or {}).values()] or [0])
    lines += ["[limits]", f"no_cycles = {'false' if cyc else 'true'}" + ("   # there are cycles today; fix them, then turn this on" if cyc else ""),
              f"max_complexity = {max(25, worst)}", ""]
    return "\n".join(lines)
