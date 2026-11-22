"""Hook client: agents report prompts, tool calls and turn ends here (Claude Code command hooks,
the opencode plugin, or anything that can run a command with JSON on stdin).

It never blocks the agent and never prints to stdout: whatever goes wrong, it exits 0. A turn end
closes a step by itself when the auto-step setting allows it, so steps happen even if the agent
never calls the `step` tool.
"""

from __future__ import annotations

import json
import os
import sys

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "write", "edit", "patch", "apply_patch", "multiedit", "create_file",
               "str_replace_editor", "replace_in_file", "write_to_file"}


def _files(ti: dict) -> list[str]:
    out = []
    for k in ("file_path", "path", "notebook_path", "filePath", "target_file"):
        v = ti.get(k)
        if isinstance(v, str) and v:
            out.append(v)
    return out[:20]


def handle(agent: str, payload: dict) -> None:
    from .track import open_project
    cwd = payload.get("cwd") or payload.get("directory") or os.getcwd()
    if not os.path.isdir(cwd):
        return
    home = os.path.realpath(os.path.expanduser("~"))
    if os.path.realpath(cwd) in (home, "/"):
        return  # never track a whole home directory
    from . import config
    config.set_start(cwd)  # a project-local home is found from the payload cwd (MAPWRIGHT_HOME still wins)
    p = open_project(cwd)
    ev = payload.get("hook_event_name") or payload.get("event") or ""
    if ev in ("UserPromptSubmit", "prompt"):
        p.record("prompt", text=payload.get("prompt") or payload.get("text") or "", agent=agent)
    elif ev in ("PostToolUse", "tool"):
        tool = str(payload.get("tool_name") or payload.get("tool") or "")
        ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else payload.get("args") or {}
        if tool in WRITE_TOOLS or tool.lower() in ("bash", "shell", "run_terminal_cmd", "execute_command") or tool.startswith("mcp__"):
            root = p.root + "/"
            files = [os.path.relpath(f, p.root) if os.path.isabs(f) and f.startswith(root) else f for f in _files(ti)]
            p.record("tool", tool=tool, files=files, agent=agent)
    elif ev in ("Stop", "SessionEnd", "turn_end", "idle"):
        p.record("turn_end", agent=agent)
        p.maybe_auto_step()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    agent = argv[0] if argv else "claude-code"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if isinstance(payload, dict):
            handle(agent, payload)
    except Exception as e:  # a hook must never break the agent
        try:
            from . import config
            with open(config.home() / "hook-errors.log", "a") as fh:
                fh.write(f"{type(e).__name__}: {e}\n")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
