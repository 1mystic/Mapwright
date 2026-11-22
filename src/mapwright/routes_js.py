"""Client-side route tables for JS/TS: react-router object/array configs, <Route> JSX, lazy route groups.

Pattern based, nothing is executed. Routes are emitted as method "PAGE" (a screen, not an HTTP verb) and the
handler is the page component when it can be named. Nested paths are composed: a child path that does not start
with "/" is appended to its parent's path, an absolute one replaces it.
"""

from __future__ import annotations

import os
import re

_ROUTER_IMPORT = re.compile(r"""from\s+['"](?:react-router(?:-dom)?(?:/[\w-]+)?|@tanstack/react-router|@remix-run/router)['"]""")
_ROUTER_FILE = re.compile(r"(?:^|/)(?:routes?|routers?|routing|App|app)(?:[./]|$)|(?:routes?|routers?)\.\w+$", re.I)
_KEYS = re.compile(r"""(?<![\w$.])(?:path|index)\s*:|(?<![\w$.])children\s*:\s*\[""")
_ROUTE_KEYS = {"element", "Component", "lazy", "children", "index", "loader", "errorElement", "component"}
_WRAPPER = re.compile(r"^(?:Suspense|Fragment|\w*(?:Provider|Boundary|Gate|Guard|Route|Outlet))$")
_STR = r"""(?:'([^'\n]*)'|"([^"\n]*)"|`([^`\n$]*)`)"""
_PATH_ATTR = re.compile(r"""\bpath\s*=\s*(?:\{\s*)?""" + _STR)
_LAZY_CALL = re.compile(r"""\b([A-Za-z_$][\w$]*)\(\s*(?:\(\s*\)\s*=>\s*)?(?:async\s*\(\s*\)\s*=>\s*)?[^()\[\]]*?import\(\s*['"]([^'"]+)['"]""")


def wants(rel: str, text: str) -> bool:
    return bool(_ROUTER_IMPORT.search(text) or (_ROUTER_FILE.search(rel) and re.search(r"\bpath\s*[:=]|\bRoute\b", text)))


def _skip_string(text: str, j: int) -> int:
    q = text[j]
    j += 1
    while j < len(text) and text[j] != q:
        j += 2 if text[j] == "\\" else 1
    return j


def _match_close(text: str, i: int) -> int:
    """Offset of the bracket that closes the one at text[i] (or len(text))."""
    pairs = {"{": "}", "[": "]", "(": ")"}
    stack, j, n = [pairs[text[i]]], i + 1, len(text)
    while j < n and stack:
        ch = text[j]
        if ch in "'\"`":
            j = _skip_string(text, j)
        elif ch == "/" and text[j:j + 2] == "//":
            j = text.find("\n", j)
            if j < 0:
                return n
        elif ch == "/" and text[j:j + 2] == "/*":
            j = text.find("*/", j + 2)
            if j < 0:
                return n
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch == stack[-1]:
            stack.pop()
        j += 1
    return j - 1 if not stack else n


def _entries(text: str, a: int, b: int) -> list[tuple[int, int]]:
    """Top-level comma separated spans between offsets a and b."""
    out, start, j = [], a, a
    pairs = {"{": "}", "[": "]", "(": ")"}
    while j < b:
        ch = text[j]
        if ch in "'\"`":
            j = _skip_string(text, j)
        elif ch in pairs:
            j = _match_close(text, j)
        elif ch == ",":
            out.append((start, j))
            start = j + 1
        j += 1
    if text[start:b].strip():
        out.append((start, b))
    return out


def _enclosing_open(text: str, pos: int) -> int:
    depth = 0
    for j in range(pos - 1, -1, -1):
        ch = text[j]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                return j
            depth -= 1
    return -1


def _join(prefix: str, seg: str | None) -> str:
    if seg is None:
        return prefix
    if seg.startswith("/"):
        return seg
    return (prefix.rstrip("/") + "/" + seg.lstrip("/")).rstrip("/") if seg and seg != "" else prefix


def _component(snippet: str) -> str | None:
    for m in re.finditer(r"<([A-Z][\w.]*)", snippet):
        if not _WRAPPER.match(m.group(1)):
            return m.group(1).split(".")[-1]
    return None


def _norm(p: str) -> str:
    return re.sub(r"/{2,}", "/", p) if p else "/"


def _from_object(text: str, s: int, e: int, prefix: str, objs: list[tuple[int, int]], out: list, line_of) -> None:
    fields: dict[str, tuple[int, int]] = {}
    for a, b in _entries(text, s + 1, e):
        m = re.match(r"\s*['\"]?([\w$]+)['\"]?\s*:", text[a:b])
        if m:
            fields[m.group(1)] = (a + m.end(), b)
    seg = None
    if "path" in fields:
        m = re.fullmatch(r"\s*" + _STR + r"\s*", text[slice(*fields["path"])])
        seg = next((g for g in m.groups() if g is not None), None) if m else None
    is_index = "index" in fields and re.match(r"\s*true\b", text[slice(*fields["index"])])
    route_like = (seg is not None or is_index or "children" in fields) and (set(fields) & _ROUTE_KEYS)
    if not route_like:
        for a, b in objs:  # not a route: look for route objects inside it
            if s < a and b < e and not any(s < x <= a and b <= y < e for x, y in objs if (x, y) != (a, b)):
                _from_object(text, a, b, prefix, objs, out, line_of)
        return
    here = _join(prefix, seg) if seg is not None else prefix
    handler, target = None, None
    for key in ("element", "Component", "component", "lazy"):
        if key not in fields:
            continue
        v = text[slice(*fields[key])]
        if key == "element":
            handler = handler or _component(v)
        elif key in ("Component", "component"):
            mm = re.match(r"\s*([A-Z][\w$]*)\s*$", v)
            handler = handler or (mm.group(1) if mm else None)
        else:
            im = re.search(r"import\(\s*['\"]([^'\"]+)['\"]", v)
            target = im.group(1) if im else None
            tm = re.search(r"(?:default|Component)\s*:\s*\w+\.([A-Z][\w$]*)|\.then\(\s*\(?\w+\)?\s*=>\s*\w+\.([A-Z][\w$]*)", v)
            handler = handler or (next((g for g in tm.groups() if g), None) if tm else None)
    if seg is not None or is_index:
        r = {"method": "PAGE", "path": _norm(here) if (seg is not None or here) else "/", "via": "react-router", "handler": handler,
             "line": line_of(s)}
        if target:
            r["target"] = target
        out.append(r)
    if "children" in fields:
        a, b = fields["children"]
        i = text.find("[", a)
        if 0 <= i < b:
            for x, y in _entries(text, i + 1, _match_close(text, i)):
                k = text.find("{", x)
                if 0 <= k < y and not text[x:k].strip():
                    _from_object(text, k, _match_close(text, k), here, objs, out, line_of)


def _jsx_routes(text: str, out: list, line_of) -> None:
    stack: list[str] = []
    for m in re.finditer(r"<Route\b|</Route\s*>", text):
        if m.group(0).startswith("</"):
            if stack:
                stack.pop()
            continue
        j, depth = m.end(), 0
        while j < len(text):
            ch = text[j]
            if ch in "'\"`":
                j = _skip_string(text, j)
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                break
            j += 1
        tag = text[m.end():j]
        selfclose = tag.rstrip().endswith("/")
        parent = stack[-1] if stack else ""
        pm = _PATH_ATTR.search(tag)
        seg = next((g for g in pm.groups() if g is not None), None) if pm else None
        here = _join(parent, seg) if seg is not None else parent
        is_index = bool(re.search(r"\bindex\b(?!\s*=\s*\{?\s*false)", tag))
        if seg is not None or is_index:
            em = re.search(r"\belement\s*=\s*\{(.*)", tag, re.S)
            cm = re.search(r"\bComponent\s*=\s*\{\s*([A-Z][\w$]*)", tag)
            handler = _component(em.group(1)) if em else (cm.group(1) if cm else None)
            out.append({"method": "PAGE", "path": _norm(here) if here else "/", "via": "react-router", "handler": handler,
                        "line": line_of(m.start())})
        if not selfclose:
            stack.append(here)


def _lazy_groups(text: str, out: list, line_of) -> None:
    """lazyGroup(() => import('./x'), ['/a', '/b']): a helper that code-splits a list of paths."""
    for m in _LAZY_CALL.finditer(text):
        if m.group(1) in ("lazy", "import", "require", "Promise"):
            continue
        op = text.find("(", m.start())
        end = _match_close(text, op)
        am = re.search(r"\[\s*((?:(?:'[^'\n]*'|\"[^\"\n]*\")\s*,?\s*)+)\]", text[m.end():end])
        if not am:
            continue
        paths = re.findall(r"""['"]([^'"\n]*)['"]""", am.group(1))
        if not paths or not all(p.startswith("/") for p in paths):
            continue
        for p in paths:
            out.append({"method": "PAGE", "path": p, "via": "lazy-group", "handler": None, "target": m.group(2),
                        "line": line_of(m.start())})


def find_routes(rel: str, text: str) -> list[dict]:
    if not wants(rel, text):
        return []
    line_of = lambda pos: text.count("\n", 0, pos) + 1  # noqa: E731
    out: list[dict] = []
    objs = set()
    for m in _KEYS.finditer(text):
        s = _enclosing_open(text, m.start())
        if s >= 0:
            objs.add((s, _match_close(text, s)))
    objs_l = sorted(objs)
    roots = [(a, b) for a, b in objs_l if not any(x < a and b < y for x, y in objs_l)]
    for a, b in roots:
        _from_object(text, a, b, "", objs_l, out, line_of)
    if "<Route" in text:
        _jsx_routes(text, out, line_of)
    _lazy_groups(text, out, line_of)
    seen, uniq = set(), []
    for r in out:
        k = (r["path"], r["handler"], r["via"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def drop_shadowed(routes: list[dict]) -> list[dict]:
    """A lazy-group path that is also defined for real elsewhere is listed once, with the real route."""
    real = {r["path"] for r in routes if r.get("via") != "lazy-group"}
    return [r for r in routes if r.get("via") != "lazy-group" or r["path"] not in real]


# ---------------------------------------------------------------- React components, hooks, zod schemas
_COMPONENT_FN = re.compile(r"^[A-Z]")


def tag_react(rel: str, text: str, functions: list[dict]) -> None:
    """Mark function components (capitalised, returns JSX) and hooks (use*) in .jsx/.tsx/.ts files."""
    if os.path.splitext(rel)[1].lower() not in (".tsx", ".jsx", ".ts", ".js"):
        return
    lines = text.split("\n")
    for f in functions:
        if f.get("cls"):
            continue
        body = "\n".join(lines[f["line"] - 1:f["end"]])
        if re.match(r"use[A-Z0-9]", f["name"]):
            f["hints"] = [*f["hints"], "react hook"]
            f["react"] = "hook"
        elif _COMPONENT_FN.match(f["name"]) and re.search(r"<[A-Za-z][\w.]*[\s/>]|<>|\bjsx\(|createElement\(", body):
            f["hints"] = [*f["hints"], "react component"]
            f["react"] = "component"


def zod_schemas(text: str) -> list[dict]:
    """`const Name = z.object({ a: z.string(), ... })` as table-like data entities."""
    out = []
    for m in re.finditer(r"^[ \t]*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*z\.object\(\s*\{", text, re.M):
        s = text.find("{", m.end() - 1)
        e = _match_close(text, s)
        cols = []
        for a, b in _entries(text, s + 1, e):
            km = re.match(r"\s*['\"]?([\w$]+)['\"]?\s*:\s*(.*)", text[a:b], re.S)
            if not km:
                continue
            tm = re.search(r"\bz\.(\w+)|\b(\w+)\b", km.group(2))
            typ = (tm.group(1) or tm.group(2)) if tm else "any"
            cols.append({"name": km.group(1), "type": typ, "pk": False, "fk": None})
        if cols:
            out.append({"name": m.group(1), "line": text.count("\n", 0, m.start()) + 1, "columns": cols[:60], "source": "zod"})
    return out
