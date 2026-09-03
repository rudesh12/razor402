"""gateway/app.py — FastAPI application factory."""
import os
import asyncio
import json
import threading

from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from core.catalog import CATALOG, MERCHANT_ACCOUNT, RECONCILE_TICK_S
from state.db import get_connection, set_db_path
from state.ledger import init_db
from facilitator.rzp import PaymentAdapter
from gateway.webhooks import router as webhook_router
from gateway.checkout import router as checkout_router

# Global adapter
_adapter: PaymentAdapter | None = None
_chaos_mode = "ok"  # ok | rzp_timeout | rzp_refund_timeout


def get_adapter() -> PaymentAdapter:
    global _adapter
    if _adapter is None:
        _adapter = PaymentAdapter()
    return _adapter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init DB, start reconciler."""
    db_path = os.environ.get("DB_PATH", "razor402.db")
    set_db_path(db_path)
    init_db(db_path)

    # Start reconciler
    reconciler_task = asyncio.create_task(_reconciler_loop())

    yield

    reconciler_task.cancel()
    try:
        await reconciler_task
    except asyncio.CancelledError:
        pass


async def _reconciler_loop():
    """Background reconciler loop."""
    from reconciler.sweeper import sweep
    while True:
        try:
            await asyncio.sleep(RECONCILE_TICK_S)
            adapter = get_adapter()
            conn = get_connection()
            sweep(conn, adapter)
        except asyncio.CancelledError:
            break
        except Exception as e:
            # Log but don't crash
            print(f"[reconciler] Error: {e}")
            await asyncio.sleep(5)


app = FastAPI(title="Razor402 Gateway", lifespan=lifespan)

# Include webhook and checkout routers
app.include_router(webhook_router)
app.include_router(checkout_router)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/.well-known/agent-catalog")
async def agent_catalog():
    """Free, unpriced catalog endpoint."""
    items = []
    for item_id, item in CATALOG.items():
        entry = {
            "id": item_id,
            "title": item["title"],
            "pricePaise": item["price_paise"],
            "category": item["category"],
            "specs": item["specs"],
            "purchaseUrl": f"/provision/{item_id}",
        }
        if "description" in item:
            entry["description"] = item["description"]
        if "covers" in item:
            entry["covers"] = item["covers"]
        items.append(entry)

    return {
        "protocol": "razor402/0.1",
        "merchant": {
            "id": MERCHANT_ACCOUNT,
            "name": "BuildBroker",
            "note": "Demonstration merchant. Provisioning is simulated.",
        },
        "currency": "INR",
        "items": items,
    }


@app.api_route("/provision/{item_id}", methods=["GET", "POST"])
async def provision(item_id: str, request: Request):
    """Main provision endpoint — intercepted by 402 middleware."""
    from gateway.middleware import intercept_provision
    adapter = get_adapter()

    # Apply chaos
    global _chaos_mode
    if _chaos_mode == "rzp_timeout":
        adapter.fault = "timeout"
    elif _chaos_mode == "rzp_refund_timeout":
        adapter.fault = "refund_timeout"
    else:
        adapter.fault = None

    return await intercept_provision(request, adapter)


@app.post("/chaos")
async def set_chaos(request: Request):
    global _chaos_mode
    body = await request.json()
    mode = body.get("mode", "ok")
    if mode not in ("ok", "rzp_timeout", "rzp_refund_timeout"):
        return JSONResponse(status_code=400,
                            content={"error": f"Invalid chaos mode: {mode}"})
    _chaos_mode = mode

    adapter = get_adapter()
    if mode == "ok":
        adapter.fault = None
    elif mode == "rzp_timeout":
        adapter.fault = "timeout"
    elif mode == "rzp_refund_timeout":
        adapter.fault = "refund_timeout"

    return {"chaos": _chaos_mode}


@app.get("/chaos")
async def get_chaos():
    return {"chaos": _chaos_mode}


# API endpoints for dashboard (P12)
@app.get("/api/v1/catalog")
async def api_catalog():
    return CATALOG


@app.get("/api/v1/audit")
async def api_audit(limit: int = 50):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,)
    ).fetchall()

    from state.ledger import verify_chain
    valid, head = verify_chain(conn)

    head_row = conn.execute(
        "SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1"
    ).fetchone()

    return {
        "entries": [dict(r) for r in rows],
        "chain_valid": valid,
        "head_hash": head_row["entry_hash"] if head_row else None,
    }


@app.get("/api/v1/txns")
async def api_txns(limit: int = 20):
    conn = get_connection()
    rows = conn.execute(
        "SELECT challenge_id, state, rank, agent_kid, item_id, amount_paise, "
        "payment_id, refund_id, payment_mode, attempts, fail_reason, "
        "created_at, updated_at FROM txn ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return {"transactions": [dict(r) for r in rows]}


@app.get("/api/v1/budget")
async def api_budget(agent: str = "agt_coding_01"):
    conn = get_connection()
    from core.clock import now
    now_ts = now()
    day_start = now_ts - (now_ts % 86400)

    held = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) as total FROM budget_reservations "
        "WHERE agent_kid=? AND status='HELD' AND created_at >= ?",
        (agent, day_start)
    ).fetchone()

    captured = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) as total FROM budget_reservations "
        "WHERE agent_kid=? AND status='CAPTURED' AND created_at >= ?",
        (agent, day_start)
    ).fetchone()

    released = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) as total FROM budget_reservations "
        "WHERE agent_kid=? AND status='RELEASED' AND created_at >= ?",
        (agent, day_start)
    ).fetchone()

    from core.catalog import AGENT_POLICY
    policy = AGENT_POLICY.get(agent, {})
    pool = policy.get("daily_pool_paise", 0)

    return {
        "agent": agent,
        "daily_pool_paise": pool,
        "held_paise": held["total"],
        "captured_paise": captured["total"],
        "released_paise": released["total"],
        "remaining_paise": pool - held["total"] - captured["total"],
    }


@app.post("/api/v1/demo/tamper")
async def api_tamper():
    """Demo-only: tamper with the last audit entry."""
    import sqlite3 as _sqlite3
    db_path = os.environ.get("DB_PATH", "razor402.db")
    raw_conn = _sqlite3.connect(db_path)
    raw_conn.execute("PRAGMA journal_mode=WAL")

    try:
        raw_conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    except Exception:
        pass

    row = raw_conn.execute(
        "SELECT seq, payload FROM audit ORDER BY seq DESC LIMIT 1"
    ).fetchone()

    if row is None:
        raw_conn.close()
        return {"demo_only": True, "error": "No audit entries"}

    seq = row[0]
    payload = json.loads(row[1])
    payload["tampered"] = True
    raw_conn.execute("UPDATE audit SET payload=? WHERE seq=?",
                     (json.dumps(payload), seq))
    raw_conn.commit()

    raw_conn.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit "
        "BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END"
    )
    raw_conn.commit()
    raw_conn.close()

    return {"demo_only": True, "tampered_seq": seq}


# Serve dashboard
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/dashboard")
async def dashboard():
    from fastapi.responses import FileResponse
    html_path = os.path.join(static_dir, "dashboard.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse(status_code=404, content={"error": "Dashboard not built"})


@app.get("/checkout")
async def checkout():
    from fastapi.responses import FileResponse
    html_path = os.path.join(static_dir, "checkout.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse(status_code=404, content={"error": "Checkout page not found"})
