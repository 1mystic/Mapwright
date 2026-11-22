# Commands

`mw` is a short alias for `mapwright`. Every command has `--help`. Commands that act on a project use the
current folder (or `--path DIR`).

## Start and stop

| Command | What it does |
|---|---|
| `mapwright init [--connect AGENT] [--agents-md [FILE]]` | Track this project; the current state becomes step 0 |
| `mapwright open [--print] [--json]` | Open the map in the browser (starts the daemon if needed) |
| `mapwright up [-d] [--no-watch]` · `mapwright down` | Start (foreground or background) or stop the daemon |
| `mapwright watch` | Track from the files alone, without the daemon or any agent integration |
| `mapwright doctor` | Check the setup |
| `mapwright guide` | Quick reference |

## Agents

| Command | What it does |
|---|---|
| `mapwright connect --list` | Agents found on this machine and what is connected |
| `mapwright connect AGENT [--scope project\|user]` | Write the agent's MCP config (and hooks for Claude Code) |
| `mapwright connect --print AGENT` | Print the config to paste by hand |
| `mapwright disconnect AGENT [--scope …]` | Remove it again |
| `mapwright agents-md [--file AGENTS.md\|CLAUDE.md\|GEMINI.md\|.cursorrules]` | Add six lines of usage notes for agents |
| `mapwright mcp [--root DIR]` | The MCP server on stdio (agents start this) |
| `mapwright hook AGENT` | Hook entry point (agents call this with JSON on stdin) |

Agents: `claude-code`, `cursor`, `vscode`, `windsurf`, `opencode`, `codex`, `gemini`, `claude-desktop`;
print-only: `cline`, `zed`, `jetbrains`, `any`.

## While the agent works

| Command | What it does |
|---|---|
| `mapwright status [--json]` | Current step, pending changes, todos, problems |
| `mapwright steps` | Every step with its changes and design delta |
| `mapwright changes [--step N] [--diff]` | File changes since the last step, or in step N |
| `mapwright step "TITLE" [--intent "WHY"]` | Close a step yourself |
| `mapwright problems` | Claims, notes, links, todos and step titles that do not check out |
| `mapwright todo add TEXT` · `todo done ID --evidence SYMBOL` · `todo drop ID` · `todo list` | The plan |

## For agents (also available as MCP tools)

| Command | MCP tool | What it does |
|---|---|---|
| `mapwright brief [--budget N] [--focus PATH]` | `map` | The map as compact text |
| `mapwright find QUERY` | `find` | Locate symbols |
| `mapwright symbol NAME` | `symbol` | Callers, callees, tables, routes, history |
| `mapwright step "TITLE"` | `step` | Record a step |
| `mapwright todo …` | `todo` | Plan items, verified on done |
| `mapwright claim CONCEPT SYMBOL [--note …]` | `claim` | Tag a mechanism; checked against the code |
| `mapwright note SYMBOL ROLE…` | `note` | One-line role, shown on the map |
| `mapwright link FROM TO [--label …]` | `link` | A relation the code cannot show |
| `mapwright catalog` | `catalog` | Concept ids |

## Diagrams and export

| Command | What it does |
|---|---|
| `mapwright diagram architecture\|files\|classes\|data\|cloud\|processes\|calls\|concepts [--step N] [--focus X]` | Print a diagram as Mermaid |
| `mapwright flow FUNCTION` | Flowchart of one function |
| `mapwright export -o DIR` | `MAP.md` (renders on GitHub) + every diagram + steps and verification as JSON |

## Settings

`mapwright settings` lists them; `mapwright settings KEY VALUE` changes one (also in the UI: Settings).

| Setting | Default | Meaning |
|---|---|---|
| `auto_step` | `turn` | `turn`: close a step at each agent turn end (hooks) · `idle`: after a quiet period · `off` |
| `idle_seconds` | `60` | Quiet period for `idle` (and for agents without hooks) |
| `watch_interval` | `2.0` | Seconds between scans while the daemon runs |
| `brief_budget` | `2400` | Characters in `map` / `brief` (about 600 tokens) |
| `max_files` · `ignore` | `5000` · `[]` | Size cap and extra folders to skip |
| `redact` | `true` | Redact secrets in code shown in the UI |
| `theme` · `font_size` | `dark` · `13` | Appearance |

Environment: `MAPWRIGHT_HOME` (default `~/.mapwright`), `MAPWRIGHT_PORT` (default `7979`), `MAPWRIGHT_ROOT` (project for `mcp`).
