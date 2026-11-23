"""The project store: file versions, steps, annotations and their verification.

One directory per project under ~/.mapwright/projects/<key>/:

    journal.jsonl     append-only log: prompts, tool calls, steps, todos, claims, notes, links
    steps/NNNN.json.gz    each step: the file index (path -> content hash), the model, what changed
    blobs/ab/<sha>.gz     every version of every tracked text file, stored once by hash
    cache.json.gz     per-file analysis results, so a new process starts warm
    meta.json         root, last change time

Several processes share it (the daemon, the MCP server an agent runs, hook calls, the CLI), so
writes take a file lock. Analysis never trusts the agent: what changed is computed from the
files, and every claim the agent makes is checked against the code and marked verified or not.
"""

from __future__ import annotations

import contextlib
import difflib
import gzip
import hashlib
import json
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path

from . import analyze as A
from . import concepts as C
from . import config, infra, noise, titles
from . import ignore as ignore_mod
from .redact import redact

try:
    import fcntl
except ImportError:  # Windows: in-process locking only
    fcntl = None

SCHEMA = 6  # bump when analysis output changes, so cached per-file results are rebuilt
_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_LOCKS: dict[str, threading.RLock] = {}
COALESCE_SECONDS = 2.0       # auto steps closer together than this are merged (the later turn end picks up the rest)
SESSION_STALE_SECONDS = 600  # a session with no event for this long is not "in a turn" any more
MAX_DEFER_SECONDS = 300      # how long a finished turn waits for other sessions still working
JOURNAL_CAP_BYTES = 20 * 1024 * 1024  # past this, hook events (prompt/tool/turn_end) stop being journaled
MAX_TOOL_EVENTS_PER_STEP = 500


def project_key(root: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", os.path.basename(root.rstrip("/")) or "project").strip("-.")[:40] or "project"
    return f"{slug}-{hashlib.sha1(root.encode()).hexdigest()[:8]}"


def _gz_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with gzip.open(tmp, "wb", compresslevel=5) as fh:
        fh.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _gz_read(path: Path) -> bytes | None:
    try:
        with gzip.open(path, "rb") as fh:
            return fh.read()
    except (OSError, EOFError):
        return None


_TITLE_CHECKS = [  # words in a step title -> what must have changed for the title to be plausible
    (r"\btests?\b|\bspecs?\b", "test", "a test file"),
    (r"\bmigrations?\b", "migration", "a migration"),
    (r"\b(endpoint|route|api)s?\b", "route", "an HTTP route"),
    (r"\b(schema|table|column|model)s?\b", "data", "a table or model"),
    (r"\b(docs?|readme|documentation)\b", "docs", "a documentation file"),
    (r"\b(docker|compose|terraform|deploy|infra|ci)\b", "infra", "an infrastructure file"),
]


class Project:
    def __init__(self, root: str):
        self.root = os.path.realpath(A.find_root(os.path.abspath(root)))
        self.key = project_key(self.root)
        self.dir = config.home() / "projects" / self.key
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.name = os.path.basename(self.root) or self.root
        self.cache: dict[str, dict] = {}
        self.index: dict[str, str] = {}
        self.model: dict | None = None
        self.concepts: dict = {}
        self.infra: dict = {"nodes": [], "edges": []}
        self.truncated = False
        self.truncated_info: dict | None = None
        self._journal_cache: tuple[int, list[dict]] = (-1, [])
        self._lock = _LOCKS.setdefault(self.key, threading.RLock())
        self._held = 0
        self._step_cache: dict[int, dict] = {}
        self._rechecked: dict[int, str] = {}
        self.version = 0
        meta = config.read_json(self.dir / "meta.json", {})
        if not meta:
            config.write_json(self.dir / "meta.json", {"schema": SCHEMA, "root": self.root, "key": self.key, "created": time.time()})
        self._load_cache()
        config.register(self.key, self.root)

    # ------------------------------------------------------------------ storage helpers
    @contextlib.contextmanager
    def locked(self):
        """Exclusive across threads (RLock) and processes (flock). Re-entrant: only the outermost
        level takes the file lock, since a second flock on a new handle would wait for itself."""
        with self._lock:
            fh = open(self.dir / "lock", "a") if fcntl and self._held == 0 else None
            self._held += 1
            try:
                if fh:
                    fcntl.flock(fh, fcntl.LOCK_EX)
                yield
            finally:
                self._held -= 1
                if fh:
                    fcntl.flock(fh, fcntl.LOCK_UN)
                    fh.close()

    def _blob_path(self, sha: str) -> Path:
        return self.dir / "blobs" / sha[:2] / f"{sha}.gz"

    def put_blob(self, sha: str, text: str) -> None:
        p = self._blob_path(sha)
        if not p.exists():
            _gz_write(p, text.encode("utf-8", "replace"))

    def blob(self, sha: str | None) -> str | None:
        if not sha or sha.startswith("secret:") or not re.match(r"^[0-9a-f]{16}$", sha):
            return None
        raw = _gz_read(self._blob_path(sha))
        return raw.decode("utf-8", "replace") if raw is not None else None

    def _load_cache(self) -> None:
        raw = _gz_read(self.dir / "cache.json.gz")
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        if data.get("schema") == SCHEMA:
            self.cache = data.get("files", {})

    def _save_cache(self) -> None:
        _gz_write(self.dir / "cache.json.gz", json.dumps({"schema": SCHEMA, "files": self.cache}, separators=(",", ":")).encode())

    def journal(self) -> list[dict]:
        p = self.dir / "journal.jsonl"
        try:
            size = p.stat().st_size
        except OSError:
            return []
        if size == self._journal_cache[0]:
            return self._journal_cache[1]
        out = []
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and "t" in ev:
                    out.append(ev)
        self._journal_cache = (size, out)
        return out

    def append(self, ev: dict) -> dict:
        with self.locked():
            evs = self.journal()
            ev = {"id": (evs[-1]["id"] + 1) if evs else 1, "ts": time.time(), **ev}
            fd = os.open(self.dir / "journal.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, separators=(",", ":")) + "\n")
            self.version += 1
            return ev

    # ------------------------------------------------------------------ scanning & analysis
    def refresh(self) -> list[str]:
        """Re-read whatever changed on disk. Returns the paths whose content changed."""
        with self.locked():
            st = config.settings()
            matcher = ignore_mod.Matcher(self.root, st.get("ignore") or [], st.get("respect_gitignore", True))
            info: dict = {}
            stats, self.truncated = A.scan(self.root, matcher, st.get("max_files"), info)
            self.truncated_info = info if self.truncated else None
            changed = []
            new_cache = {}
            for rel, sig in stats.items():
                old = self.cache.get(rel)
                if old and tuple(old["stat"]) == tuple(sig):
                    new_cache[rel] = old
                    continue
                entry = self._analyze(rel, sig)
                if not old or old["sha"] != entry["sha"]:
                    changed.append(rel)
                new_cache[rel] = entry
            removed = [r for r in self.cache if r not in stats]
            changed += removed
            if changed or self.model is None:
                self.cache = new_cache
                self.index = {r: e["sha"] for r, e in self.cache.items()}
                self._build()
                if changed:
                    self._save_cache()
                    meta = config.read_json(self.dir / "meta.json", {})
                    meta["last_change"] = time.time()
                    config.write_json(self.dir / "meta.json", meta)
                    self.version += 1
            if not self.steps():
                self._snapshot("baseline (before tracking started)", "", "baseline")
            return changed

    def _analyze(self, rel: str, sig) -> dict:
        if A._secretish(rel):
            return {"stat": list(sig), "sha": f"secret:{sig[0]}:{sig[1]}", "part": None, "concepts": {}, "secret": True}
        text = A.read_text(self.root, rel)
        if text is None:
            return {"stat": list(sig), "sha": f"secret:{sig[0]}:{sig[1]}", "part": None, "concepts": {}, "binary": True}
        sha = A._sha(text)
        self.put_blob(sha, text)
        part = A.analyze_file(rel, text) if os.path.splitext(rel)[1].lower() in A.CODE_EXT else None
        concepts = C.detect_file(rel, text, part) if part else {}
        return {"stat": list(sig), "sha": sha, "part": part, "concepts": concepts, "lines": text.count("\n") + 1}

    def _build(self) -> None:
        parts = {r: e["part"] for r, e in self.cache.items() if e.get("part")}
        self.model = A.link(parts)
        agg: dict[str, list[dict]] = {}
        for rel, e in sorted(self.cache.items()):
            for cid, evs in (e.get("concepts") or {}).items():
                for ev in evs:
                    agg.setdefault(cid, []).append({"file": rel, **ev})
        # a mechanism counts when source code shows it; evidence only from tests/scripts/examples goes to model["aux"]
        src = {cid: [e for e in evs if A.file_scope(e["file"]) == "source"] for cid, evs in agg.items()}
        self.concepts = {cid: (src[cid] + [e for e in evs if e not in src[cid]])[:12] for cid, evs in agg.items() if src[cid]}
        aux_only = {cid: [{"file": e["file"], "line": e["line"], "symbol": e["symbol"], "scope": A.file_scope(e["file"])} for e in evs[:6]]
                    for cid, evs in agg.items() if not src[cid]}
        self.infra = infra.detect(self.root, self.index, self.text, self.model["modules"])
        self.model["concepts"] = {cid: [{"file": e["file"], "line": e["line"], "symbol": e["symbol"]} for e in evs[:6]]
                                  for cid, evs in self.concepts.items()}
        self.model["infra"] = self.infra
        if aux_only:
            self.model.setdefault("aux", {})["concepts"] = aux_only

    def ensure(self) -> "Project":
        if self.model is None:
            self.refresh()
        return self

    def text(self, rel: str, step: int | None = None) -> str | None:
        """Text of a tracked file, now or at a step. Secret-looking files are never returned."""
        if A._secretish(rel):
            return None
        idx = self.index if step is None else self.step_files(step)
        return self.blob(idx.get(rel))

    # ------------------------------------------------------------------ steps
    def steps(self) -> list[dict]:
        return [e for e in self.journal() if e["t"] == "step"]

    def load_step(self, n: int) -> dict | None:
        if n in self._step_cache:
            return self._step_cache[n]
        raw = _gz_read(self.dir / "steps" / f"{n:04d}.json.gz")
        if raw is None:
            return None
        data = json.loads(raw)
        if len(self._step_cache) > 6:
            self._step_cache.pop(next(iter(self._step_cache)))
        self._step_cache[n] = data
        return data

    def step_files(self, n: int) -> dict:
        s = self.load_step(n)
        return s["files"] if s else {}

    def changes_between(self, a: dict, b: dict, counts: bool = True) -> list[dict]:
        out = []
        for rel in sorted(set(a) | set(b)):
            if a.get(rel) == b.get(rel):
                continue
            kind = "added" if rel not in a else "deleted" if rel not in b else "modified"
            ch = {"path": rel, "kind": kind}
            if counts:
                ta, tb = self.blob(a.get(rel)), self.blob(b.get(rel))
                if ta is None and tb is None:
                    ch["note"] = "secret-looking or binary: content not read"
                else:
                    sm = difflib.SequenceMatcher(None, (ta or "").splitlines(), (tb or "").splitlines(), autojunk=False)
                    add = rem = 0
                    for op, i1, i2, j1, j2 in sm.get_opcodes():
                        if op in ("replace", "delete"):
                            rem += i2 - i1
                        if op in ("replace", "insert"):
                            add += j2 - j1
                    ch["added"], ch["removed"] = add, rem
            out.append(ch)
        return out

    def pending(self, counts: bool = True) -> list[dict]:
        steps = self.steps()
        last = self.step_files(steps[-1]["n"]) if steps else {}
        return self.changes_between(last, self.index, counts)

    def _title_check(self, title: str, changes: list[dict], marks: dict) -> str:
        paths = [c["path"] for c in changes]
        low = title.lower()
        for pat, what, words in _TITLE_CHECKS:
            if not re.search(pat, low):
                continue
            ok = {
                "test": any(A.layer_of(p) == "test" for p in paths),
                "migration": any("migration" in p.lower() or "alembic" in p.lower() for p in paths),
                "route": any(r["file"] in paths for r in (self.model or {}).get("routes", [])),
                "data": bool(marks.get("tables")) or any(A.layer_of(p) == "data" or p.endswith((".sql", ".prisma")) for p in paths),
                "docs": any(p.lower().endswith((".md", ".rst", ".txt")) or p.lower().startswith("docs/") for p in paths),
                "infra": any(re.search(r"docker|compose|\.tf$|\.github/|k8s|helm|deploy", p.lower()) for p in paths),
            }[what]
            if not ok:
                return f"title mentions {words}, but no such file changed in this step"
        return "ok"

    def _model_at(self, files: dict) -> dict:
        parts = {}
        for rel, sha in files.items():
            if os.path.splitext(rel)[1].lower() in A.CODE_EXT:
                cached = self.cache.get(rel)
                if cached and cached.get("sha") == sha and cached.get("part"):
                    parts[rel] = cached["part"]
                else:
                    text = self.blob(sha)
                    if text is not None:
                        parts[rel] = A.analyze_file(rel, text)
        return A.link({k: v for k, v in parts.items() if v})

    def title_check(self, step: dict) -> str:
        """A stored title warning, re-checked with the current analysis (which may have learned to see
        what it missed then, e.g. tables created in SQL strings). Cached per process."""
        stored = step.get("title_check", "ok")
        if stored == "ok" or step["n"] == 0:
            return stored
        if step["n"] not in self._rechecked:
            data, prev = self.load_step(step["n"]), self.load_step(step["n"] - 1)
            if not data or not prev:
                self._rechecked[step["n"]] = stored
            else:
                saved = self.model
                try:
                    now_model = self._model_at(data["files"])
                    self.model = now_model  # _title_check reads routes from self.model
                    marks = A.diff_models(self._model_at(prev["files"]), now_model)
                    self._rechecked[step["n"]] = self._title_check(step["title"], data["changes"], marks)
                finally:
                    self.model = saved
        return self._rechecked[step["n"]]

    def _snapshot(self, title: str, intent: str, source: str, prompt: str | None = None) -> dict:
        steps = self.steps()
        n = (steps[-1]["n"] + 1) if steps else 0
        prev = self.load_step(steps[-1]["n"]) if steps else None
        all_changes = self.changes_between(prev["files"] if prev else {}, self.index) if prev else []
        real, noisy = noise.split(all_changes)
        changes = real + noisy  # noisy ones stay tracked, flagged with `noise`
        marks = A.diff_models(prev["model"] if prev else None, self.model)
        delta = {k: dict(Counter(v.values())) for k, v in marks.items() if v}
        check = self._title_check(title, real, marks) if source == "agent" else "ok"
        summary = {"files": len(real), "added": sum(c.get("added", 0) for c in real),
                   "removed": sum(c.get("removed", 0) for c in real), "delta": delta,
                   "modules": len(self.model["modules"]), "functions": len(self.model["functions"]),
                   "classes": len(self.model["classes"]), "tables": len(self.model["tables"]), "routes": len(self.model["routes"])}
        if noisy:
            summary["noise"] = len(noisy)
        evs = self.journal()
        since = steps[-1]["id"] if steps else 0
        tools = Counter(e.get("tool") for e in evs if e["id"] > since and e["t"] == "tool")
        if prompt is None:
            prompt = next((e.get("text") for e in reversed(evs) if e["id"] > since and e["t"] == "prompt"), "")
        data = {"n": n, "title": title, "intent": intent, "source": source, "ts": time.time(), "files": dict(self.index),
                "model": self.model, "changes": changes, "summary": summary, "marks": marks, "title_check": check,
                "tools": dict(tools), "prompt": prompt}
        _gz_write(self.dir / "steps" / f"{n:04d}.json.gz", json.dumps(data, separators=(",", ":")).encode())
        self._step_cache[n] = data
        keep = ("path", "kind", "added", "removed", "note")
        logged = [{k: c[k] for k in keep if k in c} for c in real][:200]
        if noisy:
            logged.append({"path": noise.collapse_line(noisy), "kind": "noise", "noise": len(noisy)})
        self.append({"t": "step", "n": n, "title": title[:120], "intent": intent[:300], "source": source,
                     "summary": summary, "title_check": check, "prompt": prompt[:200], "changes": logged})
        return data

    def step(self, title: str, intent: str = "", source: str = "agent") -> dict:
        """Close a step: snapshot the files and the model as they are now. The agent supplies only the
        title; the changed files and the design delta are computed, not taken from the agent."""
        title = " ".join((title or "").split())[:120] or "untitled step"
        with self.locked():
            self.refresh()
            data = self._snapshot(title, " ".join((intent or "").split())[:300], source)
        return data

    def _sessions(self, evs: list[dict], since: int) -> dict[str, dict]:
        """Per session since the last step: id/ts of its last activity (prompt or tool) and last turn end."""
        out: dict[str, dict] = {}
        for e in evs:
            if e["id"] <= since or e["t"] not in ("prompt", "tool", "turn_end"):
                continue
            st = out.setdefault(str(e.get("session") or ""), {"act": 0, "act_ts": 0.0, "end": 0, "end_ts": 0.0})
            if e["t"] == "turn_end":
                st["end"], st["end_ts"] = e["id"], e["ts"]
            else:
                st["act"], st["act_ts"] = e["id"], e["ts"]
        return out

    def _turn_prompt(self, evs: list[dict], since: int, session: str | None) -> str:
        """The prompt that drove this turn: the first substantive one from the ending session (any session
        if it has none), not simply the latest one, which is often 'ok' or a follow-up."""
        prompts = [e for e in evs if e["id"] > since and e["t"] == "prompt" and e.get("text")]
        mine = [e for e in prompts if session is None or str(e.get("session") or "") == session] or prompts
        for e in mine:
            if titles.prompt_title(e["text"]):
                return e["text"]
        return mine[0]["text"] if mine else ""

    def maybe_auto_step(self, session: str | None = None, final: bool = False) -> dict | None:
        """Close a step by itself when the settings say so and something meaningful changed.

        Never creates an empty step, nor one for noise-only changes (lockfiles, build output, ...). In
        `turn` mode a step closes only when a session's turn has ended and no other session is mid-turn
        (for at most MAX_DEFER_SECONDS), and not within COALESCE_SECONDS of the previous step, so a burst
        of turn ends (one per subagent) makes one step. `final` (session end) skips the waiting."""
        mode = config.settings()["auto_step"]
        if mode == "off":
            return None
        with self.locked():
            self.refresh()
            pend = self.pending(counts=False)
            if not pend or not noise.split(pend)[0]:
                return None
            evs = self.journal()
            steps = self.steps()
            since = steps[-1]["id"] if steps else 0
            now = time.time()
            sess = self._sessions(evs, since)
            ended = {k: v for k, v in sess.items() if v["end"] > v["act"]}
            if not final and steps and steps[-1].get("source") == "auto" and now - steps[-1].get("ts", 0) < COALESCE_SECONDS:
                return None
            if mode == "turn" and not ended:
                if sess:
                    return None  # a turn is in progress
                mode = "idle"    # no hooks: fall back to quiet-period steps
            if mode == "turn" and not final:
                busy = [v for v in sess.values() if v["act"] > v["end"] and now - v["act_ts"] < SESSION_STALE_SECONDS]
                if busy and now - max(v["end_ts"] for v in ended.values()) < MAX_DEFER_SECONDS:
                    return None  # another session is still working
            if mode == "idle" and not ended:
                last = config.read_json(self.dir / "meta.json", {}).get("last_change", 0)
                if time.time() - last < config.settings()["idle_seconds"]:
                    return None
            if session is None and ended:
                session = max(ended, key=lambda k: ended[k]["end"])
            prompt = self._turn_prompt(evs, since, session)
            real = noise.split(pend)[0]
            new_syms = []
            if self.model:
                prev = self.load_step(steps[-1]["n"]) if steps else None
                marks = A.diff_models(prev["model"] if prev else None, self.model)
                new_syms = [k.split(":")[-1].split(".")[-1] for kind in ("functions", "classes") for k, v in (marks.get(kind) or {}).items() if v == "new"][:3]
            title = titles.derive_title(prompt, real, new_syms)
            return self._snapshot(title, prompt[:300], "auto", prompt=prompt)

    # ------------------------------------------------------------------ annotations
    def annotations(self) -> dict:
        todos: dict[str, dict] = {}
        claims, notes, links = [], {}, []
        for e in self.journal():
            t = e["t"]
            if t == "todo":
                todos[e["tid"]] = {"id": e["tid"], "text": e["text"], "status": "open", "added_step": e.get("step"),
                                   "added": e["ts"], "evidence": None, "by": e.get("by", "agent")}
            elif t == "todo_done" and e.get("tid") in todos:
                todos[e["tid"]].update(status="done", evidence=e.get("evidence"), done_step=e.get("step"), done=e["ts"])
            elif t == "todo_drop" and e.get("tid") in todos:
                todos[e["tid"]]["status"] = "dropped"
            elif t == "claim":
                claims = [c for c in claims if not (c["concept"] == e["concept"] and c["symbol"] == e["symbol"])]
                claims.append({"id": e["id"], "concept": e["concept"], "symbol": e["symbol"], "note": e.get("note", ""), "ts": e["ts"]})
            elif t == "note":
                notes[e["symbol"]] = {"symbol": e["symbol"], "role": e["role"], "ts": e["ts"]}
            elif t == "link":
                links = [x for x in links if not (x["from"] == e["from"] and x["to"] == e["to"])]
                links.append({"id": e["id"], "from": e["from"], "to": e["to"], "label": e.get("label", ""), "ts": e["ts"]})
            elif t == "retract":
                claims = [c for c in claims if c["id"] != e.get("ref")]
                links = [x for x in links if x["id"] != e.get("ref")]
        return {"todos": list(todos.values()), "claims": claims, "notes": list(notes.values()), "links": links}

    def _segment(self, kind: str, node: dict) -> str:
        text = self.text(node["file"]) or ""
        if kind in ("functions", "classes") and node.get("line"):
            ls = text.splitlines()
            return "\n".join(ls[(node.get("start") or node["line"]) - 1: node.get("end") or node["line"] + 60])
        return text

    def verify(self) -> dict:
        """Check every annotation against the code as it is now."""
        self.ensure()
        ann = self.annotations()
        problems = []
        for c in ann["claims"]:
            hit = A.resolve(self.model, c["symbol"])
            if not hit:
                c["status"], c["reason"] = "missing", f"no symbol named {c['symbol']}"
            elif c["concept"] not in C.CATALOG:
                c["status"], c["reason"] = "unverified", f"{c['concept']} is not in the catalog"
            else:
                kind, sid, node = hit
                c["resolved"], c["file"], c["line"] = sid, node["file"], node.get("line")
                part = (self.cache.get(node["file"]) or {}).get("part") or {}
                strong = C.evidence_in(c["concept"], self._segment(kind, node))
                weak = None if strong else C.evidence_in(c["concept"], "", part.get("raw_imports", []))
                if strong:
                    c["status"], c["reason"] = "verified", strong
                elif weak:
                    c["status"], c["reason"] = "weak", f"only {weak}; nothing in {sid.split(':')[-1]} itself"
                else:
                    c["status"], c["reason"] = "unverified", f"no sign of {C.CATALOG[c['concept']][0].lower()} in {sid.split(':')[-1]}"
            if c["status"] != "verified":
                problems.append({"kind": "claim", "id": c["id"], "status": c["status"], "text": f"{c['concept']} → {c['symbol']}: {c['reason']}"})
        for nt in ann["notes"]:
            hit = A.resolve(self.model, nt["symbol"])
            nt["status"] = "ok" if hit else "stale"
            if hit:
                nt["resolved"] = hit[1]
            else:
                problems.append({"kind": "note", "status": "stale", "text": f"note on {nt['symbol']}: the symbol no longer exists"})
        for ln in ann["links"]:
            a, b = A.resolve(self.model, ln["from"]), A.resolve(self.model, ln["to"])
            ln["status"] = "ok" if a and b else "stale"
            if a and b:
                ln["from_id"], ln["to_id"] = a[1], b[1]
            else:
                problems.append({"kind": "link", "id": ln["id"], "status": "stale",
                                 "text": f"link {ln['from']} → {ln['to']}: {'from' if not a else 'to'} side not found"})
        for td in ann["todos"]:
            if td["status"] != "done":
                continue
            ev = (td.get("evidence") or "").strip()
            if not ev:
                td["verified"], td["reason"] = False, "marked done without evidence"
            else:
                hit = A.resolve(self.model, ev)
                path = hit[2]["file"] if hit else (ev if ev in self.index else None)
                if not path:
                    td["verified"], td["reason"] = False, f"evidence {ev} not found"
                else:
                    base = self.step_files(td["added_step"]) if td.get("added_step") is not None else {}
                    if base.get(path) == self.index.get(path) and path in base:
                        td["verified"], td["reason"] = False, f"{path} has not changed since the todo was added"
                    else:
                        td["verified"], td["reason"] = True, f"{path} changed after the todo was added"
            if not td["verified"]:
                problems.append({"kind": "todo", "id": td["id"], "status": "unverified", "text": f"todo “{td['text'][:60]}” done: {td['reason']}"})
        for s in self.steps():
            check = self.title_check(s)
            if check != "ok":
                problems.append({"kind": "step", "id": s["n"], "status": "mismatch", "text": f"step {s['n']} “{s['title'][:50]}”: {check}"})
        for rel, e in self.cache.items():
            if (e.get("part") or {}).get("error"):
                problems.append({"kind": "parse", "status": "error", "text": f"{rel} does not parse (the agent may be mid-edit)"})
        try:
            from . import rules as R
            problems += R.problems(self.root, self.model)
        except Exception as e:  # a broken rules file must not break the map
            problems.append({"kind": "rule", "status": "error", "text": f"rules could not be checked: {e}"})
        return {**ann, "problems": problems}

    def todo_add(self, text: str, by: str = "agent") -> dict:
        text = " ".join((text or "").split())[:200]
        if not text:
            raise ValueError("a todo needs text")
        steps = self.steps()
        n = len([e for e in self.journal() if e["t"] == "todo"]) + 1
        return self.append({"t": "todo", "tid": f"T{n}", "text": text, "step": steps[-1]["n"] if steps else None, "by": by})

    def todo_done(self, tid: str, evidence: str = "") -> dict:
        if not any(t["id"] == tid for t in self.annotations()["todos"]):
            raise ValueError(f"no todo {tid}")
        self.refresh()
        steps = self.steps()
        self.append({"t": "todo_done", "tid": tid, "evidence": (evidence or "")[:200], "step": steps[-1]["n"] if steps else None})
        return next(t for t in self.verify()["todos"] if t["id"] == tid)

    def todo_drop(self, tid: str) -> None:
        self.append({"t": "todo_drop", "tid": tid})

    def claim(self, concept: str, symbol: str, note: str = "") -> dict:
        if concept not in C.CATALOG:
            raise ValueError(f"unknown concept {concept}; see `catalog`")
        self.refresh()
        ev = self.append({"t": "claim", "concept": concept, "symbol": symbol[:200], "note": " ".join(note.split())[:160]})
        return next(c for c in self.verify()["claims"] if c["id"] == ev["id"])

    def note(self, symbol: str, role: str) -> dict:
        role = " ".join((role or "").split())[:140]
        if not role:
            raise ValueError("a note needs text")
        self.refresh()
        self.append({"t": "note", "symbol": symbol[:200], "role": role})
        return next(n for n in self.verify()["notes"] if n["symbol"] == symbol[:200])

    def link(self, a: str, b: str, label: str = "") -> dict:
        self.refresh()
        ev = self.append({"t": "link", "from": a[:200], "to": b[:200], "label": " ".join(label.split())[:60]})
        return next(x for x in self.verify()["links"] if x["id"] == ev["id"])

    def record(self, kind: str, **data) -> dict:
        """Prompts, tool calls and turn ends reported by hooks or plugins. Text is redacted. Hook events
        are dropped (returns {}) when the journal is past its size cap, when a tool event repeats the
        previous one without adding information, or when too many tool events piled up since the last step."""
        if kind == "prompt":
            data["text"] = redact(" ".join(str(data.get("text", "")).split()))[:300]
        if data.get("session") is not None:
            data["session"] = str(data["session"])[:64]
        if kind in ("prompt", "tool", "turn_end"):
            with self.locked():
                try:
                    if (self.dir / "journal.jsonl").stat().st_size > JOURNAL_CAP_BYTES:
                        return {}
                except OSError:
                    pass
                if kind == "tool":
                    evs = self.journal()
                    last = evs[-1] if evs else {}
                    if (last.get("t") == "tool" and last.get("tool") == data.get("tool") and not data.get("files")
                            and not last.get("files") and last.get("session") == data.get("session")):
                        return {}
                    steps = self.steps()
                    since = steps[-1]["id"] if steps else 0
                    if sum(1 for e in evs if e["id"] > since and e["t"] == "tool") >= MAX_TOOL_EVENTS_PER_STEP:
                        return {}
                return self.append({"t": kind, **data})
        return self.append({"t": kind, **data})

    # ------------------------------------------------------------------ views
    def files_view(self, base: dict | None) -> list[dict]:
        rows = []
        for rel, e in sorted(self.cache.items()):
            part = e.get("part") or {}
            status = None
            if base is not None:
                status = "A" if rel not in base else "M" if base[rel] != e["sha"] else None
            rows.append({"path": rel, "lang": part.get("lang") or os.path.splitext(rel)[1].lstrip(".") or rel,
                         "layer": A.layer_of(rel, part) if part else None, "lines": e.get("lines"),
                         "functions": len(part.get("functions", [])), "classes": len(part.get("classes", [])),
                         "secret": bool(e.get("secret")), "status": status, "error": bool(part.get("error"))})
        if base is not None:
            rows += [{"path": rel, "lang": "", "layer": None, "lines": 0, "functions": 0, "classes": 0, "secret": False,
                      "status": "D", "error": False} for rel in sorted(set(base) - set(self.cache))]
        return rows

    def state(self) -> dict:
        self.ensure()
        steps = self.steps()
        base = self.step_files(steps[-1]["n"]) if steps else None
        v = self.verify()
        fns = self.model["functions"]
        hot = sorted(fns.items(), key=lambda kv: -kv[1]["complexity"])[:12]
        evs = self.journal()
        return {
            "key": self.key, "name": self.name, "root": self.root, "version": self.version, "truncated": self.truncated,
            "truncated_info": self.truncated_info,
            "steps": [{**{k: s.get(k) for k in ("n", "title", "intent", "source", "ts", "summary", "changes", "prompt")}, "title_check": self.title_check(s)}
                      for s in steps],
            "pending": self.pending(),
            "files": self.files_view(base),
            "counts": {"files": len(self.cache), "modules": len(self.model["modules"]), "classes": len(self.model["classes"]),
                       "functions": len(fns), "tables": len(self.model["tables"]), "routes": len(self.model["routes"]),
                       "concepts": len(self.concepts), "infra": len(self.infra["nodes"])},
            "layers": dict(Counter(m["layer"] for m in self.model["modules"].values())),
            "routes": self.model["routes"],
            "concepts": [{"id": cid, "title": C.CATALOG[cid][0], "icon": C.CATALOG[cid][1], "group": C.CATALOG[cid][2],
                          "meaning": C.CATALOG[cid][3], "evidence": evs_[:8],
                          "claims": [c for c in v["claims"] if c["concept"] == cid]}
                         for cid, evs_ in sorted(self.concepts.items(), key=lambda kv: list(C.CATALOG).index(kv[0]))]
                        + [{"id": cid, "title": C.CATALOG[cid][0], "icon": C.CATALOG[cid][1], "group": C.CATALOG[cid][2],
                            "meaning": C.CATALOG[cid][3], "evidence": [], "claims": [c for c in v["claims"] if c["concept"] == cid]}
                           for cid in sorted({c["concept"] for c in v["claims"]} - set(self.concepts)) if cid in C.CATALOG],
            "infra": self.infra,
            "hotspots": [{"id": fid, "complexity": f["complexity"], "loc": f["loc"], "hints": f["hints"], "file": f["file"], "line": f["line"]}
                         for fid, f in hot],
            "algorithms": sorted(({"id": fid, "hints": f["hints"], "file": f["file"], "line": f["line"]}
                                  for fid, f in fns.items() if any(h not in ("async I/O",) for h in f["hints"])),
                                 key=lambda x: (-len(x["hints"]), x["id"]))[:60],
            "todos": v["todos"], "claims": v["claims"], "notes": v["notes"], "links": v["links"], "problems": v["problems"],
            "activity": [{k: e.get(k) for k in ("id", "ts", "t", "text", "tool", "files", "n", "title", "tid", "concept", "symbol", "role", "agent")}
                         for e in evs[-80:]],
        }


_PROJECTS: dict[tuple[str, str], Project] = {}
_PLOCK = threading.Lock()


def open_project(root: str) -> Project:
    """One Project object per root (and per MAPWRIGHT_HOME) in this process."""
    real = os.path.realpath(A.find_root(os.path.abspath(root)))
    k = (str(config.home()), real)
    with _PLOCK:
        p = _PROJECTS.get(k)
        if p is None:
            p = _PROJECTS[k] = Project(real)
        return p


def by_key(key: str) -> Project | None:
    if not _KEY.match(key or ""):
        return None
    entry = config.projects().get(key)
    if not entry or not os.path.isdir(entry["root"]):
        return None
    return open_project(entry["root"])
