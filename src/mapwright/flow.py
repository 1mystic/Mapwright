"""Control flow of one function as a flowchart, built from its syntax tree.

Python is parsed with `ast`. JS/TS gets a lighter outline (branches, loops and calls in order),
because there is no parser in the standard library. Each node carries the source line it stands
for, so clicking a box in the UI jumps to that line.
"""

from __future__ import annotations

import ast
import re

MAX_NODES = 70


def _short(node, n: int = 46) -> str:
    try:
        text = ast.unparse(node)
    except Exception:
        text = type(node).__name__
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _lab(text: str) -> str:
    text = re.sub(r"[\"`<>{}\[\]|#;\\]", " ", text)
    return " ".join(text.split()) or " "


class _Builder:
    def __init__(self):
        self.lines: list[str] = []
        self.nodes: dict[str, dict] = {}
        self.n = 0
        self.truncated = False
        self.loops: list[tuple[str, list[str]]] = []  # (head id, break exits)

    def node(self, shape: str, label: str, line: int | None, cls: str = "") -> str:
        self.n += 1
        nid = f"f{self.n}"
        label = _lab(label)
        wrap = {"box": ('["', '"]'), "cond": ('{"', '"}'), "term": ('(["', '"])'), "loop": ('{{"', '"}}'),
                "io": ('[/"', '"/]'), "sub": ('[["', '"]]')}[shape]
        self.lines.append(f"  {nid}{wrap[0]}{label}{wrap[1]}" + (f":::{cls}" if cls else ""))
        self.nodes[nid] = {"line": line, "label": label}
        return nid

    def edge(self, a: str, b: str, label: str = "") -> None:
        self.lines.append(f"  {a} -->|{_lab(label)}| {b}" if label else f"  {a} --> {b}")

    def link_all(self, srcs: list[tuple[str, str]], dst: str) -> None:
        for s, lab in srcs:
            self.edge(s, dst, lab)

    def block(self, stmts: list, entry: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Lay out a statement list; returns the open exits [(node id, edge label)]."""
        cur = entry
        run: list = []

        def flush():
            nonlocal cur, run
            if run:
                text = "; ".join(_short(s, 30) for s in run[:2]) + (f"  (+{len(run) - 2})" if len(run) > 2 else "")
                nid = self.node("io" if any(_is_io(s) for s in run) else "box", text, run[0].lineno)
                self.link_all(cur, nid)
                cur = [(nid, "")]
                run = []

        for st in stmts:
            if not cur:
                break  # unreachable after return/raise/break
            if self.n > MAX_NODES:
                self.truncated = True
                flush()
                nid = self.node("box", "… more", st.lineno, "muted")
                self.link_all(cur, nid)
                return [(nid, "")]
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                flush()
                nid = self.node("sub", f"def {st.name}" if not isinstance(st, ast.ClassDef) else f"class {st.name}", st.lineno)
                self.link_all(cur, nid)
                cur = [(nid, "")]
            elif isinstance(st, ast.If):
                flush()
                c = self.node("cond", _short(st.test) + "?", st.lineno)
                self.link_all(cur, c)
                yes = self.block(st.body, [(c, "yes")])
                no = self.block(st.orelse, [(c, "no")]) if st.orelse else [(c, "no")]
                cur = yes + no
            elif isinstance(st, (ast.For, ast.AsyncFor, ast.While)):
                flush()
                head = self.node("loop", ("for " + _short(st.target, 16) + " in " + _short(st.iter, 22)) if not isinstance(st, ast.While)
                                 else "while " + _short(st.test), st.lineno)
                self.link_all(cur, head)
                self.loops.append((head, []))
                body = self.block(st.body, [(head, "each" if not isinstance(st, ast.While) else "true")])
                for s, lab in body:
                    self.edge(s, head, lab or "next")
                _, breaks = self.loops.pop()
                done = [(head, "done")]
                if st.orelse:
                    done = self.block(st.orelse, done)
                cur = done + breaks
            elif isinstance(st, ast.Try) or type(st).__name__ == "TryStar":
                flush()
                t = self.node("box", "try", st.lineno)
                self.link_all(cur, t)
                ok = self.block(st.body, [(t, "")])
                outs = []
                for h in st.handlers:
                    e = self.node("cond", "except " + (_short(h.type, 28) if h.type else "any"), h.lineno, "warn")
                    self.edge(t, e, "error")
                    outs += self.block(h.body, [(e, "")])
                if st.orelse:
                    ok = self.block(st.orelse, ok)
                cur = ok + outs
                if st.finalbody:
                    fin = self.node("box", "finally", st.finalbody[0].lineno)
                    self.link_all(cur, fin)
                    cur = self.block(st.finalbody, [(fin, "")])
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                flush()
                w = self.node("box", "with " + ", ".join(_short(i.context_expr, 24) for i in st.items), st.lineno)
                self.link_all(cur, w)
                cur = self.block(st.body, [(w, "")])
            elif type(st).__name__ == "Match":
                flush()
                m = self.node("cond", "match " + _short(st.subject), st.lineno)
                self.link_all(cur, m)
                outs = []
                for case in st.cases:
                    outs += self.block(case.body, [(m, _short(case.pattern, 18))])
                cur = outs
            elif isinstance(st, ast.Return):
                flush()
                r = self.node("term", "return " + (_short(st.value) if st.value else ""), st.lineno, "ret")
                self.link_all(cur, r)
                self.edge(r, "fEnd")
                cur = []
            elif isinstance(st, ast.Raise):
                flush()
                r = self.node("term", "raise " + (_short(st.exc, 36) if st.exc else ""), st.lineno, "err")
                self.link_all(cur, r)
                cur = []
            elif isinstance(st, ast.Break):
                flush()
                if self.loops:
                    self.loops[-1][1].extend((s, lab or "break") for s, lab in cur)
                cur = []
            elif isinstance(st, ast.Continue):
                flush()
                if self.loops:
                    for s, lab in cur:
                        self.edge(s, self.loops[-1][0], lab or "continue")
                cur = []
            elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                continue  # docstring
            else:
                run.append(st)
                if len(run) >= 3 or _is_io(st):
                    flush()
        flush()
        return cur


def _is_io(st) -> bool:
    if not isinstance(st, (ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return False
    text = _short(st, 200).lower()
    return bool(re.search(r"\b(await|open|print|write|read|send|fetch|request|execute|commit|query|get|post|put|save|delete|emit|publish|log\w*)\(", text))


STYLE = ["  classDef ret stroke:#57965C,stroke-width:2px", "  classDef err stroke:#DB5C5C,stroke-width:2px",
         "  classDef warn stroke:#E5A13E,stroke-width:1.5px", "  classDef muted stroke-dasharray:4 3"]


def python_flow(text: str, line: int) -> dict | None:
    """Flowchart for the function that starts at `line`. None if it cannot be found or parsed."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    fn = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno == line), None)
    if fn is None:
        return None
    b = _Builder()
    args = ", ".join(a.arg for a in fn.args.args if a.arg not in ("self", "cls"))
    start = b.node("term", f"{'async ' if isinstance(fn, ast.AsyncFunctionDef) else ''}{fn.name}({args})", fn.lineno, "ret")
    exits = b.block(fn.body, [(start, "")])
    b.lines.insert(0, '  fEnd(["end"])')
    b.nodes["fEnd"] = {"line": getattr(fn, "end_lineno", fn.lineno), "label": "end"}
    b.link_all(exits, "fEnd")
    return {"mermaid": "flowchart TD\n" + "\n".join(b.lines + STYLE), "nodes": b.nodes, "truncated": b.truncated,
            "kind": "flowchart", "lang": "python"}


_JS_STEP = re.compile(r"^\s*(?:\}\s*)?(if|else if|else|for|while|switch|case|try|catch|finally|return|throw|await)\b(.*)$")


def js_outline(text: str, line: int, end: int) -> dict:
    """A lighter flow for JS/TS: branches, loops, returns and calls in source order."""
    b = _Builder()
    lines = text.splitlines()[line - 1:end]
    head = lines[0].strip() if lines else "function"
    start = b.node("term", head[:46], line, "ret")
    prev = [(start, "")]
    stack: list[str] = []
    for i, raw in enumerate(lines[1:], start=line + 1):
        if b.n > MAX_NODES:
            b.truncated = True
            break
        m = _JS_STEP.match(raw)
        s = raw.strip()
        if m:
            kw, rest = m.group(1), m.group(2).strip().rstrip("{").strip()
            if kw in ("if", "else if", "while", "switch"):
                nid = b.node("cond", f"{kw} {rest}"[:46], i)
            elif kw == "for":
                nid = b.node("loop", f"for {rest}"[:46], i)
            elif kw in ("return", "throw"):
                nid = b.node("term", f"{kw} {rest}"[:46], i, "ret" if kw == "return" else "err")
            elif kw in ("catch",):
                nid = b.node("cond", f"catch {rest}"[:46], i, "warn")
            else:
                nid = b.node("box", f"{kw} {rest}"[:46], i)
            b.link_all(prev, nid)
            prev = [(nid, "")]
            if kw in ("if", "for", "while"):
                stack.append(nid)
        elif re.search(r"\w\s*\(", s) and not s.startswith(("//", "*", "/*")) and len(s) > 3:
            nid = b.node("io" if re.search(r"\b(await|fetch|query|save|send|write|emit)\b", s) else "box", s[:46], i)
            b.link_all(prev, nid)
            prev = [(nid, "")]
    b.lines.insert(0, '  fEnd(["end"])')
    b.nodes["fEnd"] = {"line": end, "label": "end"}
    b.link_all(prev, "fEnd")
    return {"mermaid": "flowchart TD\n" + "\n".join(b.lines + STYLE), "nodes": b.nodes, "truncated": b.truncated,
            "kind": "outline", "lang": "js"}
