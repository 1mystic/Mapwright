"""Infrastructure and cloud: what the project runs on and talks to, read from the files that describe it.

Sources: Dockerfile, docker-compose, Terraform, Kubernetes manifests, serverless.yml, Procfile,
GitHub Actions, Vercel/Netlify/Fly/Render configs, `.env.example` keys, and the SDKs the code
imports. Every node records the file it came from.
"""

from __future__ import annotations

import json
import os
import re

KINDS = ("app", "container", "function", "db", "cache", "queue", "storage", "search", "external", "ci", "cdn", "cloud")

# SDK / driver import -> (node id, label, kind)
SDKS = {
    "boto3": ("aws", "AWS", "cloud"), "botocore": ("aws", "AWS", "cloud"), "@aws-sdk": ("aws", "AWS", "cloud"), "aws-sdk": ("aws", "AWS", "cloud"),
    "google.cloud": ("gcp", "Google Cloud", "cloud"), "@google-cloud": ("gcp", "Google Cloud", "cloud"), "firebase_admin": ("firebase", "Firebase", "cloud"),
    "firebase": ("firebase", "Firebase", "cloud"), "azure": ("azure", "Azure", "cloud"), "@azure": ("azure", "Azure", "cloud"),
    "psycopg": ("postgres", "PostgreSQL", "db"), "psycopg2": ("postgres", "PostgreSQL", "db"), "asyncpg": ("postgres", "PostgreSQL", "db"), "pg": ("postgres", "PostgreSQL", "db"),
    "pymysql": ("mysql", "MySQL", "db"), "mysql": ("mysql", "MySQL", "db"), "mysql2": ("mysql", "MySQL", "db"),
    "sqlite3": ("sqlite", "SQLite", "db"), "better-sqlite3": ("sqlite", "SQLite", "db"),
    "pymongo": ("mongodb", "MongoDB", "db"), "motor": ("mongodb", "MongoDB", "db"), "mongoose": ("mongodb", "MongoDB", "db"), "mongodb": ("mongodb", "MongoDB", "db"),
    "redis": ("redis", "Redis", "cache"), "ioredis": ("redis", "Redis", "cache"), "aioredis": ("redis", "Redis", "cache"),
    "celery": ("broker", "Task broker", "queue"), "pika": ("rabbitmq", "RabbitMQ", "queue"), "aio_pika": ("rabbitmq", "RabbitMQ", "queue"), "amqplib": ("rabbitmq", "RabbitMQ", "queue"),
    "kafka": ("kafka", "Kafka", "queue"), "aiokafka": ("kafka", "Kafka", "queue"), "confluent_kafka": ("kafka", "Kafka", "queue"), "kafkajs": ("kafka", "Kafka", "queue"),
    "bullmq": ("redis", "Redis", "cache"), "elasticsearch": ("elasticsearch", "Elasticsearch", "search"), "@elastic/elasticsearch": ("elasticsearch", "Elasticsearch", "search"),
    "meilisearch": ("meilisearch", "Meilisearch", "search"), "stripe": ("stripe", "Stripe", "external"), "@stripe": ("stripe", "Stripe", "external"),
    "sendgrid": ("sendgrid", "SendGrid", "external"), "twilio": ("twilio", "Twilio", "external"), "resend": ("resend", "Resend", "external"),
    "anthropic": ("anthropic", "Anthropic API", "external"), "@anthropic-ai": ("anthropic", "Anthropic API", "external"),
    "openai": ("openai", "OpenAI API", "external"), "slack_sdk": ("slack", "Slack", "external"), "@slack": ("slack", "Slack", "external"),
    "supabase": ("supabase", "Supabase", "cloud"), "@supabase": ("supabase", "Supabase", "cloud"), "@prisma/client": ("prisma-db", "Database (Prisma)", "db"),
}
# env key -> (node id, label, kind); the value of a URL can refine the label
ENV = [
    (r"^(DATABASE_URL|DB_URL|POSTGRES\w*|PG\w+)$", ("db", "Database", "db")), (r"^MYSQL\w*$", ("mysql", "MySQL", "db")),
    (r"^(MONGO\w*)$", ("mongodb", "MongoDB", "db")), (r"^REDIS\w*$", ("redis", "Redis", "cache")),
    (r"^(AMQP\w*|RABBIT\w*|BROKER_URL|CELERY_BROKER\w*)$", ("broker", "Message broker", "queue")), (r"^KAFKA\w*$", ("kafka", "Kafka", "queue")),
    (r"^(AWS_\w+|S3_\w+)$", ("aws", "AWS", "cloud")), (r"^(GCP_\w+|GOOGLE_APPLICATION_CREDENTIALS)$", ("gcp", "Google Cloud", "cloud")),
    (r"^AZURE_\w+$", ("azure", "Azure", "cloud")), (r"^STRIPE_\w+$", ("stripe", "Stripe", "external")),
    (r"^(SMTP_\w+|SENDGRID\w*|MAILGUN\w*|POSTMARK\w*|RESEND\w*)$", ("email", "Email provider", "external")),
    (r"^ANTHROPIC_\w+$", ("anthropic", "Anthropic API", "external")), (r"^OPENAI_\w+$", ("openai", "OpenAI API", "external")),
    (r"^SENTRY_\w+$", ("sentry", "Sentry", "external")), (r"^(ELASTIC\w*|OPENSEARCH\w*)$", ("elasticsearch", "Elasticsearch", "search")),
]
_IMAGE_KIND = [(r"postgres|postgis|timescale", "db", "PostgreSQL"), (r"mysql|mariadb", "db", "MySQL"), (r"mongo", "db", "MongoDB"),
               (r"redis|valkey|keydb", "cache", "Redis"), (r"memcached", "cache", "Memcached"), (r"rabbitmq", "queue", "RabbitMQ"),
               (r"kafka|redpanda", "queue", "Kafka"), (r"elasticsearch|opensearch", "search", "Search"), (r"meilisearch|typesense", "search", "Search"),
               (r"minio|localstack", "storage", "Object storage"), (r"nginx|traefik|caddy|envoy|haproxy", "cdn", "Proxy"),
               (r"clickhouse", "db", "ClickHouse"), (r"cassandra|scylla", "db", "Cassandra")]
_TF_KIND = [(r"_(db_instance|rds_cluster|sql_database_instance|sql_server|postgresql|mysql|dynamodb_table|cosmosdb|firestore|bigtable|spanner)", "db"),
            (r"_(elasticache|memorystore|redis)", "cache"), (r"_(sqs|sns|pubsub|kinesis|eventbridge|servicebus|eventhub|msk|mq_broker)", "queue"),
            (r"_(s3_bucket|storage_bucket|storage_account|storage_container)$", "storage"), (r"_(lambda_function|cloudfunctions|cloud_run|function_app|app_runner)", "function"),
            (r"_(ecs_service|ecs_task|eks|container_cluster|kubernetes|instance|compute_instance|virtual_machine|app_service|beanstalk)", "container"),
            (r"_(cloudfront|cdn|lb|alb|elb|load_balancer|api_gateway|apigateway)", "cdn"), (r"_(opensearch|elasticsearch)", "search")]


def mini_yaml(text: str):
    """A small YAML subset (mappings, lists, scalars, inline [a, b]) for compose/k8s/workflow files when
    PyYAML is not installed. Anchors, multi-line strings and flow mappings are not supported."""
    try:
        import yaml  # type: ignore
        docs = [d for d in yaml.safe_load_all(text) if d is not None]
        return docs[0] if len(docs) == 1 else docs
    except ImportError:
        pass
    except Exception:
        return None

    def scalar(v: str):
        v = v.strip()
        if not v:
            return None
        if v[0] in "\"'" and v[-1] == v[0]:
            return v[1:-1]
        if v.startswith("[") and v.endswith("]"):
            return [scalar(x) for x in v[1:-1].split(",") if x.strip()]
        return v
    docs = []
    for chunk in re.split(r"(?m)^---\s*$", text):
        lines = [(len(ln) - len(ln.lstrip(" ")), ln.strip()) for ln in chunk.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        pos = 0

        def block(indent: int):
            nonlocal pos
            if pos >= len(lines):
                return None
            if lines[pos][1].startswith("- "):
                out = []
                while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                    item = lines[pos][1][2:]
                    if re.match(r"^[\w.\-\"']+:\s", item + " ") and not item.startswith(("http", "\"", "'")):
                        lines[pos] = (indent + 2, item)
                        out.append(block(indent + 2))
                    else:
                        pos += 1
                        out.append(scalar(item))
                return out
            out = {}
            while pos < len(lines) and lines[pos][0] == indent and not lines[pos][1].startswith("- "):
                m = re.match(r"^([^:]+?):(?:\s+(.*))?$", lines[pos][1])
                if not m:
                    pos += 1
                    continue
                key, val = m.group(1).strip().strip("\"'"), m.group(2)
                pos += 1
                if val and val.strip() not in ("|", ">", "|-", ">-"):
                    out[key] = scalar(val)
                elif pos < len(lines) and (lines[pos][0] > indent or (lines[pos][0] == indent and lines[pos][1].startswith("- "))):
                    out[key] = block(lines[pos][0])
                else:
                    out[key] = None
            return out
        d = block(lines[0][0]) if lines else None
        if d is not None:
            docs.append(d)
    return docs[0] if len(docs) == 1 else docs


def detect(root: str, index: dict, read, modules: dict) -> dict:
    """{nodes: [...], edges: [...]} for the infrastructure diagram. `read(rel)` returns file text."""
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str, str]] = set()

    def node(nid: str, label: str, kind: str, src: str, detail: str = "", group: str = "") -> str:
        nid = re.sub(r"[^\w-]", "_", nid)[:60]
        n = nodes.setdefault(nid, {"id": nid, "label": label, "kind": kind, "sources": [], "detail": detail, "group": group})
        if src not in n["sources"]:
            n["sources"].append(src)
        if detail and not n["detail"]:
            n["detail"] = detail
        if group and not n["group"]:
            n["group"] = group
        return nid

    app = None
    if modules:
        app = node("app", os.path.basename(root.rstrip("/")) or "app", "app", "source code",
                   f"{len(modules)} modules", "application")
    files = sorted(index)
    for rel in files:
        base = os.path.basename(rel)
        low = rel.lower()
        text = None
        if base in ("Dockerfile", "Containerfile") or base.endswith(".Dockerfile") or base.startswith("Dockerfile."):
            text = read(rel) or ""
            img = re.findall(r"(?im)^\s*FROM\s+(\S+)", text)
            ports = re.findall(r"(?im)^\s*EXPOSE\s+([\d\s/a-z]+)", text)
            cid = node("container_" + (os.path.dirname(rel) or "app"), f"container ({os.path.dirname(rel) or 'root'})", "container", rel,
                       ("from " + img[-1] if img else "") + (f" · port {' '.join(ports).strip()}" if ports else ""), "containers")
            if app:
                edges.add((cid, app, "runs"))
        elif re.search(r"(^|/)(docker-)?compose[\w.-]*\.ya?ml$", low):
            doc = mini_yaml(read(rel) or "")
            services = (doc or {}).get("services") if isinstance(doc, dict) else None
            if isinstance(services, dict):
                for name, svc in services.items():
                    svc = svc if isinstance(svc, dict) else {}
                    image = str(svc.get("image") or "")
                    kind, label = "container", name
                    for pat, k, lab in _IMAGE_KIND:
                        if re.search(pat, image.lower()) or re.search(pat, name.lower()):
                            kind, label = k, f"{name} ({lab})"
                            break
                    ports = svc.get("ports") or []
                    detail = (image or ("build " + str(svc.get("build")) if svc.get("build") else "")) + \
                             (f" · ports {', '.join(map(str, ports))}" if isinstance(ports, list) and ports else "")
                    sid = node("svc_" + name, label, kind, rel, detail, "docker compose")
                    deps = svc.get("depends_on") or []
                    for d in (deps if isinstance(deps, list) else list(deps) if isinstance(deps, dict) else []):
                        edges.add((sid, "svc_" + re.sub(r"[^\w-]", "_", str(d)), "depends on"))
                    if svc.get("build") and app:
                        edges.add((sid, app, "builds"))
        elif low.endswith(".tf"):
            text = read(rel) or ""
            for prov in re.findall(r'(?m)^\s*provider\s+"([\w-]+)"', text):
                node("tf_provider_" + prov, {"aws": "AWS", "google": "Google Cloud", "azurerm": "Azure"}.get(prov, prov), "cloud", rel, "terraform provider", "terraform")
            for rtype, rname in re.findall(r'(?m)^\s*resource\s+"([\w-]+)"\s+"([\w-]+)"', text):
                kind = next((k for pat, k in _TF_KIND if re.search(pat, rtype)), None)
                if not kind:
                    continue
                rid = node(f"tf_{rtype}_{rname}", f"{rname} ({rtype.split('_', 1)[-1].replace('_', ' ')})", kind, rel, rtype, "terraform")
                prov = rtype.split("_")[0]
                pid = {"aws": "tf_provider_aws", "google": "tf_provider_google", "azurerm": "tf_provider_azurerm"}.get(prov)
                if pid:
                    edges.add((rid, pid, "on"))
            for a, b in re.findall(r'resource\s+"[\w-]+"\s+"([\w-]+)"[^{]*\{[^}]*?\b[a-z]+_[\w]+\.([\w-]+)\.', text):
                pass  # cross-resource references are noisy; providers are enough for the overview
        elif low.endswith((".yaml", ".yml")) and re.search(r"(?m)^kind:\s*(Deployment|StatefulSet|Service|Ingress|CronJob|DaemonSet)\b", read(rel) or ""):
            text = read(rel) or ""
            for kind_, name in re.findall(r"(?ms)^kind:\s*(\w+).*?^\s+name:\s*([\w.-]+)", text):
                k = {"Ingress": "cdn", "CronJob": "function", "StatefulSet": "db"}.get(kind_, "container")
                node(f"k8s_{kind_}_{name}", f"{name} ({kind_})", k, rel, "kubernetes", "kubernetes")
        elif re.search(r"(^|/)serverless\.ya?ml$", low):
            doc = mini_yaml(read(rel) or "") or {}
            for fn in (doc.get("functions") or {}) if isinstance(doc, dict) else {}:
                fid = node("fn_" + fn, f"{fn} (function)", "function", rel, "serverless", "serverless")
                if app:
                    edges.add((fid, app, "runs"))
        elif base == "Procfile":
            for proc, cmd in re.findall(r"(?m)^([\w-]+):\s*(.+)$", read(rel) or ""):
                node("proc_" + proc, f"{proc} process", "container", rel, cmd.strip()[:60], "processes")
        elif low.startswith(".github/workflows/") and low.endswith((".yml", ".yaml")):
            text = read(rel) or ""
            m = re.search(r"(?m)^name:\s*(.+)$", text)
            node("ci_" + base.rsplit(".", 1)[0], f"CI: {(m.group(1).strip() if m else base)[:40]}", "ci", rel, "GitHub Actions", "delivery")
        elif base in ("vercel.json", "netlify.toml", "fly.toml", "render.yaml", "app.yaml", "railway.json", "wrangler.toml"):
            label = {"vercel.json": "Vercel", "netlify.toml": "Netlify", "fly.toml": "Fly.io", "render.yaml": "Render",
                     "app.yaml": "App Engine", "railway.json": "Railway", "wrangler.toml": "Cloudflare Workers"}[base]
            hid = node("host_" + label.lower().replace(" ", "_").replace(".", ""), label, "cloud", rel, "hosting", "hosting")
            if app:
                edges.add((app, hid, "deployed to"))
        elif re.match(r"(^|.*/)\.env\.(example|sample|template)$", low) or base in (".env.example", ".env.sample", ".env.template"):
            for key, val in re.findall(r"(?m)^\s*([A-Z][A-Z0-9_]+)\s*=\s*(.*)$", read(rel) or ""):
                for pat, (nid, label, kind) in ENV:
                    if re.match(pat, key):
                        v = val.lower()
                        if nid == "db":
                            nid, label = next(((i, lab) for s_, i, lab in (("postgres", "postgres", "PostgreSQL"), ("mysql", "mysql", "MySQL"),
                                                                        ("sqlite", "sqlite", "SQLite"), ("mongodb", "mongodb", "MongoDB"))
                                               if s_ in v), (nid, label))
                        n_ = node(nid, label, kind, rel, f"env {key}", "services")
                        if app:
                            edges.add((app, n_, "uses"))
                        break
    for mid, mod in modules.items():
        for e in mod.get("ext", []):
            for prefix, (nid, label, kind) in SDKS.items():
                if e == prefix or e.startswith(prefix + ".") or e.startswith(prefix + "/"):
                    n_ = node(nid, label, kind, mod["file"], f"imported by {mod['file']}", "services")
                    if app:
                        edges.add((app, n_, "uses"))
                    break
    # merge the same backing service found two ways (e.g. compose `db` with image postgres + psycopg import)
    by_label = {}
    for nid, n in list(nodes.items()):
        if n["kind"] in ("db", "cache", "queue", "search") and nid.startswith("svc_"):
            by_label[n["label"].split("(")[-1].rstrip(")").lower()] = nid
    for nid, n in list(nodes.items()):
        if not nid.startswith(("svc_", "tf_", "k8s_")) and n["kind"] in ("db", "cache", "queue", "search"):
            twin = by_label.get(n["label"].lower())
            if twin:
                nodes[twin]["sources"] += [s for s in n["sources"] if s not in nodes[twin]["sources"]]
                del nodes[nid]
                edges = {(twin if a == nid else a, twin if b == nid else b, lab) for a, b, lab in edges}
    edges = {e for e in edges if e[0] in nodes and e[1] in nodes and e[0] != e[1]}
    return {"nodes": sorted(nodes.values(), key=lambda n: (KINDS.index(n["kind"]) if n["kind"] in KINDS else 99, n["id"])),
            "edges": [{"from": a, "to": b, "label": lab} for a, b, lab in sorted(edges)]}


def summary(infra: dict) -> str:
    return json.dumps({n["id"]: n["kind"] for n in infra.get("nodes", [])})
