"""Regenerate the UI screenshots (web/img/*.png and docs/img/*.png) from the current UI.

    python scripts/screenshots.py [name ...]

Builds the site (web/app/ with the demo bundle), serves web/ on a free local port and drives a headless
Chromium through its command line only (no Playwright needed). Views are chosen with the URL hash
(#view=..., #theme=...), which app.js reads at start.

Browser: $MAPWRIGHT_CHROME, else a Playwright headless shell in ~/.cache/ms-playwright, else
google-chrome / chromium on PATH.
"""

from __future__ import annotations

import functools
import glob
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
WEB = ROOT / "web"
DOCS_IMG = ROOT / "docs" / "img"
SIZE = "1600,1000"
BUDGET_MS = 20000

# file name -> URL hash
SHOTS = {
    "overview": "view=overview",
    "system": "view=system",
    "architecture": "view=d:architecture",
    "logic": "view=logic",
    "data": "view=d:data",
    "cloud": "view=d:cloud",
    "processes": "view=d:processes",
    "concepts": "view=concepts",
    "timeline": "view=timeline",
    "settings": "view=settings",
    "light": "view=overview&theme=light",
}


def find_chrome() -> str:
    env = os.environ.get("MAPWRIGHT_CHROME")
    if env:
        return env
    pats = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")))
    if pats:
        return pats[-1]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("No Chrome/Chromium found. Set MAPWRIGHT_CHROME to a binary.")


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def shoot(chrome: str, url: str, out: Path) -> None:
    profile = tempfile.mkdtemp(prefix="mw-shot-")  # fresh profile: no saved tabs or theme
    try:
        cmd = [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
               f"--user-data-dir={profile}", f"--window-size={SIZE}", f"--virtual-time-budget={BUDGET_MS}", f"--screenshot={out}", url]
        subprocess.run(cmd, check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    names = sys.argv[1:] or list(SHOTS)
    unknown = [n for n in names if n not in SHOTS]
    if unknown:
        sys.exit(f"unknown: {', '.join(unknown)}; choose from {', '.join(SHOTS)}")
    chrome = find_chrome()
    import build_site

    build_site.main()
    srv, port = serve(WEB)
    try:
        for name in names:
            out = DOCS_IMG / f"{name}.png"
            shoot(chrome, f"http://127.0.0.1:{port}/app/?demo#{SHOTS[name]}", out)
            shutil.copy2(out, WEB / "img" / out.name)
            print(f"{name}.png  {out.stat().st_size // 1024} KB")
    finally:
        srv.shutdown()


if __name__ == "__main__":
    main()
