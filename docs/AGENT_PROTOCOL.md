# Agent protocol

What an agent does with Mapwright, and why each part is shaped the way it is.

## The loop

1. **Start of a task:** call `map`. Read structure from it instead of listing directories and opening files.
2. **Plan:** `todo add` for each part.
3. **Before changing a function:** `symbol NAME` to see its callers, callees and tables. Open the file only to edit.
4. **After each meaningful change:** `step` with a short title of what was done.
5. **When a part is finished:** `todo done ID` with the symbol or file you changed as `evidence`.
6. **When you implement a mechanism** (cache, retry, queue, auth …): `claim CONCEPT SYMBOL`.
7. Optional: `note` a module's role; `link` two symbols the code does not connect directly.

With hooks (Claude Code, opencode), turn ends close a step even if the agent forgets step 4.

## Why it is cheap

- Tool definitions total under 3,000 characters (they are sent with every request).
- `map` is capped (default 2,400 characters, about 600 tokens) and shrinks long sections first.
- No result contains source code. Results point at `file:line`, so the agent reads only what it needs.
- The agent sends titles and ids, never diagrams, file lists or summaries. Diagrams, icons, layouts and
  flowcharts are built from the code by Mapwright.

## Why it cannot be gamed

| The agent says | Mapwright checks |
|---|---|
| a step title | The changed files are computed. Titles that mention tests, migrations, routes, tables, docs or infrastructure are checked against what actually changed. |
| a todo is done | The evidence must exist and must have changed after the todo was added. |
| a symbol implements a concept | The concept's signals must appear in that symbol's code (decorators included). Only a module-level import counts as "weak". |
| a note or link | The symbols must exist; when they disappear the note or link is marked stale. |

## MCP details

- Transport: stdio, JSON-RPC 2.0, one message per line. Protocol versions `2025-06-18`, `2025-03-26`, `2024-11-05`.
- Project root: `--root`, else `MAPWRIGHT_ROOT`, else the server's working directory (the nearest folder with `.git`).
- Errors in a tool are returned as `isError: true` with a one-line message; the session is never interrupted.

## Hook events

`mapwright hook AGENT` reads one JSON object on stdin and always exits 0 without output.

| `hook_event_name` | Recorded |
|---|---|
| `UserPromptSubmit` (`prompt`) | the prompt, redacted, up to 300 characters |
| `PostToolUse` (`tool_name`, `tool_input`) | the tool and the files it named |
| `Stop` / `SessionEnd` | a turn end; closes a step if files changed and `auto_step` allows |
