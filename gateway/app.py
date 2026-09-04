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
from gateway.console_api import router as console_router
from gateway.demo_api import router as demo_router

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

# Include webhook, checkout, console, and demo routers
app.include_router(webhook_router)
app.include_router(checkout_router)
app.include_router(console_router)
app.include_router(demo_router)


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
            "seller": item.get("seller", "BuildBroker"),
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
async def api_audit(limit: int = 50, verify: int = 0):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,)
    ).fetchall()

    from state.ledger import verify_chain, _compute_entry_hash
    valid, head = verify_chain(conn)

    head_row = conn.execute(
        "SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1"
    ).fetchone()

    chain_height_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM audit"
    ).fetchone()
    chain_height = chain_height_row["cnt"] if chain_height_row else 0

    if verify == 1:
        # Full sequential verification of each entry
        asc_rows = conn.execute(
            "SELECT seq, challenge_id, event, to_state, to_rank, actor, payload, "
            "prev_hash, entry_hash FROM audit ORDER BY seq ASC"
        ).fetchall()

        hash_status = {}
        prev_hash = "0" * 64
        first_bad_seq = None
        for r in asc_rows:
            payload = json.loads(r["payload"])
            computed = _compute_entry_hash(
                prev_hash,
                r["challenge_id"],
                r["event"],
                r["to_state"],
                r["to_rank"],
                r["actor"],
                payload,
            )
            is_ok = (computed == r["entry_hash"])
            if not is_ok and first_bad_seq is None:
                first_bad_seq = r["seq"]
            hash_status[r["seq"]] = {
                "hash_ok": is_ok,
                "expected_hash": r["entry_hash"],
                "computed_hash": computed,
            }
            prev_hash = r["entry_hash"]

        entries = []
        for r in rows:
            d = dict(r)
            status_info = hash_status.get(r["seq"], {
                "hash_ok": True,
                "expected_hash": r["entry_hash"],
                "computed_hash": r["entry_hash"],
            })
            d.update(status_info)
            entries.append(d)

        return {
            "entries": entries,
            "chain_valid": valid,
            "head_hash": head_row["entry_hash"] if head_row else None,
            "first_bad_seq": first_bad_seq,
            "verified_count": len(asc_rows),
            "chain_height": chain_height,
        }

    return {
        "entries": [dict(r) for r in rows],
        "chain_valid": valid,
        "head_hash": head_row["entry_hash"] if head_row else None,
        "chain_height": chain_height,
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


@app.post("/api/v1/budget/adjust")
async def api_budget_adjust(request: Request):
    """Adjust agent budget at runtime (demo-appropriate, not persisted to disk)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    agent = body.get("agent", "agt_coding_01")
    pool = body.get("daily_pool_paise")
    cap = body.get("per_call_cap_paise")

    from core.catalog import AGENT_POLICY
    if agent not in AGENT_POLICY:
        return JSONResponse(status_code=404,
                            content={"error": f"Unknown agent: {agent}"})

    if pool is not None:
        pool = int(pool)
        if pool < 1000 or pool > 50000:
            return JSONResponse(status_code=400,
                                content={"error": "daily_pool_paise must be 1000-50000 (₹10-₹500)"})
        AGENT_POLICY[agent]["daily_pool_paise"] = pool

    if cap is not None:
        cap = int(cap)
        if cap < 100 or cap > 10000:
            return JSONResponse(status_code=400,
                                content={"error": "per_call_cap_paise must be 100-10000 (₹1-₹100)"})
        AGENT_POLICY[agent]["per_call_cap_paise"] = cap

    return {"agent": agent, "policy": AGENT_POLICY[agent]}


@app.get("/api/v1/stats")
async def api_stats():
    """Aggregate dashboard statistics in a single call."""
    conn = get_connection()

    txn_counts = conn.execute(
        "SELECT state, COUNT(*) as cnt FROM txn GROUP BY state"
    ).fetchall()
    state_map = {r["state"]: r["cnt"] for r in txn_counts}
    total_txns = sum(state_map.values())

    captured_row = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) as total FROM budget_reservations "
        "WHERE status='CAPTURED'"
    ).fetchone()

    pass_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM passes"
    ).fetchone()

    from core.clock import now
    now_ts = now()
    active_passes = conn.execute(
        "SELECT COUNT(*) as cnt FROM passes WHERE expires_at > ?", (now_ts,)
    ).fetchone()

    audit_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM audit"
    ).fetchone()

    in_doubt_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM txn WHERE state IN ('SETTLEMENT_UNKNOWN', 'SETTLING')"
    ).fetchone()["cnt"]

    attacks_blocked = conn.execute(
        "SELECT COUNT(*) as cnt FROM audit WHERE event IN ('POLICY_DENY', 'REJECT_ILLEGAL_TRANSITION', 'ALERT_MAX_ATTEMPTS')"
    ).fetchone()["cnt"]

    from gateway.console_api import is_envelope_revoked

    return {
        "total_txns": total_txns,
        "settled_count": state_map.get("SETTLED", 0),
        "fulfilled_count": state_map.get("FULFILLED", 0),
        "failed_count": state_map.get("FAILED", 0),
        "refunded_count": state_map.get("REFUNDED", 0),
        "compensated_count": state_map.get("COMPENSATED", 0),
        "paying_count": state_map.get("PAYING", 0),
        "total_captured_paise": captured_row["total"],
        "total_passes": pass_count["cnt"],
        "active_passes": active_passes["cnt"],
        "audit_entries": audit_count["cnt"],
        "chain_height": audit_count["cnt"],
        "challenges_issued": total_txns,
        "in_doubt_count": in_doubt_count,
        "attacks_blocked": attacks_blocked,
        "reconciler_tick_s": RECONCILE_TICK_S,
        "chaos_mode": _chaos_mode,
        "envelope_status": "revoked" if is_envelope_revoked() else "active",
    }


@app.post("/api/v1/reset-db")
async def api_reset_db():
    """Reset the database — clear all transactions, audit, reservations."""
    import sqlite3 as _sqlite3
    db_path = os.environ.get("DB_PATH", "razor402.db")
    raw_conn = _sqlite3.connect(db_path)
    raw_conn.execute("PRAGMA journal_mode=WAL")

    cleared = []
    # Drop triggers first
    for trigger in ["audit_no_update", "audit_no_delete"]:
        try:
            raw_conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        except Exception:
            pass

    # Clear tables
    for table in ["txn", "audit", "budget_reservations", "jti_seen",
                   "passes", "webhook_events", "mandates", "checkpoints"]:
        try:
            raw_conn.execute(f"DELETE FROM {table}")
            cleared.append(table)
        except Exception:
            pass

    raw_conn.commit()

    # Recreate triggers
    raw_conn.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit "
        "BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END"
    )
    raw_conn.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit "
        "BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END"
    )
    raw_conn.commit()
    raw_conn.close()

    return {"cleared": True, "tables": cleared}


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


# ---------------------------------------------------------------------------
# Static files & route handlers
# ---------------------------------------------------------------------------
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
@app.get("/dashboard")
@app.get("/checkout")
@app.get("/console")
async def serve_spa():
    from fastapi.responses import FileResponse
    html_path = os.path.join(static_dir, "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return JSONResponse(content={"status": "Razor402 Gateway", "docs": "/docs"})
