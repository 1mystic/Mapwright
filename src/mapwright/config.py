"""Local state: home directory, token, port, settings and the list of tracked projects. Stdlib only."""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path

DEFAULT_PORT = 7979
DEFAULTS = {
    "theme": "dark",              # dark | light
    "font_size": 13,
    "auto_step": "turn",          # turn: at the end of each agent turn · idle: after a quiet period · off: only explicit steps
    "idle_seconds": 60,
    "watch_interval": 2.0,        # seconds between scans of tracked projects while the daemon runs
    "brief_budget": 2400,         # characters in `map` / `brief` (about 600 tokens)
    "max_files": 5000,
    "ignore": [],                 # extra names or gitignore-style patterns to skip (e.g. "public/bank/**", "*.pdf")
    "web_origins": ["https://mapwright.pages.dev"],  # hosted sites allowed to call this daemon from the browser (exact origins; the token is still required)
    "respect_gitignore": True,    # also skip what .gitignore / .git/info/exclude ignore
    "redact": True,
    "keep_blobs_days": 0,         # 0 = keep every file version
}


_START: str | None = None          # where project-local discovery starts (default: the current directory)
_CACHE: dict[tuple, Path] = {}
MARKER_DIR = ".mapwright"
MARKER = "home.json"


def set_start(path: str | os.PathLike | None) -> None:
    """Start project-local home discovery from this directory (a --path / --root / hook cwd) instead of the cwd."""
    global _START
    _START = os.path.abspath(os.fspath(path)) if path else None


def reset_cache() -> None:
    _CACHE.clear()


def local_home(start: str | os.PathLike | None = None) -> Path | None:
    """The project-local home found by walking up from start (default cwd) for .mapwright/home.json, or None."""
    try:
        cur = Path(os.path.abspath(os.fspath(start) if start else (_START or os.getcwd())))
    except OSError:
        return None
    user_home = Path.home()
    for d in [cur, *cur.parents]:
        if d == user_home:
            break  # ~/.mapwright is the default home, not a project marker
        marker = d / MARKER_DIR / MARKER
        if marker.is_file():
            data = read_json(marker, {})
            h = data.get("home") if isinstance(data, dict) else None
            if isinstance(h, str) and os.path.isabs(h):
                return Path(h)
            return None
    return None


def write_marker(root: str, home_dir: str) -> Path:
    """Record home_dir as the home for the project at root (<root>/.mapwright/home.json)."""
    m = Path(root) / MARKER_DIR / MARKER
    write_json(m, {"home": home_dir})
    reset_cache()
    return m


def home() -> Path:
    env = os.environ.get("MAPWRIGHT_HOME")
    key = (env, _START or os.getcwd())
    p = _CACHE.get(key)
    if p is None:
        p = Path(env) if env else (local_home() or Path.home() / ".mapwright")
        _CACHE[key] = p
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        if p.stat().st_mode & 0o077:
            p.chmod(0o700)
    except OSError:
        pass
    return p


def port() -> int:
    try:
        p = int(os.environ.get("MAPWRIGHT_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT
    return p if 0 < p < 65536 else DEFAULT_PORT


def base_url() -> str:
    return f"http://127.0.0.1:{port()}"


def token() -> str:
    f = home() / "token"
    for _ in range(2):
        try:
            tok = f.read_text().strip()
            if tok:
                return tok
            f.unlink()
        except OSError:
            pass
        tok = secrets.token_urlsafe(32)
        try:
            fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(tok)
        return tok
    return f.read_text().strip()


def read_json(path: Path | str, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path | str, data) -> None:
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def settings() -> dict:
    s = dict(DEFAULTS)
    saved = read_json(home() / "settings.json", {})
    if isinstance(saved, dict):
        for k, v in saved.items():
            want = DEFAULTS.get(k)
            if want is None:
                continue
            if type(v) is type(want) or (isinstance(want, float) and isinstance(v, int) and not isinstance(v, bool)):
                s[k] = v
    return s


def save_settings(changes: dict) -> dict:
    """Validate and save. Unknown keys and wrong types are rejected with a message."""
    errors = []
    s = settings()
    for k, v in changes.items():
        if k not in DEFAULTS:
            errors.append(f"unknown setting {k}")
            continue
        want = DEFAULTS[k]
        if isinstance(want, bool):
            ok = isinstance(v, bool)
        elif isinstance(want, (int, float)) and not isinstance(want, bool):
            ok = isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
            v = type(want)(v) if ok else v
        elif isinstance(want, list):
            ok = isinstance(v, list) and all(isinstance(x, str) and x.strip() and "\n" not in x for x in v)
        else:
            ok = isinstance(v, str)
        if k == "theme" and v not in ("dark", "light"):
            ok = False
        if k == "web_origins" and ok and not all(re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d{2,5})?|http://(127\.0\.0\.1|localhost)(:\d{2,5})?", x) for x in v):
            ok = False  # exact origins only: no paths, no wildcards, https unless loopback
        if k == "auto_step" and v not in ("turn", "idle", "off"):
            ok = False
        if k == "brief_budget" and ok and not 400 <= v <= 20000:
            ok = False
        if not ok:
            errors.append(f"bad value for {k}")
        else:
            s[k] = v
    if errors:
        raise ValueError("; ".join(errors))
    write_json(home() / "settings.json", {k: s[k] for k in DEFAULTS if s[k] != DEFAULTS[k]})
    return s


def projects() -> dict:
    return read_json(home() / "projects.json", {})


def register(key: str, root: str) -> None:
    reg = projects()
    if reg.get(key, {}).get("root") != root:
        import time
        reg[key] = {"root": root, "added": reg.get(key, {}).get("added", time.time())}
        write_json(home() / "projects.json", reg)


def unregister(key: str) -> bool:
    reg = projects()
    if reg.pop(key, None) is None:
        return False
    write_json(home() / "projects.json", reg)
    return True
