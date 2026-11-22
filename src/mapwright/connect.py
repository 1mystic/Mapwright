"""Connect Mapwright to coding agents: write (or remove) the MCP server entry, and hooks where the
agent supports them, in each tool's own config file.

Existing config is merged, never replaced: a file that is not valid JSON is left alone and the
call fails with a message. A copy of every file is saved under ~/.mapwright/backups before it is
changed.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

from . import config

NAME = "mapwright"


def server_command() -> tuple[str, list[str]]:
    exe = shutil.which("mapwright")
    if exe:
        return "mapwright", ["mcp"]
    return sys.executable, ["-m", "mapwright", "mcp"]


def hook_command(agent: str) -> str:
    exe = shutil.which("mapwright")
    return f"mapwright hook {agent}" if exe else f'"{sys.executable}" -m mapwright hook {agent}'


def hook_command_with_home(agent: str, home: str | None = None) -> str:
    cmd = hook_command(agent)
    if not home:
        return cmd
    if sys.platform.startswith("win"):  # best effort: cmd.exe form
        return f'cmd /d /c "set MAPWRIGHT_HOME={home}&& {cmd}"'
    return f"MAPWRIGHT_HOME={shlex.quote(home)} {cmd}"


def _vscode_user_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Code/User"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home())) / "Code/User"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Code/User"


def _cc_dir() -> Path:
    return Path(os.environ.get("MAPWRIGHT_CLAUDE_DIR", Path.home() / ".claude"))


# target id: title, website hint, {scope: (path factory, format)}
TARGETS: dict[str, dict] = {
    "claude-code": {"title": "Claude Code", "how": "MCP server + hooks (prompts, edits, turn ends)",
                    "scopes": {"project": lambda r: Path(r) / ".mcp.json", "user": lambda r: Path(os.environ.get("MAPWRIGHT_CLAUDE_JSON", Path.home() / ".claude.json"))},
                    "format": "mcpServers"},
    "cursor": {"title": "Cursor", "how": "MCP server", "format": "mcpServers",
               "scopes": {"project": lambda r: Path(r) / ".cursor/mcp.json", "user": lambda r: Path.home() / ".cursor/mcp.json"}},
    "vscode": {"title": "VS Code (Copilot agent mode)", "how": "MCP server (+ the Mapwright extension for the map inside the editor)", "format": "servers",
               "scopes": {"project": lambda r: Path(r) / ".vscode/mcp.json", "user": lambda r: _vscode_user_dir() / "mcp.json"}},
    "windsurf": {"title": "Windsurf", "how": "MCP server", "format": "mcpServers",
                 "scopes": {"user": lambda r: Path.home() / ".codeium/windsurf/mcp_config.json"}},
    "opencode": {"title": "opencode", "how": "MCP server", "format": "opencode",
                 "scopes": {"project": lambda r: Path(r) / "opencode.json", "user": lambda r: Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode/opencode.json"}},
    "codex": {"title": "Codex CLI", "how": "MCP server", "format": "toml",
              "scopes": {"user": lambda r: Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"}},
    "gemini": {"title": "Gemini CLI", "how": "MCP server", "format": "mcpServers",
               "scopes": {"project": lambda r: Path(r) / ".gemini/settings.json", "user": lambda r: Path.home() / ".gemini/settings.json"}},
    "claude-desktop": {"title": "Claude Desktop", "how": "MCP server (map and steps; no file edits of its own)", "format": "mcpServers",
                       "scopes": {"user": lambda r: (Path.home() / "Library/Application Support/Claude/claude_desktop_config.json") if sys.platform == "darwin"
                                  else Path(os.environ.get("APPDATA", Path.home() / ".config")) / "Claude/claude_desktop_config.json"}},
}
MANUAL = {
    "cline": ("Cline / Roo Code", "Open the extension's MCP settings (\"Configure MCP Servers\") and add the JSON below under mcpServers."),
    "zed": ("Zed", "Add to settings.json under \"context_servers\": {\"mapwright\": {\"command\": {\"path\": CMD, \"args\": ARGS}}}."),
    "jetbrains": ("JetBrains AI Assistant / Junie", "Settings → Tools → AI Assistant → Model Context Protocol → Add, then paste the JSON below."),
    "any": ("Any other agent", "Any MCP client: add the JSON below. No MCP at all: run `mapwright watch` in the project; changes are tracked from the files."),
}


def snippet(target: str = "any", root: str | None = None, home: str | None = None) -> str:
    cmd, args = server_command()
    env = {"MAPWRIGHT_HOME": str(home)} if home else None
    if target == "vscode":
        return json.dumps({"servers": {NAME: _entry("vscode", cmd, args, env)}}, indent=2)
    if target == "opencode":
        return json.dumps({"mcp": {NAME: _entry("opencode", cmd, args, env)}}, indent=2)
    if target == "codex":
        text = f'[mcp_servers.{NAME}]\ncommand = "{cmd}"\nargs = {json.dumps(args)}\n'
        if env:
            text += f"\n[mcp_servers.{NAME}.env]\nMAPWRIGHT_HOME = {json.dumps(env['MAPWRIGHT_HOME'])}\n"
        return text
    if target == "zed":
        c = {"path": cmd, "args": args}
        if env:
            c["env"] = env
        return json.dumps({"context_servers": {NAME: {"command": c}}}, indent=2)
    return json.dumps({"mcpServers": {NAME: _entry("mcpServers", cmd, args, env)}}, indent=2)


def _entry(fmt: str, cmd: str, args: list[str], env: dict | None) -> dict:
    if fmt == "vscode":
        e = {"type": "stdio", "command": cmd, "args": args}
        if env:
            e["env"] = env
    elif fmt == "opencode":
        e = {"type": "local", "command": [cmd, *args], "enabled": True}
        if env:
            e["environment"] = env
    else:
        e = {"command": cmd, "args": args}
        if env:
            e["env"] = env
    return e


def _backup(path: Path) -> None:
    if path.exists():
        dest = config.home() / "backups" / f"{path.name}.{time.strftime('%Y%m%d-%H%M%S')}.{abs(hash(str(path))) % 10000}"
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(path, dest)


def _load(path: Path) -> dict:
    if not path.exists() or not path.read_text().strip():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        raise ValueError(f"{path} is not plain JSON ({e.msg}); add the entry by hand: `mapwright connect --print`") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    tmp = path.with_name(path.name + ".mapwright.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


_TOML_BLOCK = re.compile(r"(?ms)^\[mcp_servers\.mapwright\]\n.*?(?=^\[(?!mcp_servers\.mapwright\.)|\Z)")


def _hooks_path(scope: str, root: str) -> Path:
    return (Path(root) / ".claude/settings.local.json") if scope == "project" else _cc_dir() / "settings.json"


_OWN_DIRS = {".claude", ".cursor", ".vscode", ".gemini"}


def _remove_file(path: Path) -> None:
    """Back up, then delete a config file that uninstall left with nothing in it; drop its directory if that is empty too."""
    _backup(path)
    path.unlink()
    if path.parent.name in _OWN_DIRS and path.parent != Path.home():
        try:
            path.parent.rmdir()
        except OSError:
            pass


def _claude_hooks(path: Path, on: bool, home: str | None = None) -> None:
    data = _load(path)
    hooks = data.get("hooks") or {}
    for ev in list(hooks):
        hooks[ev] = [m for m in hooks[ev] if not any("mapwright" in (h.get("command") or "") for h in m.get("hooks", []))]
        if not hooks[ev]:
            del hooks[ev]
    if on:
        cmd = hook_command_with_home("claude-code", home)
        entry = lambda matcher=None: {**({"matcher": matcher} if matcher else {}), "hooks": [{"type": "command", "command": cmd, "timeout": 10}]}  # noqa: E731
        hooks.setdefault("UserPromptSubmit", []).append(entry())
        hooks.setdefault("PostToolUse", []).append(entry("Write|Edit|MultiEdit|NotebookEdit|Bash"))
        hooks.setdefault("Stop", []).append(entry())
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    if not on and not data:
        _remove_file(path)
    else:
        _save(path, data)


def install(target: str, scope: str = "project", root: str | None = None, home: str | None = None) -> list[str]:
    """Returns the files written. With home, the MCP server and the Claude Code hooks run with MAPWRIGHT_HOME=home."""
    home = os.path.abspath(str(home)) if home else None
    root = root or os.getcwd()
    spec = TARGETS.get(target)
    if not spec:
        raise ValueError(f"unknown target {target}; one of: {', '.join(TARGETS)}")
    if scope not in spec["scopes"]:
        raise ValueError(f"{spec['title']} supports scope: {', '.join(spec['scopes'])}")
    path = spec["scopes"][scope](root)
    cmd, args = server_command()
    env = {"MAPWRIGHT_HOME": home} if home else None
    written = [str(path)]
    if target == "claude-code" and scope == "user" and _claude_cli_add(cmd, args, home):
        pass  # `claude mcp add -s user` wrote it
    elif spec["format"] == "toml":
        text = path.read_text() if path.exists() else ""
        block = snippet("codex", home=home)
        text = _TOML_BLOCK.sub(block, text) if _TOML_BLOCK.search(text) else (text.rstrip() + "\n\n" if text.strip() else "") + block
        path.parent.mkdir(parents=True, exist_ok=True)
        _backup(path)
        path.write_text(text)
    else:
        data = _load(path)
        if spec["format"] == "servers":
            data.setdefault("servers", {})[NAME] = _entry("vscode", cmd, args, env)
        elif spec["format"] == "opencode":
            data.setdefault("$schema", "https://opencode.ai/config.json")
            data.setdefault("mcp", {})[NAME] = _entry("opencode", cmd, args, env)
        else:
            entry = _entry("mcpServers", cmd, args, env)
            if target == "claude-code" and scope == "project":
                entry = {"type": "stdio", **entry}
            data.setdefault("mcpServers", {})[NAME] = entry
        _save(path, data)
    if target == "claude-code":
        hp = _hooks_path(scope, root)
        _claude_hooks(hp, True, home)
        written.append(str(hp))
    return written


def _claude_cli_add(cmd: str, args: list[str], home: str | None = None) -> bool:
    """User scope for Claude Code: let its own CLI edit ~/.claude.json when it is installed."""
    import subprocess
    exe = shutil.which("claude")
    if not exe or os.environ.get("MAPWRIGHT_CLAUDE_JSON"):
        return False
    subprocess.run([exe, "mcp", "remove", "-s", "user", NAME], capture_output=True, timeout=30)
    r = subprocess.run([exe, "mcp", "add", "-s", "user", *(["-e", f"MAPWRIGHT_HOME={home}"] if home else []), NAME, "--", cmd, *args], capture_output=True, timeout=30)
    return r.returncode == 0


def uninstall(target: str, scope: str = "project", root: str | None = None) -> list[str]:
    root = root or os.getcwd()
    spec = TARGETS.get(target)
    if not spec or scope not in spec["scopes"]:
        raise ValueError(f"unknown target or scope: {target} {scope}")
    path = spec["scopes"][scope](root)
    changed = []
    if path.exists():
        if spec["format"] == "toml":
            text = path.read_text()
            if _TOML_BLOCK.search(text):
                rest = _TOML_BLOCK.sub("", text).rstrip()
                if rest:
                    _backup(path)
                    path.write_text(rest + "\n")
                else:
                    _remove_file(path)
                changed.append(str(path))
        else:
            data = _load(path)
            key = {"servers": "servers", "opencode": "mcp"}.get(spec["format"], "mcpServers")
            if NAME in (data.get(key) or {}):
                del data[key][NAME]
                if not data[key]:
                    del data[key]
                # opencode's $schema is added by install() itself, so it alone counts as empty
                leftover = {"$schema": "https://opencode.ai/config.json"} if spec["format"] == "opencode" else {}
                if data == leftover:
                    _remove_file(path)
                else:
                    _save(path, data)
                changed.append(str(path))
    if target == "claude-code":
        hp = _hooks_path(scope, root)
        if hp.exists() and "mapwright" in hp.read_text():
            _claude_hooks(hp, False)
            changed.append(str(hp))
    return changed


def status(root: str | None = None) -> list[dict]:
    """Every target, with what is connected and whether the tool looks installed."""
    root_given = bool(root)
    root = root or os.getcwd()
    bins = {"claude-code": "claude", "cursor": "cursor", "vscode": "code", "windsurf": "windsurf", "opencode": "opencode",
            "codex": "codex", "gemini": "gemini", "claude-desktop": None}
    dirs = {"claude-code": _cc_dir(), "cursor": Path.home() / ".cursor", "vscode": _vscode_user_dir(), "windsurf": Path.home() / ".codeium/windsurf",
            "opencode": Path.home() / ".config/opencode", "codex": Path.home() / ".codex", "gemini": Path.home() / ".gemini",
            "claude-desktop": TARGETS["claude-desktop"]["scopes"]["user"]("").parent}
    out = []
    for tid, spec in TARGETS.items():
        scopes = {}
        for scope, fn in spec["scopes"].items():
            if scope == "project" and not root_given:
                scopes[scope] = {"path": None, "connected": False}
                continue
            path = fn(root)
            try:
                scopes[scope] = {"path": str(path), "connected": path.exists() and re.search(r'["\[.]mapwright["\]]|mcp_servers\.mapwright', path.read_text()) is not None}
            except OSError:
                scopes[scope] = {"path": str(path), "connected": False}
        installed = bool(bins.get(tid) and shutil.which(bins[tid])) or dirs[tid].exists()
        out.append({"id": tid, "title": spec["title"], "how": spec["how"], "installed": installed, "scopes": scopes,
                    "snippet": snippet(tid if tid in ("vscode", "opencode", "codex") else "any")})
    for mid, (title, how) in MANUAL.items():
        out.append({"id": mid, "title": title, "how": how, "installed": None, "scopes": {}, "manual": True,
                    "snippet": snippet(mid if mid == "zed" else "any")})
    return out


AGENTS_MD = """<!-- mapwright:start -->
## Project map (Mapwright)
This project is tracked by Mapwright. To save tokens and stay accurate:
- Start with the `map` tool (or `mapwright brief`) instead of listing and opening files to learn the structure.
- Use `find` / `symbol` to locate code and see callers and callees before reading a file.
- After each meaningful change, call `step` with a short title. Changed files and design deltas are computed for you.
- Keep the plan in `todo`; mark items done with the symbol or file you changed as evidence.
- `claim` a mechanism (see `catalog`) only for code that implements it; claims are checked.
<!-- mapwright:end -->
"""


def write_agents_md(root: str, filename: str = "AGENTS.md") -> str:
    path = Path(root) / filename
    text = path.read_text() if path.exists() else ""
    if "<!-- mapwright:start -->" in text:
        text = re.sub(r"(?s)<!-- mapwright:start -->.*?<!-- mapwright:end -->\n?", AGENTS_MD, text)
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + AGENTS_MD
    path.write_text(text)
    return str(path)
