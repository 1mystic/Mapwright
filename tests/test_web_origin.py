import urllib.error
import urllib.request

import pytest

from mapwright import config
from mapwright.server import Daemon

SITE = "https://mapwright.pages.dev"


@pytest.fixture
def daemon():
    d = Daemon(port=17992, watch=False).start()
    yield d
    d.shutdown()


def call(d, path, method="GET", origin=None, token=True):
    h = {"Host": f"127.0.0.1:{d.port}"}
    if origin:
        h["Origin"] = origin
    if token:
        h["Authorization"] = f"Bearer {d.token}"
    try:
        r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{d.port}{path}", method=method, headers=h), timeout=5)
        return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


def test_allowlisted_site_gets_cors_and_private_network(daemon):
    code, h = call(daemon, "/v1/ping", origin=SITE)
    assert code == 200 and h["Access-Control-Allow-Origin"] == SITE and h["Access-Control-Allow-Private-Network"] == "true"


def test_preflight(daemon):
    code, h = call(daemon, "/v1/ping", "OPTIONS", origin=SITE, token=False)
    assert code == 204 and "Authorization" in h["Access-Control-Allow-Headers"]


def test_other_origins_refused(daemon):
    assert call(daemon, "/v1/ping", origin="https://evil.example")[0] == 403
    assert call(daemon, "/v1/ping", "OPTIONS", origin="https://evil.example", token=False)[0] == 403


def test_token_still_required_for_allowed_origin(daemon):
    assert call(daemon, "/v1/ping", origin=SITE, token=False)[0] == 401


def test_web_origins_validation():
    config.save_settings({"web_origins": [SITE, "http://localhost:3000"]})
    for bad in ("*", "https://*.x.com", "http://example.com", "https://x.com/path"):
        with pytest.raises(ValueError):
            config.save_settings({"web_origins": [bad]})


def test_app_js_has_loopback_only_api_base():
    from pathlib import Path
    js = (Path(config.__file__).parent / "ui/app.js").read_text()
    assert "127\\.0\\.0\\.1|localhost" in js and "BASE + path" in js
