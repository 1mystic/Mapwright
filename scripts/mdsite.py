"""Generate web/docs.html and web/setup.html from docs/*.md (stdlib only).

    python scripts/mdsite.py

build_site.py calls build() too, so a deploy always publishes pages that match the Markdown.
The converter supports what our docs use: headings (with ids), paragraphs, inline code, bold, italic,
links, images, fenced code, pipe tables, bullet/numbered lists, blockquotes. All text is escaped.
"""

from __future__ import annotations

import html
import posixpath
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
WEB = ROOT / "web"
GITHUB = "https://github.com/1mystic/Mapwright/blob/main/"

# docs/*.md -> generated page (the link's #fragment is kept)
PAGE_OF = {
    "docs/COMMANDS.md": "docs.html",
    "docs/AGENT_PROTOCOL.md": "docs.html",
    "docs/SETUP.md": "setup.html",
    "docs/RELEASING.md": "setup.html",
}

ALIASES = {"4-deploy-plan-free-tier": "deploy", "stop-disconnect-remove": "remove"}
ABS = re.compile(r"^([a-z][a-z0-9+.-]*:|//)", re.I)


def slugify(text: str) -> str:
    s = re.sub(r"[`*]", "", text).strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def rewrite_href(href: str, src: str = "docs/x.md") -> str:
    """Links between docs -> generated pages; other repo files -> GitHub; absolute URLs untouched."""
    if ABS.match(href) or href.startswith("#"):
        return href
    path, _, frag = href.partition("#")
    if not path:
        return href
    full = posixpath.normpath(posixpath.join(posixpath.dirname(src), path))
    tail = "#" + frag if frag else ""
    return PAGE_OF[full] + tail if full in PAGE_OF else GITHUB + full + tail


def rewrite_image(src: str) -> str:
    if ABS.match(src):
        return src
    full = posixpath.normpath(posixpath.join("docs", src))
    return full[len("docs/"):] if full.startswith("docs/img/") else GITHUB + full


def inline(text: str, src: str = "docs/x.md") -> str:
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append("<code>" + html.escape(m.group(2).replace("\\|", "|")) + "</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"(`+)(.+?)\1", stash, text)
    text = html.escape(text)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)\)",
        lambda m: f'<img src="{html.escape(rewrite_image(html.unescape(m.group(2))), quote=True)}" alt="{m.group(1)}">',
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: f'<a href="{html.escape(rewrite_href(html.unescape(m.group(2)), src), quote=True)}">{m.group(1)}</a>',
        text,
    )
    text = re.sub(r"\*\*(\S(?:.*?\S)?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(\S(?:[^*]*?\S)?)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


class Converter:
    """convert(md) -> html. Heading ids are unique per Converter; `headings` collects the h2s.

    h1_level=2 shows a Markdown H1 as an h2 (a section of a bigger page); skip_h1 drops it."""

    def __init__(self, src: str = "docs/x.md", h1_level: int = 1, skip_h1: bool = False, shift: int = 0):
        self.src, self.h1_level, self.skip_h1, self.shift = src, h1_level, skip_h1, shift
        self.used: set[str] = set()
        self.headings: list[tuple[int, str, str]] = []

    def uid(self, text: str) -> str:
        base = slugify(text) or "section"
        s, n = base, 1
        while s in self.used:
            s, n = f"{base}-{n}", n + 1
        self.used.add(s)
        return s

    def convert(self, md: str) -> str:
        lines = md.replace("\r\n", "\n").split("\n")
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            m = re.match(r"^(```+|~~~+)", line)
            if m:
                fence, buf = m.group(1), []
                i += 1
                while i < n and not lines[i].startswith(fence):
                    buf.append(lines[i])
                    i += 1
                i += 1
                out.append('<pre class="code"><code>' + html.escape("\n".join(buf)) + "</code></pre>")
                continue
            m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
            if m:
                lvl = len(m.group(1))
                i += 1
                if lvl == 1 and self.skip_h1:
                    continue
                shown = min(6, 2 if (lvl == 1 and self.h1_level == 2) else lvl + self.shift)
                hid = self.uid(m.group(2))
                if shown == 2:
                    self.headings.append((2, m.group(2).replace("`", ""), hid))
                alias = f'<a id="{ALIASES[hid]}"></a>' if hid in ALIASES else ""  # keeps old links (#deploy) working
                out.append(f'<h{shown} id="{hid}">{alias}{inline(m.group(2), self.src)}</h{shown}>')
                continue
            if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
                i += 1
                continue
            if line.lstrip().startswith("|") and i + 1 < n and SEP.match(lines[i + 1]):
                head = split_row(line)
                i += 2
                t = "<tr>" + "".join(f"<th>{inline(c, self.src)}</th>" for c in head) + "</tr>"
                while i < n and lines[i].strip().startswith("|"):
                    r = (split_row(lines[i]) + [""] * len(head))[: len(head)]
                    t += "<tr>" + "".join(f"<td>{inline(c, self.src)}</td>" for c in r) + "</tr>"
                    i += 1
                out.append(f'<div class="tbl"><table>{t}</table></div>')
                continue
            if line.startswith(">"):
                buf = []
                while i < n and lines[i].startswith(">"):
                    buf.append(lines[i][1:].strip())
                    i += 1
                out.append('<div class="note">' + inline(" ".join(buf), self.src) + "</div>")
                continue
            m = ITEM.match(line)
            if m:
                tag = "ol" if m.group(2)[0].isdigit() else "ul"
                items: list[str] = []
                while i < n:
                    mm = ITEM.match(lines[i])
                    if mm:
                        items.append(mm.group(3))
                    elif lines[i].strip() and lines[i][0] in " \t" and items:
                        items[-1] += " " + lines[i].strip()
                    else:
                        break
                    i += 1
                out.append(f"<{tag}>" + "".join(f"<li>{inline(x, self.src)}</li>" for x in items) + f"</{tag}>")
                continue
            buf = []
            while i < n and lines[i].strip() and not re.match(r"^(```|~~~|#{1,6}\s|>|\s*\|)", lines[i]) and not (buf and ITEM.match(lines[i])):
                buf.append(lines[i].strip())
                i += 1
            if not buf:  # never loop forever on odd input
                buf, i = [line.strip()], i + 1
            out.append("<p>" + inline(" ".join(buf), self.src) + "</p>")
        return "\n".join(out)


def convert(md: str, src: str = "docs/x.md", **kw) -> tuple[str, list[tuple[int, str, str]]]:
    c = Converter(src, **kw)
    body = c.convert(md)
    return body, c.headings


NAV = [("index.html#views", "Views"), ("index.html#how", "How it works"), ("index.html#verify", "Verification"), ("index.html#agents", "Agents"), ("docs.html", "Docs"), ("setup.html", "Setup &amp; deploy")]


def page(title: str, description: str, current: str, toc: list[tuple[str, str]], body: str) -> str:
    links = "".join(f'<a href="{h}"' + (' class="on"' if h == current else "") + f">{t}</a>" for h, t in NAV)
    tocs = "".join(f'<a href="#{i}">{html.escape(t)}</a>' for i, t in toc)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{html.escape(title)} | Mapwright</title><meta name="description" content="{html.escape(description, quote=True)}">'
        '<link rel="icon" href="assets/mark.svg"><link rel="stylesheet" href="assets/site.css"></head><body><header class="nav"><div class="wrap">\n'
        '<a class="brand" href="index.html"><img src="assets/mark.svg" alt="">Mapwright</a>\n'
        f'<nav class="links">{links}</nav>\n'
        '<span class="grow"></span><a class="btn sm" href="app/?demo">Live demo</a><a class="btn sm primary" href="setup.html">Get started</a></div></header>'
        f'<div class="wrap doc"><aside class="toc">{tocs}</aside><div>{body}</div></div>'
        '<footer><div class="wrap"><a class="brand" href="index.html"><img src="assets/mark.svg" alt="">Mapwright</a><span>Runs on your machine. MIT licensed.</span><span class="grow"></span>\n'
        '<a href="docs.html">Docs</a><a href="setup.html">Setup</a><a href="setup.html#deploy">Deploy</a><a href="app/?demo">Demo</a></div></footer>\n'
        '<script src="assets/site.js"></script></body></html>\n'
    )


def _compose(parts: list[tuple[str, dict]], head: str) -> tuple[str, list[tuple[str, str]]]:
    """Each part is (markdown file, Converter options); heading ids stay unique across the page."""
    used: set[str] = set()
    body, toc = [head], []
    for name, opts in parts:
        c = Converter("docs/" + name, **opts)
        c.used = used
        body.append(c.convert((DOCS / name).read_text(encoding="utf-8")))
        toc += [(i, t) for _, t, i in c.headings]
    return "\n".join(body), toc


def build(web: Path = WEB) -> list[Path]:
    docs_body, docs_toc = _compose(
        [("COMMANDS.md", {"h1_level": 2}), ("AGENT_PROTOCOL.md", {"h1_level": 2})],
        '<h1>Docs</h1><p>Every command, the MCP tools agents use, the settings, and why the protocol is shaped the way it is. '
        'Setup and hosting: <a href="setup.html">Setup &amp; deploy</a>.</p>',
    )
    setup_body, setup_toc = _compose(
        [("SETUP.md", {"skip_h1": True}), ("RELEASING.md", {"h1_level": 2, "shift": 1})],
        '<h1>Setup &amp; deploy</h1><p>Two minutes on your machine. Hosting is only needed if you publish Mapwright for others, and it fits in free tiers.</p>',
    )
    outs = {
        "docs.html": page("Docs", "Commands, MCP tools, settings and the agent protocol.", "docs.html", docs_toc, docs_body),
        "setup.html": page("Setup & deploy", "Install Mapwright, connect your coding agent, add the editor extension, and host the website for free.", "setup.html", setup_toc, setup_body),
    }
    written = []
    for name, text in outs.items():
        (web / name).write_text(text, encoding="utf-8")
        written.append(web / name)
    # images referenced from the Markdown live in docs/img; the site serves them from web/img
    (web / "img").mkdir(exist_ok=True)
    for img in (DOCS / "img").glob("*"):
        if img.is_file():
            shutil.copy2(img, web / "img" / img.name)
    return written


if __name__ == "__main__":
    for p in build():
        print("wrote", p.relative_to(ROOT))
