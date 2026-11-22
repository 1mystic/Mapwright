from mapwright import analyze as A
from mapwright import concepts as C
from mapwright import flow, infra


def model(files: dict):
    parts = {rel: A.analyze_file(rel, text) for rel, text in files.items() if A.analyze_file(rel, text)}
    return A.link(parts)


def test_python_functions_routes_and_call_graph():
    m = model({
        "app/api.py": 'from fastapi import APIRouter\nfrom .services import orders as svc\nrouter = APIRouter(prefix="/orders")\n\n'
                      '@router.post("/")\ndef create(body):\n    return svc.place(body)\n\n@router.get("/{oid}")\ndef show(oid):\n    return svc.get(oid)\n',
        "app/services/orders.py": "from ..models import Order\n\ndef place(body):\n    o = Order(**body)\n    return check(o)\n\n\ndef check(o):\n    if not o:\n        raise ValueError('x')\n    return o\n\n\ndef get(oid):\n    return Order.query.get(oid)\n",
        "app/models.py": "from sqlalchemy import Column, Integer\nclass Order(Base):\n    __tablename__ = 'orders'\n    id = Column(Integer, primary_key=True)\n",
    })
    routes = {(r["method"], r["path"]): r["fid"] for r in m["routes"]}
    assert routes == {("POST", "/orders"): "app.api:create", ("GET", "/orders/{oid}"): "app.api:show"}
    f = m["functions"]
    assert f["app.api:create"]["callees"] == ["app.services.orders:place"]           # through the `svc` alias
    assert f["app.services.orders:place"]["callees"] == ["app.services.orders:check"]
    assert f["app.services.orders:place"]["tables"] == ["orders"] and f["app.services.orders:get"]["tables"] == ["orders"]
    assert "app.api:create" in f["app.services.orders:place"]["callers"]
    assert f["app.services.orders:check"]["complexity"] == 2
    assert m["modules"]["app.api"]["layer"] == "interface" and m["modules"]["app.models"]["layer"] == "data"


def test_method_calls_do_not_jump_to_unrelated_modules():
    m = model({"a.py": "def write(x):\n    pass\n", "b.py": "def save(fh):\n    fh.write('x')\n"})
    assert m["functions"]["b:save"]["callees"] == []


def test_algorithm_hints():
    m = model({"alg.py": "from functools import lru_cache\nfrom collections import deque\nimport bisect\n\n@lru_cache\ndef fib(n):\n    return n if n < 2 else fib(n-1) + fib(n-2)\n\n"
                         "def bfs(g, s):\n    seen = {s}\n    q = deque([s])\n    while q:\n        v = q.popleft()\n        for w in g[v]:\n            if w not in seen:\n                seen.add(w); q.append(w)\n    return seen\n\n"
                         "def find(xs, x):\n    return bisect.bisect_left(xs, x)\n"})
    f = m["functions"]
    assert {"recursion", "memoization"} <= set(f["alg:fib"]["hints"])
    assert "breadth-first search" in f["alg:bfs"]["hints"] and "binary search" in f["alg:find"]["hints"]


def test_js_ts_functions_routes_and_classes():
    m = model({"src/server.ts": "import express from 'express'\nimport { price } from './pricing'\nconst app = express()\n"
                                "app.get('/items', listItems)\nexport async function listItems(req, res) {\n  if (!req) return\n  res.json(price(1))\n}\n"
                                "class Cart extends Base {\n  add(item) {\n    this.total(item)\n  }\n  total(i) { return i }\n}\n",
               "src/pricing.ts": "export const price = (n: number) => n * 2\n"})
    f = m["functions"]
    assert {"src/server:listItems", "src/server:Cart.add", "src/server:Cart.total", "src/pricing:price"} <= set(f)
    assert f["src/server:listItems"]["callees"] == ["src/pricing:price"]
    assert f["src/server:Cart.add"]["callees"] == ["src/server:Cart.total"]
    assert [(r["method"], r["path"], r.get("fid")) for r in m["routes"]] == [("GET", "/items", "src/server:listItems")]


def test_sql_and_prisma_tables():
    m = model({"db/schema.sql": "CREATE TABLE a (id INT PRIMARY KEY);\nCREATE TABLE b (id INT PRIMARY KEY, a_id INT REFERENCES a(id));\n",
               "schema.prisma": "model User {\n  id Int @id\n  posts Post[]\n}\nmodel Post {\n  id Int @id\n  author User @relation(fields: [authorId], references: [id])\n  authorId Int\n}\n"})
    assert m["tables"]["b"]["columns"][1]["fk"] == "a"
    assert {"User", "Post"} <= set(m["tables"])


def test_resolve_and_find():
    m = model({"x.py": "class K:\n    def run(self):\n        pass\n\ndef run():\n    pass\n", "y.py": "def run():\n    pass\n"})
    assert A.resolve(m, "K.run")[1] == "x:K.run"
    assert A.resolve(m, "x:run")[1] == "x:run"
    assert A.resolve(m, "run") is None                      # two top-level functions named run: ambiguous
    assert A.resolve(m, "y.py")[1] == "y"
    assert A.find_symbols(m, "run")[0]["id"] in ("x:run", "x:K.run")


def test_concept_detection_and_evidence():
    text = "import redis\nr = redis.Redis()\n\ndef get(k):\n    v = r.get(k)\n    r.setex(k, 60, v)\n    return v\n"
    part = A.analyze_file("cache.py", text)
    found = C.detect_file("cache.py", text, part)
    assert "caching" in found and found["caching"][0]["line"] >= 1
    assert C.evidence_in("caching", "def get(k):\n    r.setex(k, 60, v)") is not None
    assert C.evidence_in("retry-backoff", "def add(a, b):\n    return a + b") is None
    assert "transactions" not in C.detect_file("k.py", "PEM = '-----BEGIN RSA PRIVATE KEY-----'\n", A.analyze_file("k.py", "PEM = 1\n"))


def test_python_flowchart_maps_nodes_to_lines():
    src = "def f(xs):\n    total = 0\n    for x in xs:\n        if x < 0:\n            continue\n        total += x\n    try:\n        save(total)\n    except OSError:\n        return None\n    return total\n"
    out = flow.python_flow(src, 1)
    assert out["mermaid"].startswith("flowchart TD") and "for x in xs" in out["mermaid"] and "except OSError" in out["mermaid"]
    lines = {n["line"] for n in out["nodes"].values()}
    assert {1, 3, 4, 8, 9} <= lines
    assert flow.python_flow("def g(:\n", 1) is None
    js = flow.js_outline("function h(a) {\n  if (a) {\n    return go(a)\n  }\n  throw new Error('x')\n}\n", 1, 6)
    assert "if" in js["mermaid"] and "throw" in js["mermaid"]


def test_infra_from_compose_terraform_env_and_sdks():
    files = {
        "docker-compose.yml": "services:\n  api:\n    build: .\n    depends_on: [db]\n  db:\n    image: postgres:16\n",
        "infra/main.tf": 'provider "aws" {}\nresource "aws_s3_bucket" "files" {}\nresource "aws_lambda_function" "fn" {}\n',
        ".env.example": "REDIS_URL=redis://x\nSTRIPE_API_KEY=sk_test\n",
        ".github/workflows/ci.yml": "name: tests\non: [push]\n",
        "Dockerfile": "FROM python:3.12\nEXPOSE 8000\n",
    }
    out = infra.detect("/proj", {k: "x" for k in files}, files.get, {"app": {"file": "app.py", "ext": ["boto3", "anthropic"]}})
    ids = {n["id"]: n["kind"] for n in out["nodes"]}
    assert ids["svc_db"] == "db" and ids["tf_aws_s3_bucket_files"] == "storage" and ids["tf_aws_lambda_function_fn"] == "function"
    assert ids["redis"] == "cache" and ids["stripe"] == "external" and ids["anthropic"] == "external" and ids["ci_ci"] == "ci"
    assert {"from": "svc_api", "to": "svc_db", "label": "depends on"} in out["edges"]


def test_mini_yaml_without_pyyaml(monkeypatch):
    import builtins
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == "yaml" else real(n, *a, **k))
    doc = infra.mini_yaml("services:\n  web:\n    image: nginx\n    ports:\n      - \"80:80\"\n    depends_on: [api]\n  api:\n    build: .\n")
    assert doc["services"]["web"]["ports"] == ["80:80"] and doc["services"]["web"]["depends_on"] == ["api"] and doc["services"]["api"]["build"] == "."


def test_sql_inside_code_strings_becomes_tables():
    py = 'SCHEMA = """\nCREATE TABLE IF NOT EXISTS links (\n  id INTEGER PRIMARY KEY,\n  code TEXT UNIQUE\n);\nCREATE TABLE clicks (id INTEGER PRIMARY KEY, link_id INTEGER REFERENCES links(id));\n"""\n'
    js = "db.exec(`CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)`)\n"
    m = model({"store.py": py, "db.js": js})
    assert set(m["tables"]) == {"links", "clicks", "users"} and m["tables"]["clicks"]["columns"][1]["fk"] == "links"
    assert m["tables"]["links"]["line"] == 2


def test_claim_evidence_accepts_camel_and_snake_case_names():
    cls = "class TokenBucketLimiter:\n    def acquire(self, key):\n        self.tokens[key] -= 1\n"
    assert C.evidence_in("rate-limiting", cls) == "names: tokenbucket"
    assert C.evidence_in("rate-limiting", "def do_POST(self):\n    if not self.limiter.allow(ip):\n        self.send_error(429)\n")
    assert C.evidence_in("input-validation", "def validate_url(u):\n    return u.startswith('http')\n")
    assert C.evidence_in("rate-limiting", "def add(a, b):\n    return a + b\n") is None
