# Changelog

## Unreleased

- Architecture rules: `mapwright.toml` with forbidden imports between layers or paths, import-cycle, complexity and module-size limits; checked at every step and shown in Problems and the agent's map; `mapwright check` (exit 1 on violations) and `mapwright rules --init` (a starter that holds today).
- Docs: how to stop Mapwright (daemon, watch, agent hooks, history, uninstall).

## 0.2.0

- PyPI release pipeline (trusted publishing, tag-driven, TestPyPI rehearsal) under the name `mapwright-agent`; version is single-sourced in `src/mapwright/__init__.py`; timeline markers centred on their line.

- First-run UI: clear "Unauthorised" and "daemon not running" states, paste-link/token box, token remembered in the browser, "Forget token"; consistent control sizes and alignment.
- Project-local homes: `mapwright init --local` / `--home DIR`, discovery via `.mapwright/home.json`, `MAPWRIGHT_HOME` written into generated MCP entries and Claude Code hook commands; `/v1/ping` reports the daemon's home.
- Respect `.gitignore` by default (`respect_gitignore`), gitignore-style patterns in `ignore`, `max_files` now honoured and truncation reported (`init`, `doctor`, `state`), ignore suggestions on `init` (`--apply-ignore`); scans are deterministic and share no global state.
- Auto steps get short clean titles instead of raw prompts, skip noise-only changes (lockfiles, generated output), ignore subagent and overlapping-session stops; read-only Bash calls are no longer journaled.
- Detect React Router routes (config arrays, JSX, lazy groups), Firestore/Storage security rules and collection usage as data collections, zod schemas as entities, and tag React components and hooks.
- Hosted website support: `web_origins` allowlist with CORS and private-network preflight in the daemon, `mapwright open --web`, and a UI that talks to a loopback daemon when served from a hosted site (demo stays the default until a token link is used).
- System view (default tab): an abstract icon diagram of clients, interface, logic, data, outside services and platform built from the analysis; click a component to see its files, routes, tables and most complex functions in the Inspector; new and changed components are marked.
- `mapwright disconnect` deletes config files (and empty tool folders) it leaves empty.

## 0.1.0

First release.

- Static analysis of Python, JS/TS, SQL (including SQL in code strings) and Prisma: modules, layers, classes,
  functions, call graph, routes, tables, algorithm hints.
- 29-concept catalog with detectors and verified claims.
- Infrastructure from Docker, Compose, Terraform, Kubernetes, serverless, Procfile, CI, hosting configs, env files and SDK imports.
- Step store with every file version, computed changes and design deltas; automatic steps at turn ends (hooks) or after a quiet period.
- Verification of step titles, todos, claims, notes and links.
- MCP server (9 tools), hook client, config writers for 8 agents plus paste-in snippets.
- IDE-style UI (dark/light): overview, architecture, files, classes, data, cloud, processes, logic with flowcharts,
  concepts, timeline, code and diff viewers, inspector, search everywhere, settings, connect panel.
- VS Code extension, Claude Code plugin, opencode plugin, Agent Skill.
- Website with a live demo; setup and free-tier deploy guide.
