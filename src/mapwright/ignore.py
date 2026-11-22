"""Ignore handling: a stdlib-only gitignore matcher plus suggestions for bulky generated/data folders.

`Matcher` combines .git/info/exclude, the root and nested .gitignore files (when `respect_gitignore`)
and the user's `ignore` setting (gitignore patterns; plain names match at any depth). It holds no
module state, so concurrent scans of different projects do not interfere.
"""

from __future__ import annotations

import os
import re
from collections import Counter

DATA_EXT = {".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".parquet", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp",
            ".svg", ".avif", ".ico", ".bin", ".dat", ".xml", ".txt", ".md", ".mp3", ".mp4", ".webm", ".woff", ".woff2",
            ".ttf", ".zip", ".gz", ".map", ".html", ".xlsx", ".sqlite", ".db"}
GENERATED_NAMES = {"storybook-static", "__generated__", ".docusaurus", ".angular", ".expo", ".vercel", ".netlify",
                   "generated", "_next", ".astro", ".yarn", ".pnpm-store", "playwright-report", "test-results"}
SKIP_SURVEY = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mapwright", "dist", "build", ".next", "out", "coverage",
               "target", ".tox", "site-packages"}


def _translate(pat: str) -> str:
    out, i, n = [], 0, len(pat)
    while i < n:
        ch = pat[i]
        if pat.startswith("**", i):
            j = i + 2
            while j < n and pat[j] == "*":
                j += 1
            at_start = i == 0 or pat[i - 1] == "/"
            if at_start and j < n and pat[j] == "/":
                out.append("(?:.*/)?")
                i = j
                i += 1
                continue
            out.append(".*")
            i = j
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        elif ch == "[":
            j = i + 1
            if j < n and pat[j] in "!^":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                j += 1
            if j >= n:
                out.append(r"\[")
            else:
                body = pat[i + 1:j]
                neg = body[:1] in ("!", "^")
                if neg:
                    body = body[1:]
                body = body.replace("\\", "\\\\")
                out.append("[" + ("^" if neg else "") + body + "]")
                i = j
        elif ch == "\\" and i + 1 < n:
            i += 1
            out.append(re.escape(pat[i]))
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)


class Rule:
    __slots__ = ("base", "neg", "dir_only", "anchored", "rx")

    def __init__(self, base: str, neg: bool, dir_only: bool, anchored: bool, rx):
        self.base, self.neg, self.dir_only, self.anchored, self.rx = base, neg, dir_only, anchored, rx

    def match(self, rel: str, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        if self.base:
            if not rel.startswith(self.base + "/"):
                return False
            rel = rel[len(self.base) + 1:]
        if not self.anchored:
            rel = rel.rsplit("/", 1)[-1]
        return self.rx.fullmatch(rel) is not None


def parse_line(line: str, base: str = "") -> Rule | None:
    line = line.rstrip("\r\n")
    if not line.strip() or line.startswith("#"):
        return None
    while line.endswith(" ") and not line.endswith("\\ "):  # trailing spaces drop unless escaped
        line = line[:-1]
    neg = line.startswith("!")
    if neg:
        line = line[1:]
    dir_only = line.endswith("/")
    line = line.rstrip("/")
    if not line:
        return None
    anchored = "/" in line
    line = line.lstrip("/")
    if not line:
        return None
    try:
        rx = re.compile(_translate(line))
    except re.error:
        return None
    return Rule(base, neg, dir_only, anchored, rx)


def parse(text: str, base: str = "") -> list[Rule]:
    return [r for r in (parse_line(ln, base) for ln in text.splitlines()) if r]


def _decide(rules, rel: str, is_dir: bool):
    verdict = None
    for r in rules:
        if r.match(rel, is_dir):
            verdict = not r.neg
    return verdict


class Matcher:
    """gitignore semantics. Nested .gitignore files are read lazily as the scan descends."""

    def __init__(self, root: str, patterns=(), respect_gitignore: bool = True):
        self.root = root
        self.respect = respect_gitignore
        self.user = [r for r in (parse_line(p) for p in patterns or ()) if r]
        self._dir_rules: dict[str, list[Rule]] = {}

    def _read(self, path: str, base: str) -> list[Rule]:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return parse(fh.read(), base)
        except OSError:
            return []

    def _rules_for(self, d: str) -> list[Rule]:
        got = self._dir_rules.get(d)
        if got is not None:
            return got
        if d == "":
            rules = (self._read(os.path.join(self.root, ".git", "info", "exclude"), "")
                     + self._read(os.path.join(self.root, ".gitignore"), ""))
        else:
            parent = d.rsplit("/", 1)[0] if "/" in d else ""
            rules = self._rules_for(parent) + self._read(os.path.join(self.root, *d.split("/"), ".gitignore"), d)
        self._dir_rules[d] = rules
        return rules

    def matches(self, rel: str, is_dir: bool) -> bool:
        """Does this one entry match (its parents assumed not ignored, as in a pruned scan)?"""
        if self.user:
            v = _decide(self.user, rel, is_dir)
            if v is not None:
                return v
        if not self.respect:
            return False
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        return bool(_decide(self._rules_for(parent), rel, is_dir))

    def is_ignored(self, rel: str, is_dir: bool = False) -> bool:
        """Full check including ancestors (an ignored directory cannot be re-included)."""
        parts = rel.replace(os.sep, "/").strip("/").split("/")
        for k in range(1, len(parts) + 1):
            if self.matches("/".join(parts[:k]), is_dir if k == len(parts) else True):
                return True
        return False


def survey(root: str, matcher: Matcher | None = None, limit: int = 200_000) -> dict[str, int]:
    """rel path -> size for every non-ignored file of any type (used only by `init` suggestions)."""
    out: dict[str, int] = {}
    for dirpath, dirs, files in os.walk(root):
        rd = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rd = "" if rd == "." else rd
        keep = []
        for d in sorted(dirs):
            rel = f"{rd}/{d}" if rd else d
            if d in SKIP_SURVEY or d.endswith(".egg-info") or (matcher and matcher.matches(rel, True)):
                continue
            keep.append(d)
        dirs[:] = keep
        for f in sorted(files):
            rel = f"{rd}/{f}" if rd else f
            if matcher and matcher.matches(rel, False):
                continue
            try:
                out[rel] = os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                continue
            if len(out) >= limit:
                return out
    return out


def suggest_ignores(files: dict[str, int], min_files: int = 200, min_bytes: int = 50_000_000) -> list[dict]:
    """Pure heuristic. `files` maps rel path -> size. Returns [{pattern, files, bytes, reason}], largest first.

    A directory is suggested when it has at least `min_files` files or `min_bytes` bytes and is mostly data
    (json/pdf/images/csv/...), when it has a generated-looking name, or when its name says "bank".
    The highest qualifying directory wins; its subtree is not reported again.
    """
    tree: dict[str, dict] = {}
    for rel, size in files.items():
        parts = rel.split("/")
        ext = os.path.splitext(parts[-1])[1].lower()
        for k in range(1, len(parts)):
            d = "/".join(parts[:k])
            t = tree.setdefault(d, {"files": 0, "bytes": 0, "data": 0, "ext": Counter()})
            t["files"] += 1
            t["bytes"] += size
            t["data"] += ext in DATA_EXT
            t["ext"][ext] += 1
    out, taken = [], []
    for d in sorted(tree, key=lambda x: (x.count("/"), x)):
        if any(d == t or d.startswith(t + "/") for t in taken):
            continue
        t, name = tree[d], d.rsplit("/", 1)[-1]
        mostly_data = t["data"] >= 0.8 * t["files"]
        top_ext, top_n = t["ext"].most_common(1)[0]
        reason = None
        if name in GENERATED_NAMES:
            reason = "generated output"
        elif "bank" in name.lower() and t["files"] >= 20 and mostly_data:
            reason = f"data folder ({t['files']} files)"
        elif mostly_data and t["files"] >= min_files:
            reason = f"{t['files']} mostly data/binary files" + (f", {top_n} of them {top_ext}" if top_n >= 0.5 * t["files"] else "")
        elif mostly_data and t["bytes"] >= min_bytes:
            reason = f"{t['bytes'] // 1_000_000} MB of data/binary files"
        if reason:
            while True:  # narrow to the one child holding nearly everything
                kids = [k for k in tree if k.startswith(d + "/") and k.count("/") == d.count("/") + 1 and tree[k]["files"] >= 0.9 * t["files"]]
                if not kids or name in GENERATED_NAMES:
                    break
                d = kids[0]
                t = tree[d]
            taken.append(d)
            out.append({"pattern": d + "/", "files": t["files"], "bytes": t["bytes"], "reason": reason})
    covered = tuple(t + "/" for t in taken)
    mins = [r for r in files if r.endswith((".min.js", ".min.css")) and not r.startswith(covered)]
    if len(mins) >= 3:
        out.append({"pattern": "*.min.*", "files": len(mins), "bytes": sum(files[r] for r in mins), "reason": "minified bundles"})
    out.sort(key=lambda s: (-s["files"], s["pattern"]))
    return out
