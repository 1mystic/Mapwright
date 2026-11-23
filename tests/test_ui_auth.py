import urllib.error
import urllib.request
from pathlib import Path

import pytest

from mapwright.server import Daemon

UI = Path(__file__).resolve().parents[1] / "src" / "mapwright" / "ui"


def _get(url, token=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture()
def daemon():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    d = Daemon(port=port, watch=False).start()
    try:
        yield d
    finally:
        d.httpd.shutdown()
        d.httpd.server_close()


def test_ping_needs_token_but_ui_is_public(daemon):
    base = f"http://127.0.0.1:{daemon.port}"
    assert _get(base + "/v1/ping")[0] == 401
    assert _get(base + "/v1/ping", "wrong-token")[0] == 401
    assert _get(base + "/v1/ping", daemon.token)[0] == 200
    for path in ("/", "/app.js", "/app.css"):
        status, body = _get(base + path)
        assert status == 200 and body
        assert daemon.token.encode() not in body


def test_served_app_has_auth_flow_markers(daemon):
    status, body = _get(f"http://127.0.0.1:{daemon.port}/app.js")
    js = body.decode()
    for marker in ("auth-box", "offline-box", "auth-input", "forget-token", "mapwright open", "mapwright up -d", "localStorage"):
        assert marker in js, marker
    assert (UI / "app.js").read_text() == js
