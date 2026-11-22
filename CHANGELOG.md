# Changelog

## Unreleased

- First-run UI: clear "Unauthorised" and "daemon not running" states, paste-link/token box, token remembered in the browser, "Forget token"; consistent control sizes and alignment.
- Project-local homes: `mapwright init --local` / `--home DIR`, discovery via `.mapwright/home.json`, `MAPWRIGHT_HOME` written into generated MCP entries and Claude Code hook commands; `/v1/ping` reports the daemon's home.
- Respect `.gitignore` by default (`respect_gitignore`), gitignore-style patterns in `ignore`, `max_files` now honoured and truncation reported (`init`, `doctor`, `state`), ignore suggestions on `init` (`--apply-ignore`); scans are deterministic and share no global state.
- Auto steps get short clean titles instead of raw prompts, skip noise-only changes (lockfiles, generated output), ignore subagent and overlapping-session stops; read-only Bash calls are no longer journaled.
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
