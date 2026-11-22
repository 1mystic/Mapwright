"""Hook client: agents report prompts, tool calls and turn ends here (Claude Code command hooks,
the opencode plugin, or anything that can run a command with JSON on stdin).

It never blocks the agent and never prints to stdout: whatever goes wrong, it exits 0. A turn end
closes a step by itself when the auto-step setting allows it, so steps happen even if the agent
never calls the `step` tool.
"""

from __future__ import annotations

import json
import os
import re
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


_READ_ONLY = {"ls", "cat", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag", "find", "fd", "pwd", "echo", "printf", "wc", "which",
              "whoami", "date", "env", "printenv", "tree", "stat", "file", "du", "df", "diff", "sort", "uniq", "cut", "tr", "less",
              "more", "type", "realpath", "dirname", "basename", "test", "true", "sleep", "jq", "node_version", "ps", "id", "uname"}
_GIT_READ = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files", "blame", "remote", "describe", "config", "grep", "shortlog"}
_WRITING = re.compile(r"(?<![<=>&|0-9])>{1,2}(?![&>])|\btee\b|\s-delete\b|\s-exec\b|\s-i\b|\bsed\s+-[a-z]*i|\bxargs\b|\$\(|`")


def read_only_bash(cmd: str) -> bool:
    """True when a shell command only looks at things (cheap heuristic: every `;`/`&&`/`||`/`|`-separated
    part starts with a known read-only program, and there is no redirect, tee, in-place edit or substitution)."""
    if not cmd or _WRITING.search(cmd):
        return False
    for part in re.split(r"&&|\|\||;|\||\n", cmd):
        words = part.split()
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]
        if not words:
            continue
        prog = os.path.basename(words[0])
        if prog == "git":
            rest = [w for w in words[1:] if not w.startswith("-")]
            if not rest or rest[0] not in _GIT_READ:
                return False
        elif prog not in _READ_ONLY:
            return False
    return True


def handle(agent: str, payload: dict) -> None:
    from .track import open_project
    cwd = payload.get("cwd") or payload.get("directory") or os.getcwd()
    if not os.path.isdir(cwd):
        return
    home = os.path.realpath(os.path.expanduser("~"))
    if os.path.realpath(cwd) in (home, "/"):
        return  # never track a whole home directory
    ev = payload.get("hook_event_name") or payload.get("event") or ""
    if ev == "SubagentStop":
        return  # a subagent finishing is not the end of the user's turn
    p = open_project(cwd)
    session = payload.get("session_id") or payload.get("sessionID") or payload.get("sessionId") or ""
    if ev in ("UserPromptSubmit", "prompt"):
        p.record("prompt", text=payload.get("prompt") or payload.get("text") or "", agent=agent, session=session)
    elif ev in ("PostToolUse", "tool"):
        tool = str(payload.get("tool_name") or payload.get("tool") or "")
        ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else payload.get("args") or {}
        is_shell = tool.lower() in ("bash", "shell", "run_terminal_cmd", "execute_command")
        if is_shell and read_only_bash(str(ti.get("command") or ti.get("cmd") or "")):
            return
        if tool in WRITE_TOOLS or is_shell or tool.startswith("mcp__"):
            root = p.root + "/"
            files = [os.path.relpath(f, p.root) if os.path.isabs(f) and f.startswith(root) else f for f in _files(ti)]
            p.record("tool", tool=tool, files=files, agent=agent, session=session)
    elif ev in ("Stop", "SessionEnd", "turn_end", "idle"):
        if payload.get("stop_hook_active") or payload.get("agent_id") or payload.get("agent_type"):
            return  # a Stop re-fired by a Stop hook, or one that comes from inside a subagent
        final = ev == "SessionEnd"
        with p.locked():  # record + step as one unit: concurrent hook processes cannot interleave
            p.record("turn_end", agent=agent, session=session)
            p.maybe_auto_step(session=str(session), final=final)


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
