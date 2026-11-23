# Commands

`mw` is a short alias for `mapwright`. Every command has `--help`. Commands that act on a project use the
current folder (or `--path DIR`).

## Start and stop

| Command | What it does |
|---|---|
| `mapwright init [--connect AGENT] [--agents-md [FILE]] [--local \| --home DIR] [--apply-ignore]` | Track this project; the current state becomes step 0. Warns when `max_files` truncates the scan and suggests ignores for bulky generated/data folders (`--apply-ignore` saves them) |
| `mapwright init --local` / `--home DIR` | Keep this project's history in `<project>/.mapwright` (or DIR, relative to the project root) instead of `~/.mapwright`. Creates it with mode 0700, writes the marker `.mapwright/home.json`, adds it to `.gitignore`. With `--connect X` the MCP entry gets `env.MAPWRIGHT_HOME` and Claude Code hooks are prefixed with `MAPWRIGHT_HOME=…` |
| `mapwright open [--print] [--json] [--web [--site URL]]` | Open the map in the browser (starts the daemon if needed). `--web` opens the hosted website instead; its page calls your local daemon directly (the token travels in the URL hash, never to the host), and the site is added to `web_origins` |
| `mapwright up [-d] [--no-watch]` · `mapwright down` | Start (foreground or background) or stop the daemon |
| `mapwright watch` | Track from the files alone, without the daemon or any agent integration |
| `mapwright forget [--purge] [--yes]` | Stop tracking this project; `--purge` also deletes its stored history (only inside the Mapwright home; for a project-local home, that directory and its marker) |
| `mapwright token [--rotate] [--show]` | Where the local API token lives (never printed unless `--show`); `--rotate` writes a new one, then restart the daemon and rerun `mapwright open` |
| `mapwright doctor` | Check the setup |
| `mapwright guide` | Quick reference |

## Stopping Mapwright

| I want to… | Do this |
|---|---|
| Stop the map server (daemon) | `mapwright down` (started with `up -d` or `open`) · **Ctrl-C** if `mapwright up` runs in a terminal |
| Stop `mapwright watch` | **Ctrl-C** |
| Stop it if `down` does not answer | `pkill -f "mapwright up"` (it also frees port 7979) |
| Stop an agent from recording steps in this project | `mapwright disconnect claude-code` (also `cursor`, `vscode`, …; add `--scope user` if you connected it for every project). Restart the agent afterwards |
| Pause automatic steps but keep everything else | `mapwright settings auto_step off` |
| Remove all recorded history | stop the daemon, then delete the home: `~/.mapwright`, or `<project>/.mapwright` for a project-local home (`init --local`) |
| Remove the tool | `pipx uninstall mapwright-agent` (or `pip uninstall mapwright-agent`) |

The daemon only serves the map and watches files; the MCP server and hooks the agent starts are separate and exit
with the agent. Stopping the daemon never touches your project files.

## Agents

| Command | What it does |
|---|---|
| `mapwright connect --list` | Agents found on this machine and what is connected |
| `mapwright connect AGENT [--scope project\|user]` | Write the agent's MCP config (and hooks for Claude Code) |
| `mapwright connect --print AGENT` | Print the config to paste by hand |
| `mapwright disconnect AGENT [--scope …]` | Remove it again; config files (and empty `.claude/`, `.cursor/`, `.vscode/`, `.gemini/` folders) that are left with nothing in them are deleted |
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
| `mapwright check [--json]` | Check the architecture rules in `mapwright.toml`; exits 1 when one is broken (for CI and pre-commit) |
| `mapwright rules [--init [--force]]` | Show the rules, or write a starter `mapwright.toml` that holds for the code as it is today |
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

## Architecture rules

`mapwright.toml` in the project root (commit it) turns the map into a guardrail. Rules are checked at every step;
violations appear in Problems, in the agent's `map`, in exports, and make `mapwright check` exit non-zero.

```toml
[layers]                       # optional: pin paths to layers when the heuristics guess wrong
"src/app/web/**" = "ui"

[[forbid]]                     # an import that must not exist
from = "ui"                    # a layer name or a path glob
to = ["data"]                  # layers or globs
except = ["src/app/db/types.py"]
reason = "UI goes through services"

[limits]
no_cycles = true               # import cycles between modules
max_complexity = 25            # per function
max_module_lines = 800
# include_tests = true         # tests are skipped unless this is set
```

**Live feedback.** When `mapwright.toml` exists, the Claude Code hook refreshes the project after each edit and compares
the rule violations with the state before. If the edit introduced new ones, the agent gets one short line of context
(at most 3 items), for example `Mapwright: this edit broke a rule: src/ui/v.py [ui] imports src/db/m.py [data]: UI goes
through services. Fix it or explain.` Each violation is reported once; ones that existed before are never reported; the
hook never blocks and stays silent when nothing is new. Turn it off with `mapwright settings live_feedback false`.

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
| `auto_step` | `turn` | `turn`: close a step when an agent turn ends (Claude Code Stop/SessionEnd hooks). Waits while another session in the project is mid-turn (up to 5 min), ignores subagent stops and re-fired Stop hooks, merges turn ends within 2 s, and creates no step for turns with no file changes or only generated/lockfile changes (lockfiles, build output, minified/map files, shards, large data JSON, tool config, ignored files); those are still recorded, collapsed into one `generated/lockfile (N files)` line, and not counted. Titles come from the first clear sentence of the prompt (≤ ~60 chars) or are computed from the changes for long prompts; the prompt is kept (redacted) as the intent · `idle`: after a quiet period · `off` |
| `idle_seconds` | `60` | Quiet period for `idle` (and for agents without hooks) |
| `watch_interval` | `2.0` | Seconds between scans while the daemon runs |
| `brief_budget` | `2400` | Characters in `map` / `brief` (about 600 tokens) |
| `max_files` | `5000` | Cap on tracked files. When hit, `init`, `doctor` and `state` (`truncated_info`) show files seen and the folders that used the budget |
| `web_origins` | `["https://mapwright.pages.dev"]` | Hosted sites allowed to call this daemon from the browser. Exact origins only (https, or loopback http); the token is still required |
| `live_feedback` | `true` | After an edit, the Claude Code hook tells the agent about architecture-rule violations or import cycles that the edit introduced |
| `respect_gitignore` | `true` | Skip files matched by `.gitignore` (root and nested) and `.git/info/exclude` |
| `ignore` | `[]` | Extra names or gitignore-style patterns, e.g. `["public/question-bank/**", "*.pdf", "apps/*/dist"]`. Plain names match at any depth; `!pattern` re-includes something `.gitignore` excludes |
| `redact` | `true` | Redact secrets in code shown in the UI |
| `theme` · `font_size` | `dark` · `13` | Appearance |

Home resolution: `MAPWRIGHT_HOME` env, then a project-local home found by walking up from the current directory (or `--path`, `--root`, or the hook's cwd) to a `.mapwright/home.json` marker, then `~/.mapwright`. One daemon serves one home, so `open`/`up` start it with the project's home and refuse (with a message) if a daemon with a different home holds the port.

Environment: `MAPWRIGHT_HOME` (default `~/.mapwright`), `MAPWRIGHT_PORT` (default `7979`), `MAPWRIGHT_ROOT` (project for `mcp`).
