# Mapwright for VS Code

A live map of what your coding agent is building, beside your code: architecture, files, classes,
data model, cloud, API flows, call graph, function flowcharts and every step the agent took.

Works in VS Code, Cursor, Windsurf and VSCodium.

## Requires

The Mapwright CLI: `pipx install mapwright` (or `pip install mapwright`). If it is not on your PATH,
set **Mapwright: Command** to e.g. `python3 -m mapwright`.

## Commands

- **Mapwright: Open Map**: the map in a panel beside the editor (or your browser, see settings)
- **Mapwright: Track This Workspace**: start tracking; the current state becomes step 0
- **Mapwright: Connect an Agent**: writes the MCP config for Copilot, Claude Code, Cursor, Windsurf, opencode, Codex or Gemini
- **Mapwright: Record Step** · **Copy Agent Brief**

The status bar shows the current step, pending changes, open todos and unverified claims.

On VS Code 1.101 and later the extension also offers the Mapwright MCP server to Copilot agent mode directly.
