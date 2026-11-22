// Mapwright plugin for opencode: reports prompts, file edits and idle (turn end) to Mapwright,
// so steps close by themselves. The map and tools come from the MCP server (`mapwright connect opencode`).
// Install: copy to .opencode/plugin/ (project) or ~/.config/opencode/plugin/ (all projects).
import { spawn } from "node:child_process"

const CMD = process.env.MAPWRIGHT_CMD || "mapwright"

function report(payload) {
  try {
    const p = spawn(CMD, ["hook", "opencode"], { stdio: ["pipe", "ignore", "ignore"] })
    p.on("error", () => {})
    p.stdin.end(JSON.stringify(payload))
  } catch {}
}

export const Mapwright = async ({ directory, worktree }) => {
  const cwd = directory || worktree || process.cwd()
  return {
    "tool.execute.after": async (input) => {
      report({ hook_event_name: "PostToolUse", tool_name: input.tool, tool_input: input.args || {}, cwd })
    },
    "chat.message": async (_input, output) => {
      const text = (output?.parts || []).filter((p) => p.type === "text" && !p.synthetic).map((p) => p.text).join("\n")
      if (text) report({ hook_event_name: "UserPromptSubmit", prompt: text, cwd })
    },
    event: async ({ event }) => {
      if (event?.type === "session.idle") report({ hook_event_name: "Stop", cwd })
    },
  }
}
