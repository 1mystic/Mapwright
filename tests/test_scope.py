from mapwright import analyze as A, concepts as C

SQL = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);"


def _parts(files):
    return {r: A.analyze_file(r, t) for r, t in files.items()}


def test_file_scope():
    for rel, sc in [("tests/test_a.py", "test"), ("src/x_test.go", "test"), ("web/a.spec.ts", "test"), ("a/__tests__/b.js", "test"),
                    ("fixtures/x.py", "fixture"), ("examples/demo.py", "example"), ("scripts/build.py", "script"),
                    ("vendor/lib.js", "vendor"), ("node_modules/x/i.js", "vendor"), ("web/app.min.js", "vendor"),
                    ("docs/conf.py", "docs"), ("src/app/models.py", "source")]:
        assert A.file_scope(rel) == sc, rel


def test_aux_tables_and_routes_are_split_out():
    m = A.link(_parts({
        "src/models.sql": SQL,
        "tests/users.sql": SQL.replace("users", "only_test"),
        "scripts/r.py": "from flask import Flask\napp = Flask(__name__)\n@app.get('/s')\ndef s():\n    return 1\n",
    }))
    assert set(m["tables"]) == {"users"}
    assert m["aux"]["tables"]["only_test"]["scope"] == "test"
    assert m["routes"] == [] and m["aux"]["routes"][0]["path"] == "/s"


def test_source_table_wins_over_test_copy():
    m = A.link(_parts({"tests/users.sql": SQL, "db/users.sql": SQL}))
    assert "users" in m["tables"] and "users" not in m["aux"]["tables"]


def test_pattern_table_is_not_a_mechanism():
    py = 'PATTERNS = {"rl": r"\\bthrottle\\b", "c": "@lru_cache", "r": "for i in range(3): sleep(1)"}\n'
    assert C.detect_file("p.py", py, A.analyze_file("p.py", py)) == {}
    real = "from functools import lru_cache\n@lru_cache\ndef f():\n    pass\n"
    assert "caching" in C.detect_file("q.py", real, A.analyze_file("q.py", real))


def test_js_strings_and_regex_ignored():
    js = "const P = ['new WebSocket(', /process\\.env\\./];\nconst t = `Promise.all(`;\n"
    assert C.detect_file("a.js", js, A.analyze_file("a.js", js)) == {}
    real = "const x = process.env.PORT;\n"
    assert "config-env" in C.detect_file("b.js", real, A.analyze_file("b.js", real))


def test_sql_in_string_still_detected():
    py = 'import sqlite3\ndef f(c):\n    c.execute("select id from users")\n'
    assert "sql" in C.detect_file("s.py", py, A.analyze_file("s.py", py))


def test_layers_for_cli_and_libraries():
    L = A.layer_of
    assert L("src/pkg/cli.py") == "interface" and L("src/pkg/__main__.py") == "interface"
    assert L("src/pkg/mcp.py") == "interface" and L("src/pkg/server.py") == "interface"
    assert L("src/pkg/analyze.py") == "service" and L("src/pkg/track.py") == "data"
    assert L("web/assets/site.js") == "ui" and L("web/index.html") == "ui"
    assert L("scripts/demo_session.py") == "tooling" and L("examples/a.py") == "tooling"
    assert L("tests/test_a.py") == "test"


def test_comments_are_not_evidence():
    py = "# uses a token_bucket and lru_cache\nx = 1\n"
    assert C.detect_file("c.py", py, A.analyze_file("c.py", py)) == {}
    js = "// process.env.X\n/* new WebSocket( */\nlet a = 1;\n"
    assert C.detect_file("c.js", js, A.analyze_file("c.js", js)) == {}
