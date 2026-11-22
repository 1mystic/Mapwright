# Architecture

```
agent ──stdio──▶ mcp.py ─┐                         ┌─▶ render.py ─▶ Mermaid + node map ─▶ ui/app.js
agent ──hooks──▶ hooks.py┼─▶ track.Project ────────┤
CLI  ─────────▶ cli.py  ─┘   (refresh, steps,      ├─▶ brief.py  ─▶ compact text for agents
UI   ──HTTP───▶ server.py    annotations, verify)  └─▶ flow.py   ─▶ function flowcharts
                                 │
                                 ├─ analyze.py   per-file analysis (cached by content hash) + link()
                                 ├─ concepts.py  catalog + detectors + claim evidence
                                 └─ infra.py     Docker, compose, Terraform, k8s, CI, env, SDKs
```

## Storage (`track.py`)

`~/.mapwright/projects/<name>-<hash>/`:

| File | Contents |
|---|---|
| `journal.jsonl` | Append-only events: `prompt`, `tool`, `turn_end`, `step`, `todo`, `todo_done`, `todo_drop`, `claim`, `note`, `link`, `retract` |
| `steps/NNNN.json.gz` | Per step: file index (path → content hash), the full model, changes with line counts, design delta, title check |
| `blobs/ab/<sha>.gz` | Every version of every tracked text file, stored once by hash; secret-looking files are never stored |
| `cache.json.gz` | Per-file analysis keyed by (mtime, size); a new process starts warm |

Several processes share a project (daemon, MCP server, hooks, CLI). Writes take an `flock` on the project
directory, re-entrant within a process. Annotations are derived by replaying the journal; verification is
recomputed against the current model each time it is read.

## Analysis (`analyze.py`)

- Python: `ast` for imports (relative imports and aliases resolved), classes, functions and methods (args,
  decorators, calls, complexity, docstring, algorithm hints), routes (FastAPI, Flask, router prefixes),
  SQLAlchemy and Django models, SQL inside string literals.
- JS/TS: patterns for imports, classes, interfaces, functions, arrow functions, methods, Express-style and
  Next.js routes. SQL: `CREATE TABLE`. Prisma: models.
- `link()` resolves module dependencies, then the call graph (bare calls within the module and its imports;
  `self.x` within the class; `alias.f` through import aliases; `obj.m` only when a single method in reach
  matches), then which functions touch which tables (ORM classes referenced, SQL table names in the function).
- Layers come from path conventions, then from content (routes → interface, tables → data).

## Daemon (`server.py`)

ThreadingHTTPServer on 127.0.0.1. Token (Bearer) on every `/v1` route, Host allowlist, no cross-origin
requests, JSON-only POST. A watcher thread refreshes tracked projects and closes automatic steps.

## UI (`ui/`)

No framework and no build step. `app.js` renders the IDE frame, polls `/v1/p/<key>/version`, and renders
diagrams with the bundled Mermaid in strict mode with HTML labels off. Clickable nodes come from the node
map each renderer returns. The website's demo uses the same UI with a recorded bundle of API responses.
