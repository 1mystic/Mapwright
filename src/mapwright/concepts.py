"""The concept catalog: mechanisms a codebase uses, each with an icon, a one-line meaning and the
signals that give it away in code.

This is the "component library" agents use. An agent never draws a diagram or an icon: it names a
concept id from this catalog and the symbol that implements it (`claim`). Mapwright then checks the
claim against the code with the same signals it uses for detection, so a claim without evidence is
shown as unverified instead of being taken at its word.
"""

from __future__ import annotations

import io
import re
import tokenize

# id: (title, icon, group, meaning, import prefixes, code patterns)
CATALOG: dict[str, tuple[str, str, str, str, tuple[str, ...], tuple[str, ...]]] = {
    "http-api": ("HTTP API", "globe", "interface", "Serves requests over HTTP routes.",
                 ("flask", "fastapi", "django.urls", "starlette", "aiohttp.web", "express", "koa", "hono", "@nestjs", "next/server", "bottle", "tornado"),
                 (r"@\w+\.(get|post|put|patch|delete|route)\(", r"\b(app|router)\.(get|post|put|patch|delete)\(\s*['\"`]/", r"export\s+(async\s+)?function\s+(GET|POST)\b")),
    "graphql": ("GraphQL", "graph", "interface", "Exposes a typed query API.",
                ("graphene", "strawberry", "ariadne", "graphql", "@apollo", "apollo-server", "type-graphql"), (r"\btype\s+Query\s*\{", r"gql`")),
    "websockets": ("WebSockets", "bolt", "interface", "Keeps live two-way connections with clients.",
                   ("websockets", "socket.io", "ws", "socketio", "channels"), (r"@\w+\.websocket\(", r"new\s+WebSocket\(", r"\.on\(\s*['\"]connection['\"]")),
    "cli": ("Command line", "terminal", "interface", "Is driven from a terminal.",
            ("argparse", "click", "typer", "commander", "yargs", "fire", "docopt"), (r"add_subparsers\(", r"@click\.command", r"\.command\(\s*['\"]")),
    "auth": ("Authentication", "key", "security", "Checks who is calling.",
             ("jwt", "jose", "authlib", "passport", "next-auth", "flask_login", "django.contrib.auth", "oauthlib", "fastapi.security", "jsonwebtoken"),
             (r"\b(login|logout|authenticate|verify_token|get_current_user|require_auth|is_authenticated)\b", r"['\"]Authorization['\"]\s*[:\]]", r"['\"]Bearer\b")),
    "password-hashing": ("Password hashing", "lock", "security", "Stores passwords as slow salted hashes.",
                         ("bcrypt", "argon2", "passlib", "scrypt"), (r"\bpbkdf2_hmac\(", r"\b(hash_password|check_password|verify_password)\b", r"bcrypt\.(hash|compare|gensalt)")),
    "encryption": ("Encryption", "shield", "security", "Encrypts data with a key.",
                   ("cryptography", "nacl", "Crypto", "crypto-js"), (r"\bFernet\(", r"createCipheriv\(", r"\bAES\b", r"\bencrypt\(")),
    "input-validation": ("Input validation", "check", "security", "Checks the shape of incoming data.",
                         ("pydantic", "marshmallow", "cerberus", "voluptuous", "zod", "joi", "yup", "class-validator", "ajv"),
                         (r"class\s+\w+\(BaseModel\)", r"\bz\.object\(", r"Joi\.object\(")),
    "rate-limiting": ("Rate limiting", "gauge", "security", "Caps how often a caller can do something.",
                      ("slowapi", "ratelimit", "flask_limiter", "express-rate-limit", "limits", "rate-limiter-flexible"),
                      (r"\b(rate_?limit|token_?bucket|leaky_?bucket|throttle)\w*", r"\bRateLimit\w*")),
    "caching": ("Caching", "layers", "performance", "Keeps results to avoid recomputing or refetching them.",
                ("cachetools", "diskcache", "redis", "memcache", "pymemcache", "aiocache", "node-cache", "lru-cache", "ioredis"),
                (r"@(functools\.)?(lru_cache|cache)\b", r"\bcache\.(get|set)\(", r"\b(setex|expire)\(", r"\bttl\b")),
    "retry-backoff": ("Retry with backoff", "rotate", "resilience", "Tries a failing call again, waiting longer each time.",
                      ("tenacity", "backoff", "retrying", "p-retry", "async-retry"),
                      (r"@retry\b", r"\bfor\s+\w+\s+in\s+range\([^)]*\):[\s\S]{0,300}?\bsleep\(", r"\b(max_retries|backoff|retry_count)\b")),
    "circuit-breaker": ("Circuit breaker", "zap-off", "resilience", "Stops calling a dependency that keeps failing.",
                        ("pybreaker", "circuitbreaker", "opossum"), (r"\bcircuit_?breaker\b", r"\bCircuitBreaker\b")),
    "queue-jobs": ("Background jobs", "inbox", "async", "Hands work to a queue processed outside the request.",
                   ("celery", "rq", "dramatiq", "huey", "arq", "bull", "bullmq", "kafka", "aiokafka", "confluent_kafka", "pika", "aio_pika", "kombu", "sqs"),
                   (r"\.delay\(", r"\.enqueue\(", r"\.apply_async\(", r"@\w+\.task\b", r"new\s+Queue\(", r"send_message\(")),
    "events": ("Events & pub/sub", "radio", "async", "Publishes events that other parts react to.",
               ("blinker", "pyee", "eventemitter3", "events", "redis.client"), (r"\.(emit|publish|subscribe)\(", r"\bEventEmitter\b", r"\bon_event\b", r"\bwebhook")),
    "scheduling": ("Scheduled tasks", "clock", "async", "Runs work on a timer or calendar.",
                   ("apscheduler", "schedule", "croniter", "node-cron", "agenda", "celery.schedules"),
                   (r"\bcrontab\(", r"schedule\.every\(", r"@(scheduled|periodic_task)\b", r"\bbeat_schedule\b", r"cron\.schedule\(")),
    "concurrency": ("Concurrency", "split", "async", "Does several things at once.",
                    ("threading", "multiprocessing", "concurrent.futures", "asyncio", "worker_threads", "trio", "anyio", "gevent"),
                    (r"asyncio\.gather\(", r"ThreadPoolExecutor\(", r"Promise\.all\(", r"\bThread\(", r"create_task\(")),
    "orm": ("ORM / data mapper", "table", "data", "Maps tables to classes.",
            ("sqlalchemy", "django.db", "peewee", "tortoise", "sqlmodel", "pony", "@prisma/client", "prisma", "typeorm", "sequelize", "mongoose", "drizzle-orm", "mikro-orm", "objection"),
            (r"class\s+\w+\((Base|db\.Model|models\.Model|SQLModel)\)", r"\bprisma\.\w+\.(find|create|update)", r"@Entity\(")),
    "sql": ("Raw SQL", "database", "data", "Talks to a database in SQL.",
            ("sqlite3", "psycopg", "psycopg2", "asyncpg", "pymysql", "mysql", "pg", "better-sqlite3", "mysql2", "knex"),
            (r"""['"`]\s*(?i:select)\s+[\w*,\s.()]+\s+(?i:from)\s+\w+""", r"""['"`]\s*(?i:insert\s+into|update\s+\w+\s+set|delete\s+from)\s""", r"(?i)\bcreate\s+table\b")),
    "migrations": ("Schema migrations", "git-merge", "data", "Changes the database schema in tracked steps.",
                   ("alembic", "yoyo", "flyway", "knex", "umzug", "django.db.migrations"), (r"\bop\.(create_table|add_column)\(", r"class\s+Migration\b", r"exports\.up\s*=")),
    "transactions": ("Transactions", "repeat", "data", "Groups writes so they all happen or none do.",
                     (), (r"\.begin\(\)", r"\.transaction\(", r"\.rollback\(", r"(?i)\bBEGIN\s+TRANSACTION\b", r"\batomic\(")),
    "search": ("Search index", "search", "data", "Indexes data for fast search.",
               ("elasticsearch", "opensearchpy", "meilisearch", "typesense", "whoosh", "algoliasearch", "@elastic/elasticsearch", "lunr"),
               (r"\bfull[_ ]?text\b", r"\bto_tsvector\(", r"\bindex\.search\(")),
    "file-storage": ("File & object storage", "box", "data", "Stores files or blobs.",
                     ("boto3", "botocore", "google.cloud.storage", "azure.storage", "minio", "@aws-sdk/client-s3", "multer", "aws-sdk"),
                     (r"\bupload_file\(", r"\bput_object\(", r"\bS3Client\b", r"\bupload\(")),
    "config-env": ("Configuration from environment", "sliders", "operations", "Reads settings from the environment.",
                   ("dotenv", "python-dotenv", "decouple", "pydantic_settings", "environs", "convict"),
                   (r"os\.environ\b", r"os\.getenv\(", r"process\.env\.", r"\bBaseSettings\b")),
    "logging": ("Logging & observability", "activity", "operations", "Records what happens for later inspection.",
                ("logging", "structlog", "loguru", "opentelemetry", "prometheus_client", "sentry_sdk", "winston", "pino", "@sentry", "datadog"),
                (r"logging\.getLogger\(", r"\blogger\.(info|warning|error|debug)\(", r"\bconsole\.(error|warn)\(")),
    "feature-flags": ("Feature flags", "flag", "operations", "Switches behaviour on and off without a deploy.",
                      ("launchdarkly", "unleash", "flagsmith", "growthbook", "posthog"), (r"\bfeature_?flag\w*", r"\bis_enabled\(\s*['\"]")),
    "payments": ("Payments", "card", "external", "Takes payments through a provider.",
                 ("stripe", "paypalrestsdk", "braintree", "adyen", "@stripe"), (r"\bPaymentIntent\b", r"\bcheckout\.Session\b")),
    "email": ("Email", "mail", "external", "Sends email.",
              ("smtplib", "sendgrid", "mailgun", "postmark", "nodemailer", "resend", "email.mime"), (r"\bsend_mail\(", r"\bsendMail\(", r"\bSMTP\(")),
    "llm": ("LLM / AI model calls", "sparkles", "external", "Calls a language or ML model.",
            ("anthropic", "openai", "langchain", "llama_index", "transformers", "@anthropic-ai", "ai", "cohere", "google.generativeai", "ollama"),
            (r"\bmessages\.create\(", r"\bchat\.completions\.create\(", r"\bgenerateText\(")),
    "testing": ("Automated tests", "beaker", "quality", "Checks behaviour with tests.",
                ("pytest", "unittest", "hypothesis", "jest", "vitest", "mocha", "@testing-library", "playwright", "cypress"),
                (r"^\s*def\s+test_\w+\(", r"\b(describe|it|test)\(\s*['\"`]", r"\bassert\b")),
}

# Words that name a mechanism in identifiers. Matched against the claimed symbol's own code with
# case and underscores removed, so TokenBucketLimiter, token_bucket and tokenBucket all count.
WORDS: dict[str, tuple[str, ...]] = {
    "http-api": ("route", "endpoint", "requesthandler", "dopost", "doget", "httpserver", "router", "view"),
    "graphql": ("graphql", "resolver"), "websockets": ("websocket", "socketio"), "cli": ("argparse", "subcommand", "argv"),
    "auth": ("authenticat", "authoriz", "login", "jwt", "bearer", "credential"), "password-hashing": ("bcrypt", "argon2", "pbkdf2", "scrypt", "hashpassword"),
    "encryption": ("encrypt", "decrypt", "cipher", "fernet"), "input-validation": ("validat", "sanitiz", "isvalid", "schema"),
    "rate-limiting": ("ratelimit", "tokenbucket", "leakybucket", "throttl", "limiter", "retryafter", "toomanyrequests"),
    "caching": ("cache", "memoiz", "lru"), "retry-backoff": ("retry", "backoff", "maxretries", "attempt"),
    "circuit-breaker": ("circuitbreaker", "halfopen", "tripped"), "queue-jobs": ("enqueue", "queue", "celery", "worker", "job"),
    "events": ("emit", "publish", "subscribe", "eventbus", "listener", "webhook"), "scheduling": ("schedule", "cron", "periodic"),
    "concurrency": ("thread", "asyncio", "gather", "executor", "lock", "concurrent", "multiprocess"),
    "orm": ("session", "declarativebase", "orm", "model"), "sql": ("select", "insert", "execute", "cursor", "sqlite"),
    "migrations": ("migrat", "alembic", "altertable"), "transactions": ("transaction", "commit", "rollback", "atomic"),
    "search": ("search", "fulltext", "invertedindex"), "file-storage": ("upload", "bucket", "putobject", "blob"),
    "config-env": ("environ", "getenv", "dotenv", "settings"), "logging": ("logger", "logging"),
    "feature-flags": ("featureflag", "isenabled"), "payments": ("payment", "charge", "stripe", "invoice"),
    "email": ("smtp", "sendmail", "email"), "llm": ("anthropic", "openai", "completion", "llm"), "testing": ("pytest", "assert", "expect"),
}

GROUPS = {"interface": "Interface", "security": "Security", "performance": "Performance", "resilience": "Resilience",
          "async": "Async & jobs", "data": "Data", "operations": "Operations", "external": "External services", "quality": "Quality"}

_RX = {cid: [re.compile(p, re.M) for p in spec[5]] for cid, spec in CATALOG.items()}


def _py_string_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges of Python string literal contents (quotes excluded) and comments."""
    starts, pos = [0], 0
    for ln in text.splitlines(keepends=True):
        pos += len(ln)
        starts.append(pos)
    spans = []
    fmid = getattr(tokenize, "FSTRING_MIDDLE", None)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.STRING:
                a, b = starts[tok.start[0] - 1] + tok.start[1], starts[tok.end[0] - 1] + tok.end[1]
                body = tok.string.lstrip("rRbBuUfF")
                q = 3 if body[:3] in ('"""', "'''") else 1
                spans.append((a + len(tok.string) - len(body) + q, b - q))
            elif tok.type == tokenize.COMMENT:
                spans.append((starts[tok.start[0] - 1] + tok.start[1], starts[tok.end[0] - 1] + tok.end[1]))
            elif fmid is not None and tok.type == fmid:
                spans.append((starts[tok.start[0] - 1] + tok.start[1], starts[tok.end[0] - 1] + tok.end[1]))
    except (tokenize.TokenError, IndentationError, SyntaxError, IndexError):
        pass
    return spans


_RX_PREV = set("(,=:[!&|?{};+-*%<>~^") | {""}


def _js_string_spans(text: str) -> list[tuple[int, int]]:
    """Contents of quoted strings, template literals and regex literals in JS/TS."""
    spans, i, n, prev = [], 0, len(text), ""
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            spans.append((i, j))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append((i, j))
            i = j
        elif c in "\"'`":
            j = i + 1
            while j < n and text[j] != c and not (c != "`" and text[j] == "\n"):
                j += 2 if text[j] == "\\" else 1
            spans.append((i + 1, min(j, n)))
            i, prev = j + 1, c
        elif c == "/" and (prev in _RX_PREV or text[max(0, i - 7):i].strip().endswith("return")):
            j, cls = i + 1, False
            while j < n and text[j] != "\n" and (cls or text[j] != "/"):
                cls = (text[j] == "[") or (cls and text[j] != "]")
                j += 2 if text[j] == "\\" else 1
            if j < n and text[j] == "/":
                spans.append((i + 1, j))
                i, prev = j + 1, "/"
            else:
                i += 1
        else:
            if not c.isspace():
                prev = c
            i += 1
    return spans


def _in_spans(pos: int, spans: list[tuple[int, int]], starts: list[int]) -> bool:
    import bisect
    k = bisect.bisect_right(starts, pos) - 1
    return k >= 0 and spans[k][0] <= pos < spans[k][1]


def string_spans(rel: str, text: str) -> list[tuple[int, int]]:
    low = rel.lower()
    if low.endswith(".py"):
        return sorted(_py_string_spans(text))
    if low.endswith((".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")):
        return sorted(_js_string_spans(text))
    return []


def _search(rx: re.Pattern, text: str, spans: list[tuple[int, int]], starts: list[int]):
    """First match of `rx` that does not begin inside a string literal. A pattern table that merely
    lists a signal as text is not evidence the code does it."""
    for m in rx.finditer(text):
        if not spans or not _in_spans(m.start(), spans, starts):
            return m
    return None


def catalog() -> list[dict]:
    return [{"id": cid, "title": t, "icon": icon, "group": g, "meaning": m} for cid, (t, icon, g, m, _, _) in CATALOG.items()]


def _imports_hit(raw_imports: list[str], prefixes: tuple[str, ...]) -> str | None:
    for imp in raw_imports:
        for p in prefixes:
            if imp == p or imp.startswith(p + ".") or imp.startswith(p + "/"):
                return imp
    return None


def detect_file(rel: str, text: str, part: dict | None) -> dict[str, list[dict]]:
    """concept id -> evidence in this file: [{line, signal, symbol}]. At most 3 per concept."""
    raw = (part or {}).get("raw_imports", [])
    funcs = (part or {}).get("functions", [])
    out: dict[str, list[dict]] = {}
    spans = string_spans(rel, text)
    sstarts = [a for a, _ in spans]

    def symbol_at(line: int) -> str | None:
        best = None
        for f in funcs:
            if f["line"] <= line <= f.get("end", f["line"]) and (best is None or f["line"] >= best["line"]):
                best = f
        return best["qual"] if best else None

    for cid, spec in CATALOG.items():
        ev = []
        imp = _imports_hit(raw, spec[4])
        if imp:
            line = next((i + 1 for i, ln in enumerate(text.splitlines()) if re.search(rf"\b{re.escape(imp.split('/')[0].split('.')[0])}\b", ln)
                         and ("import" in ln or "require" in ln)), 1)
            ev.append({"line": line, "signal": f"imports {imp}", "symbol": None})
        for rx in _RX[cid]:
            m = _search(rx, text, spans, sstarts)
            if m:
                line = text.count("\n", 0, m.start()) + 1
                ev.append({"line": line, "signal": "code: " + m.group(0).strip()[:48], "symbol": symbol_at(line)})
            if len(ev) >= 3:
                break
        if cid == "testing" and not re.search(r"(^|/)(tests?|spec|__tests__)/|test_|_test\.|\.(spec|test)\.", rel):
            ev = [e for e in ev if e["signal"].startswith("imports")]  # a bare `assert` is not a test suite
        if cid == "concurrency" and imp == "asyncio" and len(ev) == 1:
            continue  # importing asyncio alone is not doing things at once
        if ev:
            out[cid] = ev[:3]
    return out


def evidence_in(cid: str, text: str, raw_imports: list[str] | None = None) -> str | None:
    """Is there a signal for concept `cid` in this piece of code? Returns the signal, or None.
    Used to verify an agent's claim that a symbol implements a concept."""
    spec = CATALOG.get(cid)
    if not spec:
        return None
    for rx in _RX[cid]:
        m = rx.search(text)
        if m:
            return "code: " + m.group(0).strip()[:48]
    squashed = re.sub(r"[^a-z0-9]", "", text.lower())
    for w in WORDS.get(cid, ()):
        if w in squashed:
            return f"names: {w}"
    low = text.lower()
    for p in spec[4]:
        tail = p.split("/")[-1].split(".")[0].lower()
        if len(tail) > 2 and re.search(rf"\b{re.escape(tail)}\b", low):
            return f"uses {tail}"
    if raw_imports:
        imp = _imports_hit(raw_imports, spec[4])
        if imp:
            return f"module imports {imp}"
    return None
