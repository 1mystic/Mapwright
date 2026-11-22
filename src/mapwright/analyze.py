"""Static analysis: turn the files of a project into one structured model.

Python goes through `ast`; JS/TS, SQL and Prisma through patterns. Nothing in the project is
imported or executed. Per-file results are cached by content hash, so re-analysing after an
agent edit costs one file, not the whole tree.

The model holds modules, classes, functions (with calls, complexity and algorithm hints),
HTTP routes, tables, layers, concepts (see concepts.py) and infrastructure (see infra.py).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from mapwright import firestore as _fs
from mapwright import routes_js as _rjs

IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".tox", ".mypy_cache",
               ".pytest_cache", ".ruff_cache", ".next", ".nuxt", "target", "vendor", ".idea", ".vscode", "coverage",
               ".cache", "site-packages", ".eggs", ".terraform", ".gradle", "htmlcov", ".mapwright", ".svelte-kit", ".turbo",
               ".parcel-cache", ".output", "out", "bower_components", ".serverless"}
CODE_EXT = {".py": "python", ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
            ".sql": "sql", ".prisma": "prisma", ".rules": "rules"}
TEXT_EXT = set(CODE_EXT) | {".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".html", ".css", ".scss", ".sh",
                            ".go", ".rs", ".java", ".rb", ".php", ".c", ".h", ".cpp", ".txt", ".graphql", ".proto",
                            ".kt", ".swift", ".cs", ".vue", ".svelte", ".tf", ".xml"}
TEXT_NAMES = {"Makefile", "Dockerfile", "Procfile", "Jenkinsfile", ".gitignore", ".dockerignore", "Containerfile",
              "Gemfile", "requirements.txt", "go.mod", "Cargo.toml", ".env.example", ".env.sample", ".env.template"}
MAX_FILES, MAX_FILE_BYTES, MAX_CACHE_CHARS, MAX_DIFF_LINES = 5000, 256_000, 32_000_000, 120
def _secretish(rel: str) -> bool:
    name = os.path.basename(rel).lower()
    if name.startswith(".env"):
        return not name.endswith((".example", ".sample", ".template", ".dist"))
    return (name.endswith((".pem", ".key", ".p12", ".pfx", ".keystore")) or "id_rsa" in name or "id_ed25519" in name
            or name in (".netrc", ".npmrc", ".pypirc", "credentials", "secrets.yaml", "secrets.yml", "secrets.json"))


def _texty(rel: str) -> bool:
    return os.path.splitext(rel)[1].lower() in TEXT_EXT or os.path.basename(rel) in TEXT_NAMES


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def find_root(cwd: str) -> str:
    """The project root: the nearest ancestor holding .git, else the directory itself."""
    p = Path(cwd)
    for d in [p, *p.parents][:6]:
        if (d / ".git").exists():
            return str(d)
    return str(p)


def scan(root: str) -> tuple[dict[str, tuple[int, int]], bool]:
    """rel path -> (mtime_ns, size) for every file worth tracking. Second value: hit the file cap."""
    out: dict[str, tuple[int, int]] = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and not d.endswith(".egg-info"))
        for f in files:
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root)
            if not (_texty(rel) or _secretish(rel)):
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            out[rel] = (st.st_mtime_ns, st.st_size)
            if len(out) >= MAX_FILES:
                return out, True
    return out, False


def read_text(root: str, rel: str) -> str | None:
    """File text, or None if it is missing, too large, binary or secret-looking."""
    if _secretish(rel):
        return None
    try:
        with open(os.path.join(root, rel), "rb") as fh:
            raw = fh.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_FILE_BYTES or b"\0" in raw:
        return None
    return raw.decode("utf-8", "replace")


# ============================================================================ per-file analysis
def _name(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _py_module_id(rel: str) -> str:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1] or ["__init__"]
    return ".".join(parts)


def _call_name(node) -> str:
    return _name(node.func).split(".")[-1] if isinstance(node, ast.Call) else ""


def _py_class(node: ast.ClassDef) -> tuple[dict, dict | None]:
    attrs, methods, table, cols = [], [], None, []
    bases = [_name(b) for b in node.bases if _name(b)]
    django = any(b.split(".")[-1] == "Model" and "models" in b or b == "Model" for b in bases)

    def column(name: str, value, ann: str = "") -> None:
        fn = _call_name(value)
        if fn in ("Column", "mapped_column"):
            typ = next((_name(a).split("(")[0].split(".")[-1] for a in value.args if _call_name(a) != "ForeignKey"), "") or ann
            fk = next((a.args[0].value for a in value.args if _call_name(a) == "ForeignKey" and a.args
                       and isinstance(a.args[0], ast.Constant) and isinstance(a.args[0].value, str)), None)
            pk = any(k.arg == "primary_key" and getattr(k.value, "value", False) for k in value.keywords)
            cols.append({"name": name, "type": typ or "col", "pk": pk, "fk": fk.split(".")[0] if fk else None})
        elif django and (fn.endswith("Field") or fn in ("ForeignKey", "OneToOneField", "ManyToManyField")):
            fk = None
            if fn in ("ForeignKey", "OneToOneField", "ManyToManyField") and value.args:
                a = value.args[0]
                fk = (a.value if isinstance(a, ast.Constant) else _name(a)).split(".")[-1].lower()
            cols.append({"name": name, "type": fn.replace("Field", "") or "Field", "pk": False, "fk": fk})

    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            ann = _name(item.annotation)
            attrs.append([item.target.id, ann])
            if item.value is not None:
                column(item.target.id, item.value, re.sub(r"^Mapped\[(.*)\]$", r"\1", ann))
        elif isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
            n = item.targets[0].id
            if n == "__tablename__" and isinstance(item.value, ast.Constant):
                table = str(item.value.value)
            elif not n.startswith("__"):
                attrs.append([n, ""])
                column(n, item.value)
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(item.name)
            if item.name == "__init__":
                for sub in ast.walk(item):
                    tgt = sub.target if isinstance(sub, ast.AnnAssign) else sub.targets[0] if isinstance(sub, ast.Assign) and sub.targets else None
                    if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                        ann = _name(sub.annotation) if isinstance(sub, ast.AnnAssign) else ""
                        if tgt.attr not in [a[0] for a in attrs]:
                            attrs.append([tgt.attr, ann])
    cls = {"name": node.name, "line": node.lineno, "bases": bases, "attrs": attrs[:40], "methods": methods[:60]}
    if django and not table:
        table = node.name.lower()
        if not any(c["pk"] for c in cols):
            cols.insert(0, {"name": "id", "type": "Auto", "pk": True, "fk": None})
    if table and cols:
        return cls, {"name": table, "line": node.lineno, "columns": cols, "source": "django" if django else "sqlalchemy"}
    return cls, None


def analyze_python(rel: str, text: str) -> dict:
    out = {"lang": "python", "id": _py_module_id(rel), "loc": text.count("\n") + 1, "imports": [], "classes": [], "tables": [],
           "functions": [], "routes": [], "raw_imports": [], "aliases": {}}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return {**out, "error": True}  # the agent may be half-way through an edit
    parts = rel[:-3].split("/")
    pkg = parts if parts[-1] == "__init__" else parts[:-1]
    if parts[-1] == "__init__":
        pkg = parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out["imports"] += [[a.name] for a in node.names]
            out["raw_imports"] += [a.name for a in node.names]
            for a in node.names:
                if a.asname:
                    out["aliases"][a.asname] = [a.name]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[: len(pkg) - (node.level - 1)] if node.level - 1 <= len(pkg) else []
                mod = ".".join(base + ([node.module] if node.module else []))
                rel_import = True
            else:
                mod, rel_import = node.module or "", False
                out["raw_imports"].append(mod)
            for a in node.names:
                cands = [f"{mod}.{a.name}" if mod else a.name, mod] if a.name != "*" else [mod]
                out["imports"].append([c for c in cands if c] + (["."] if rel_import else []))
                if a.name != "*":
                    out["aliases"][a.asname or a.name] = [c for c in cands if c][:1]
    prefixes = {}
    for node in tree.body:  # router = APIRouter(prefix="/orders") · bp = Blueprint("x", __name__, url_prefix="/x")
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call):
            for kw in node.value.keywords:
                if kw.arg in ("prefix", "url_prefix") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    prefixes[node.targets[0].id] = kw.value.value.rstrip("/")
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            cls, table = _py_class(node)
            cls["end"] = getattr(node, "end_lineno", node.lineno)
            out["classes"].append(cls)
            if table:
                cls["table"] = table["name"]
                out["tables"].append(table)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out["functions"].append(_py_func(item, text, cls_name=node.name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["functions"].append(_py_func(node, text))
    out["raw_imports"] = sorted({m for m in out["raw_imports"] if m})
    for node in ast.walk(tree):  # CREATE TABLE inside string literals (sqlite3 scripts, migrations in code)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"(?i)create\s+table", node.value):
            for t in analyze_sql(rel, node.value)["tables"]:
                if t["name"] not in {x["name"] for x in out["tables"]}:
                    out["tables"].append({**t, "line": node.lineno + t["line"] - 1, "source": "sql in code"})
    for f in out["functions"]:
        for r in f.pop("_routes", []):
            path = (prefixes.get(r["via"], "") + "/" + r["path"].lstrip("/")).rstrip("/") or "/" if r["via"] in prefixes else r["path"]
            out["routes"].append({**r, "path": path, "handler": f["qual"], "line": f["line"]})
    out["sql_tables"] = sorted(set(_SQL_REF.findall(text)))[:40]
    return out


_JS_IMPORT = re.compile(r"""(?:\bimport\s+(?:[^'"()]*?\sfrom\s+)?|\bexport\s+[^'"()]*?\sfrom\s+|\brequire\(\s*|\bimport\(\s*)['"]([^'"\n]+)['"]""")
_JS_CLASS = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)(?:\s+extends\s+([\w$.]+))?", re.M)
_JS_IFACE = re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)(?:\s+extends\s+([\w$., ]+?))?\s*\{", re.M)


def analyze_js(rel: str, text: str) -> dict:
    out = {"lang": "js", "id": os.path.splitext(rel)[0], "loc": text.count("\n") + 1, "imports": [], "classes": [], "tables": [],
           "functions": [], "routes": [], "raw_imports": sorted(set(_JS_IMPORT.findall(text)))}
    here = os.path.dirname(rel)
    for spec in dict.fromkeys(_JS_IMPORT.findall(text)):
        if spec.startswith("."):
            target = os.path.normpath(os.path.join(here, spec))
            target = re.sub(r"\.(?:js|jsx|ts|tsx|mjs|cjs)$", "", target)
            out["imports"].append([target, target + "/index", "."])
        elif not spec.startswith(("node:", "/", "http")):
            out["imports"].append(["/".join(spec.split("/")[: 2 if spec.startswith("@") else 1])])
    line_of = lambda m: text.count("\n", 0, m.start()) + 1  # noqa: E731
    for m in _JS_CLASS.finditer(text):
        out["classes"].append({"name": m.group(1), "line": line_of(m), "bases": [m.group(2)] if m.group(2) else [],
                               "attrs": [], "methods": []})
    for m in _JS_IFACE.finditer(text):
        bases = [b.strip() for b in (m.group(2) or "").split(",") if b.strip()]
        out["classes"].append({"name": m.group(1), "line": line_of(m), "bases": bases, "attrs": [], "methods": [], "kind": "interface"})
    _js_functions(rel, text, out)
    for m in re.finditer(r"(`|\"|')((?:(?!\1)[\s\S]){0,4000}?(?i:create\s+table)[\s\S]{0,4000}?)\1", text):
        for t in analyze_sql(rel, m.group(2))["tables"]:
            if t["name"] not in {x["name"] for x in out["tables"]}:
                out["tables"].append({**t, "line": text.count("\n", 0, m.start()) + t["line"], "source": "sql in code"})
    out["sql_tables"] = sorted(set(_SQL_REF.findall(text)))[:40]
    _js_extras(rel, text, out)
    return out


def _js_extras(rel: str, text: str, out: dict) -> None:
    """Client routes (react-router), Firestore collections, zod schemas and React tags: see routes_js / firestore."""
    out["routes"] += _rjs.find_routes(rel, text)
    usage = _fs.find_usage(text)
    have = {t["name"] for t in out["tables"]}
    out["tables"] += [t for t in _fs.usage_tables(text) if t["name"] not in have]
    _fs.function_refs(usage, out["functions"])
    out["tables"] += [t for t in _rjs.zod_schemas(text) if t["name"] not in have]
    _rjs.tag_react(rel, text, out["functions"])


_SQL_TABLE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?[`\"\[]?([\w.]+)[`\"\]]?\s*\(", re.I)


def _split_top(body: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def analyze_sql(rel: str, text: str) -> dict:
    out = {"lang": "sql", "id": rel, "loc": text.count("\n") + 1, "imports": [], "classes": [], "tables": [],
           "functions": [], "routes": [], "raw_imports": []}
    clean = re.sub(r"--[^\n]*", "", text)
    for m in _SQL_TABLE.finditer(clean):
        depth, i = 1, m.end()
        while i < len(clean) and depth:
            depth += {"(": 1, ")": -1}.get(clean[i], 0)
            i += 1
        cols, pks = [], set()
        for part in _split_top(clean[m.end(): i - 1]):
            low = part.lower()
            fkm = re.match(r"(?:constraint\s+\S+\s+)?foreign\s+key\s*\(\s*[`\"]?(\w+)[`\"]?\s*\)\s*references\s+[`\"]?([\w.]+)", low)
            pkm = re.match(r"(?:constraint\s+\S+\s+)?primary\s+key\s*\(([^)]*)\)", low)
            if fkm:
                for c in cols:
                    if c["name"].lower() == fkm.group(1):
                        c["fk"] = fkm.group(2).split(".")[-1]
            elif pkm:
                pks |= {x.strip(" `\"") for x in pkm.group(1).split(",")}
            elif not re.match(r"(constraint|unique|check|index|key)\b", low):
                toks = part.split()
                if len(toks) >= 2:
                    ref = re.search(r"references\s+[`\"]?([\w.]+)", low)
                    cols.append({"name": toks[0].strip("`\"[]"), "type": re.sub(r"\(.*", "", toks[1]).strip(",") or "col",
                                 "pk": "primary key" in low, "fk": ref.group(1).split(".")[-1] if ref else None})
        for c in cols:
            c["pk"] = c["pk"] or c["name"].lower() in pks
        if cols:
            out["tables"].append({"name": m.group(1).split(".")[-1].strip("`\""), "line": clean.count("\n", 0, m.start()) + 1,
                                  "columns": cols, "source": "sql"})
    return out


_PRISMA = re.compile(r"^model\s+(\w+)\s*\{(.*?)^\}", re.M | re.S)


def analyze_prisma(rel: str, text: str) -> dict:
    out = {"lang": "prisma", "id": rel, "loc": text.count("\n") + 1, "imports": [], "classes": [], "tables": [],
           "functions": [], "routes": [], "raw_imports": []}
    models = {m.group(1) for m in _PRISMA.finditer(text)}
    for m in _PRISMA.finditer(text):
        cols = []
        for line in m.group(2).splitlines():
            toks = line.split("//")[0].split()
            if len(toks) < 2 or toks[0].startswith("@@"):
                continue
            typ = toks[1].rstrip("?[]")
            if typ in models:
                if "@relation" in line and "fields:" in line:  # the owning side names the relation
                    cols.append({"name": toks[0], "type": typ, "pk": False, "fk": typ})
                continue
            cols.append({"name": toks[0], "type": typ, "pk": "@id" in line, "fk": None})
        out["tables"].append({"name": m.group(1), "line": text.count("\n", 0, m.start()) + 1, "columns": cols, "source": "prisma"})
    return out


ANALYZERS = {"python": analyze_python, "js": analyze_js, "sql": analyze_sql, "prisma": analyze_prisma, "rules": _fs.analyze_rules}




# ============================================================================ functions, routes, hints
_SQL_REF = re.compile(r"(?i)\b(?:from|join|into|update|table)\s+[`\"\[]?([A-Za-z_][\w]*)[`\"\]]?(?=[\s;(,)]|$)")
_ROUTE_DECO = re.compile(r"""^([\w.]+)\.(get|post|put|patch|delete|head|options|route|websocket|api_route)\(\s*(?:path\s*=\s*)?['"]([^'"]*)['"](.*)$""", re.S)
_SQL_KW = {"select", "where", "set", "values", "the", "a", "an", "it", "this", "that", "each", "which"}


def _complexity(node) -> int:
    n = 1
    for sub in ast.walk(node):
        if isinstance(sub, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler, ast.Assert)):
            n += 1
        elif isinstance(sub, ast.BoolOp):
            n += len(sub.values) - 1
        elif isinstance(sub, ast.comprehension):
            n += 1 + len(sub.ifs)
        elif sys.version_info >= (3, 10) and isinstance(sub, ast.match_case):
            n += 1
    return n


def algorithm_hints(names: set[str], calls: set[str], text: str, own: str, is_async: bool, decos: list[str]) -> list[str]:
    """Recognisable algorithms and mechanisms in one function, from the names it uses.
    Hints, not proofs: the UI and the brief label them as such."""
    low = text.lower()
    h = []
    if own in calls:
        h.append("recursion")
    if any(d.split("(")[0].split(".")[-1] in ("lru_cache", "cache", "cached", "memoize") for d in decos) or "memo" in names:
        h.append("memoization")
    if {"sorted", "sort"} & calls:
        h.append("sorting")
    if "heapq" in low or {"heappush", "heappop"} & calls:
        h.append("priority queue (heap)")
    if "bisect" in low or ({"lo", "hi", "mid"} <= names) or ({"low", "high", "mid"} <= names) or ({"left", "right", "mid"} <= names):
        h.append("binary search")
    if ("popleft" in calls or "shift" in calls) and ("visited" in names or "seen" in names):
        h.append("breadth-first search")
    elif ("visited" in names or "seen" in names) and ("stack" in names or own in calls):
        h.append("depth-first search")
    if "dp" in names or "table" in names and "range" in calls and "min" in calls | {"max"}:
        h.append("dynamic programming")
    if {"sha256", "sha1", "md5", "blake2b", "hexdigest", "createHash"} & calls or "hashlib" in low:
        h.append("hashing")
    if {"compile", "match", "search", "findall", "sub", "fullmatch"} & calls and ("re." in low or "regex" in low):
        h.append("regular expressions")
    if {"sleep"} & calls and any(w in low for w in ("retry", "attempt", "backoff", "tries")):
        h.append("retry with backoff")
    if {"limit", "offset"} <= names or "cursor" in names and "next" in names:
        h.append("pagination")
    if "chunk" in low or "batch" in low:
        h.append("batching")
    if {"execute", "executemany", "query", "raw"} & calls or re.search(r"\bselect\b.+\bfrom\b", low):
        h.append("database query")
    if {"get", "post", "put", "delete", "request", "fetch", "urlopen"} & calls and any(w in low for w in ("http", "requests", "httpx", "fetch(", "url", "axios")):
        h.append("HTTP call")
    if is_async:
        h.append("async I/O")
    if {"gather", "create_task", "ThreadPoolExecutor", "submit", "Thread", "Pool", "all"} & calls and any(w in low for w in ("gather", "thread", "pool", "promise.all", "executor")):
        h.append("concurrency")
    if {"lock", "Lock", "acquire", "Semaphore"} & calls or "with lock" in low:
        h.append("locking")
    if "yield" in low and re.search(r"\byield\b", text):
        h.append("generator / streaming")
    return list(dict.fromkeys(h))


def _py_func(node, text: str, cls_name: str | None = None) -> dict:
    decos = [_name(d) for d in node.decorator_list]
    calls, names = set(), set()
    body_nodes = [x for st in node.body for x in ast.walk(st)] + list(ast.walk(node.args))
    for sub in body_nodes:
        if isinstance(sub, ast.Call):
            nm = _name(sub.func)
            if nm and len(nm) < 80 and "(" not in nm and "[" not in nm:
                segs = nm.split(".")
                calls.add(nm if len(segs) == 1 else ".".join(segs[-2:]))  # bare `f`, `self.f`, `obj.f`
        elif isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.arg):
            names.add(sub.arg)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
    end = getattr(node, "end_lineno", node.lineno)
    seg = "\n".join(text.splitlines()[min([d.lineno for d in node.decorator_list] + [node.lineno]) - 1:end])
    doc = (ast.get_docstring(node) or "").strip().split("\n")[0][:120]
    args = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    is_async = isinstance(node, ast.AsyncFunctionDef)
    f = {"name": node.name, "qual": f"{cls_name}.{node.name}" if cls_name else node.name, "cls": cls_name,
         "line": node.lineno, "start": min([d.lineno for d in node.decorator_list] + [node.lineno]), "end": end, "args": args[:12], "decorators": decos[:6], "async": is_async,
         "doc": doc, "calls": sorted(calls)[:80], "complexity": _complexity(node), "loc": end - node.lineno + 1,
         "returns": _name(node.returns) if node.returns else "",
         "refs": sorted(n for n in names if n[:1].isupper())[:30],
         "sql_refs": sorted({t for t in _SQL_REF.findall(seg) if t.lower() not in _SQL_KW})[:20],
         "hints": algorithm_hints(names, {c.split(".")[-1] for c in calls}, seg, node.name, is_async, decos)}
    routes = []
    for d in decos:
        m = _ROUTE_DECO.match(d)
        if m:
            meth = m.group(2).upper()
            if meth in ("ROUTE", "API_ROUTE"):
                mm = re.search(r"methods\s*=\s*\[([^\]]*)\]", m.group(4))
                meths = re.findall(r"['\"](\w+)['\"]", mm.group(1)) if mm else ["GET"]
            else:
                meths = ["WS" if meth == "WEBSOCKET" else meth]
            for x in meths:
                routes.append({"method": x.upper(), "path": m.group(3) or "/", "via": m.group(1)})
    if routes:
        f["_routes"] = routes
    return f


_JS_KW = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "new", "await", "import", "require",
          "super", "constructor", "else", "do", "try", "with", "yield", "delete", "void", "in", "of", "case", "throw"}
_JS_FN = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
    r"|^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:function\b[^(]*\(([^)]*)\)|\(([^)]*)\)\s*(?::[^=]+)?=>|([A-Za-z_$][\w$]*)\s*=>)"
    r"|^[ \t]+(?:public\s+|private\s+|protected\s+|static\s+|async\s+|readonly\s+)*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*(?::\s*[^{;]+)?\{", re.M)
_JS_CALL = re.compile(r"(?<![\w$.])((?:this\.)?[A-Za-z_$][\w$]*)\s*\(")
_JS_ROUTE = re.compile(r"""\b(app|router|server|api|routes|r)\.(get|post|put|patch|delete|all|head|options)\(\s*(['"`])([^'"`]+)\3\s*,\s*(?:[^,()]+,\s*)*?(?:async\s+)?([A-Za-z_$][\w$.]*)?""")
_NEXT_ROUTE = re.compile(r"^\s*export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", re.M)


def _js_body(text: str, start: int) -> tuple[int, int]:
    """(start, end) offsets of the brace-delimited body that starts at or after `start`; strings and
    comments are skipped roughly. An arrow function without braces ends at the end of its line."""
    i = text.find("{", start)
    nl = text.find("\n", start)
    if i < 0 or (nl >= 0 and i > nl and "=>" in text[start:nl] and not text[start:nl].rstrip().endswith("=>")):
        return start, nl if nl >= 0 else len(text)
    depth, j, n = 0, i, len(text)
    quote = None
    while j < n:
        ch = text[j]
        if quote:
            if ch == "\\":
                j += 1
            elif ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch == "/" and text[j:j + 2] == "//":
            j = text.find("\n", j)
            if j < 0:
                break
        elif ch == "/" and text[j:j + 2] == "/*":
            j = text.find("*/", j + 2)
            if j < 0:
                break
            j += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i, j + 1
        j += 1
    return i, n


def _js_functions(rel: str, text: str, out: dict) -> None:
    line_of = lambda pos: text.count("\n", 0, pos) + 1  # noqa: E731
    classes = [(text.count("\n", 0, m.start()) + 1, m.group(1)) for m in _JS_CLASS.finditer(text)]
    seen = set()
    for m in _JS_FN.finditer(text):
        name = m.group(1) or m.group(3) or m.group(7)
        if not name or name in _JS_KW:
            continue
        args = m.group(2) if m.group(1) else (m.group(4) or m.group(5) or m.group(6) or "") if m.group(3) else m.group(8)
        line = line_of(m.start())
        method = bool(m.group(7))
        cls = None
        if method:
            cls = next((c for ln, c in reversed(classes) if ln < line), None)
            if not cls:
                continue  # an indented call followed by a block, not a method
        a, b = _js_body(text, m.end())
        seg = text[m.start():b]
        calls = {c.replace("this.", "self.") for c in _JS_CALL.findall(seg) if c.split(".")[-1] not in _JS_KW and c != name} \
            | ({name} if re.search(rf"(?<![\w$.]){re.escape(name)}\s*\(", text[a:b]) else set())
        qual = f"{cls}.{name}" if cls else name
        if qual in seen:
            continue
        seen.add(qual)
        names = set(re.findall(r"[A-Za-z_$][\w$]*", seg))
        is_async = bool(re.search(r"\basync\b", text[max(0, m.start()):m.end()]))
        cx = 1 + len(re.findall(r"\b(?:if|for|while|case|catch)\b|&&|\|\||\?\?|\?(?=[^.:])", seg))
        out["functions"].append({
            "name": name, "qual": qual, "cls": cls, "line": line, "end": line_of(b), "async": is_async,
            "args": [x.strip().split(":")[0].split("=")[0].strip() for x in (args or "").split(",") if x.strip()][:12],
            "decorators": [], "doc": "", "calls": sorted(calls)[:80], "complexity": cx, "loc": line_of(b) - line + 1,
            "sql_refs": sorted({t for t in _SQL_REF.findall(seg) if t.lower() not in _SQL_KW})[:20],
            "returns": "", "hints": algorithm_hints(names, {c.split(".")[-1] for c in calls}, seg, name, is_async, [])})
    for m in _JS_ROUTE.finditer(text):
        out["routes"].append({"method": m.group(2).upper().replace("ALL", "ANY"), "path": m.group(4), "via": m.group(1),
                              "handler": (m.group(5) or "").split(".")[-1] or None, "line": line_of(m.start())})
    if re.search(r"(?:^|/)app/(?:.+/)?route\.(?:js|ts)$", rel):  # Next.js app router
        path = "/" + "/".join(p for p in rel.split("app/", 1)[1].split("/")[:-1] if not p.startswith("("))
        for m in _NEXT_ROUTE.finditer(text):
            out["routes"].append({"method": m.group(1), "path": path or "/", "via": "next", "handler": m.group(1), "line": line_of(m.start())})


def analyze_file(rel: str, text: str) -> dict | None:
    lang = CODE_EXT.get(os.path.splitext(rel)[1].lower())
    if not lang:
        return None
    rel = rel.replace(os.sep, "/")
    try:
        part = ANALYZERS[lang](rel, text)
    except Exception:  # an analyser bug must never stop tracking
        part = {"lang": lang, "id": rel, "loc": text.count("\n") + 1, "imports": [], "classes": [], "tables": [],
                "functions": [], "routes": [], "raw_imports": [], "error": True}
    part["file"], part["sha"] = rel, _sha(text)
    part["sql_tables"] = [t for t in part.get("sql_tables", []) if t.lower() not in _SQL_KW]
    return part


# ============================================================================ layers
LAYERS = ("interface", "service", "data", "integration", "ui", "core", "util", "config", "test")
LAYER_TITLES = {"interface": "Interface (API, CLI, handlers)", "service": "Services & domain logic", "data": "Data access & models",
                "integration": "Integrations & clients", "ui": "User interface", "core": "Core", "util": "Utilities",
                "config": "Configuration", "test": "Tests"}
_LAYER_WORDS = [
    ("test", r"(^|/)(tests?|spec|__tests__|e2e)(/|$)|(^|/)test_[^/]*$|_test\.\w+$|\.(spec|test)\.\w+$|(^|/)conftest\.py$"),
    ("ui", r"(^|/)(components?|pages|views|ui|frontend|client|app/\(.*\)|layouts|screens|widgets)(/|$)|\.(jsx|tsx|vue|svelte)$"),
    ("interface", r"(^|/)(api|routes?|routers?|controllers?|handlers?|endpoints?|cli|commands?|graphql|resolvers?|server|web)(/|$|\.)|(^|/)(main|app|server|cli|wsgi|asgi|manage)\.\w+$"),
    ("data", r"(^|/)(models?|db|database|repositor(y|ies)|schemas?|entities|migrations?|orm|dao|store|persistence|prisma)(/|$|\.)"),
    ("integration", r"(^|/)(clients?|integrations?|adapters?|gateways?|providers?|external|sdk|connectors?)(/|$|\.)"),
    ("service", r"(^|/)(services?|domain|core|logic|usecases?|use_cases|workers?|jobs?|tasks?|engine|pipelines?)(/|$|\.)"),
    ("config", r"(^|/)(config|settings|conf|env|constants)(/|$|\.)"),
    ("util", r"(^|/)(utils?|helpers?|lib|common|shared|tools)(/|$|\.)"),
]


def layer_of(rel: str, part: dict | None = None) -> str:
    low = rel.lower()
    for layer, pat in _LAYER_WORDS:
        if re.search(pat, low):
            return layer
    if part:
        if part.get("routes"):
            return "interface"
        if part.get("tables"):
            return "data"
    return "core"


# ============================================================================ linking into one model
_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


def link(parts: dict[str, dict]) -> dict:
    """Join per-file results into one model."""
    by_id, suffix = {}, {}
    for rel, p in parts.items():
        by_id[p["id"]] = rel
    for mid in sorted(by_id):
        segs = re.split(r"[./]", mid)
        sep = "/" if "/" in mid and parts[by_id[mid]]["lang"] == "js" else "."
        for i in range(len(segs)):
            suffix.setdefault(sep.join(segs[i:]), mid)
    own = {re.split(r"[./]", s_)[0] for s_ in suffix} | {os.path.basename(os.path.dirname(r)) for r in parts}
    modules, classes, tables, functions, routes = {}, {}, {}, {}, []
    for rel in sorted(parts):
        p = parts[rel]
        deps, ext = set(), set()
        for cands in p["imports"]:
            relative = cands[-1] == "."
            hit = next((suffix[c] for c in cands if c != "." and c in suffix), None)
            if hit and hit != p["id"]:
                deps.add(hit)
            elif not hit and not relative:
                top = cands[-1].split(".")[0] if p["lang"] == "python" else cands[-1]
                if top and top not in _STDLIB and top not in own:
                    ext.add(top)
        if p["lang"] in ("python", "js"):
            modules[p["id"]] = {"file": rel, "lang": p["lang"], "pkg": os.path.dirname(rel) or ".", "deps": sorted(deps),
                                "ext": sorted(ext), "loc": p["loc"], "sha": p["sha"], "error": bool(p.get("error")),
                                "layer": layer_of(rel, p), "functions": [], "classes": [c["name"] for c in p["classes"]],
                                "sql_tables": p.get("sql_tables", [])}
        for c in p["classes"]:
            classes[f'{p["id"]}:{c["name"]}'] = {**c, "module": p["id"], "file": rel}
        for t in p["tables"]:
            if t["name"] in tables:  # the same table in SQL and in an ORM model: keep the first, note the other
                if t.get("kind") == "firestore":
                    _fs.merge(tables[t["name"]], {**t, "file": rel}, rel)
                else:
                    tables[t["name"]].setdefault("also_in", []).append(rel)
            else:
                tables[t["name"]] = {**t, "file": rel}
        for f in p.get("functions", []):
            fid = f'{p["id"]}:{f["qual"]}'
            functions[fid] = {**f, "module": p["id"], "file": rel, "callees": [], "callers": []}
            if p["id"] in modules:
                modules[p["id"]]["functions"].append(f["qual"])
        for r in p.get("routes", []):
            routes.append({**r, "module": p["id"], "file": rel})

    # ---- call graph: resolve call names to project functions
    by_name: dict[str, list[str]] = {}
    for fid, f in functions.items():
        by_name.setdefault(f["name"], []).append(fid)
    mod_tail = {}
    for mid in modules:
        mod_tail.setdefault(re.split(r"[./]", mid)[-1], []).append(mid)
    alias_mod: dict[str, dict[str, str]] = {}   # module -> alias -> module id it names
    for rel, p in parts.items():
        for al, cands in (p.get("aliases") or {}).items():
            hit = next((suffix[c] for c in cands if c in suffix), None)
            if hit and hit in modules:
                alias_mod.setdefault(p["id"], {})[al] = hit
    cls_names = {c["name"]: k for k, c in classes.items()}
    for fid, f in functions.items():
        mod = f["module"]
        near = set(modules.get(mod, {}).get("deps", [])) | {mod}
        out = set()
        for c in f["calls"]:
            head, _, nm = c.rpartition(".")
            cands = by_name.get(nm, [])
            if not cands:
                continue
            fn = lambda x: functions[x]  # noqa: E731
            if head == "self" and f.get("cls"):          # self.method(): the same class
                pick = [x for x in cands if fn(x)["module"] == mod and fn(x).get("cls") == f["cls"]]
            elif head:                                    # obj.f(): a module's function, or a method in reach
                aliased = alias_mod.get(mod, {}).get(head)
                mods = [aliased] if aliased else [m for m in mod_tail.get(head, []) if m in near]
                pick = [x for x in cands if fn(x)["module"] in mods and not fn(x).get("cls")]
                if not pick and head not in cls_names:
                    meth = [x for x in cands if fn(x).get("cls") and fn(x)["module"] in near]
                    pick = meth if len(meth) == 1 else []
                elif not pick:
                    pick = [x for x in cands if fn(x).get("cls") == head]
            else:                                         # f(): same module first, then imported modules
                pick = [x for x in cands if fn(x)["module"] == mod and not fn(x).get("cls")] \
                    or [x for x in cands if fn(x)["module"] in near and not fn(x).get("cls")]
            for x in pick[:2]:
                if x != fid or nm == f["name"]:
                    out.add(x)
        f["callees"] = sorted(out)
    for fid, f in functions.items():
        for x in f["callees"]:
            if x != fid:
                functions[x]["callers"].append(fid)
    routes = _rjs.drop_shadowed(routes)
    for r in routes:
        h = r.get("handler")
        if h:
            r["fid"] = next((fid for fid in (f'{r["module"]}:{h}',) if fid in functions), None) \
                or next((x for x in by_name.get(h.split(".")[-1], []) if functions[x]["module"] in set(modules.get(r["module"], {}).get("deps", [])) | {r["module"]}), None)
    # ---- which functions touch which tables (by ORM class name or SQL text)
    tlow = {t.lower(): t for t in tables}
    cls_table = {c["name"]: c["table"] for c in classes.values() if c.get("table") in tables}
    for fid, f in functions.items():
        touched = set()
        for c in list(f["calls"]) + list(f.get("refs", [])):
            for part in c.split("."):
                if cls_table.get(part):
                    touched.add(cls_table[part])
        for t in f.get("sql_refs", []):
            if t.lower() in tlow:
                touched.add(tlow[t.lower()])
        touched |= {k for k in f.get("fs_refs", []) if k in tables}
        f["tables"] = sorted(touched)
    return {"modules": modules, "classes": classes, "tables": tables, "functions": functions, "routes": routes}


def _sig(kind: str, node: dict) -> str:
    if kind == "modules":
        return node["sha"]
    keys = {"classes": ("bases", "attrs", "methods"), "tables": ("columns", "ops"),
            "functions": ("args", "calls", "complexity", "loc", "decorators")}[kind]
    return json.dumps([node.get(k) for k in keys], sort_keys=True)


def diff_models(prev: dict | None, cur: dict) -> dict:
    """node id -> 'new' | 'changed' | 'removed' for each node kind, relative to an earlier step."""
    marks = {"modules": {}, "classes": {}, "tables": {}, "functions": {}}
    if prev is None:
        return marks
    for kind in marks:
        a, b = prev.get(kind, {}), cur.get(kind, {})
        for k in b:
            if k not in a:
                marks[kind][k] = "new"
            elif _sig(kind, a[k]) != _sig(kind, b[k]):
                marks[kind][k] = "changed"
        for k in a:
            if k not in b:
                marks[kind][k] = "removed"
    return marks


def find_symbols(model: dict, query: str, limit: int = 20) -> list[dict]:
    """Symbols whose name matches: exact name first, then prefix, then substring. No source code."""
    q = query.strip().lower()
    if not q:
        return []
    rows = []
    for kind in ("functions", "classes", "tables", "modules"):
        for key, n in model.get(kind, {}).items():
            name = (n.get("qual") or n.get("name") or key).lower() if kind != "modules" else key.lower()
            short = name.split(".")[-1].split(":")[-1]
            score = 0 if q in (name, short) else 1 if short.startswith(q) or name.startswith(q) else 2 if q in name or q in key.lower() else None
            if score is not None:
                rows.append((score, kind, key, n))
    rows.sort(key=lambda r: (r[0], len(r[2])))
    return [{"kind": k[:-1] if k != "classes" else "class", "id": key, "file": n.get("file"), "line": n.get("line")} for _, k, key, n in rows[:limit]]


def resolve(model: dict, ref: str) -> tuple[str, str, dict] | None:
    """A symbol reference -> (kind, id, node). Accepts a full id (module:qual), a qualified name
    (Class.method), a plain name if it is unique, a table name, a module id or a file path."""
    ref = (ref or "").strip()
    if not ref:
        return None
    for kind in ("functions", "classes", "tables", "modules"):
        if ref in model.get(kind, {}):
            return kind, ref, model[kind][ref]
    for kind, nodes in (("modules", model.get("modules", {})),):
        for k, n in nodes.items():
            if n["file"] == ref:
                return kind, k, n
    hits = []
    for kind in ("functions", "classes"):
        for k, n in model.get(kind, {}).items():
            qual = n.get("qual") or n.get("name")
            if ref in (qual, n.get("name")) or k.endswith(":" + ref) or ref.endswith("." + (qual or "")) and "." in ref:
                hits.append((kind, k, n))
    if len(hits) == 1:
        return hits[0]
    exact = [h for h in hits if (h[2].get("qual") or h[2].get("name")) == ref]
    return exact[0] if len(exact) == 1 else None
