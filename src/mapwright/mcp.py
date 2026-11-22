"""MCP server (stdio, JSON-RPC 2.0): how any MCP-capable coding agent talks to Mapwright.

Tool descriptions and results are deliberately short: every tool definition is sent to the model
on every turn, so a verbose server costs tokens on each request. Results never include source
code; they point at file:line so the agent opens only what it needs.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

from . import __version__, brief
from . import analyze as A
from .track import open_project

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = ("Mapwright keeps a live map of this project from its code. Start with `map` instead of exploring files. "
                "After each meaningful change call `step` with a short title (what changed is computed, not taken from you). "
                "Track plan items with `todo`. `claim` a mechanism only where the code shows it; claims are verified.")


def _s(props: dict, req: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": req or [], "additionalProperties": False}


STR = {"type": "string"}
TOOLS = [
    {"name": "map", "description": "Project map: layers, modules and key symbols, routes, tables, infra, mechanisms, todos. No code.",
     "inputSchema": _s({"focus": {**STR, "description": "path prefix to expand"}, "budget": {"type": "integer", "description": "max chars"}})},
    {"name": "find", "description": "Locate symbols by name. Returns id, kind, file:line.", "inputSchema": _s({"query": STR}, ["query"])},
    {"name": "symbol", "description": "One symbol: signature, callers, callees, tables, routes, history. No code.",
     "inputSchema": _s({"name": STR}, ["name"])},
    {"name": "step", "description": "Record a step after a change. Title only; files and design changes are computed.",
     "inputSchema": _s({"title": STR, "intent": {**STR, "description": "optional: why"}}, ["title"])},
    {"name": "todo", "description": "Plan items. action: add | done | drop | list. done needs evidence (symbol or file you changed).",
     "inputSchema": _s({"action": {"type": "string", "enum": ["add", "done", "drop", "list"]}, "text": STR, "id": STR, "evidence": STR}, ["action"])},
    {"name": "claim", "description": "Tag a symbol with a mechanism id from `catalog` (e.g. caching, retry-backoff). Verified against the code.",
     "inputSchema": _s({"concept": STR, "symbol": STR, "note": STR}, ["concept", "symbol"])},
    {"name": "note", "description": "One-line role of a module or symbol, shown on the map.", "inputSchema": _s({"symbol": STR, "role": STR}, ["symbol", "role"])},
    {"name": "link", "description": "A relation static analysis cannot see (queue, event, HTTP between services).",
     "inputSchema": _s({"from": STR, "to": STR, "label": STR}, ["from", "to"])},
    {"name": "catalog", "description": "Concept ids usable in `claim`.", "inputSchema": _s({})},
]


def call(project, name: str, args: dict) -> str:
    p = project
    p.refresh()
    if name == "map":
        b = args.get("budget")
        return brief.project_brief(p, int(b) if isinstance(b, int) and 400 <= b <= 20000 else _budget(), args.get("focus"))
    if name == "find":
        rows = A.find_symbols(p.model, str(args.get("query", "")), 15)
        return "\n".join(f"{r['id']} ({r['kind']}) {r['file']}:{r['line'] or ''}" for r in rows) or "no match"
    if name == "symbol":
        return brief.symbol_card(p, str(args.get("name", "")))
    if name == "step":
        return brief.step_receipt(p.step(str(args.get("title", "")), str(args.get("intent", "") or "")))
    if name == "todo":
        act = args.get("action")
        if act == "add":
            ev = p.todo_add(str(args.get("text", "")))
            return f"added {ev['tid']}"
        if act == "done":
            t = p.todo_done(str(args.get("id", "")), str(args.get("evidence", "") or ""))
            return f"{t['id']} done · {'verified' if t.get('verified') else 'unverified'}: {t.get('reason', '')}"
        if act == "drop":
            p.todo_drop(str(args.get("id", "")))
            return "dropped"
        todos = p.verify()["todos"]
        return "\n".join(f"{t['id']} [{t['status']}{'' if t['status'] != 'done' else ', verified' if t.get('verified') else ', unverified'}] {t['text']}"
                         for t in todos) or "no todos"
    if name == "claim":
        c = p.claim(str(args.get("concept", "")), str(args.get("symbol", "")), str(args.get("note", "") or ""))
        return f"{c['concept']} → {c['symbol']}: {c['status']} ({c.get('reason', '')})"
    if name == "note":
        n = p.note(str(args.get("symbol", "")), str(args.get("role", "")))
        return f"noted ({n['status']})"
    if name == "link":
        ln = p.link(str(args.get("from", "")), str(args.get("to", "")), str(args.get("label", "") or ""))
        return f"linked ({ln['status']})"
    if name == "catalog":
        return brief.catalog_text()
    raise ValueError(f"unknown tool {name}")


def _budget() -> int:
    from . import config
    return config.settings()["brief_budget"]


def handle(project, msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if method is None:
        return None  # a response to something we never send
    if mid is None:
        return None  # notification (notifications/initialized, cancelled …)
    try:
        if method == "initialize":
            want = (msg.get("params") or {}).get("protocolVersion")
            result = {"protocolVersion": want if want in VERSIONS else VERSIONS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "mapwright", "version": __version__}, "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            name, args = params.get("name"), params.get("arguments") or {}
            if name not in {t["name"] for t in TOOLS}:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
            try:
                text, err = call(project, name, args if isinstance(args, dict) else {}), False
            except (ValueError, KeyError) as e:
                text, err = f"error: {e}", True
            result = {"content": [{"type": "text", "text": text}], "isError": err}
        elif method in ("resources/list", "prompts/list"):
            result = {method.split("/")[0]: []}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    except Exception as e:  # never kill the agent's session over one bad call
        traceback.print_exc(file=sys.stderr)
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"internal error: {type(e).__name__}: {e}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(root: str | None = None, stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    root = root or os.environ.get("MAPWRIGHT_ROOT") or os.getcwd()
    from . import config
    config.set_start(root)
    project = open_project(root)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            batch = msg if isinstance(msg, list) else [msg]
            outs = [r for r in (handle(project, m) for m in batch if isinstance(m, dict)) if r is not None]
            out = outs if isinstance(msg, list) else (outs[0] if outs else None)
        if out is not None:
            stdout.write(json.dumps(out, separators=(",", ":")) + "\n")
            stdout.flush()
    return 0
