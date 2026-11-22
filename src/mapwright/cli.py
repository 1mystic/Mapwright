"""mapwright command line. Stdlib only (argparse)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import __version__, brief, config, connect, render
from . import analyze as A

USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


BLUE, GREEN, AMBER, RED, DIM, BOLD = "38;5;75", "38;5;71", "38;5;179", "38;5;167", "38;5;245", "1"


def project(args):
    from .track import open_project
    p = open_project(getattr(args, "path", None) or os.getcwd())
    p.refresh()
    return p


def api(method: str, path: str, body=None, timeout: float = 2.0):
    req = urllib.request.Request(config.base_url() + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {config.token()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def daemon_state() -> str:
    """none: nothing on the port · ours: a daemon with this home · other: something else (a daemon with another home) holds the port."""
    try:
        r = api("GET", "/v1/ping", timeout=0.6)
        if r.get("ok"):
            h = r.get("home")
            return "ours" if not h or os.path.realpath(h) == os.path.realpath(str(config.home())) else "other"
    except (urllib.error.URLError, OSError, ValueError):
        pass
    import socket
    try:
        with socket.create_connection(("127.0.0.1", config.port()), timeout=0.3):
            return "other"
    except OSError:
        return "none"


def _other_daemon_msg() -> str:
    return (f"another process (probably a daemon with a different MAPWRIGHT_HOME) already listens on {config.base_url()}; "
            f"this project's home is {config.home()}. One daemon serves one home: stop it (`mapwright down` with its home) "
            f"or set MAPWRIGHT_PORT to another port.")


def _daemon_env() -> dict:
    return dict(os.environ, MAPWRIGHT_HOME=str(config.home()))


def alive() -> bool:
    try:
        return bool(api("GET", "/v1/ping", timeout=0.6).get("ok"))
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ------------------------------------------------------------------ commands
def _gitignore_add(root: str, entries: list[str]) -> None:
    path = os.path.join(root, ".gitignore")
    try:
        text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    except OSError:
        return
    have = {ln.strip().strip("/") for ln in text.splitlines()}
    add = [e for e in entries if e.strip("/") not in have]
    if add:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + ("" if not text or text.endswith("\n") else "\n") + "\n".join(add) + "\n")


def _setup_local_home(a) -> str | None:
    """init --local / --home DIR: create the home (0700), write the discovery marker, ignore it in version control, use it from here on."""
    if a.local and a.home:
        raise ValueError("use either --local or --home DIR, not both")
    if not (a.local or a.home):
        return None
    root = os.path.realpath(A.find_root(os.path.abspath(getattr(a, "path", None) or os.getcwd())))
    target = os.path.join(root, config.MARKER_DIR) if a.local else os.path.abspath(os.path.join(root, os.path.expanduser(a.home)))
    os.makedirs(target, mode=0o700, exist_ok=True)
    os.chmod(target, 0o700)
    config.write_marker(root, target)
    os.environ["MAPWRIGHT_HOME"] = target
    config.reset_cache()
    entries = [config.MARKER_DIR + "/"]
    rel = os.path.relpath(target, root)
    if not rel.startswith("..") and rel != config.MARKER_DIR:
        entries.append(rel.replace(os.sep, "/") + "/")
        if os.sep not in rel and rel not in A.IGNORE_DIRS:  # the tracker must not scan its own home
            ign = config.settings()["ignore"]
            if rel not in ign:
                config.save_settings({"ignore": [*ign, rel]})
    _gitignore_add(root, entries)
    return target


def cmd_init(a):
    local = _setup_local_home(a)
    p = project(a)
    if local:
        print(f"  {c('✓', GREEN)} project-local home {c(local, DIM)} (found automatically from this project)")
    print(f"{c('◆', BLUE)} tracking {c(p.name, BOLD)}  {c(p.root, DIM)}")
    print(f"  {len(p.cache)} files · {len(p.model['modules'])} modules · {len(p.model['functions'])} functions · baseline recorded as step 0")
    for t in a.connect or []:
        files = connect.install(t, a.scope, p.root, home=str(local or config.local_home(p.root) or "") or None)
        print(f"  {c('✓', GREEN)} connected {connect.TARGETS[t]['title']}: {', '.join(files)}")
    if a.agents_md:
        print(f"  {c('✓', GREEN)} wrote {connect.write_agents_md(p.root, a.agents_md)}")
    print(f"  next: {c('mapwright open', BLUE)} to see the map · {c('mapwright connect --list', BLUE)} to connect an agent")


def cmd_up(a):
    st = daemon_state()
    if st == "ours":
        print(f"{c('●', GREEN)} already running on {config.base_url()}")
        return
    if st == "other":
        print(c(f"✖ {_other_daemon_msg()}", RED))
        sys.exit(1)
    if a.detach:
        log = open(config.home() / "daemon.log", "a")
        args = [sys.executable, "-m", "mapwright", "up"] + (["--no-watch"] if a.no_watch else [])
        subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True, env=_daemon_env())
        for _ in range(50):
            time.sleep(0.1)
            if alive():
                print(f"{c('●', GREEN)} started on {config.base_url()}   open the map: {c('mapwright open', BLUE)}")
                return
        print(c(f"✖ did not start; see {config.home() / 'daemon.log'}", RED))
        sys.exit(1)
    from .server import Daemon
    os.environ["MAPWRIGHT_HOME"] = str(config.home())  # pin: the daemon serves one home whatever its cwd
    try:
        d = Daemon(watch=not a.no_watch)
    except OSError as e:
        print(c(f"✖ cannot listen on {config.base_url()}: {e.strerror or e}. Set MAPWRIGHT_PORT to use another port.", RED))
        sys.exit(1)
    print(f"{c('◆', BLUE)} mapwright {__version__} on {config.base_url()}  {c('(Ctrl-C to stop)', DIM)}")
    try:
        d.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        d.stopping.set()
        d.httpd.server_close()


def cmd_down(a):
    if not alive():
        print(c("not running", DIM))
        return
    api("POST", "/v1/shutdown", {})
    print(f"{c('●', GREEN)} stopped")


def cmd_open(a):
    p = project(a)
    st = daemon_state()
    if st == "other":
        print(c(f"✖ {_other_daemon_msg()}", RED), file=sys.stderr)
        sys.exit(1)
    if st == "none":
        subprocess.run([sys.executable, "-m", "mapwright", "up", "-d"], stdout=subprocess.DEVNULL, check=False, env=_daemon_env())
    url = f"{config.base_url()}/#p={p.key}&t={config.token()}"
    if a.json:
        print(json.dumps({"url": url, "key": p.key, "root": p.root}))
        return
    print(url)
    print(c("the link carries your local token; don't share it", DIM))
    if not a.print:
        import webbrowser
        webbrowser.open(url)


def cmd_status(a):
    p = project(a)
    st = p.state()
    if a.json:
        print(json.dumps({k: st[k] for k in ("key", "name", "root", "counts", "layers")} | {
            "steps": len(st["steps"]), "pending": len(st["pending"]), "open_todos": sum(t["status"] == "open" for t in st["todos"]),
            "problems": len(st["problems"]), "daemon": alive()}))
        return
    print(f"{c('◆', BLUE)} {c(st['name'], BOLD)} · step {st['steps'][-1]['n'] if st['steps'] else 0} · "
          f"{len(st['pending'])} file changes pending · daemon {'on' if alive() else 'off'}")
    k = st["counts"]
    print(f"  {k['files']} files · {k['modules']} modules · {k['functions']} functions · {k['classes']} classes · {k['tables']} tables · "
          f"{k['routes']} routes · {k['concepts']} mechanisms · {k['infra']} infra nodes")
    for s in st["steps"][-5:]:
        print(f"  {c(str(s['n']).rjust(3), DIM)} {s['title'][:70]}  {c(f'+{s['summary']['added']}/-{s['summary']['removed']}', DIM)}"
              + (c(f"  ⚠ {s['title_check']}", AMBER) if s.get("title_check", "ok") != "ok" else ""))
    todos = [t for t in st["todos"] if t["status"] == "open"]
    if todos:
        print("  todos: " + " · ".join(f"{t['id']} {t['text'][:40]}" for t in todos[:5]))
    if st["problems"]:
        print(c(f"  {len(st['problems'])} unverified item(s): mapwright problems", AMBER))


def cmd_brief(a):
    p = project(a)
    print(brief.project_brief(p, a.budget or config.settings()["brief_budget"], a.focus))


def cmd_find(a):
    p = project(a)
    for r in A.find_symbols(p.model, a.query, 25):
        print(f"{r['id']}  {c(r['kind'], DIM)}  {r['file']}:{r['line'] or ''}")


def cmd_symbol(a):
    print(brief.symbol_card(project(a), a.name))


def cmd_step(a):
    data = project(a).step(a.title, a.intent or "", source=a.source)
    print(brief.step_receipt(data))


def cmd_steps(a):
    p = project(a)
    for s in p.steps():
        sm = s["summary"]
        delta = "; ".join(f"{k} " + ", ".join(f"{n} {st}" for st, n in v.items()) for k, v in sm["delta"].items())
        print(f"{c(str(s['n']).rjust(3), BLUE)} {time.strftime('%H:%M', time.localtime(s['ts']))} {c(s['source'][:5], DIM)} "
              f"{s['title'][:60]}  {c(f'{sm['files']} files +{sm['added']}/-{sm['removed']}', DIM)}  {delta}")


def cmd_changes(a):
    p = project(a)
    if a.step is None:
        changes, label = p.pending(), "since the last step"
        frm, to = (str(p.steps()[-1]["n"]) if p.steps() else "live"), "live"
    else:
        data = p.load_step(a.step)
        if not data:
            sys.exit(f"no step {a.step}")
        changes, label, frm, to = data["changes"], f"in step {a.step}", str(max(0, a.step - 1)), str(a.step)
    print(c(f"{len(changes)} file change(s) {label}", DIM))
    for ch in changes:
        pm = f"+{ch.get('added', 0)} -{ch.get('removed', 0)}" if "added" in ch else ch.get("note", "")
        col = {"added": GREEN, "deleted": RED}.get(ch["kind"], BLUE)
        print(f"  {c(ch['kind'][:3].upper(), col)} {ch['path']}  {c(pm, DIM)}")
        if a.diff and "added" in ch:
            import difflib
            def idx(s):
                return p.index if s == "live" else p.step_files(int(s))
            ta, tb = p.blob(idx(frm).get(ch["path"])), p.blob(idx(to).get(ch["path"]))
            from .redact import redact
            for ln in difflib.unified_diff((ta or "").splitlines(), (tb or "").splitlines(), lineterm="", n=2):
                if ln.startswith(("+++", "---")):
                    continue
                print("      " + c(redact(ln), GREEN if ln.startswith("+") else RED if ln.startswith("-") else DIM))


def cmd_todo(a):
    p = project(a)
    if a.action == "add":
        print("added", p.todo_add(" ".join(a.rest), by=a.by)["tid"])
    elif a.action == "done":
        if not a.rest:
            sys.exit("usage: mapwright todo done ID [--evidence SYMBOL_OR_FILE]")
        t = p.todo_done(a.rest[0], a.evidence or "")
        print(f"{t['id']} done · " + (c("verified", GREEN) if t.get("verified") else c("unverified", AMBER)) + f": {t.get('reason')}")
    elif a.action == "drop":
        p.todo_drop(a.rest[0])
        print("dropped")
    else:
        for t in p.verify()["todos"]:
            mark = {"open": "○", "done": "●" if t.get("verified") else "◐", "dropped": "×"}[t["status"]]
            print(f"{mark} {t['id']} {t['text']}" + (c(f"  ({t.get('reason')})", DIM) if t["status"] == "done" else ""))


def cmd_claim(a):
    cl = project(a).claim(a.concept, a.symbol, a.note or "")
    col = GREEN if cl["status"] == "verified" else AMBER
    print(f"{cl['concept']} → {cl['symbol']}: {c(cl['status'], col)} ({cl.get('reason')})")


def cmd_note(a):
    print("noted", project(a).note(a.symbol, " ".join(a.role))["status"])


def cmd_link(a):
    print("linked", project(a).link(a.source, a.target, a.label or "")["status"])


def cmd_catalog(a):
    print(brief.catalog_text())


def cmd_problems(a):
    v = project(a).verify()
    if not v["problems"]:
        print(f"{c('✓', GREEN)} everything the agent claimed checks out")
    for x in v["problems"]:
        print(f"{c('⚠', AMBER)} [{x['kind']}] {x['text']}")


def cmd_diagram(a):
    from .server import Daemon
    p = project(a)
    out = Daemon.diagram(None, p, a.kind, {"step": str(a.step) if a.step is not None else "live", "focus": a.focus})  # type: ignore[arg-type]
    print(out["mermaid"])


def cmd_flow(a):
    from .server import Daemon
    p = project(a)
    hit = A.resolve(p.model, a.symbol)
    if not hit or hit[0] != "functions":
        sys.exit(f"no function named {a.symbol}; try `mapwright find {a.symbol}`")
    print(Daemon.flow(None, p, hit[1], "live")["mermaid"])  # type: ignore[arg-type]


def cmd_connect(a):
    root = os.path.realpath(A.find_root(os.path.abspath(a.path or os.getcwd())))
    if a.list or not a.target:
        for t in connect.status(root):
            if t.get("manual"):
                print(f"  {c('·', DIM)} {t['title']:<30} {c('manual: mapwright connect --print ' + t['id'], DIM)}")
                continue
            sc = " ".join((c(f"{s}✓", GREEN) if v["connected"] else c(s, DIM)) for s, v in t["scopes"].items())
            print(f"  {c('●', GREEN) if t['installed'] else c('○', DIM)} {t['id']:<15} {t['title']:<30} {sc}")
        print(c("\n  mapwright connect <id> [--scope project|user]   ·   --print <id> shows the config to paste", DIM))
        return
    if a.print:
        print(connect.snippet(a.target, root, home=str(config.local_home(root) or "") or None))
        if a.target in connect.MANUAL:
            print(c("\n" + connect.MANUAL[a.target][1], DIM))
        return
    files = connect.install(a.target, a.scope, root, home=str(config.local_home(root) or "") or None)
    print(f"{c('✓', GREEN)} {connect.TARGETS[a.target]['title']} connected ({a.scope}): " + ", ".join(files))
    print(c("  restart the agent (or start a new session) so it loads the MCP server", DIM))


def cmd_disconnect(a):
    root = os.path.realpath(A.find_root(os.path.abspath(a.path or os.getcwd())))
    files = connect.uninstall(a.target, a.scope, root)
    print(f"{c('✓', GREEN)} removed from: " + ", ".join(files) if files else c("nothing to remove", DIM))


def cmd_agents_md(a):
    p = project(a)
    print(f"{c('✓', GREEN)} wrote {connect.write_agents_md(p.root, a.file)}")


def cmd_watch(a):
    p = project(a)
    print(f"{c('◆', BLUE)} watching {p.root}  {c('(steps close after a quiet period; Ctrl-C to stop)', DIM)}")
    try:
        while True:
            changed = p.refresh()
            if changed:
                print(f"  {time.strftime('%H:%M:%S')} {len(changed)} changed: " + ", ".join(changed[:5]))
            data = p.maybe_auto_step()
            if data:
                print(f"  {c('step', BLUE)} {brief.step_receipt(data)}")
            time.sleep(max(0.5, config.settings()["watch_interval"]))
    except KeyboardInterrupt:
        pass


def cmd_export(a):
    from .export import export
    out = export(project(a), a.out)
    print(f"{c('✓', GREEN)} wrote {out}")


def cmd_mcp(a):
    from . import mcp
    sys.exit(mcp.serve(a.root))


def cmd_hook(a):
    from . import hooks
    sys.exit(hooks.main([a.agent]))


def cmd_settings(a):
    if a.key:
        val = a.value
        try:
            val = json.loads(val)
        except (ValueError, TypeError):
            pass
        try:
            config.save_settings({a.key: val})
        except ValueError as e:
            sys.exit(str(e))
    for k, v in config.settings().items():
        print(f"  {k:<16} {json.dumps(v)}" + (c("  (default)", DIM) if v == config.DEFAULTS[k] else ""))


def cmd_doctor(a):
    ok = True
    print(f"{c('◆', BLUE)} mapwright {__version__} · python {sys.version.split()[0]} · home {config.home()}")
    print(f"  {'✓' if alive() else '!'} daemon " + ("running on " + config.base_url() if alive() else "not running (only the UI needs it): mapwright up -d"))
    p = project(a)
    print(f"  ✓ project {p.name}: {len(p.cache)} files tracked" + (c(" (file cap reached)", AMBER) if p.truncated else ""))
    errs = [r for r, e in p.cache.items() if (e.get("part") or {}).get("error")]
    if errs:
        print(c(f"  ! {len(errs)} file(s) do not parse: {', '.join(errs[:3])}", AMBER))
    conn = [t["title"] for t in connect.status(p.root) if any(s["connected"] for s in t["scopes"].values())]
    print(f"  {'✓' if conn else '!'} agents: " + (", ".join(conn) if conn else "none connected; see `mapwright connect --list`"))
    ok = ok and bool(conn)
    log = config.home() / "hook-errors.log"
    if log.exists() and log.stat().st_size:
        print(c(f"  ! hook errors logged in {log}", AMBER))
    sys.exit(0)


GUIDE = """Mapwright quick guide

  Start             mapwright init                      track this project (baseline = step 0)
                    mapwright connect --list            see agents you can connect
                    mapwright connect claude-code       MCP server + hooks for this project (--scope user for all)
                    mapwright open                      the map in your browser (starts the daemon)
  While working     mapwright status                    steps, pending changes, todos
                    mapwright step "Add refunds"        close a step yourself
                    mapwright changes [--step N] --diff what changed
                    mapwright problems                  claims and todos that do not check out
  For agents        mapwright brief                     the map as compact text (~600 tokens)
                    mapwright find NAME · symbol NAME   locate code, callers, callees
                    mapwright todo add|done|list        plan items, verified on done
                    mapwright claim CONCEPT SYMBOL      tag a mechanism (see: mapwright catalog)
  Diagrams          mapwright diagram architecture|files|classes|data|cloud|processes|calls|concepts
                    mapwright flow FUNCTION             flowchart of one function (Mermaid)
                    mapwright export -o docs/map        MAP.md + every diagram, ready to commit
  Stop / remove     mapwright down                      stop the daemon
                    mapwright disconnect claude-code    remove the MCP entry and hooks
                    rm -rf ~/.mapwright                 delete all tracked history
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mapwright", description="A live map of what your coding agent is building.")
    ap.add_argument("--version", action="version", version=f"mapwright {__version__}")
    sp = ap.add_subparsers(dest="cmd")

    def add(name, fn, help_, path=True):
        p_ = sp.add_parser(name, help=help_, description=help_)
        p_.set_defaults(fn=fn)
        if path:
            p_.add_argument("--path", default=None, help="project directory (default: current)")
        return p_

    x = add("init", cmd_init, "Track this project and record the baseline.")
    x.add_argument("--connect", action="append", choices=list(connect.TARGETS), help="also connect an agent (repeatable)")
    x.add_argument("--scope", default="project", choices=["project", "user"])
    x.add_argument("--agents-md", nargs="?", const="AGENTS.md", default=None, help="add usage notes to AGENTS.md (or a file you name)")
    x.add_argument("--local", action="store_true", help="keep history in <project>/.mapwright instead of ~/.mapwright")
    x.add_argument("--home", metavar="DIR", default=None, help="keep history in DIR (relative to the project root)")
    x = add("up", cmd_up, "Start the daemon (UI + background tracking).", path=False)
    x.add_argument("-d", "--detach", action="store_true")
    x.add_argument("--no-watch", action="store_true")
    add("down", cmd_down, "Stop the daemon.", path=False)
    x = add("open", cmd_open, "Open the map in the browser.")
    x.add_argument("--print", action="store_true", help="print the URL only")
    x.add_argument("--json", action="store_true")
    x = add("status", cmd_status, "Steps, pending changes, todos.")
    x.add_argument("--json", action="store_true")
    x = add("brief", cmd_brief, "The project map as compact text for an agent.")
    x.add_argument("--budget", type=int)
    x.add_argument("--focus")
    x = add("find", cmd_find, "Locate symbols by name.")
    x.add_argument("query")
    x = add("symbol", cmd_symbol, "One symbol: callers, callees, tables, history.")
    x.add_argument("name")
    x = add("step", cmd_step, "Close a step (the changes are computed).")
    x.add_argument("title")
    x.add_argument("--intent")
    x.add_argument("--source", default="user", choices=["user", "agent"])
    add("steps", cmd_steps, "List steps.")
    x = add("changes", cmd_changes, "File changes since the last step, or in a step.")
    x.add_argument("--step", type=int)
    x.add_argument("--diff", action="store_true")
    x = add("todo", cmd_todo, "Plan items: add TEXT | done ID | drop ID | list.")
    x.add_argument("action", choices=["add", "done", "drop", "list"])
    x.add_argument("rest", nargs="*")
    x.add_argument("--evidence")
    x.add_argument("--by", default="user")
    x = add("claim", cmd_claim, "Tag a symbol with a mechanism from the catalog.")
    x.add_argument("concept")
    x.add_argument("symbol")
    x.add_argument("--note")
    x = add("note", cmd_note, "One-line role of a module or symbol.")
    x.add_argument("symbol")
    x.add_argument("role", nargs="+")
    x = add("link", cmd_link, "A relation the code does not show (queue, event, service call).")
    x.add_argument("source")
    x.add_argument("target")
    x.add_argument("--label")
    add("catalog", cmd_catalog, "Concept ids for claims.", path=False)
    add("problems", cmd_problems, "Claims, notes, links and todos that do not check out.")
    x = add("diagram", cmd_diagram, "Print a diagram as Mermaid.")
    x.add_argument("kind", choices=list(render.KINDS))
    x.add_argument("--step", type=int)
    x.add_argument("--focus")
    x = add("flow", cmd_flow, "Flowchart of one function (Mermaid).")
    x.add_argument("symbol")
    x = add("connect", cmd_connect, "Connect an agent (writes its MCP config; hooks for Claude Code).")
    x.add_argument("target", nargs="?", choices=list(connect.TARGETS) + list(connect.MANUAL))
    x.add_argument("--scope", default="project", choices=["project", "user"])
    x.add_argument("--list", action="store_true")
    x.add_argument("--print", action="store_true", help="print the config to paste instead of writing it")
    x = add("disconnect", cmd_disconnect, "Remove Mapwright from an agent's config.")
    x.add_argument("target", choices=list(connect.TARGETS))
    x.add_argument("--scope", default="project", choices=["project", "user"])
    x = add("agents-md", cmd_agents_md, "Add short usage notes for agents to AGENTS.md / CLAUDE.md.")
    x.add_argument("--file", default="AGENTS.md", choices=["AGENTS.md", "CLAUDE.md", ".cursorrules", "GEMINI.md"])
    add("watch", cmd_watch, "Track from the files alone (any agent, no integration).")
    x = add("export", cmd_export, "Write MAP.md and every diagram to a folder.")
    x.add_argument("-o", "--out", default="mapwright-export")
    x = add("mcp", cmd_mcp, "Run the MCP server on stdio (agents start this).", path=False)
    x.add_argument("--root")
    x = add("hook", cmd_hook, "Hook entry point (agents call this).", path=False)
    x.add_argument("agent", nargs="?", default="claude-code")
    x = add("settings", cmd_settings, "Show or change a setting: settings KEY VALUE.", path=False)
    x.add_argument("key", nargs="?")
    x.add_argument("value", nargs="?")
    add("doctor", cmd_doctor, "Check the setup.")
    add("guide", lambda a: print(GUIDE), "Quick guide.", path=False)
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        print(GUIDE)
        return 0
    config.set_start(getattr(a, "path", None) or getattr(a, "root", None))
    try:
        a.fn(a)
    except ValueError as e:
        print(c(f"✖ {e}", RED), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
