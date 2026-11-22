"""Redaction applied before anything is stored or displayed."""

from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S), "⟨private-key⟩"),
    (re.compile(r"fwk_live_[A-Za-z0-9]{6,}"), "⟨canary⟩"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"), "⟨anthropic-key⟩"),
    (re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"), "⟨stripe-key⟩"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "⟨api-key⟩"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "⟨github-token⟩"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "⟨github-token⟩"),
    (re.compile(r"glpat-[A-Za-z0-9_\-]{16,}"), "⟨gitlab-token⟩"),
    (re.compile(r"A[KS]IA[0-9A-Z]{16}"), "⟨aws-key⟩"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "⟨google-key⟩"),
    (re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"), "⟨slack-token⟩"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "⟨jwt⟩"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{16,}"), r"\1 ⟨token⟩"),
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1⟨user:pass⟩@"),
    # NAME=value anywhere on a line (after `export`, or as a prefix to a command)
    (re.compile(r"(?i)(?<![A-Za-z0-9_])([A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PASS|CREDENTIALS?)[A-Z0-9_]*\s*=\s*)(?!⟨)(\"[^\"]*\"|'[^']*'|[^\s;&|]+)"), r"\1⟨redacted⟩"),
    # "password": "value" and password: value
    (re.compile(r"(?i)([\"']?[a-z0-9_\-]*(?:password|passwd|secret|api[_\-]?key|token)[\"']?\s*:\s*)(?!⟨)(\"[^\"]*\"|'[^']*'|[^\s,;}]+)"), r"\1⟨redacted⟩"),
    # --password value, --token=value
    (re.compile(r"(?i)(--?(?:password|passwd|token|secret|api-key|apikey)[= ]\s*)(?!⟨)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1⟨redacted⟩"),
]


def redact(text: str, canaries: dict[str, str] | None = None) -> str:
    if not text:
        return text
    for value, cid in (canaries or {}).items():
        if value:
            text = text.replace(value, f"⟨canary:{cid}⟩")
    for pat, rep in _PATTERNS:
        text = pat.sub(rep, text)
    return text
