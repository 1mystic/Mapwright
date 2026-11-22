# Roadmap

Status key: **done** · **in progress** · **planned**. Updated as work merges to `main`.

## Phase 1: field fixes from the Kairos run (0.1.x)

| # | Item | Status |
|---|---|---|
| 1 | First-run UX: unauthorised state, paste-link/token box, remembered token | in progress |
| 2 | Project-local home: `init --local` / `--home DIR`, env in MCP config and hooks, ignore entries | in progress |
| 3 | Ignore handling: `.gitignore` by default, glob patterns, init suggestions, `max_files` warning | in progress |
| 4 | TS/React: react-router route tables, Firestore rules and collections as a data source, zod, components | in progress |
| 5 | Hooks: clean step titles, subagent-safe `auto_step=turn`, noise (lockfiles, generated, ignored) excluded | in progress |
| 6 | `disconnect` removes config files it leaves empty | in progress |
| 7 | UI polish: consistent alignment of buttons, icons and panels | in progress |

## Phase 2: web version (0.2)

Static site; the browser talks to the user's own local daemon, so no code or data leaves the machine.

- Daemon: exact-origin allowlist and CORS preflight for the official site; token still required.
- Handle browser local-network permission prompts; fall back to the daemon-served UI where blocked (Safari).
- Site: landing, docs, live demo, connect guide generating `connect` commands, MCP and skill snippets.
- Hosting: Cloudflare Pages (primary), GitHub Pages (backup, workflow exists), Firebase Hosting (config exists).

## Phase 2b: System view (default landing view, app and site)

An abstract, illustrative system-design diagram drawn with icons: clients, UI, API gateway/routes, services,
workers/queues, databases and caches, storage, external APIs, CI/hosting. Built from data Mapwright already has
(layers, routes, tables, infra nodes, concepts), not drawn by the agent.

- Own SVG renderer (icons + labelled boxes + arrows, auto layout by tier), not Mermaid, so it can look designed.
- Click a component: the right sidebar (Inspector) opens its detail: files, key symbols, routes, tables, callers/callees, mechanisms, history.
- Becomes the default tab in the app and the hero on the website demo; the other views stay as drill-downs.
- Works per step (like other views) and marks added/changed components.
- Needs a stable component-classification step (shared with Phase 1 item 4 analysis) and icon set additions.

## Phase 3: native apps (0.3+)

- `.deb` (Ubuntu) and Homebrew formula installing the Python package, launcher and desktop entry.
- Native shell (tray, window around the local UI, daemon auto-start): Tauri or pywebview.
- macOS `.app`/`.pkg`; signing and notarisation need the paid Apple Developer program, so Homebrew first.

## Working agreement

- One branch per item (`fix/<topic>`), merged into `main` after `pytest` passes.
- Single-line commit messages.
- Every user-visible change updates `docs/COMMANDS.md` and `CHANGELOG.md`.
- Real-project traces (e.g. Kairos) are used as local fixtures only and are never committed.
