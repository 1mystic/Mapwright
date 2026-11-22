"""A scripted agent session: builds a small order service in seven turns through the same
interfaces a real agent uses (hook events for prompts, edits and turn ends; MCP tool calls for
steps, todos and claims). Used for the website demo, the screenshots and the tests.

    python scripts/demo_session.py /tmp/shop-api          # build the project and its history
    MAPWRIGHT_HOME=/tmp/mwh python scripts/demo_session.py /tmp/shop-api

Turn 7 is deliberately dishonest (a step title that claims tests, a todo marked done with
evidence that did not change, a claim with no code behind it) to show what verification catches.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mapwright import hooks, mcp  # noqa: E402
from mapwright.track import open_project  # noqa: E402

F: dict[int, dict[str, str]] = {}
F[1] = {
    "README.md": "# shop-api\n\nOrder service: customers, orders, pricing and payments.\n\n```bash\npip install -r requirements.txt\nuvicorn app.main:app --reload\n```\n",
    "requirements.txt": "fastapi==0.115.0\nuvicorn==0.30.6\nsqlalchemy==2.0.35\npsycopg[binary]==3.2.3\nredis==5.1.1\ncelery==5.4.0\nstripe==10.12.0\npydantic==2.9.2\n",
    "app/__init__.py": "",
    "app/main.py": '''"""HTTP entry point."""
from fastapi import FastAPI

app = FastAPI(title="shop-api")


@app.get("/health")
def health():
    return {"ok": True}
''',
}
F[2] = {
    "db/schema.sql": '''CREATE TABLE customers (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  tier VARCHAR(16) NOT NULL DEFAULT 'standard'
);
CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  status VARCHAR(16) NOT NULL DEFAULT 'new',
  total NUMERIC(10,2) NOT NULL
);
CREATE TABLE order_items (
  id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id),
  sku VARCHAR(40) NOT NULL,
  qty INTEGER NOT NULL,
  unit_price NUMERIC(10,2) NOT NULL
);
''',
    "app/db.py": '''"""Database session."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

engine = create_engine(os.environ.get("DATABASE_URL", "sqlite:///shop.db"))
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
''',
    "app/models.py": '''"""ORM models mirroring db/schema.sql."""
from sqlalchemy import Column, ForeignKey, Integer, Numeric, String

from .db import Base


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    tier = Column(String(16), default="standard")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    status = Column(String(16), default="new")
    total = Column(Numeric(10, 2))


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    sku = Column(String(40))
    qty = Column(Integer)
    unit_price = Column(Numeric(10, 2))
''',
}
F[3] = {
    "app/services/__init__.py": "",
    "app/services/pricing.py": '''"""Prices, tiers and discounts."""
from bisect import bisect_right
from dataclasses import dataclass

TIER_THRESHOLDS = [0, 100, 500, 2000]
TIER_RATES = [0.0, 0.02, 0.05, 0.08]


def volume_rate(subtotal: float) -> float:
    """Volume discount rate for a subtotal (binary search over thresholds)."""
    return TIER_RATES[bisect_right(TIER_THRESHOLDS, subtotal) - 1]


def apply_discount(total: float, percent: float) -> float:
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return round(total * (1 - percent / 100), 2)


@dataclass
class Pricing:
    tax_rate: float = 0.2

    def quote(self, items: list[dict], tier: str = "standard") -> float:
        subtotal = sum(i["qty"] * i["unit_price"] for i in items)
        if not items:
            return 0.0
        rate = volume_rate(subtotal)
        if tier == "gold":
            rate += 0.05
        elif tier == "silver":
            rate += 0.02
        discounted = apply_discount(subtotal, min(rate, 0.3) * 100)
        return round(discounted * (1 + self.tax_rate), 2)
''',
    "tests/__init__.py": "",
    "tests/test_pricing.py": '''from app.services.pricing import Pricing, apply_discount, volume_rate


def test_volume_rate_tiers():
    assert volume_rate(50) == 0.0
    assert volume_rate(600) == 0.05


def test_apply_discount():
    assert apply_discount(200, 10) == 180


def test_quote_gold():
    assert Pricing(tax_rate=0).quote([{"qty": 1, "unit_price": 100}], "gold") == 93.0
''',
}
F[4] = {
    "app/services/orders.py": '''"""Order use cases."""
from sqlalchemy.orm import Session

from ..models import Customer, Order, OrderItem
from .pricing import Pricing

pricing = Pricing()


def list_orders(session: Session, customer_id: int, limit: int = 20, offset: int = 0):
    q = session.query(Order).filter(Order.customer_id == customer_id)
    return q.order_by(Order.id.desc()).limit(limit).offset(offset).all()


def create_order(session: Session, customer_id: int, items: list[dict]) -> Order:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise LookupError("unknown customer")
    order = Order(customer_id=customer_id, total=pricing.quote(items, customer.tier))
    session.add(order)
    session.flush()
    for it in items:
        session.add(OrderItem(order_id=order.id, sku=it["sku"], qty=it["qty"], unit_price=it["unit_price"]))
    session.commit()
    return order
''',
    "app/api/__init__.py": "",
    "app/api/orders.py": '''"""Order routes."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import get_session
from ..services import orders as svc

router = APIRouter(prefix="/orders")


class Item(BaseModel):
    sku: str
    qty: int
    unit_price: float


class NewOrder(BaseModel):
    customer_id: int
    items: list[Item]


@router.get("/")
def get_orders(customer_id: int, session=Depends(get_session)):
    return svc.list_orders(session, customer_id)


@router.post("/")
def post_order(body: NewOrder, session=Depends(get_session)):
    try:
        return svc.create_order(session, body.customer_id, [i.model_dump() for i in body.items])
    except LookupError as e:
        raise HTTPException(404, str(e))
''',
    "app/main.py": '''"""HTTP entry point."""
from fastapi import FastAPI

from .api.orders import router as orders_router

app = FastAPI(title="shop-api")
app.include_router(orders_router)


@app.get("/health")
def health():
    return {"ok": True}
''',
}
F[5] = {
    "app/clients/__init__.py": "",
    "app/clients/payments.py": '''"""Card payments through Stripe, with retries."""
import os
import time

import stripe

stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
MAX_RETRIES = 4


class PaymentError(Exception):
    pass


def charge(amount_cents: int, customer_ref: str) -> str:
    """Create a payment intent; retry transient failures with exponential backoff."""
    delay = 0.5
    for attempt in range(MAX_RETRIES):
        try:
            intent = stripe.PaymentIntent.create(amount=amount_cents, currency="eur", customer=customer_ref)
            return intent.id
        except stripe.error.RateLimitError:
            if attempt == MAX_RETRIES - 1:
                raise PaymentError("payment provider is busy")
            time.sleep(delay)
            delay *= 2
        except stripe.error.CardError as e:
            raise PaymentError(str(e))
    raise PaymentError("unreachable")
''',
    "app/services/checkout.py": '''"""Checkout: price, charge, confirm."""
from ..clients.payments import PaymentError, charge
from ..models import Order


def checkout(session, order: Order, customer_ref: str) -> Order:
    if order.status != "new":
        raise ValueError("order already processed")
    try:
        charge(int(order.total * 100), customer_ref)
    except PaymentError:
        order.status = "payment_failed"
        session.commit()
        raise
    order.status = "paid"
    session.commit()
    return order
''',
}
F[6] = {
    "app/cache.py": '''"""Read-through cache in Redis."""
import functools
import json
import os

import redis

r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def cached(ttl: int = 60):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args):
            key = f"{fn.__name__}:{json.dumps(args, default=str)}"
            hit = r.get(key)
            if hit is not None:
                return json.loads(hit)
            value = fn(*args)
            r.setex(key, ttl, json.dumps(value, default=str))
            return value
        return wrapper
    return deco
''',
    "app/worker.py": '''"""Background jobs."""
import os
import smtplib

from celery import Celery

celery = Celery("shop", broker=os.environ.get("REDIS_URL", "redis://localhost:6379/1"))


@celery.task(bind=True, max_retries=3)
def send_receipt(self, email: str, order_id: int):
    try:
        with smtplib.SMTP(os.environ.get("SMTP_HOST", "localhost")) as s:
            s.sendmail("shop@example.com", [email], f"Subject: Order {order_id}\\n\\nThanks for your order.")
    except OSError as e:
        raise self.retry(exc=e, countdown=30)
''',
    "Dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\nEXPOSE 8000\nCMD [\"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\"]\n",
    "docker-compose.yml": '''services:
  api:
    build: .
    ports: ["8000:8000"]
    depends_on: [db, redis]
  worker:
    build: .
    command: celery -A app.worker worker
    depends_on: [redis]
  db:
    image: postgres:16
    ports: ["5432:5432"]
  redis:
    image: redis:7
''',
    ".env.example": "DATABASE_URL=postgresql://shop:shop@localhost:5432/shop\nREDIS_URL=redis://localhost:6379/0\nSTRIPE_API_KEY=sk_test_replace_me\nSMTP_HOST=localhost\n",
    "infra/main.tf": '''provider "aws" {
  region = "eu-west-1"
}

resource "aws_db_instance" "shop" {
  engine         = "postgres"
  instance_class = "db.t4g.micro"
}

resource "aws_elasticache_cluster" "cache" {
  engine    = "redis"
  node_type = "cache.t4g.micro"
}

resource "aws_s3_bucket" "receipts" {
  bucket = "shop-receipts"
}
''',
    ".github/workflows/ci.yml": "name: tests\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: pip install -r requirements.txt pytest\n      - run: pytest -q\n",
}
F[7] = {
    "README.md": F[1]["README.md"] + "\n## Integration tests\n\nRun `pytest -q tests/` against a local Postgres.\n",
}

TURNS = [
    (1, "Set up a FastAPI order service with a health check", "Scaffold the service", [("todo", {"action": "add", "text": "data model for customers and orders"}),
                                                                                     ("todo", {"action": "add", "text": "pricing with volume tiers"}),
                                                                                     ("todo", {"action": "add", "text": "payments with retries"})]),
    (2, "Add the data model: customers, orders and order items", "Add schema and ORM models", [("todo", {"action": "done", "id": "T1", "evidence": "app/models.py"}),
                                                                                             ("note", {"symbol": "app.models", "role": "ORM models mirroring db/schema.sql"})]),
    (3, "Pricing: volume tiers, customer tiers, discounts, with tests", "Add pricing service and tests", [("todo", {"action": "done", "id": "T2", "evidence": "Pricing.quote"}),
                                                                                                         ("note", {"symbol": "Pricing.quote", "role": "final price: volume tier + customer tier, capped at 30%, plus tax"})]),
    (4, "Expose orders over HTTP: list and create", "Add orders API and service", [("link", {"from": "post_order", "to": "create_order", "label": "use case"})]),
    (5, "Take card payments at checkout; retry when Stripe is rate limiting", "Add payments client and checkout", [("claim", {"concept": "retry-backoff", "symbol": "charge"}),
                                                                                                                ("todo", {"action": "done", "id": "T3", "evidence": "charge"})]),
    (6, "Cache reads in Redis, send receipts in the background, add Docker, Terraform and CI", "Add cache, worker, containers and infrastructure",
     [("claim", {"concept": "caching", "symbol": "cached"}), ("claim", {"concept": "queue-jobs", "symbol": "send_receipt"}), ("todo", {"action": "add", "text": "integration tests against Postgres"})]),
    (7, "Add integration tests", "Add integration tests for orders and checkout", [("todo", {"action": "done", "id": "T4", "evidence": "create_order"}),
                                                                                     ("claim", {"concept": "rate-limiting", "symbol": "post_order"})]),
]


def run(root: str, quiet: bool = False) -> str:
    rootp = Path(root)
    if rootp.exists():
        shutil.rmtree(rootp)
    rootp.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(rootp)], check=False)
    p = open_project(str(rootp))
    p.refresh()  # baseline: an empty repository
    sid = "demo"

    def hook(payload: dict) -> None:
        hooks.handle("claude-code", {"session_id": sid, "cwd": str(rootp), **payload})

    def tool(name: str, args: dict) -> str:
        out = mcp.handle(p, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
        text = out["result"]["content"][0]["text"]
        if not quiet:
            print(f"  {name}: {text.splitlines()[0][:110]}")
        return text

    for n, prompt, title, calls in TURNS:
        if not quiet:
            print(f"turn {n}: {prompt}")
        hook({"hook_event_name": "UserPromptSubmit", "prompt": prompt})
        if n == 1:
            tool("map", {})
        for rel, text in F[n].items():
            path = rootp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            hook({"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": str(path)}})
        if n == 3:
            hook({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "pytest -q"}})
        for name, args in calls:
            if name in ("claim", "note", "link", "todo") and not (name == "todo" and args["action"] == "add" and n == 6):
                tool(name, args)
        if n == 6:
            tool("todo", calls[-1][1])
        tool("step", {"title": title})
        hook({"hook_event_name": "Stop"})
    if not quiet:
        print("verification problems:")
        for x in p.verify()["problems"]:
            print("  -", x["text"])
    return p.key


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "shop-api-demo")
    key = run(target)
    print(json.dumps({"project": target, "key": key}))
