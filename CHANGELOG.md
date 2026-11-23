# Changelog

## Unreleased

- Fix: expanding a long file tree no longer pushes the bottom panel and status bar out of the window; the layout also fits the window at every interface zoom level.

## 0.3.0

- `mapwright open` no longer lets the browser's console noise reach the terminal.
- System view timelapse: replays the architecture step by step to LIVE (play/pause, slider, 1x/2x, Space; respects reduced motion).
- Estimated token savings: `map`/`find`/`symbol` answers compared with reading the files they summarise, shown in the Overview and status bar and in `state().savings` (labelled as an estimate).
- Custom select menus in the UI (themed list, check on the current item, keyboard navigation, filter for long lists) replace the native selects.
- `mapwright report`: reviewer-ready Markdown or JSON summary of architecture changes since a step or git ref (counts, modules by layer, Mermaid diagram of changed modules, routes, tables, hotspots, rule status, verification), plus a manual PR-comment workflow.
- Live feedback: right after an edit, the Claude Code hook tells the agent about rule violations and import cycles that edit introduced, so it can fix them in the same turn (setting `live_feedback`, default on; about 10 ms warm).
- Landing page: one spacing scale for every section, a 5x2 views grid, consistent section layouts, cleaner copy.
- Website: light theme with a toggle in the nav on every page (first visit follows the system preference, no flash on load); inline code in docs no longer breaks mid-token.
- UI: Record step opens an in-app dialog (title and intent) instead of a browser prompt; Ctrl/Cmd + = / - / 0 zooms the whole interface; the System view pans and zooms like the diagrams (wheel at the cursor, drag, double-click to fit); search sits on the right of the header; pills share the control radius; Overview is the first tab again; the timeline rail is visible in the light theme; small-button labels centred (measured in pixels).
- Accuracy: tables, routes and mechanisms found only in tests, examples, scripts or vendored code are kept out of the project map and listed separately; detector pattern tables and comments no longer count as mechanisms; better layers for CLIs and libraries (new `tooling` layer); JS regex literals no longer break function bounds (one 17-line function was read as 299 lines). Cached analyses are rebuilt automatically.
- Website docs and setup pages are generated from `docs/*.md` (`scripts/mdsite.py`, run on every site build); `scripts/screenshots.py` regenerates the UI screenshots with headless Chromium; the UI accepts `#view=` and `#theme=` in the URL.
- `mapwright forget [--purge] [--yes]` and `mapwright token [--rotate] [--show]`; ruff configuration with a manual lint job; CONTRIBUTING, SECURITY, issue and PR templates.
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
