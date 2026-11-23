"""Build the website: copy the UI into web/app/ and record the live demo.

    python scripts/build_site.py

The demo is the real UI reading a recorded bundle of API responses (web/app/demo.json) from the
scripted agent session in demo_session.py, so it works on any static host with no server.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
UI = ROOT / "src" / "mapwright" / "ui"
WEB = ROOT / "web"


def url(path: str, params: dict) -> str:
    """Same as url() in app.js: sorted keys, encodeURIComponent values, empty values dropped."""
    items = sorted((k, v) for k, v in params.items() if v not in (None, ""))
    return path + ("?" + "&".join(f"{k}={quote(str(v), safe='-_.!~*()' + chr(39))}" for k, v in items) if items else "")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    home = tempfile.mkdtemp(prefix="mw-site-")
    os.environ["MAPWRIGHT_HOME"] = home
    os.environ["MAPWRIGHT_PORT"] = str(free_port())
    import demo_session

    from mapwright import config
    from mapwright.server import Daemon
    from mapwright.track import by_key

    project_dir = Path(home) / "shop-api"
    key = demo_session.run(str(project_dir), quiet=True)
    p = by_key(key)
    d = Daemon(watch=False).start()
    tok = config.token()
    bundle: dict[str, object] = {}

    def get(u: str):
        req = urllib.request.Request(config.base_url() + u, headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                bundle[u] = json.loads(r.read())
        except urllib.error.HTTPError:
            pass

    try:
        P = lambda rest: f"/v1/p/{quote(key, safe='')}/{rest}"  # noqa: E731
        for u in ("/v1/projects", "/v1/settings", "/v1/catalog", url("/v1/integrations", {"key": key}), P("state"), P("version"), P("brief")):
            get(u)
        # the demo is recorded somewhere temporary: show a neutral path
        for u in ("/v1/projects", P("state"), url("/v1/integrations", {"key": key}), "/v1/settings"):
            text = json.dumps(bundle.get(u)).replace(str(project_dir), "~/projects/shop-api").replace(home, "~/.mapwright")
            bundle[u] = json.loads(text)
        steps = [s["n"] for s in p.steps()]
        last = steps[-1]
        kinds = ("architecture", "files", "classes", "data", "cloud", "processes", "calls", "concepts")
        for st in ["live"] + [str(n) for n in steps]:
            get(url(P("model"), {"step": st}))
            for k in kinds:
                get(url(P(f"diagram/{k}"), {"step": st}))
            model = bundle.get(url(P("model"), {"step": st})) or {}
            for fid in model.get("functions", {}):
                get(url(P("flow"), {"fid": fid, "step": st}))
            files = p.index if st == "live" else p.step_files(int(st))
            prev = str(last) if st == "live" else str(max(0, int(st) - 1))
            for path in files:
                get(url(P("file"), {"path": path, "step": st}))
                get(url(P("diff"), {"path": path, "from": prev, "to": st}))
            if st != "live":
                for ch in (p.load_step(int(st)) or {}).get("changes", []):
                    get(url(P("diff"), {"path": ch["path"], "from": prev, "to": st}))
        live = bundle[url(P("model"), {"step": "live"})]
        for fid in live["functions"]:
            get(url(P("diagram/calls"), {"step": "live", "focus": fid}))
        for r in live["routes"]:
            get(url(P("diagram/processes"), {"step": "live", "focus": f"{r['method']} {r['path']}"}))
        for kind in ("functions", "classes", "tables", "modules"):
            for ref in live[kind]:
                get(url(P("symbol"), {"ref": ref}))
    finally:
        d.shutdown()
    text = json.dumps(bundle, separators=(",", ":")).replace(str(project_dir), "~/projects/shop-api").replace(home, "~/.mapwright")

    app = WEB / "app"
    if app.exists():
        shutil.rmtree(app)
    shutil.copytree(UI, app, ignore=shutil.ignore_patterns("__pycache__"))
    html = (app / "index.html").read_text().replace('<html lang="en" data-theme="dark">', '<html lang="en" data-theme="dark" data-demo="1">')
    (app / "index.html").write_text(html.replace("<title>Mapwright</title>", "<title>Mapwright · live demo</title>"))
    (app / "demo.json").write_text(text)
    for img in (ROOT / "docs" / "img").glob("*.png"):
        (WEB / "img").mkdir(exist_ok=True)
        shutil.copy2(img, WEB / "img" / img.name)
    shutil.rmtree(home, ignore_errors=True)
    import mdsite

    mdsite.build(WEB)  # web/docs.html and web/setup.html are generated from docs/*.md
    print(f"web/app/demo.json: {len(bundle)} responses, {len(text) // 1024} KB · site ready in {WEB}")


if __name__ == "__main__":
    main()
