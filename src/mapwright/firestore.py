"""Firestore (and Cloud Storage) security rules plus collection usage in JS/TS code, as 'tables' of kind firestore.

A collection is keyed "firestore:users/{id}/notes" (every wildcard becomes {id}) so it never collides with an
SQL table. Rules give the allowed operations and an abbreviated condition; code usage (collection(db,'x'),
doc(db,'x',id), db.collection('x'), collectionGroup) adds collections the rules do not mention and lets the
Logic view link functions to the collections they touch. A subcollection carries a relation to its parent.
"""

from __future__ import annotations

import re

_RULE_TOKEN = re.compile(
    r"match\s+(/\S*)\s*\{|allow\s+([a-z][a-z,\s]*?)\s*(?::\s*if\s+([^;]*?))?\s*;|function\s+\w+\s*\([^)]*\)\s*\{|[{}]", re.S)
_WILD = re.compile(r"\{[^}]*\}")
_ID = "{id}"


def _abbr(cond: str | None, n: int = 70) -> str:
    c = " ".join((cond or "true").split())
    return c if len(c) <= n else c[: n - 1] + "…"


def key_of(path: str, prefix: str = "firestore") -> str:
    return f"{prefix}:{_WILD.sub(_ID, path.strip('/'))}"


def _entry(path: str, line: int, source: str, kind_prefix: str) -> dict:
    segs = path.strip("/").split("/")
    cols = []
    if len(segs) > 2:  # users/{uid}/notes -> relation to users
        parent = "/".join(segs[:-2])
        cols.append({"name": segs[-2].strip("{}").split("=")[0] or "id", "type": "ref", "pk": False, "fk": key_of(parent, kind_prefix)})
    return {"name": key_of(path, kind_prefix), "path": path.strip("/"), "line": line, "columns": cols, "source": source,
            "kind": "firestore" if kind_prefix == "firestore" else "storage", "ops": {}}


def analyze_rules(rel: str, text: str) -> dict:
    out = {"lang": "rules", "id": rel, "loc": text.count("\n") + 1, "imports": [], "classes": [], "tables": [], "functions": [],
           "routes": [], "raw_imports": []}
    storage = "firebase.storage" in text or rel.endswith("storage.rules")
    prefix = "storage" if storage else "firestore"
    clean = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)
    stack: list[str | None] = []  # the collection path owned by each open block, None for other braces
    base: list[str] = []          # composed path prefix at each open block
    tables: dict[str, dict] = {}
    for m in _RULE_TOKEN.finditer(clean):
        tok = m.group(0)
        if m.group(1):
            segs = [s for s in m.group(1).strip("/").split("/") if s]
            full = (base[-1] if base else "").split("/") if base and base[-1] else []
            if segs[:1] == ["databases"] and len(segs) >= 3 and segs[2] == "documents":
                segs = segs[3:]
            elif segs[:1] == ["b"] and len(segs) >= 3 and segs[2] == "o":
                segs = segs[3:]
                full = []
            path = "/".join([*full, *segs])
            base.append(path)
            stack.append(path or None)
        elif m.group(2):
            if not stack or not stack[-1]:
                continue
            segs = stack[-1].split("/")
            while segs and segs[-1].startswith("{") and (len(segs) % 2 == 0 or storage or segs[-1].endswith("=**}")):
                segs.pop()
            path = "/".join(segs)
            if not path:
                continue
            t = tables.get(path)
            if t is None:
                line = clean.count("\n", 0, m.start()) + 1
                t = tables[path] = _entry(path, line, "firestore rules" if not storage else "storage rules", prefix)
            ops = [o.strip() for o in m.group(2).replace("\n", " ").split(",") if o.strip()]
            for o in ops:
                t["ops"][o] = (t["ops"][o] + " | " if o in t["ops"] else "") + _abbr(m.group(3))
        elif tok.startswith("function"):
            stack.append(None)
            base.append(base[-1] if base else "")
        elif tok == "{":
            stack.append(None)
            base.append(base[-1] if base else "")
        elif tok == "}":
            if stack:
                stack.pop()
                base.pop()
    out["tables"] = list(tables.values())
    return out


# ---------------------------------------------------------------- usage in code
_DBISH = r"(?:\w*(?:db|Db|DB|irestore|tore)|firestore\(\)|getFirestore\([^)]*\))"
_STRARG = r"""(?:'[^'\n]*'|"[^"\n]*"|`[^`\n]*`)"""
_MODULAR = re.compile(r"(?<![\w$.])(collectionGroup|collection|doc)\(\s*" + _DBISH + r"\s*,\s*([^()]*(?:\([^()]*\)[^()]*)*)\)")
_CHAIN = re.compile(r"(?<![\w$])" + _DBISH + r"\s*\.(collectionGroup|collection)\(\s*(" + _STRARG + r")\s*\)((?:\s*\.doc\([^()]*\)\s*\.collection\(\s*" + _STRARG + r"\s*\))*)")
_SUB = re.compile(r"\.doc\([^()]*\)\s*\.collection\(\s*(" + _STRARG + r")\s*\)")


def _segments(args: str) -> list[str] | None:
    segs = []
    for a in re.split(r",(?![^()]*\))", args):
        a = a.strip()
        if not a:
            continue
        m = re.fullmatch(r"""'([^']*)'|"([^"]*)"|`([^`]*)`""", a)
        if m:
            s = next(g for g in m.groups() if g is not None)
            segs += [re.sub(r"\$\{[^}]*\}", _ID, p) or _ID for p in s.strip("/").split("/")]
        else:
            segs.append(_ID)
    return segs or None


def find_usage(text: str) -> list[tuple[str, int]]:
    """(collection path, line) for each statically known Firestore collection used in the text."""
    out = []
    line_of = lambda pos: text.count("\n", 0, pos) + 1  # noqa: E731
    for m in _MODULAR.finditer(text):
        segs = _segments(m.group(2))
        if not segs or segs[0] == _ID:
            continue
        if m.group(1) == "doc":
            segs = segs[:-1] if len(segs) % 2 == 0 else segs
        elif m.group(1) != "collectionGroup" and len(segs) % 2 == 0:
            continue
        if segs and segs[0] != _ID:
            out.append(("/".join(segs), line_of(m.start())))
    for m in _CHAIN.finditer(text):
        first = _segments(m.group(2))
        if not first or first[0] == _ID:
            continue
        segs = list(first)
        out.append(("/".join(segs), line_of(m.start())))
        for sm in _SUB.finditer(m.group(3)):
            segs += _segments(sm.group(1)) or []
            segs.insert(len(segs) - 1, _ID)
            out.append(("/".join(segs), line_of(m.start())))
    return out


def usage_tables(text: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for path, line in find_usage(text):
        if path not in seen:
            seen[path] = _entry(path, line, "firestore (code)", "firestore")
    return list(seen.values())


def function_refs(usages: list[tuple[str, int]], functions: list[dict]) -> None:
    """Record on each JS function the collection keys used inside its line range."""
    for path, line in usages:
        inside = [f for f in functions if f["line"] <= line <= f["end"]]
        if inside:
            f = min(inside, key=lambda f: f["end"] - f["line"])
            k = key_of(path)
            if k not in f.setdefault("fs_refs", []):
                f["fs_refs"].append(k)


def merge(old: dict, new: dict, rel: str) -> None:
    """Fold a second description of the same collection into the first; rules beat code usage."""
    if "rules" in new.get("source", "") and "rules" not in old.get("source", ""):
        keep = {k: v for k, v in old.items() if k in ("file",)}
        also = [old["file"], *old.get("also_in", [])]
        old.clear()
        old.update({**new, **keep, "file": rel, "also_in": also})
    elif rel != old.get("file") and rel not in old.get("also_in", []):
        old.setdefault("also_in", []).append(rel)
