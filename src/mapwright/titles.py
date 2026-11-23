"""Derive a short, clean step title for automatic steps. Pure functions, stdlib only.

An auto step must never echo a long or messy prompt as its title. `derive_title` cleans the prompt
(markdown, code, paths, urls, filler) and uses its first meaningful sentence when that is short and
clear; otherwise it computes a title from the actual changes.
"""

from __future__ import annotations

import os
import re
from collections import Counter

MAX_TITLE = 60
_FILLER = re.compile(
    r"^(?:(?:hey|hi|hello|ok(?:ay)?|so|well|and|also|now|then|just|please|pls|plz|kindly|great|thanks|thank you|"
    r"can you|could you|would you|will you|can we|could we|let'?s|i want you to|i need you to|i want to|i need to|"
    r"i'd like you to|i would like you to|go ahead and|next|first|lastly)\b[,:;\s-]*)+", re.I)
_TRIVIAL = re.compile(r"^(?:y|yes|yeah|yep|no|ok|okay|k|continue|go|go on|proceed|do it|done|thanks|thank you|great|good|nice|"
                      r"sure|fine|retry|again|next|keep going|looks good|lgtm)\W*$", re.I)
_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_URL = re.compile(r"https?://\S+|www\.\S+")
_PATH = re.compile(r"(?<![\w])(?:~|\.{1,2})?/(?:[\w.@+-]+/)+[\w.@+-]*|(?<![\w])[\w.@+-]+/(?:[\w.@+-]+/)*[\w.@+-]+\.\w{1,6}\b")
_MD = re.compile(r"[*_#>`~|]+|^\s*[-+]\s+|^\s*\d+[.)]\s+", re.M)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|;\s+")


# Text an agent harness injects into the prompt stream: never the user's own words.
_INJECTED = ("pasted_content", "agent-message", "task-notification", "system-reminder", "ide_opened_file", "ide_selection",
             "local-command-stdout", "local-command-caveat", "command-name", "command-message", "command-args", "tool-use-id",
             "bash-input", "bash-stdout", "bash-stderr", "user-memory-input", "cross-session-message")
_INJECTED_BLOCK = re.compile(r"<(%s)\b[^>]*>.*?(?:</\1\s*>|\Z)" % "|".join(map(re.escape, _INJECTED)), re.S | re.I)
# Whole messages that are not from the user at all (as opposed to blocks that accompany the user's words).
_NOT_USER = ("agent-message", "task-notification", "cross-session-message", "local-command-stdout", "local-command-caveat",
             "command-name", "command-message", "bash-input", "bash-stdout", "bash-stderr")
_MACHINE_START = re.compile(r"^\s*(?:\[SYSTEM NOTIFICATION|Another Claude session sent a message|<(?:%s)\b)" % "|".join(map(re.escape, _NOT_USER)), re.I)
_TAG = re.compile(r"</?[A-Za-z][\w:-]*(?:\s[^<>]*)?/?>")


def human_text(text: str) -> str:
    """The user's own words: injected harness blocks (pasted content, agent messages, notifications, reminders) removed."""
    return " ".join(_TAG.sub(" ", _INJECTED_BLOCK.sub(" ", text or "")).split())


def clean_prompt(text: str) -> str:
    """Prompt text with fences, urls, paths, markdown and links removed, whitespace collapsed."""
    t = _FENCE.sub(" ", human_text(text))
    t = _LINK.sub(r"\1", t)
    t = re.sub(r"⟨[^⟩]*⟩", " ", t)  # redaction placeholders
    t = _URL.sub(" ", t)
    t = _PATH.sub(" ", t)
    t = _MD.sub(" ", t)
    return " ".join(t.split())


def _first_sentence(text: str) -> str:
    for part in _SPLIT.split(text):
        part = _FILLER.sub("", part.strip()).strip(" ,:;-.")
        if len(re.findall(r"[A-Za-z]{2,}", part)) >= 2 and not _TRIVIAL.match(part):
            return part
    return ""


def cap(text: str, limit: int = MAX_TITLE) -> str:
    """Cut at a word boundary, with an ellipsis."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if text[limit] != " " and " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,:;-.") + "…"


def prompt_title(prompt: str) -> str | None:
    """A title from the prompt, or None when it is trivial, long/pasted text or too ambiguous to trust."""
    if _MACHINE_START.match(prompt or ""):
        return None  # a subagent report or notification, not something the user asked
    raw = human_text(prompt)
    if len(raw.split()) > 60 or raw.count("\n") > 6 or raw.count("```") >= 2:
        return None  # a long prompt or pasted text: describe the changes instead
    sentence = _first_sentence(clean_prompt(raw))
    if not sentence or len(sentence.split()) < 2 or len(sentence) > 160:
        return None
    return cap(sentence)


def _top_dir(paths: list[str]) -> str:
    dirs: Counter = Counter()
    for p in paths:
        parts = p.split("/")[:-1]
        dirs["/".join(parts[:2])] += 1
    d, n = dirs.most_common(1)[0]
    return d if d and n * 2 >= len(paths) else ""


def changes_title(changes: list[dict], new_symbols: list[str] | None = None) -> str:
    """'Update 5 files in apps/web (+3 new)', 'Add calc.py' ... computed from the changes."""
    paths = [c["path"] for c in changes]
    if not paths:
        return "Update files"
    added = [c["path"] for c in changes if c.get("kind") == "added"]
    deleted = [c["path"] for c in changes if c.get("kind") == "deleted"]
    n = len(paths)
    if n == 1:
        verb = "Add" if added else "Delete" if deleted else "Update"
        title = f"{verb} {os.path.basename(paths[0])}"
        if new_symbols and verb == "Update":
            title += f": {new_symbols[0]}"
        return cap(title)
    verb = "Add" if len(added) == n else "Delete" if len(deleted) == n else "Update"
    where = _top_dir(paths)
    title = f"{verb} {n} files" + (f" in {where}" if where else "")
    extras = []
    if verb == "Update" and added:
        extras.append(f"+{len(added)} new")
    if verb == "Update" and deleted:
        extras.append(f"-{len(deleted)} deleted")
    if extras:
        title += f" ({', '.join(extras)})"
    if new_symbols and len(title) < 40:
        title += f": {', '.join(new_symbols[:2])}"
    return cap(title)


def derive_title(prompt: str, changes: list[dict], new_symbols: list[str] | None = None) -> str:
    """Title of an auto step: the prompt's first meaningful sentence when it is short and clear,
    else one computed from the changes. Never longer than ~60 chars."""
    return prompt_title(prompt) or changes_title(changes, new_symbols)
