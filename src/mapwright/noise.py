"""Noise classifier: which changed paths are lockfiles, build output, generated shards or tool config.

Noisy changes are still tracked in a step, but they are collapsed into one line and never count
towards `files changed`, and a turn that only touched noisy files does not warrant an auto step.
Pure functions, stdlib only.
"""

from __future__ import annotations

import posixpath
import re
from typing import Callable, Iterable

LOCKFILES = {
    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "bun.lock", "poetry.lock",
    "uv.lock", "pipfile.lock", "cargo.lock", "gemfile.lock", "composer.lock", "go.sum", "pdm.lock", "mix.lock",
    "podfile.lock", "flake.lock", "packages.lock.json", "gradle.lockfile",
}
NOISE_DIRS = {
    "node_modules", "dist", "build", "out", ".next", ".nuxt", ".svelte-kit", ".turbo", ".cache", ".parcel-cache",
    "coverage", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "target", ".gradle", ".venv", "venv",
    ".mapwright", ".mapwright-venv", ".idea", ".firebase", "shards", "__generated__", "generated",
}
_FILE_PATTERNS = re.compile(
    r"(\.min\.(js|css)$|\.map$|\.bundle\.js$|\.chunk\.js$|\.pyc$|\.log$|\.tsbuildinfo$|\.generated\.\w+$|"
    r"_pb2(_grpc)?\.py$|\.pb\.go$|\.snap$|(^|[-_.])shard[-_.]?\d+|[-_.]part[-_.]?\d{3,}\.\w+$|^\.ds_store$)",
    re.I)
LARGE_DATA_LINES = 2000  # a .json/.jsonl/.csv change bigger than this (added+removed lines) is data, not design


def classify(path: str, lines_changed: int | None = None, is_ignored: Callable[[str], bool] | None = None) -> str | None:
    """Why `path` is noise ('lockfile', 'generated', 'tool config', 'data', 'ignored'), or None."""
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    base = posixpath.basename(p).lower()
    if base in LOCKFILES:
        return "lockfile"
    parts = [s.lower() for s in p.split("/")[:-1]]
    if base == ".mcp.json" or ".claude" in parts:
        return "tool config"
    if any(s in NOISE_DIRS for s in parts) or _FILE_PATTERNS.search(base):
        return "generated"
    if lines_changed is not None and lines_changed >= LARGE_DATA_LINES and base.endswith((".json", ".jsonl", ".csv", ".ndjson")):
        return "data"
    fn = is_ignored if is_ignored is not None else default_is_ignored()
    if fn is not None:
        try:
            if fn(p):
                return "ignored"
        except Exception:
            pass
    return None


def default_is_ignored() -> Callable[[str], bool] | None:
    """`mapwright.ignore.is_ignored(path)` when that module exists (gitignore-aware scanning plugs in here)."""
    try:
        from . import ignore as _ig
    except ImportError:
        return None
    fn = getattr(_ig, "is_ignored", None)
    return fn if callable(fn) else None


def split(changes: Iterable[dict], is_ignored: Callable[[str], bool] | None = None) -> tuple[list[dict], list[dict]]:
    """(meaningful, noisy) changes. Each noisy change is a copy with a `noise` reason key."""
    real, noisy = [], []
    for c in changes:
        n = (c.get("added") or 0) + (c.get("removed") or 0) if ("added" in c or "removed" in c) else None
        why = classify(c["path"], n, is_ignored)
        if why:
            noisy.append({**c, "noise": why})
        else:
            real.append(c)
    return real, noisy


def collapse_line(noisy: list[dict]) -> str:
    return f"generated/lockfile ({len(noisy)} file{'s' if len(noisy) != 1 else ''})"
