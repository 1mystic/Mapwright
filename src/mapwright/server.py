"""Local daemon on 127.0.0.1: the API behind the UI, and a watcher that keeps tracked projects current.

Every /v1 route needs the local token (Bearer). Requests must carry a Host of 127.0.0.1 or
localhost on our port (DNS rebinding), cross-origin requests are refused, and POST bodies must be
JSON. File contents are served only for tracked files, never for secret-looking ones, and pass
through redaction.
"""

from __future__ import annotations

import difflib
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, brief, config, connect, render
from . import analyze as A
from . import concepts as C
from . import flow as F
from .redact import redact
from .track import by_key, open_project

UI = Path(__file__).parent / "ui"
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/app.css": "app.css", "/icons.svg": "icons.svg",
          "/mark.svg": "mark.svg", "/vendor/mermaid.min.js": "vendor/mermaid.min.js"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self' data:; frame-ancestors 'self' vscode-webview: http://127.0.0.1:* http://localhost:*; base-uri 'none'; form-action 'none'")


def file_rows(now: dict, base: dict | None, cache: dict | None = None) -> list[dict]:
    rows = []
    for rel in sorted(now):
        part = ((cache or {}).get(rel) or {}).get("part") or {}
        st = None if base is None else "A" if rel not in base else "M" if base[rel] != now[rel] else None
        rows.append({"path": rel, "status": st, "layer": A.layer_of(rel, part) if part else None})
    if base is not None:
        rows += [{"path": rel, "status": "D", "layer": None} for rel in sorted(set(base) - set(now))]
    return rows


class Daemon:
    def __init__(self, port: int | None = None, watch: bool = True):
        self.token = config.token()
        self.port = port or config.port()
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.origins = {f"http://{h}" for h in self.hosts}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), self._handler())
        self.httpd.daemon_threads = True
        self.stopping = threading.Event()
        self.watch = watch
        self.errors: list[str] = []
        self.started = time.time()

    # ------------------------------------------------------------------ watcher
    def _watch_loop(self) -> None:
        while not self.stopping.is_set():
            interval = max(0.5, float(config.settings()["watch_interval"]))
            for key, entry in list(config.projects().items()):
                if self.stopping.is_set():
                    break
                if not os.path.isdir(entry.get("root", "")):
                    continue
                try:
                    p = open_project(entry["root"])
                    p.refresh()
                    p.maybe_auto_step()
                except Exception as e:  # one broken project must not stop the others
                    self.errors = (self.errors + [f"{key}: {type(e).__name__}: {e}"])[-20:]
            self.stopping.wait(interval)

    def start(self) -> "Daemon":
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="mw-http").start()
        if self.watch:
            threading.Thread(target=self._watch_loop, daemon=True, name="mw-watch").start()
        return self

    def serve_forever(self) -> None:
        if self.watch:
            threading.Thread(target=self._watch_loop, daemon=True, name="mw-watch").start()
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.stopping.set()
        self.httpd.shutdown()
        self.httpd.server_close()

    # ------------------------------------------------------------------ API
    def project_or_404(self, key: str):
        p = by_key(key)
        if p is None:
            raise LookupError("unknown project")
        return p.ensure()

    def diagram(self, p, kind: str, q: dict) -> dict:
        step = q.get("step", "live")
        steps = p.steps()
        if step == "live":
            model, files_now = p.model, p.index
            base_n = steps[-1]["n"] if steps else None
        else:
            data = p.load_step(int(step))
            if not data:
                raise LookupError("no such step")
            model, files_now = data["model"], data["files"]
            base_n = int(step) - 1 if int(step) > 0 else None
        if q.get("base") not in (None, "", "auto"):
            base_n = None if q["base"] == "none" else int(q["base"])
        base = p.load_step(base_n) if base_n is not None else None
        marks = A.diff_models(base["model"] if base else None, model)
        focus = q.get("focus") or None
        if kind == "architecture":
            out = render.architecture(model, marks, base["model"] if base else None, show_tests=q.get("tests") == "1")
        elif kind == "files":
            out = render.files(file_rows(files_now, base["files"] if base else None, p.cache))
        elif kind == "classes":
            out = render.classes(model, marks, base["model"] if base else None)
        elif kind == "data":
            out = render.erd(model, marks, base["model"] if base else None)
        elif kind == "cloud":
            out = render.cloud(model.get("infra") or {"nodes": [], "edges": []})
        elif kind == "processes":
            out = render.processes(model, focus)
        elif kind == "calls":
            out = render.calls(model, marks, focus)
        elif kind == "concepts":
            v = p.verify()
            out = render.concept_map(model, model.get("concepts") or {}, v["claims"])
        else:
            raise LookupError("unknown diagram")
        delta = {k: dict(__import__("collections").Counter(v.values())) for k, v in marks.items() if v}
        return {**out, "kind": kind, "step": step, "base": base_n, "delta": delta}

    def flow(self, p, fid: str, step: str) -> dict:
        model = p.model if step == "live" else (p.load_step(int(step)) or {}).get("model")
        if not model or fid not in model["functions"]:
            raise LookupError("unknown function")
        f = model["functions"][fid]
        text = p.text(f["file"], None if step == "live" else int(step))
        if text is None:
            raise LookupError("file not readable")
        out = F.python_flow(text, f["line"]) if f["file"].endswith(".py") else F.js_outline(text, f["line"], f["end"])
        if out is None:
            out = F.js_outline(text, f["line"], f["end"])
        out.update({"fid": fid, "function": {k: f.get(k) for k in ("qual", "file", "line", "end", "args", "complexity", "hints",
                                                                  "callees", "callers", "tables", "doc", "async", "loc")}})
        return out

    def file(self, p, path: str, step: str) -> dict:
        idx = p.index if step == "live" else p.step_files(int(step))
        if path not in idx:
            raise LookupError("not a tracked file")
        if A._secretish(path):
            return {"path": path, "secret": True, "text": None}
        text = p.blob(idx[path])
        if text is None:
            return {"path": path, "binary": True, "text": None}
        if config.settings()["redact"]:
            text = redact(text)
        part = (p.cache.get(path) or {}).get("part") or {}
        return {"path": path, "text": text, "lang": part.get("lang") or os.path.splitext(path)[1].lstrip("."),
                "symbols": [{"qual": f["qual"], "line": f["line"], "end": f["end"], "kind": "function", "complexity": f["complexity"],
                             "fid": f"{part['id']}:{f['qual']}"} for f in part.get("functions", [])]
                + [{"qual": c["name"], "line": c["line"], "end": c.get("end"), "kind": "class"} for c in part.get("classes", [])]}

    def diff(self, p, path: str, a: str, b: str) -> dict:
        def idx(s):
            return p.index if s == "live" else p.step_files(int(s))
        ta, tb = p.blob(idx(a).get(path)), p.blob(idx(b).get(path))
        if A._secretish(path):
            return {"path": path, "secret": True, "diff": ""}
        lines = list(difflib.unified_diff((ta or "").splitlines(), (tb or "").splitlines(), f"a/{path}", f"b/{path}", n=3, lineterm=""))
        text = "\n".join(lines[:4000])
        return {"path": path, "diff": redact(text) if config.settings()["redact"] else text}

    def _handler(self):
        d = self

        class H(BaseHTTPRequestHandler):
            server_version = f"mapwright/{__version__}"

            def log_message(self, *a):
                pass

            def _send(self, code: int, body, ctype: str = "application/json") -> None:
                raw = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                if ctype.startswith("text/html"):
                    self.send_header("Content-Security-Policy", CSP)
                self.end_headers()
                self.wfile.write(raw)

            def _guard(self) -> bool:
                if self.headers.get("Host") not in d.hosts:
                    self._send(403, {"error": "bad host"})
                    return False
                origin = self.headers.get("Origin")
                if origin and origin not in d.origins:
                    self._send(403, {"error": "cross-origin requests are not accepted"})
                    return False
                auth = self.headers.get("Authorization", "")
                if not (auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], d.token)):
                    self._send(401, {"error": "unauthorized"})
                    return False
                return True

            def _body(self) -> dict:
                n = int(self.headers.get("Content-Length") or 0)
                if n > 1_000_000:
                    raise ValueError("body too large")
                data = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("expected a JSON object")
                return data

            def do_GET(self):
                u = urlparse(self.path)
                if u.path in STATIC:
                    if self.headers.get("Host") not in d.hosts:
                        return self._send(403, {"error": "bad host"})
                    f = UI / STATIC[u.path]
                    try:
                        return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
                    except OSError:
                        return self._send(404, {"error": "not found"})
                if not u.path.startswith("/v1/"):
                    return self._send(404, {"error": "not found"})
                if not self._guard():
                    return
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                parts = [unquote(x) for x in u.path.strip("/").split("/")]
                try:
                    if u.path == "/v1/ping":
                        return self._send(200, {"ok": True, "version": __version__, "uptime": time.time() - d.started, "home": str(config.home())})
                    if u.path == "/v1/projects":
                        rows = []
                        for key, entry in config.projects().items():
                            exists = os.path.isdir(entry["root"])
                            row = {"key": key, "root": entry["root"], "name": os.path.basename(entry["root"]), "exists": exists}
                            if exists:
                                p = open_project(entry["root"])
                                steps = p.steps()
                                row.update(steps=len(steps), last=steps[-1]["ts"] if steps else None, version=p.version)
                            rows.append(row)
                        return self._send(200, {"projects": sorted(rows, key=lambda r: -(r.get("last") or 0)), "errors": d.errors[-5:]})
                    if u.path == "/v1/settings":
                        return self._send(200, {"settings": config.settings(), "defaults": config.DEFAULTS, "home": str(config.home()),
                                                "port": d.port, "version": __version__})
                    if u.path == "/v1/catalog":
                        return self._send(200, {"concepts": C.catalog(), "groups": C.GROUPS, "diagrams": render.KINDS})
                    if u.path == "/v1/integrations":
                        p = by_key(q.get("key", "")) if q.get("key") else None
                        root = p.root if p else None
                        return self._send(200, {"targets": connect.status(root), "root": root})
                    if len(parts) >= 4 and parts[:2] == ["v1", "p"]:
                        p = d.project_or_404(parts[2])
                        what = parts[3]
                        if what == "version":
                            return self._send(200, {"version": p.version, "steps": len(p.steps()), "journal": len(p.journal())})
                        if what == "state":
                            return self._send(200, p.state())
                        if what == "diagram" and len(parts) == 5:
                            return self._send(200, d.diagram(p, parts[4], q))
                        if what == "flow":
                            return self._send(200, d.flow(p, q.get("fid", ""), q.get("step", "live")))
                        if what == "file":
                            return self._send(200, d.file(p, q.get("path", ""), q.get("step", "live")))
                        if what == "diff":
                            return self._send(200, d.diff(p, q.get("path", ""), q.get("from", "live"), q.get("to", "live")))
                        if what == "symbol":
                            hit = A.resolve(p.model, q.get("ref", ""))
                            node = None
                            if hit:
                                node = {k: v for k, v in hit[2].items() if k not in ("sha",)}
                                node["kind"], node["id"] = hit[0][:-1] if hit[0] != "classes" else "class", hit[1]
                            return self._send(200, {"card": brief.symbol_card(p, q.get("ref", "")), "node": node})
                        if what == "find":
                            return self._send(200, {"results": A.find_symbols(p.model, q.get("q", ""), 30)})
                        if what == "brief":
                            b = int(q.get("budget") or config.settings()["brief_budget"])
                            text = brief.project_brief(p, max(400, min(b, 20000)), q.get("focus") or None)
                            return self._send(200, {"text": text, "chars": len(text), "tokens": round(len(text) / 4)})
                        if what == "model":
                            step = q.get("step", "live")
                            model = p.model if step == "live" else (p.load_step(int(step)) or {}).get("model")
                            return self._send(200, model or {})
                    return self._send(404, {"error": "not found"})
                except LookupError as e:
                    return self._send(404, {"error": str(e)})
                except (ValueError, TypeError) as e:
                    return self._send(400, {"error": str(e)})

            def do_POST(self):
                u = urlparse(self.path)
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self._send(415, {"error": "json only"})
                if not self._guard():
                    return
                parts = [unquote(x) for x in u.path.strip("/").split("/")]
                try:
                    body = self._body()
                    if u.path == "/v1/projects":
                        root = os.path.realpath(os.path.expanduser(str(body.get("root", ""))))
                        if not os.path.isdir(root) or root in (os.path.realpath(os.path.expanduser("~")), "/"):
                            return self._send(400, {"error": "choose a project folder (not your home directory)"})
                        p = open_project(root)
                        p.refresh()
                        return self._send(200, {"key": p.key, "root": p.root})
                    if u.path == "/v1/settings":
                        return self._send(200, {"settings": config.save_settings(body)})
                    if u.path in ("/v1/connect", "/v1/disconnect"):
                        p = by_key(str(body.get("key", "")))
                        root = p.root if p else None
                        if not root and body.get("scope", "project") == "project":
                            return self._send(400, {"error": "pick a project first"})
                        fn = connect.install if u.path == "/v1/connect" else connect.uninstall
                        files = fn(str(body.get("target", "")), str(body.get("scope", "project")), root)
                        return self._send(200, {"ok": True, "files": files, "targets": connect.status(root)})
                    if u.path == "/v1/agents-md":
                        p = d.project_or_404(str(body.get("key", "")))
                        name = body.get("file", "AGENTS.md")
                        if name not in ("AGENTS.md", "CLAUDE.md", ".cursorrules", "GEMINI.md"):
                            return self._send(400, {"error": "unsupported file"})
                        return self._send(200, {"path": connect.write_agents_md(p.root, name)})
                    if u.path == "/v1/shutdown":
                        self._send(200, {"ok": True})
                        threading.Thread(target=d.shutdown, daemon=True).start()
                        return
                    if len(parts) == 4 and parts[:2] == ["v1", "p"]:
                        p = d.project_or_404(parts[2])
                        what = parts[3]
                        if what == "step":
                            data = p.step(str(body.get("title", "")), str(body.get("intent", "")), source="user")
                            return self._send(200, {"receipt": brief.step_receipt(data), "n": data["n"]})
                        if what == "todo":
                            act = body.get("action")
                            if act == "add":
                                return self._send(200, p.todo_add(str(body.get("text", "")), by="user"))
                            if act == "done":
                                return self._send(200, p.todo_done(str(body.get("id", "")), str(body.get("evidence", ""))))
                            if act == "drop":
                                p.todo_drop(str(body.get("id", "")))
                                return self._send(200, {"ok": True})
                            return self._send(400, {"error": "action must be add, done or drop"})
                        if what == "note":
                            return self._send(200, p.note(str(body.get("symbol", "")), str(body.get("role", ""))))
                        if what == "forget":
                            return self._send(200, {"ok": config.unregister(p.key)})
                    return self._send(404, {"error": "not found"})
                except LookupError as e:
                    return self._send(404, {"error": str(e)})
                except (ValueError, TypeError, OSError) as e:
                    return self._send(400, {"error": str(e)})

        return H
